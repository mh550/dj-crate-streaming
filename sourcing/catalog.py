"""Catalog search (S3-02): what a client shows before a request exists. `GET /api/catalog/search?q=&kind=album|track`.

A provider is a class with `from_app(app)` and `search(q, kind) -> list[Hit]`, registered in `PROVIDERS` by name.
Each of its hits carries `provider` and that provider's ids (`{"mbReleaseId": …}`), which is what a catalog pick
posts back to `POST /api/requests`. A second provider is a new class here, not a new endpoint. `search` below asks
every provider and then sets `in_library` the same way for all of them.

MusicBrainz is the one provider in this run, through the existing client (`sourcing.musicbrainz.MusicBrainz`: its
limiter, cache and 503 backoff). Spotify is deliberately **not** a provider yet: the February 2026 Web API changes
removed fields from track and album objects and no real response has been captured, so it is not built against
documentation examples. `scripts/capture_spotify.py` (S3-06) captures one first; a `SpotifyCatalog` follows from
that capture.
"""
from __future__ import annotations

import http.client
import re
from dataclasses import dataclass, field, replace

from subsonic.client import SubsonicError

from . import identity
from .fetch import library_match
from .import_playlist import _search_all, query_words
from .musicbrainz import MusicBrainz, MusicBrainzError, parse_recording, phrase_query

KINDS = ("album", "track")
LIMIT = 25                                           # MusicBrainz's own default page


class CatalogBusy(Exception):
    """A provider cannot answer now (busy after the client's retries, or unreachable): the API's 503."""


@dataclass(frozen=True)
class Hit:
    provider: str
    kind: str                                        # "album" | "track"
    title: str
    artist: str
    year: int | None
    track_count: int | None                          # album
    length_s: float | None                           # track
    format: str | None                               # album: the first medium's ("CD", "Digital Media", '12" Vinyl')
    ids: dict = field(default_factory=dict)          # the provider's: {"mbReleaseId": …} / {"mbRecordingId": …}
    in_library: bool | None = None                   # None: Navidrome was not asked or could not answer

    def as_json(self) -> dict:
        return {"provider": self.provider, "kind": self.kind, "title": self.title, "artist": self.artist,
                "year": self.year, "trackCount": self.track_count, "lengthS": self.length_s, "format": self.format,
                "ids": dict(self.ids), "inLibrary": self.in_library}


def _year(date: str | None) -> int | None:
    y = (date or "")[:4]
    return int(y) if len(y) == 4 and y.isdigit() and int(y) > 0 else None


def _credit(d: dict) -> str:
    return "".join((c.get("name") or "") + (c.get("joinphrase") or "") for c in d.get("artist-credit") or [])


_DASH = re.compile(r"\s+[-\u2013\u2014]\s+")


