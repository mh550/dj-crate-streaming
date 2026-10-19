"""Placement (N4, M9 item 1, D44): a filed external row goes into its imported playlist at its Spotify position.

`insert_index` is the rule: after the nearest earlier Spotify neighbour still in the playlist, else before the nearest
later one, else at the end. `place` applies it to one (wanted row, playlist) pair, insert-only, through
`playlist_edit.rewrite`, recomputing everything right before it writes. The worker decides when (N4-04).
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path

from crates import playlist_edit as pe
from scripts.export_playlists import open_ro
from subsonic.client import SubsonicError


GONE = "skipped: playlist gone"


def insert_index(order: list[tuple[int, str | None]], entries: list[str], position: int) -> tuple[int, str]:
    """Where a track at Spotify `position` goes in `entries` (the playlist now). `order` is the import's rows as
    (position, song id or None while still wanted). The nearest earlier row whose song is in `entries` → after that
    song's last occurrence; none → before the nearest later one's first occurrence; none → the end. A neighbour
    Michael removed, or one still wanted, is skipped. Returns (index, "after <song>" | "before <song>" | "append")."""
    def first(rows):
        return next((song for _, song in rows if song is not None and song in entries), None)

    song = first(sorted((r for r in order if r[0] < position), key=lambda r: r[0], reverse=True))
    if song is not None:
        return len(entries) - entries[::-1].index(song), f"after {song}"
    song = first(sorted((r for r in order if r[0] > position), key=lambda r: r[0]))
    if song is not None:
        return entries.index(song), f"before {song}"
    return len(entries), "append"


def _filed(store, wanted_id: str | None) -> str | None:
    """The song an order row's wanted row was filed as (a neighbour placed or appended earlier), else None."""
    ext = store.external(wanted_id) if wanted_id else None
    if ext and ext["status"] == "ok" and not ext["provisional"]:
        return ext["library_song_id"]
    return None


def _in_library(db: Path, song_id: str) -> bool:
    with closing(open_ro(db)) as con:
        return con.execute("SELECT 1 FROM media_file WHERE id=? AND missing=0", (song_id,)).fetchone() is not None


def place(store, client, db: Path, playlist_id: str, wanted_id: str, song_id: str, before_write=None) -> str:
    """Insert `song_id` (wanted row `wanted_id`, filed) into imported playlist `playlist_id` at its Spotify position.
    Returns "placed at <index> (<how>)" or "skipped: <why>" (nothing written). playlist_edit's refusals
    (PlaylistSkew, PlaylistChanged, NotOwned, NotEditable, all EditRefused) propagate for the caller to retry; so
    does EditNotKept (the write was sent, the caller must look, never retry blind). `before_write(index, how, n)`,
    when given, runs after place's checks and right before rewrite (the caller's intent row); if it raises, nothing
    is written. rewrite re-reads the playlist, so an EditRefused (or "skipped: playlist gone") can still follow
    before_write: then nothing was written either. On success the song is marked imported (removed stays removed, D13) and a `placed` event is logged;
    the caller commits."""
    if not store.is_playlist_imported(playlist_id):
        return "skipped: not an imported playlist"
    if song_id in store.imported(playlist_id):
        return "skipped: added before (removed stays removed)"
    rows = store.import_order(playlist_id)
    mine = [r["position"] for r in rows if r["wanted_id"] == wanted_id]
    if not mine:
        return "skipped: no longer in the import"
    try:
        name, entries = pe.checked_playlist(client, db, playlist_id)
    except SubsonicError as e:
        if e.code == 70:
            return GONE
        raise
    if song_id in entries:
        store.mark_imported(playlist_id, [song_id])
        return "skipped: already in playlist"
    if not _in_library(db, song_id):          # retagged under a new id, or trashed: say so, not "a hidden row"
        raise pe.EditRefused(f"{name!r}: song {song_id} is not in the library now")
    order = [(r["position"], r["song_id"] or _filed(store, r["wanted_id"])) for r in rows]
    i, how = insert_index(order, entries, min(mine))
    if before_write is not None:
        before_write(i, how, len(entries))
    try:
        pe.rewrite(client, db, playlist_id, entries, entries[:i] + [song_id] + entries[i:])
    except SubsonicError as e:                # only rewrite's first read raises it (after the write: EditNotKept)
        if e.code == 70:
            return GONE
        raise
    store.mark_imported(playlist_id, [song_id])
    ext = store.external(wanted_id)
    what = f"{ext['artist']} – {ext['title']}" if ext else song_id
    store.log(playlist_id, wanted_id, "placed", f"{name}: {what} at {i + 1} ({how})")
    return f"placed at {i} ({how})"
