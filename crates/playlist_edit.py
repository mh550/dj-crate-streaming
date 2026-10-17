"""The only code that edits playlist membership by index. Every M8 edit (copy replacement, repoint, proposals) goes here.

Measured fact 5 (Navidrome v0.64.2): "`GetWithTracks` filters `missing = false`, so getPlaylist hides an entry whose
file is gone, but its `playlist_tracks` row stays with its position. `songIndexToRemove=N` deletes position `N+1`
*counting hidden rows*, then renumbers. So once a playlist holds a missing song, visible indexes no longer match
positions and an index edit removes the wrong song." That is how the M2 retag + move broke playlists.

So every edit first cross-checks getPlaylist against navidrome.db (read-only, `open_ro`) and refuses when they
disagree, refuses when the playlist is not what the caller read, refuses smart playlists, writes in ONE updatePlaylist
and reads the result back. A refusal (`EditRefused`) is always safe: nothing was written. `EditNotKept` is not a
refusal: the write was sent and the readback differs. Nothing here trashes anything.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path

from scripts.export_playlists import open_ro


class EditRefused(Exception):
    """Nothing was written; the playlist is as it was."""


class PlaylistSkew(EditRefused):
    """getPlaylist and navidrome.db disagree: an index edit would hit the wrong row."""


class PlaylistChanged(EditRefused):
    """The playlist is not what the caller expected (edited meanwhile)."""


class NotEditable(EditRefused):
    """A smart playlist: Navidrome fills it from its rules, its tracks are not ours to edit."""


class NotOwned(EditRefused):
    """Another user's playlist (runbook: never touch the amperfy account's). Navidrome lets an admin edit it; we don't."""


class StaleSlot(EditRefused):
    """The slot the caller named no longer holds the song the caller expected."""


class EditNotKept(Exception):
    """The edit was sent, but the playlist read back afterwards is not what was written (another client edited it
    right after us, or Navidrome stored something else). Not a refusal: the caller must look before acting on it."""


def _smart(rules) -> bool:
    return rules is not None and str(rules).strip() not in ("", "null")


def _checked(client, db: Path, playlist_id: str) -> tuple[str, list[str]]:
    """(name, visible ids) once both views agree; see checked_entries."""
    pl = client.playlist(playlist_id)
    if pl.owner != client.user:
        raise NotOwned(f"owned by {pl.owner or '?'}")
    seen = [e.id for e in pl.entries]
    with closing(open_ro(db)) as con:
        row = con.execute("SELECT name, rules FROM playlist WHERE id = ?", (playlist_id,)).fetchone()
        rows = con.execute(
            "SELECT t.id, t.media_file_id, m.id IS NOT NULL, COALESCE(m.missing, 0) FROM playlist_tracks t"
            " LEFT JOIN media_file m ON m.id = t.media_file_id WHERE t.playlist_id = ? ORDER BY t.id",
            (playlist_id,)).fetchall()
    if row is None:
        raise PlaylistSkew(f"playlist {playlist_id} is not in navidrome.db")
    name = row[0] or playlist_id
    if _smart(row[1]):
        raise NotEditable(f"{name!r} is a smart playlist")
    for n, (pos, sid, known, missing) in enumerate(rows, 1):
        if pos != n:
            raise PlaylistSkew(f"{name!r}: navidrome.db positions are not 1..{len(rows)} (row {n} is position {pos})")
        if not known or missing:
            why = "a song Navidrome no longer has" if not known else "a song whose file is missing"
            raise PlaylistSkew(f"{name!r}: position {pos} holds {sid}, {why}; getPlaylist hides it, so an index "
                               "edit would hit the wrong row")
    stored = [sid for _, sid, _, _ in rows]
    if stored != seen:
        raise PlaylistSkew(f"{name!r}: getPlaylist shows {len(seen)} entries but navidrome.db holds {len(stored)}, "
                           "or in another order")
    return name, seen


def checked_entries(client, db: Path, playlist_id: str) -> list[str]:
    """The visible song ids of a playlist, safe to edit by index: raises PlaylistSkew unless navidrome.db's
    playlist_tracks for it, in position order, holds the same ids and every one is a present media_file row;
    NotEditable for a smart playlist; NotOwned unless getPlaylist's owner is the client's own user. The two reads are not atomic: an edit in between shows as a skew (a refusal)."""
    return _checked(client, db, playlist_id)[1]


def references(db: Path, song_id: str) -> list[tuple[str, int]]:
    """Every (playlist_id, 1-based position) holding the song, hidden (missing) rows included: getPlaylist would not
    show those, which is why the trash asks navidrome.db."""
    with closing(open_ro(db)) as con:
        return [(str(p), int(n)) for p, n in con.execute(
            "SELECT playlist_id, id FROM playlist_tracks WHERE media_file_id = ? ORDER BY playlist_id, id", (song_id,))]


