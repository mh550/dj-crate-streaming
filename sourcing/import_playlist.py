"""Spotify/report playlist rows → Navidrome playlist + wanted rows (spec §2a, D11).

Matching, in order: search3 on artist+title words (Navidrome ignores case, accents and punctuation;
every word must hit) → keep hits within ±4 s when the row has a duration → else hits whose normalised
title and lead artist both appear in the hit's normalised "artist title" → nearest duration →
redundant copies (same normalised artist|title, lengths within ±4 s of each other) collapse to the
one outside Compilations/ → still >1 distinct track → ambiguous. No hits at all → retry with the
title words only (library titles sometimes carry the artist, e.g. "A Change Is Gonna Come - Jennifer Lara"),
keeping only hits that name the artist or have no artist tag at all.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from crates.store import CrateStore
from subsonic.client import Song, SubsonicClient
from .playlist_sources import Row, lead_artist, track_lead

TOLERANCE_S = 4
MARKER = "#imported"          # in the playlist comment: "this playlist is managed by import-playlist"
PAGE = 20                     # Navidrome search3 page size we ask for; a full page means "ask for more"
MAX_PAGES = 5


class NameCollision(Exception):
    """A playlist with this name exists and was not created by import-playlist (pass merge=True to adopt it)."""

    def __init__(self, name: str, playlist_id: str):
        super().__init__(f"playlist {name!r} already exists ({playlist_id}) and is not marked {MARKER}")
        self.name, self.playlist_id = name, playlist_id


def _fold(s: str | None) -> str:
    """Case-, accent- and punctuation-insensitive, like Navidrome's search: letters/digits and spaces only."""
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in s if not unicodedata.combining(ch)).casefold()


def norm(s: str | None) -> str:
    return "".join(_fold(s).split())


def query_words(*parts: str) -> list[str]:
    return [w for w in _fold(" ".join(parts)).split() if len(w) >= 2]


def build_query(row: Row) -> str:
    return " ".join(query_words(row.artist, row.title))


@dataclass
class Match:
    row: Row
    status: str                 # "matched" | "ambiguous" | "missing"
    song_id: str | None = None
    candidates: list[str] = field(default_factory=list)   # ids considered (ambiguous → the tie; matched → the copies)


def _blob(h: Song) -> str:
    return norm(f"{h.artist} {h.title}")


def _key(h: Song) -> str:
    return norm(h.artist) + "|" + norm(h.title)


def _untagged(artist: str | None) -> bool:
    """A file with no artist tag ("[Unknown Artist]", "Various") is no evidence against a match."""
    return norm(artist) in ("", "unknownartist", "various", "variousartists", "unknown")


def _title_fits(row: Row, hit: Song) -> bool:
    """The row's title appears in the hit, or the hit's title in the row's ("Fascination" vs
    "Fascination - 2012 Remaster"). Guards the length strategy against artist-only queries."""
    t, h = norm(row.title), norm(hit.title)
    return bool(t and h) and (t in _blob(hit) or h in t)


def _lead(row: Row) -> str:
    return norm(lead_artist(row, resolve=None))          # never a network call while matching


def _artist_gate(hits: list[Song], lead: str) -> list[Song]:
    """For the title-only retry: the artist must still be there, unless the file has none."""
    return [h for h in hits if lead and (lead in _blob(h) or _untagged(h.artist))]


def _by_length(row: Row, hits: list[Song]) -> list[Song]:
    def d(h: Song) -> int:
        return abs(h.duration - row.duration_s)
    fit = [h for h in hits if h.duration is not None and d(h) <= TOLERANCE_S and _title_fits(row, h)]
    if not fit:
        return []
    best = min(map(d, fit))
    return [h for h in fit if d(h) == best]


def _by_title(row: Row, hits: list[Song], lead: str) -> list[Song]:
    title = norm(row.title)
    fit = [h for h in hits if title and lead and title in _blob(h) and lead in _blob(h)]
    exact = [h for h in fit if norm(h.title) == title or norm(h.title).endswith(title + lead)]
    return exact or fit


def choose(row: Row, hits: list[Song]) -> Match:
    if not hits:
        return Match(row, "missing")
    fit = (_by_length(row, hits) if row.duration_s is not None else []) or _by_title(row, hits, _lead(row))
    if not fit:
        return Match(row, "missing", candidates=[h.id for h in hits])
    durs = [h.duration for h in fit if h.duration is not None]
    # Same artist|title twice is a redundant copy only when the lengths agree; "The Magician" 353 s
    # vs 300 s are two recordings, and without a row duration we cannot pick → ambiguous.
    if len({_key(h) for h in fit}) > 1 or (durs and max(durs) - min(durs) > TOLERANCE_S):
        return Match(row, "ambiguous", candidates=[h.id for h in fit])
    fit.sort(key=lambda h: (h.path or "").startswith("Compilations/"))      # the properly filed copy first
    return Match(row, "matched", fit[0].id, [h.id for h in fit])


