"""Placement (N4, M9 item 1, D44): a filed external row goes into its imported playlist at its Spotify position.

`insert_index` is the rule: after the nearest earlier Spotify neighbour still in the playlist, else before the nearest
later one, else at the end. `place` applies it to one (wanted row, playlist) pair, insert-only, through
`playlist_edit.rewrite`, recomputing everything right before it writes. `advance_all` is the worker's step (N4-04):
it places every due pair (CrateStore.due_placements, derived from state), retries a refusal after recheck_s, then
ever less often (retry_wait), and gives up after PLACE_LIMIT counted failures with a `not_placed` event. An edit that was sent but not confirmed is
never retried blind: it is looked at (the song present → done; absent → given up), so an entry is never doubled and a
track Michael removed in that moment is never put back.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from crates import playlist_edit as pe
from scripts.export_playlists import open_ro
from subsonic.client import SubsonicError


GONE = "skipped: playlist gone"
PLACE_LIMIT = 12                       # counted failures before a pair is given up (fetch's RECHECK_LIMIT habit)
RETRY_MAX_S = 86400                    # the longest wait between two tries (retry_wait)
CONFIRMED = "confirmed after an unconfirmed edit"


def transient(e: Exception) -> bool:
    """An outage, not counted toward PLACE_LIMIT: Navidrome unreachable (OSError: URLError, timeouts) or a database
    locked or busy. Any other sqlite3 error (no such table, unable to open) is permanent and counted."""
    if isinstance(e, sqlite3.OperationalError):
        return any(w in str(e).lower() for w in ("locked", "busy"))
    return isinstance(e, OSError)


def retry_wait(recheck_s: float, attempts: int) -> float:
    """Seconds an `open` pair waits after its `attempts`-th counted failure: recheck_s, then doubling, at most a day.
    A refusal such as a hidden missing row lasts until a scan or a cleanup, so the 12 tries span days, not an hour."""
    return min(recheck_s * 2 ** max(attempts - 1, 0), RETRY_MAX_S)


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


def place(store, client, db: Path, playlist_id: str, wanted_id: str, song_id: str, before_write=None,
          after_write=None) -> str:
    """Insert `song_id` (wanted row `wanted_id`, filed) into imported playlist `playlist_id` at its Spotify position.
    Returns "placed at <index> (<how>)" or "skipped: <why>" (nothing written). playlist_edit's refusals
    (PlaylistSkew, PlaylistChanged, NotOwned, NotEditable, all EditRefused) propagate for the caller to retry; so
    does EditNotKept (the write was sent, the caller must look, never retry blind). `before_write(index, how, n)`,
    when given, runs after place's checks and right before rewrite (the caller's intent row); if it raises, nothing
    is written. rewrite re-reads the playlist, so an EditRefused (or "skipped: playlist gone") can still follow
    before_write: then nothing was written either. `after_write()`, when given, runs as soon as rewrite has
    confirmed the edit, before place's own bookkeeping (which may still fail). On success the song is marked imported (removed stays removed, D13) and a `placed` event is logged;
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
    if after_write is not None:
        after_write()
    _record_placed(store, playlist_id, wanted_id, song_id, name, f"{i + 1} ({how})")
    return f"placed at {i} ({how})"


def _record_placed(store, playlist_id: str, wanted_id: str, song_id: str, name: str, where: str) -> None:
    """The song is in the playlist: removed stays removed (D13), and a `placed` event
    "<playlist>: <artist> – <title> at <where>"."""
    store.mark_imported(playlist_id, [song_id])
    ext = store.external(wanted_id)
    what = f"{ext['artist']} – {ext['title']}" if ext else song_id
    store.log(playlist_id, wanted_id, "placed", f"{name}: {what} at {where}")