def _split(q: str) -> tuple[str, str]:
    """`Artist - Title` (or an en or em dash) → (artist, title); anything else is a title alone."""
    parts = _DASH.split(q.strip(), maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 and parts[0] and parts[1] else ("", q.strip())


class MusicBrainzCatalog:
    """Releases (kind album) and recordings (kind track) from MusicBrainz search."""

    name = "musicbrainz"

    def __init__(self, musicbrainz: MusicBrainz, limit: int = LIMIT):
        self.mb, self.limit = musicbrainz, limit

    @classmethod
    def from_app(cls, app) -> "MusicBrainzCatalog":
        return cls(app.musicbrainz)

    def search(self, q: str, kind: str) -> list[Hit]:
        if kind not in KINDS:
            raise ValueError(f"kind must be album or track, not {kind!r}")
        artist, title = _split(q)
        try:
            if kind == "album":
                return [self._release(r) for r in self.mb.release_search(artist, title, limit=self.limit)]
            d = self.mb.get("recording", query=phrase_query(artist=artist, recording=title), limit=self.limit)
        except (MusicBrainzError, OSError) as e:      # retries spent, no network, or an unusable cache file
            raise CatalogBusy("MusicBrainz is busy, try again") from e
        return [self._recording(r) for r in (d or {}).get("recordings") or []]

    def _release(self, r: dict) -> Hit:
        fmt = ((r.get("media") or [{}])[0] or {}).get("format")
        return Hit(self.name, "album", r.get("title") or "", _credit(r), _year(r.get("date")), r.get("track-count"),
                   None, fmt or None, {"mbReleaseId": r["id"]})

    def _recording(self, d: dict) -> Hit:
        rec = parse_recording(d)
        return Hit(self.name, "track", rec.title, rec.artist, _year(d.get("first-release-date")), None, rec.length_s,
                   None, {"mbRecordingId": rec.id})


PROVIDERS: dict[str, type] = {"musicbrainz": MusicBrainzCatalog}


_NAVIDROME_ERRORS = (SubsonicError, OSError, ValueError, KeyError, TypeError, http.client.HTTPException)


class _Library:
    """The library questions of one search. It stands in for the Navidrome client towards import_playlist (only
    `search_songs` is asked), so each search page is fetched once however many hits ask it (25 recordings of one
    song are one query); after the first Navidrome error nothing more is asked and every hit is `None`."""

    def __init__(self, navidrome):
        self.navidrome, self.down, self._pages = navidrome, False, {}

    def search_songs(self, query: str, count: int = 20, offset: int = 0):
        key = (query, count, offset)
        if key not in self._pages:
            self._pages[key] = self.navidrome.search_songs(query, count=count, offset=offset)
        return self._pages[key]

    def _ask(self, question) -> bool | None:
        if self.down:
            return None
        try:
            return question()
        except _NAVIDROME_ERRORS:                    # down, refused, or an answer that is not Subsonic JSON
            self.down = True
            return None

    def has_album(self, title: str, artist: str) -> bool | None:
        """A song of that album name by that artist or album artist, compared with `identity.loose`. search3's song
        results carry `album`, `displayAlbumArtist` and `albumArtists` (captured shape); its album results are not
        captured. A name that folds to nothing ("÷", "!!!") cannot be asked: None."""
        lead = identity.lead_artist(artist)
        album, by = identity.loose(title), identity.loose(lead)
        queries = [" ".join(query_words(title, lead)), " ".join(query_words(title))]
        if not (album and by and queries[1]):
            return None

        def names(s) -> set[str]:
            credits = [s.artist, s.raw.get("displayAlbumArtist")]
            credits += [a.get("name") for a in s.raw.get("albumArtists") or [] if isinstance(a, dict)]
            return {identity.loose(identity.lead_artist(c)) for c in credits if c}

        def question() -> bool:      # with the artist's words first; then the album's alone, for an album artist
            return any(identity.loose(s.album) == album and by in names(s)     # search3 may not index
                       for q in queries for s in _search_all(self, q))
        return self._ask(question)

    def has_track(self, hit: Hit) -> bool | None:
        """import_playlist's rules through fetch.library_match: the same recording or the same version. With no
        artist any same-title song would pass, so that is None."""
        lead = identity.lead_artist(hit.artist)
        if not (identity.loose(lead) and identity.loose(hit.title)):
            return None
        row = {"title": hit.title, "artist": lead, "duration": hit.length_s}
        return self._ask(lambda: library_match(self, row) is not None)


def search(providers, q: str, kind: str, navidrome) -> list[Hit]:
    """Every provider's hits, in provider order, each with `in_library` set: an album when Navidrome has an album
    of that name by that artist, a track when the import would match it. Navidrome unreachable → None for all.
    A provider's CatalogBusy reaches the caller."""
    hits = [h for p in providers for h in p.search(q, kind)]
    lib = _Library(navidrome)
    marked = [replace(h, in_library=lib.has_album(h.title, h.artist) if h.kind == "album" else lib.has_track(h))
              for h in hits]
    return [replace(h, in_library=None) for h in marked] if lib.down else marked   # down part-way: all unknown
