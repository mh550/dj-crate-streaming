"""Questions about one playlist slot (D23): "replace X with Y in P at slot n?". Michael answers them.

The playlists are Michael's (fact #5), so a new *version* never replaces anything by itself, even when the playlist's
tier prefers it (D16: crates prefer 12"/extended): its arrival only asks. So does a better copy that verify could not
prove is the same recording (sourcing.fetch keeps both). Two kinds:

  version_swap   a filed song is another version of a song a tiered playlist holds, and that tier prefers it
                 (version_rank, the scorer's D16 bonus) over what the slot holds
  unproven_copy  a copy upgrade kept beside the old copy (no proof): one question per slot of the old song in a
                 tiered playlist; its row is `review` until every one is answered

Creation decides what Michael is asked, so it errs toward silence: no question for the same version, another song,
an untiered playlist, a playlist that holds the new song already, a version the tier does not prefer at least as
much as what the slot holds, or one that drops what the slot specifically is (an instrumental, a credited mix). A
question is asked once per slot and never again after a no (store.add_proposal).

Accepting is one guarded index edit (crates.playlist_edit.replace_slot) of that slot only; it never trashes anything
(a version is a different recording, an unproven copy is not proven redundant: the old file stays in the library).
Any doubt (the slot no longer holds the old song, the playlist changed, a hidden row, a smart or foreign playlist)
answers `stale` and writes nothing. Accepting a slot makes the other open questions about it stale.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from scripts.export_playlists import open_ro
from sourcing.identity import NEUTRAL, Copy, loose, parse_title, same_version, song_key
from sourcing.policy import TIERS
from sourcing.scorer import version_rank
from .playlist_edit import EditNotKept, EditRefused, StaleSlot, checked_entries, replace_slot
from .store import DECIDERS


class Decided(Exception):
    """The proposal was answered already; nothing was done."""


@dataclass(frozen=True)
class _Song:
    id: str
    title: str
    artist: str
    duration: float | None
    recording_id: str
    path: str

    @property
    def copy(self) -> Copy:
        return Copy(self.artist, self.title, self.duration, recording_id=self.recording_id)

    @property
    def key(self) -> str:
        return song_key(self.artist, self.title)


@dataclass(frozen=True)
class _Slot:
    playlist_id: str
    name: str
    index: int                 # 0-based, as getPlaylist shows it (hidden rows not counted)
    song: _Song


_COLS = "m.id, COALESCE(m.title, ''), COALESCE(m.artist, ''), m.duration, COALESCE(m.mbz_recording_id, ''), m.path"


def _song(con, song_id: str) -> _Song | None:
    row = con.execute(f"SELECT {_COLS} FROM media_file m WHERE m.id = ? AND NOT COALESCE(m.missing, 0)",
                      (song_id,)).fetchone()
    return _Song(*row) if row else None


def _slots(con, playlist_ids) -> list[_Slot]:
    """Every visible entry of these playlists, from navidrome.db, with the index getPlaylist would show it at."""
    ids = list(playlist_ids)
    if not ids:
        return []
    out: list[_Slot] = []
    seen: dict[str, int] = {}
    for pid, name, present, *song in con.execute(
            f"SELECT t.playlist_id, COALESCE(p.name, t.playlist_id), m.id IS NOT NULL AND NOT COALESCE(m.missing, 0), "
            f"{_COLS} FROM playlist_tracks t LEFT JOIN playlist p ON p.id = t.playlist_id "
            f"LEFT JOIN media_file m ON m.id = t.media_file_id "
            f"WHERE t.playlist_id IN ({','.join('?' * len(ids))}) ORDER BY t.playlist_id, t.id", ids):
        if not present:                       # hidden by getPlaylist: no index, and never a slot to swap
            continue
        n = seen.get(pid, 0)
        seen[pid] = n + 1
        out.append(_Slot(pid, name, n, _Song(*song)))
    return out


def _secs(s: _Song) -> str:
    return f"{round(s.duration)} s" if s.duration else "length unknown"


def _keeps(new, old) -> bool:
    """The new version keeps what the slot's version specifically is: every kind it names beyond an edit (an
    instrumental, a dub, a remix) and every credit (a Larry Levan mix is not any extended mix). The same rule as
    identity.stands_in, without its "adds an accepted kind" half (version_rank decides preference)."""
    credits = {b for b in old.by.split("|") if b}
    return old.kinds - {"edit"} - NEUTRAL <= new.kinds and credits <= set(new.by.split("|"))


def version_swaps(store, db: Path, new_song_id: str) -> list[int]:
    """Ask, for each slot of a tiered playlist (the cache's effective tier) holding another version of the new song
    that the tier prefers it over, whether to swap. Returns the new proposals' ids. Reads navidrome.db only."""
    tiers = {c.playlist_id: c.effective for c in store.tiered()}
    with closing(open_ro(db)) as con:
        new = _song(con, new_song_id)
        slots = _slots(con, tiers) if new is not None else []
    if new is None:
        return []
    nt = parse_title(new.title, new.artist)
    holding_new = {s.playlist_id for s in slots if s.song.id == new.id}
    out = []
    for s in slots:
        old = s.song
        if old.id == new.id or s.playlist_id in holding_new or old.key != new.key or same_version(old.copy, new.copy):
            continue
        policy = TIERS[tiers[s.playlist_id]]
        rank = version_rank(nt, policy)
        ot = parse_title(old.title, old.artist)
        held = version_rank(ot, policy)
        if rank is None or (held is not None and held <= rank) or not _keeps(nt, ot):
            continue
        shown = f"({nt.label})" if nt.label and loose(nt.base) == loose(ot.base) else new.title
        pid = store.add_proposal(
            kind="version_swap", playlist_id=s.playlist_id, position=s.index, old_song_id=old.id,
            new_song_id=new.id, new_path=new.path,
            summary=f"{s.name} #{s.index + 1}: {old.title} ({_secs(old)}) → {shown} ({_secs(new)})")
        if pid is not None:
            out.append(pid)
    return out


def unproven_copy(store, db: Path, old_song_id: str, new_song_id: str, why: str, wanted_id: str) -> list[int]:
    """One question per slot of the old song in a tiered playlist: use the new copy there? (fetch kept both because
    `why`). Returns the new proposals' ids."""
    tiers = {c.playlist_id: c.effective for c in store.tiered()}
    with closing(open_ro(db)) as con:
        new = _song(con, new_song_id)
        slots = [s for s in _slots(con, tiers) if s.song.id == old_song_id]
    new_path = new.path if new is not None else f"song {new_song_id}"
    out = []
    for s in slots:
        pid = store.add_proposal(
            kind="unproven_copy", playlist_id=s.playlist_id, position=s.index, old_song_id=old_song_id,
            new_song_id=new_song_id, wanted_id=wanted_id, new_path=new_path,
            summary=f"{s.name} #{s.index + 1}: {s.song.title} ({_secs(s.song)}, {s.song.path}) → new copy {new_path}"
                    f"{f' ({_secs(new)})' if new else ''}; not proven the same recording ({why})")
        if pid is not None:
            out.append(pid)
    return out


def _open(store, proposal_id: int, decided_by: str) -> dict:
    """The open proposal, checked before anything is done: KeyError, Decided, or ValueError for a decider outside
    the approver vocabulary."""
    if not DECIDERS.fullmatch(decided_by or ""):
        raise ValueError(f"decided_by {decided_by!r}: michael, policy:<name> or agent:<id>")
    p = store.proposal(proposal_id)
    if p is None:
        raise KeyError(f"no proposal #{proposal_id}")
    if p["decision"] is not None:
        raise Decided(f"proposal #{proposal_id} is {p['decision']} already ({p['decided_by']}: {p['result']})")
    return p


def _settle(store, p: dict) -> None:
    """An unproven copy whose questions are all answered: when one was not accepted, its old song's rows that are
    still `review` fail with where the new copy is (an accepted slot's row left with the slot: reconcile)."""
    w = p["wanted_id"]
    if p["kind"] != "unproven_copy" or not w:
        return
    mine = [q for q in store.proposals(open_only=False) if q["kind"] == "unproven_copy" and q["wanted_id"] == w
            and q["new_song_id"] == p["new_song_id"]]
    if any(q["decision"] is None for q in mine) or all(q["decision"] == "accepted" for q in mine):
        return
    row = store.find_wanted(w)
    if row is not None and row["status"] == "review":
        how = "declined" if any(q["decision"] == "declined" for q in mine) else "not made"
        store.set_wanted_status(w, "failed", f"swap {how}; the new copy stays in the library as {p['new_path']}")


def apply(store, client, db: Path, proposal_id: int, decided_by: str, reconciler=None) -> str:
    """Accept: the slot must still hold the old song, at its index or, when it moved, at the one index holding it;
    then replace_slot there and nothing else. Any refusal answers `stale` with the reason and writes nothing; an
    edit sent but not read back as written answers `stale` too, saying so (look at the playlist). Never trashes.
    A tiered playlist is re-judged afterwards (`reconciler`, else a new Reconciler) so its rows follow the slot.
    Returns the result text. KeyError for an unknown id, Decided for an answered one."""
    p = _open(store, proposal_id, decided_by)
    pid, old, new = p["playlist_id"], p["old_song_id"], p["new_song_id"]
    try:
        entries = checked_entries(client, db, pid)
        if 0 <= p["position"] < len(entries) and entries[p["position"]] == old:
            index = p["position"]
        else:
            at = [i for i, e in enumerate(entries) if e == old]
            if len(at) != 1:
                raise StaleSlot(f"slot {p['position'] + 1} no longer holds {old}, and "
                                + ("no other slot does" if not at else f"{len(at)} slots do"))
            index = at[0]
        replace_slot(client, db, pid, index, old, new)
    except EditRefused as e:
        result = f"nothing changed: {e}"
        store.decide(proposal_id, "stale", decided_by, result)
        _settle(store, p)
        return result
    except EditNotKept as e:
        result = f"edit sent but not confirmed, look at the playlist: {e}"
        store.decide(proposal_id, "stale", decided_by, result)
        _settle(store, p)
        return result
    result = f"slot {index + 1} now holds {new} (was {old}); nothing trashed"
    store.decide(proposal_id, "accepted", decided_by, result)
    for q in store.proposals():
        if q["playlist_id"] == pid and q["old_song_id"] == old and q["position"] in (p["position"], index):
            store.decide(q["id"], "stale", decided_by, f"superseded by #{proposal_id}")
    if store.playlist_tier(pid) is not None:
        if reconciler is None:
            from .reconcile import Reconciler
            reconciler = Reconciler(client, store)
        try:
            reconciler.reconcile_playlist(client.playlist(pid))
        except Exception as e:                   # the edit stands; the next reconcile re-judges the playlist
            store.log(pid, new, "proposal", f"#{proposal_id} accepted; re-judging the playlist failed: {e!r}")
            store.commit()
    _settle(store, p)
    return result


def decline(store, proposal_id: int, decided_by: str) -> None:
    """No: the playlist stays as it is, and the same question is never asked again (store.add_proposal). The last
    open question of an unproven copy fails its row, naming where the new copy is."""
    p = _open(store, proposal_id, decided_by)
    store.decide(proposal_id, "declined", decided_by, "declined; the playlist is unchanged")
    _settle(store, p)
