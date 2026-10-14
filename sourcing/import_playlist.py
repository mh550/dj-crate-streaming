"""Spotify/report playlist rows → Navidrome playlist + wanted rows (spec §2a, D11).

Matching, in order: search3 on artist+title words (Navidrome ignores case, accents and punctuation;
every word must hit) → keep hits within ±4 s when the row has a duration → else hits whose normalised
title and lead artist both appear in the hit's normalised "artist title" → nearest duration →
redundant copies (same normalised artist|title, lengths within ±4 s of each other) collapse to the
one outside Compilations/ → still >1 distinct track → ambiguous. No hits at all → retry with the
title words only (library titles sometimes carry the artist, e.g. "A Change Is Gonna Come - Jennifer Lara").
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from crates.store import CrateStore
from subsonic.client import Song, SubsonicClient
from .playlist_sources import Row, _track_lead, lead_artist

TOLERANCE_S = 4
MARKER = "#imported"          # in the playlist comment: "this playlist is managed by import-playlist"
PAGE = 20                     # Navidrome search3 page size we ask for; a full page means "ask for more"
MAX_PAGES = 5


class NameCollision(Exception):
    """A playlist with this name exists and was not created by import-playlist (pass merge=True to adopt it)."""

    def __init__(self, name: str, playlist_id: str):
        super().__init__(f"playlist {name!r} already exists ({playlist_id}) and is not marked {MARKER}")
        self.name, self.playlist_id = name, playlist_id


def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(ch for ch in s if ch.isalnum() and not unicodedata.combining(ch)).casefold()


def query_words(*parts: str) -> list[str]:
    text = unicodedata.normalize("NFKD", " ".join(parts))
    text = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text if not unicodedata.combining(ch))
    return [w for w in text.casefold().split() if len(w) >= 2]


def build_query(row: Row) -> str:
    return " ".join(query_words(row.artist.replace(";", " "), row.title))


@dataclass
class Match:
    row: Row
    status: str                 # "matched" | "ambiguous" | "missing"
    song_id: str | None = None
    candidates: list[str] = field(default_factory=list)
    picked: Song | None = None


def _key(s: Song) -> str:
    return norm(s.artist) + "|" + norm(s.title)


def _untagged(artist: str | None) -> bool:
    """… unless the file has no artist at all ("[Unknown Artist]", "Various"): no evidence against a
    match, so the length decides (the no-length fallback still demands the artist)."""
    return norm(artist) in ("", "unknownartist", "various", "variousartists", "unknown")


def _title_fits(row: Row, hit: Song) -> bool:
    """The row's title appears in the hit, or the hit's title in the row's ("Fascination" vs
    "Fascination - 2012 Remaster"). Guards the duration branch against artist-only queries."""
    t, h = norm(row.title), norm(hit.title)
    return bool(t and h) and (t in norm(f"{hit.artist} {hit.title}") or h in t)


def choose(row: Row, hits: list[Song], require_artist: bool = False) -> Match:
    if not hits:
        return Match(row, "missing")
    lead = norm(lead_artist(row, resolve=lambda sid: None))
    if require_artist:                                   # title-only retry: the artist must still be there …
        hits = [h for h in hits if lead and (lead in norm(f"{h.artist} {h.title}") or _untagged(h.artist))]
    fit: list[Song] = []
    if row.duration_s is not None:
        fit = [h for h in hits if h.duration is not None and abs(h.duration - row.duration_s) <= TOLERANCE_S and _title_fits(row, h)]
        if fit:
            best = min(abs(h.duration - row.duration_s) for h in fit)
            fit = [h for h in fit if abs(h.duration - row.duration_s) == best]
    if not fit:
        title = norm(row.title)
        fit = [h for h in hits if title and title in norm(f"{h.artist} {h.title}") and lead and lead in norm(f"{h.artist} {h.title}")]
        exact = [h for h in fit if norm(h.title) in (title, title + lead) or norm(h.title).endswith(title + lead)]
        if exact:
            fit = exact
    if not fit:
        return Match(row, "missing", candidates=[h.id for h in hits])
    distinct = {_key(h) for h in fit}
    durs = [h.duration for h in fit if h.duration is not None]
    # Same artist|title twice is a redundant copy only when the lengths agree; "The Magician" 353 s
    # vs 300 s are two recordings, and without a row duration we cannot pick → ambiguous.
    if len(distinct) > 1 or (durs and max(durs) - min(durs) > TOLERANCE_S):
        return Match(row, "ambiguous", candidates=[h.id for h in fit])
    fit.sort(key=lambda h: (h.path or "").startswith("Compilations/"))      # the properly filed copy first
    return Match(row, "matched", fit[0].id, [h.id for h in fit], fit[0])


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
    hits, require_artist = _search_all(client, query), False
    if not hits:
        title_only = " ".join(query_words(row.title))
        hits, require_artist = (_search_all(client, title_only) if title_only else []), True
    return choose(row, hits, require_artist)


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
                    source: str, dry_run: bool = False, merge: bool = False, resolve=_track_lead) -> Report:
    """Create or update the playlist `name`: matched tracks in row order (appending only what is
    missing on a re-run, never removing), public; everything else becomes an external_wanted row
    that remembers the playlist and position. Ambiguous rows are parked as `verify` with the ids.

    A same-named playlist that this tool did not create (no `#imported` in its comment) raises
    NameCollision unless `merge=True`, which adopts it (adds the marker, leaves its visibility alone)."""
    matches = [match(client, r) for r in rows]
    ordered: list[str] = []
    for m in matches:
        if m.status == "matched" and m.song_id not in ordered:
            ordered.append(m.song_id)
    existing = next((p for p in client.playlists() if p.name == name), None)
    ours = existing is not None and MARKER in (existing.comment or "")
    if existing is not None and not ours and not merge:
        raise NameCollision(name, existing.id)
    kept = 0
    if existing is None:
        new_ids, playlist_id = ordered, None
    else:
        have = {e.id for e in client.playlist(existing.id).entries}
        new_ids, playlist_id, kept = [i for i in ordered if i not in have], existing.id, len(have)
    # Resolve lead artists (may ask Spotify) before touching anything, so a failure leaves nothing half-written.
    notes, leads, failed = [], {}, set()

    def _resolve(sid):
        got = resolve(sid)
        if not got:
            failed.add(sid)
        return got

    for m in matches:
        if m.status != "matched":
            leads[m.row.position] = lead_artist(m.row, resolve=_resolve)
            if m.row.spotify_id in failed:
                notes.append(f"lead artist of {m.row.artist!r} could not be resolved; wanted row uses {leads[m.row.position]!r}")
    if not dry_run:
        if existing is None:
            playlist_id = client.create_playlist(name, new_ids).id
            client.update_playlist(playlist_id, public=True, comment=MARKER)      # spec §2a: visible to every user
        else:
            if new_ids:
                client.update_playlist(existing.id, add_song_ids=new_ids)
            if ours and not existing.public:
                client.update_playlist(existing.id, public=True)
            if not ours:                                                          # merge=True adopts the playlist
                client.update_playlist(existing.id, comment=((existing.comment or "") + " " + MARKER).strip())
        for m in matches:
            if m.status == "matched":
                continue
            ext = store.add_external_wanted(leads[m.row.position], m.row.title, album=m.row.album, duration_s=m.row.duration_s,
                                            source=source, playlist_id=playlist_id, position=m.row.position)
            if m.status == "ambiguous" and store.external(ext)["status"] in ("needs_source", "verify"):
                store.set_external_status(ext, "verify", "ambiguous: " + ", ".join(m.candidates))
        store.commit()
    return Report(name, playlist_id, existing is None, matches, len(new_ids), kept, notes)
