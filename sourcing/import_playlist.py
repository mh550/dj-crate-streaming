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
from .playlist_sources import Row, lead_artist

TOLERANCE_S = 4


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


def choose(row: Row, hits: list[Song]) -> Match:
    if not hits:
        return Match(row, "missing")
    fit: list[Song] = []
    if row.duration_s is not None:
        fit = [h for h in hits if h.duration is not None and abs(h.duration - row.duration_s) <= TOLERANCE_S]
        if fit:
            best = min(abs(h.duration - row.duration_s) for h in fit)
            fit = [h for h in fit if abs(h.duration - row.duration_s) == best]
    if not fit:
        title, lead = norm(row.title), norm(lead_artist(row, resolve=lambda sid: None))
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


def match(client: SubsonicClient, row: Row) -> Match:
    hits = client.search_songs(build_query(row), count=20)
    if not hits:
        title_only = " ".join(query_words(row.title))
        hits = client.search_songs(title_only, count=20) if title_only else []
    return choose(row, hits)


@dataclass
class Report:
    name: str
    playlist_id: str | None
    created: bool
    matches: list[Match]
    added: int                  # entries appended this run (or that a dry run would append)

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
        return "\n".join(lines)


def import_playlist(name: str, rows: list[Row], client: SubsonicClient, store: CrateStore,
                    source: str, dry_run: bool = False) -> Report:
    """Create or update the playlist `name`: matched tracks in row order (appending only what is
    missing on a re-run, never removing), public; everything else becomes an external_wanted row
    that remembers the playlist and position. Ambiguous rows are parked as `verify` with the ids."""
    matches = [match(client, r) for r in rows]
    ordered: list[str] = []
    for m in matches:
        if m.status == "matched" and m.song_id not in ordered:
            ordered.append(m.song_id)
    existing = next((p for p in client.playlists() if p.name == name), None)
    if existing is None:
        new_ids, playlist_id = ordered, None
    else:
        have = {e.id for e in client.playlist(existing.id).entries}
        new_ids, playlist_id = [i for i in ordered if i not in have], existing.id
    if not dry_run:
        if existing is None:
            playlist_id = client.create_playlist(name, new_ids).id
            client.update_playlist(playlist_id, public=True)              # spec §2a: visible to every user
        else:
            if new_ids:
                client.update_playlist(existing.id, add_song_ids=new_ids)
            if not existing.public:
                client.update_playlist(existing.id, public=True)
        for m in matches:
            if m.status == "matched":
                continue
            ext = store.add_external_wanted(lead_artist(m.row), m.row.title, album=m.row.album, duration_s=m.row.duration_s,
                                            source=source, playlist_id=playlist_id, position=m.row.position)
            if m.status == "ambiguous":
                store.set_external_status(ext, "verify", "ambiguous: " + ", ".join(m.candidates))
        store.commit()
    return Report(name, playlist_id, existing is None, matches, len(new_ids))