def advance_all(store, client, db: Path, recheck_s: float, now: float) -> list[str]:
    """The worker's placement step: every due pair whose placement is new, `writing` (an edit sent, not confirmed:
    only looked at, whatever its age) or `open` and last tried at least retry_wait(recheck_s, attempts) ago. One
    line per pair tried, "<wanted_id> → <playlist_id>: <result>"; each pair is committed on its own, and one failing
    pair never stops the others. A placed or skipped pair is `done`; a refusal or an unexpected error is `open` and counted, the
    PLACE_LIMIT-th gives up with a `not_placed` event; a transient() error is `open` and not counted, so an outage
    never gives a placement up. Call it with no transaction open: a failed pair is rolled back."""
    out = []
    for d in store.due_placements():
        row = store.placement(d["wanted_id"], d["playlist_id"])
        if row and row["state"] == "open" and row["updated_at"] > now - retry_wait(recheck_s, row["attempts"]):
            continue
        try:
            result = (_look(store, client, d, row, now) if row and row["state"] == "writing"
                      else _advance(store, client, db, d, row, now))
        except Exception as e:                    # recording the outcome failed (e.g. crates.db locked): state kept
            store.db.rollback()
            result = f"error: {type(e).__name__}: {e}"
        out.append(f"{d['wanted_id']} → {d['playlist_id']}: {result}")
    return out


def _note(store, d: dict, state: str, detail: str, now: float, count: bool = False) -> None:
    store.note_placement(d["wanted_id"], d["playlist_id"], state, detail, song_id=d["song_id"], count=count, now=now)


def _advance(store, client, db: Path, d: dict, row: dict | None, now: float) -> str:
    sent = []

    def intent(i, how, n):                        # committed before the write: a crash after it is looked at
        _note(store, d, "writing", f"inserting at {i} into {n} entries ({how})", now)
        store.commit()

    try:
        result = place(store, client, db, d["playlist_id"], d["wanted_id"], d["song_id"], before_write=intent,
                       after_write=lambda: sent.append(True))
    except Exception as e:
        store.db.rollback()
        why = f"{type(e).__name__}: {e}"
        if sent or isinstance(e, pe.EditNotKept):  # the edit was sent: the committed `writing` row stays, and the
            return f"edit sent, not confirmed: {why}; looked at next tick"   # next tick looks (Navidrome may lag)
        if transient(e):                          # rewrite raises EditNotKept once the write is sent: none was
            _note(store, d, "open", why, now)
            store.commit()
            return f"error (not counted): {why}"
        return _failed(store, d, row, e, now)     # a refusal (nothing written), a non-70 SubsonicError, a bug
    if result != "skipped: no longer in the import":   # a re-run since due_placements: simply not due any more
        _note(store, d, "done", result, now)
    store.commit()
    return result


def _failed(store, d: dict, row: dict | None, e: Exception, now: float) -> str:
    why = f"{type(e).__name__}: {e}"
    if (row["attempts"] if row else 0) + 1 < PLACE_LIMIT:
        _note(store, d, "open", why, now, count=True)
        store.commit()
        return f"{'refused' if isinstance(e, pe.EditRefused) else 'error'}: {why}"
    _note(store, d, "given_up", why, now, count=True)
    store.log(d["playlist_id"], d["wanted_id"], "not_placed", f"{d['name'] or d['playlist_id']}: not placed after "
              f"{PLACE_LIMIT} tries: {why}; re-run the import to append it")
    store.commit()
    return f"given up: not placed after {PLACE_LIMIT} tries: {why}"


def _look(store, client, d: dict, row: dict, now: float) -> str:
    """An edit was sent and not confirmed (EditNotKept, a failure after the write, or a crash): read the playlist and
    decide from what is there, for the song the intent row wrote. A failed read keeps the row `writing` for the next
    tick."""
    d = dict(d, song_id=row["song_id"] or d["song_id"])
    pid, wanted_id, song_id = d["playlist_id"], d["wanted_id"], d["song_id"]
    try:
        playlist = client.playlist(pid)
    except SubsonicError as e:
        if e.code != 70:
            return f"could not look: {type(e).__name__}: {e}"
        _note(store, d, "done", GONE, now)
        store.commit()
        return GONE
    except Exception as e:
        return f"could not look: {type(e).__name__}: {e}"
    entries = [e.id for e in playlist.entries]
    name = playlist.name or d["name"] or pid
    if song_id in entries:
        _record_placed(store, pid, wanted_id, song_id, name, f"{entries.index(song_id) + 1} ({CONFIRMED})")
        _note(store, d, "done", f"placed ({CONFIRMED})", now)
        store.commit()
        return f"placed ({CONFIRMED})"
    why = "edit not confirmed, look at the playlist"      # not marked imported: a re-run can append it
    _note(store, d, "given_up", why, now)
    store.log(pid, wanted_id, "not_placed", f"{name}: {why}; re-run the import to append it")
    store.commit()
    return f"given up: {why}"