def _present(db: Path, ids: list[str], name: str) -> None:
    """Adding a song Navidrome would hide creates exactly the skew this module guards against: refuse it."""
    with closing(open_ro(db)) as con:
        ok = {i for (i,) in con.execute(
            f"SELECT id FROM media_file WHERE missing = 0 AND id IN ({','.join('?' * len(ids))})", ids)}
    bad = [i for i in dict.fromkeys(ids) if i not in ok]
    if bad:
        raise PlaylistSkew(f"{name!r}: would add {', '.join(bad)}, not a present song in navidrome.db (it would be a "
                           "hidden row)")


def rewrite(client, db: Path, playlist_id: str, before: list[str], after: list[str]) -> None:
    """Turn the playlist from `before` into `after`. The current entries must equal `before` (else PlaylistChanged).
    Subsonic removes by index and only appends, so ONE updatePlaylist removes from the first differing index to the end
    and re-adds the tail of `after` (Navidrome applies it in one transaction, removals first). The readback must equal
    `after`, else EditNotKept. Once the write is sent, any failure (of the write or of the readback) is EditNotKept:
    whether it landed is unknown, so the caller has to look before acting on it."""
    before, after = list(before), list(after)
    name, cur = _checked(client, db, playlist_id)
    if cur != before:
        raise PlaylistChanged(f"{name!r} changed since it was read ({len(before)} entries expected, {len(cur)} now, "
                              "or other songs)")
    if after == before:
        return
    k = next((i for i, (a, b) in enumerate(zip(before, after)) if a != b), min(len(before), len(after)))
    if after[k:]:
        _present(db, after[k:], name)
    try:
        client.update_playlist(playlist_id, remove_indexes=list(range(k, len(before))), add_song_ids=after[k:])
    except Exception as e:
        raise EditNotKept(f"{name!r}: the edit failed and may or may not have landed: {e!r}") from e
    try:
        got = _checked(client, db, playlist_id)[1]
    except Exception as e:
        raise EditNotKept(f"{name!r}: edited, but the readback failed: {e!r}") from e
    if got != after:
        raise EditNotKept(f"{name!r}: edited, but the readback differs ({len(after)} entries written, {len(got)} read)")


def _remap(entries: list[str], old: str, new: str) -> list[str]:
    """dedupe_copies.remap's rule for one song: old becomes new in place; dropped when new is already there."""
    out: list[str] = []
    for e in entries:
        if e != old:
            out.append(e)
        elif new not in entries and new not in out:
            out.append(new)
    return out


def repoint_everywhere(client, db: Path, old: str, new: str, before_write=None) -> dict[str, str]:
    """Every playlist that holds `old` (navidrome.db, so not only crates and not only tiered playlists): old→new in
    place. Returns {playlist name: "repointed" | "skipped: smart playlist" | "refused: <why>" | "failed: <why>"};
    "refused" wrote nothing (another user's playlist reads "refused: owned by <owner>"); "failed" is any other error,
    and a write may have happened. A second playlist with the same name is keyed "<name> (<id>)", one whose name
    cannot be read is keyed by its id. One playlist's error does not stop the others; the caller trashes nothing
    unless references(db, old) is empty afterwards. `before_write(playlist_id, name, before, after)`, when given, is
    called once a playlist passed its checks and right before its write, with the entries the write replaces (the
    caller's reverse log); if it raises, that playlist is "failed" and not written."""
    if old == new:
        raise ValueError(f"repoint {old} to itself")
    out: dict[str, str] = {}
    for pid in dict.fromkeys(p for p, _ in references(db, old)):
        key = pid
        try:
            with closing(open_ro(db)) as con:
                row = con.execute("SELECT name FROM playlist WHERE id = ?", (pid,)).fetchone()
            name = (row[0] if row else None) or pid
            key = name if name not in out else f"{name} ({pid})"
            before = checked_entries(client, db, pid)
            after = _remap(before, old, new)
            if before_write is not None:
                before_write(pid, name, before, after)
            rewrite(client, db, pid, before, after)
            out[key] = "repointed"
        except NotEditable:
            out[key] = "skipped: smart playlist"
        except EditRefused as e:
            out[key] = f"refused: {e}"
        except Exception as e:                    # any error: recorded, the remaining playlists are still tried
            out[key] = f"failed: {e!r}" if not isinstance(e, EditNotKept) else f"failed: {e}"
    return out


def replace_slot(client, db: Path, playlist_id: str, index: int, old: str, new: str) -> None:
    """Only entries[index] (0-based, as the caller saw it) becomes `new`; StaleSlot when it no longer holds `old`.
    `new` may already be elsewhere in the playlist (a proposal swaps one slot, nothing else)."""
    cur = checked_entries(client, db, playlist_id)
    if not 0 <= index < len(cur) or cur[index] != old:
        raise StaleSlot(f"playlist {playlist_id}: slot {index} does not hold {old} any more")
    after = list(cur)
    after[index] = new
    rewrite(client, db, playlist_id, cur, after)