def _search_all(client: SubsonicClient, query: str) -> list[Song]:
    """search3 pages: a full page of common words ("love") can hide the real hit past the first 20."""
    hits: list[Song] = []
    for page in range(MAX_PAGES):
        batch = client.search_songs(query, count=PAGE, offset=page * PAGE)
        hits.extend(batch)
        if len(batch) < PAGE:
            break
    return hits


def match(client: SubsonicClient, row: Row) -> Match:
    query = build_query(row)
    if not query:                                        # nothing searchable: an empty search3 lists everything
        return Match(row, "missing")
    hits = _search_all(client, query)
    if not hits:
        title_only = " ".join(query_words(row.title))
        hits = _artist_gate(_search_all(client, title_only), _lead(row)) if title_only else []
    return choose(row, hits)


@dataclass
class Report:
    name: str
    playlist_id: str | None
    created: bool
    matches: list[Match]
    added: int                  # entries appended this run (or that a dry run would append)
    kept: int = 0               # entries the existing playlist already had before this run
    notes: list[str] = field(default_factory=list)   # things Michael should know (unresolved artists …)

    def _count(self, status: str) -> int:
        return sum(1 for m in self.matches if m.status == status)

    @property
    def matched(self) -> int:
        return self._count("matched")

    @property
    def wanted(self) -> int:
        return self._count("missing")

    @property
    def ambiguous(self) -> int:
        return self._count("ambiguous")

    def table(self) -> str:
        lines = []
        for m in self.matches:
            tail = f"→ {m.song_id}" if m.song_id else (f"? {', '.join(m.candidates)}" if m.candidates else "")
            lines.append(f"{m.row.position:4d}  {m.status:<9}  {m.row.artist} — {m.row.title}  {tail}".rstrip())
        lines.append(f"{self.name}: {self.matched} matched, {self.wanted} wanted, {self.ambiguous} ambiguous"
                     + (f"; {self.added} added to playlist {self.playlist_id}" if self.playlist_id else ""))
        if self.playlist_id:
            lines.append(f"created playlist {self.name!r}" if self.created else
                         f"updated existing playlist {self.name!r}: {self.kept} entries were already there (kept, not reordered)")
        lines.extend(f"note: {n}" for n in self.notes)
        return "\n".join(lines)


def import_playlist(name: str, rows: list[Row], client: SubsonicClient, store: CrateStore,
                    source: str, dry_run: bool = False, merge: bool = False, resolve=track_lead) -> Report:
    """Create or update the playlist `name`: matched tracks in row order (appending only what is
    missing on a re-run, never removing), public; everything else becomes an external_wanted row
    that remembers the playlist and position. Ambiguous rows are parked as `verify` with the ids.

    A same-named playlist that this tool did not create (no `#imported` in its comment) raises
    NameCollision unless `merge=True`, which adopts it (adds the marker, leaves its visibility alone)."""
    matches = [match(client, r) for r in rows]
    ordered = list(dict.fromkeys(m.song_id for m in matches if m.status == "matched"))
    existing = next((p for p in client.playlists() if p.name == name), None)
    ours = existing is not None and MARKER in (existing.comment or "")
    if existing is not None and not ours and not merge:
        raise NameCollision(name, existing.id)
    have = {e.id for e in client.playlist(existing.id).entries} if existing else set()
    new_ids = [i for i in ordered if i not in have]
    playlist_id = existing.id if existing else None
    # Resolve lead artists (may ask Spotify) before touching anything, so a failure leaves nothing half-written.
    notes, failed = [], set()

    def _resolve(sid):
        got = resolve(sid)
        if not got:
            failed.add(sid)
        return got

    pending = [(m, lead_artist(m.row, resolve=_resolve)) for m in matches if m.status != "matched"]
    notes = [f"lead artist of {m.row.artist!r} could not be resolved; wanted row uses {lead!r}"
             for m, lead in pending if m.row.spotify_id in failed]
    if not dry_run:
        if existing is None:
            playlist_id = client.create_playlist(name, new_ids).id
            client.update_playlist(playlist_id, public=True, comment=MARKER)      # spec §2a: visible to every user
        else:
            client.update_playlist(existing.id, add_song_ids=new_ids,
                                   public=True if ours and not existing.public else None,
                                   comment=None if ours else ((existing.comment or "") + " " + MARKER).strip())
        for m, lead in pending:
            ext = store.add_external_wanted(lead, m.row.title, album=m.row.album, duration_s=m.row.duration_s,
                                            source=source, playlist_id=playlist_id, position=m.row.position)
            if m.status == "ambiguous" and store.external(ext)["status"] in ("needs_source", "verify"):
                store.set_external_status(ext, "verify", "ambiguous: " + ", ".join(m.candidates))
        store.commit()
    return Report(name, playlist_id, existing is None, matches, len(new_ids), len(have), notes)
