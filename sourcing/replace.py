"""Copy replacement: a verified better copy of the same recording takes the old copy's place in every playlist, then
the old copy goes to the trash. The one code path in this project that removes a file from the library, so every
step refuses on doubt and nothing here guesses.

    repoint ─▶ trash ─▶ scan ─▶ done
       │  ▲      │         └─ (Navidrome still lists the old copy: waits, the worker re-checks)
       │  └──────┤  a playlist holds the old song again: back to repoint, never a move
       │         └─▶ blocked   the old copy moved or changed since it was compared, or is the new file
       └─ waits while any playlist entry (hidden ones included) still holds the old song

The licence (fetch decides before `start`, and every step re-checks the parts that can change):
  - the verification stored for this download says `measurements["replaceable"] is True` (the literal boolean:
    M7's decoded length vs the reference within tolerance, fingerprint BER ≤ 0.20, different files, ok) and
    names the reference it compared ({path, size, mtime_ns});
  - that reference is still the old song's file, byte-for-byte as compared: navidrome.db's path for the old song
    is the recorded `old_path`, which resolves to the reference path, with the same size and mtime;
  - identity.same_version agrees (its every doubt says "different"), and the old path is not the new one;
  - before the move, `playlist_edit.references(db, old)` is empty. repoint_everywhere's result values are never
    trusted for this: a smart playlist, another user's playlist or a hidden missing row keeps a reference, and
    then nothing moves (the reason is in the job's detail and the Log tab).

Order (measured fact 6): the new song was indexed by an earlier scan (fetch found its id), then every playlist is
repointed, then the old file moves, then a scan, so Navidrome never merges the two files into one id.

Each step commits its state before the next starts (`replacements` in crates.db): a crash anywhere leaves a row the
worker resumes, and each step is safe to run twice (a file already gone is not moved again).
"""
from __future__ import annotations

import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from crates import playlist_edit
from crates.store import REPLACEMENT_OPEN, CrateStore
from crates.trash import move_to_trash
from scripts.export_playlists import open_ro
from subsonic.client import SubsonicClient
from .identity import Copy, same_version
from .verify import MAX_SAME_BER


@dataclass
class Ctx:
    store: CrateStore
    navidrome: SubsonicClient
    navidrome_db: Path | None
    music_root: Path
    trash_root: Path | None
    forget: Callable[[Path], bool] | None            # BeetsFiler.forget in the worker; None: beets is not told
    reconciler: object | None = None                 # crates.reconcile.Reconciler: re-judges the repointed playlists
    scan_timeout_s: float = 120
    poll_s: float = 1.0


# --- the licence ---------------------------------------------------------------------------------------------------

def _reference_ok(ref) -> bool:
    """verify's record of the file it compared: {path: absolute str, size: int, mtime_ns: int}."""
    return (isinstance(ref, dict) and isinstance(ref.get("path"), str) and ref["path"].startswith("/")
            and all(isinstance(ref.get(k), int) and not isinstance(ref.get(k), bool) for k in ("size", "mtime_ns")))


def why_not(verification: dict | None) -> str | None:
    """None when the stored verification licenses a replacement, else why not (shown to Michael)."""
    if not isinstance(verification, dict) or verification.get("ok") is not True:
        return "verification failed"
    m = verification.get("measurements") or {}
    if m.get("intent") not in (None, "copy"):
        return "a new version never replaces a copy"
    if m.get("replaceable") is True and _reference_ok(m.get("reference")):
        return None
    ber = m.get("fingerprint_ber")
    if isinstance(ber, (int, float)) and ber > MAX_SAME_BER:
        return f"fingerprint differs (BER {ber:.2f})"
    if not _reference_ok(m.get("reference")) or m.get("reference_compared") is not True:
        return "no reference compared"
    ref_s, decoded_s = m.get("reference_duration_s"), m.get("decoded_s")
    if not decoded_s:
        return "decoded length not measured"
    if ref_s:
        return f"lengths differ (decoded {decoded_s:.0f}s, old copy {ref_s:.0f}s)"
    return "not marked replaceable"


def licensed(verification: dict | None) -> bool:
    """measurements["replaceable"] is True (the literal boolean) and the compared reference is recorded."""
    return why_not(verification) is None


def _media(db: Path, song_id: str) -> dict | None:
    with closing(open_ro(db)) as con:
        row = con.execute("SELECT path, artist, title, duration, COALESCE(missing, 0), COALESCE(mbz_recording_id, '') "
                          "FROM media_file WHERE id = ?", (song_id,)).fetchone()
    if row is None:
        return None
    return dict(zip(("path", "artist", "title", "duration", "missing", "recording_id"), row))


def song_path(db: Path, song_id: str) -> str | None:
    """navidrome.db's library-relative path for a song (None when it has no such row)."""
    with closing(open_ro(db)) as con:
        row = con.execute("SELECT path FROM media_file WHERE id = ?", (song_id,)).fetchone()
    return row[0] if row else None


def proof(ctx: Ctx, old_song_id: str, new_song_id: str, old_path: str, new_path: str, reference) -> str | None:
    """None when the old copy is still exactly what verify compared and identity calls the two one version; else why
    not. Reads navidrome.db and stats the old file; changes nothing. The caller has checked the file is there."""
    if not _reference_ok(reference):
        return "no reference compared"
    if ctx.navidrome_db is None:
        return "no navidrome.db to check the old copy against"
    old, new = _media(ctx.navidrome_db, old_song_id), _media(ctx.navidrome_db, new_song_id)
    if old is None:
        return f"the old song {old_song_id} is no longer in navidrome.db"
    if old["path"] != old_path:
        return f"old copy moved since verification (Navidrome now has {old['path']})"
    if new is None:
        return f"the new song {new_song_id} is not in navidrome.db"
    music = Path(ctx.music_root)
    src = music / old_path
    if old_path == new_path or src.resolve() == (music / new_path).resolve():
        return f"the new copy {new_path} is the old file"
    try:
        st = src.stat()
    except OSError as e:
        return f"old copy unreadable ({type(e).__name__})"
    if str(src.resolve()) != reference["path"]:
        return f"old copy {old_path} is not the file verification compared"
    if (st.st_size, st.st_mtime_ns) != (reference["size"], reference["mtime_ns"]):
        return f"old copy {old_path} changed since verification (size or mtime)"
    a = Copy(old["artist"] or "", old["title"] or "", old["duration"] or None, old["recording_id"])
    b = Copy(new["artist"] or "", new["title"] or "", new["duration"] or None, new["recording_id"])
    if not same_version(a, b):
        return f"identity says another version ({a.artist} – {a.title} vs {b.artist} – {b.title})"
    return None


# --- the job -------------------------------------------------------------------------------------------------------

def start(store: CrateStore, *, wanted_id: str, old_song_id: str, new_song_id: str, old_path: str, new_path: str,
          reference: dict | None = None) -> int:
    """Record the replacement (state `repoint`) before any step runs; returns its id."""
    return store.add_replacement(wanted_id=wanted_id, old_song_id=old_song_id, new_song_id=new_song_id,
                                 old_path=old_path, new_path=new_path, reference=reference)


def open_for(store: CrateStore, old_song_id: str) -> dict | None:
    """The unfinished replacement of this old song, if any: a second one is never started beside it."""
    return next((j for j in store.open_replacements() if j["old_song_id"] == old_song_id), None)


def advance(job_id: int, ctx: Ctx) -> str:
    """Run the job's steps until it is done, blocked or waiting; returns its state. An exception propagates with the
    job left in the state it had (the worker logs it and tries again next tick). Safe to call any number of times."""
    for _ in range(8):                 # repoint → trash → (back to repoint at most once more) → scan → done
        job = ctx.store.replacement(job_id)
        state = job["state"]
        if state not in REPLACEMENT_OPEN:
            return state
        if _STEPS[state](job, ctx) == state:
            return state                                  # waiting: the worker comes back
    return ctx.store.replacement(job_id)["state"]


def _set(ctx: Ctx, job: dict, state: str, detail: str | None = None, **cols) -> str:
    ctx.store.set_replacement(job["id"], state, detail, **cols)
    return state


def _reconcile(ctx: Ctx, playlist_ids) -> None:
    """Re-judge the tiered playlists a repoint touched, so the new song's rows appear and the old song's go; a failure
    is logged (the next reconcile catches up), never fatal to the replacement."""
    if ctx.reconciler is None:
        return
    for pid in sorted(set(playlist_ids)):
        if ctx.store.playlist_tier(pid) is None:
            continue
        try:
            ctx.reconciler.reconcile_playlist(ctx.navidrome.playlist(pid))
        except Exception as e:
            ctx.store.log(pid, None, "reconcile", f"not re-judged after a copy replacement: {type(e).__name__}: {e}")
            ctx.store.commit()


def _repoint(job: dict, ctx: Ctx) -> str:
    old, new = job["old_song_id"], job["new_song_id"]
    music = Path(ctx.music_root)
    if old == new:
        return _set(ctx, job, "blocked", "the new copy has the old song's id")
    if ctx.navidrome_db is None or ctx.trash_root is None:
        return _set(ctx, job, "repoint", "waiting: no navidrome.db or trash configured here")
    if (music / job["old_path"]).exists():
        why = proof(ctx, old, new, job["old_path"], job["new_path"], job["reference"])
        if why:
            return _set(ctx, job, "blocked", why)
    held = {p for p, _ in playlist_edit.references(ctx.navidrome_db, old)} | ctx.store.playlists_holding([old])
    results = playlist_edit.repoint_everywhere(ctx.navidrome, ctx.navidrome_db, old, new)
    _reconcile(ctx, held)
    left = playlist_edit.references(ctx.navidrome_db, old)
    if left:
        why = "; ".join(f"{name}: {r}" for name, r in results.items() if r != "repointed")
        return _set(ctx, job, "repoint", f"old song still in {len(left)} playlist entr{'y' if len(left) == 1 else 'ies'}"
                                         + (f" ({why})" if why else " (added again meanwhile)"))
    _settle(ctx, job)
    done = sum(r == "repointed" for r in results.values())
    return _set(ctx, job, "trash", f"repointed {done} playlist{'' if done == 1 else 's'}")


def _trash(job: dict, ctx: Ctx) -> str:
    old, rel = job["old_song_id"], job["old_path"]
    if ctx.navidrome_db is None or ctx.trash_root is None:
        return _set(ctx, job, "trash", "waiting: no navidrome.db or trash configured here")
    left = playlist_edit.references(ctx.navidrome_db, old)
    if left:                                              # someone put it back: repoint again before anything moves
        return _set(ctx, job, "repoint", f"old song back in {len(left)} playlist entr{'y' if len(left) == 1 else 'ies'}")
    src = Path(ctx.music_root).absolute() / rel
    if not src.exists():
        now = song_path(ctx.navidrome_db, old)
        if now is not None and now != rel:
            return _set(ctx, job, "blocked", f"old copy moved since verification (Navidrome now has {now})")
        _forget(ctx, job, src)
        return _set(ctx, job, "scan", "old copy already gone")
    why = proof(ctx, old, job["new_song_id"], rel, job["new_path"], job["reference"])
    if why:
        return _set(ctx, job, "blocked", why)
    dst = move_to_trash(rel, ctx.music_root, ctx.trash_root)
    ctx.store.set_replacement(job["id"], "trash", job["detail"], trash_path=str(dst))   # recorded before anything else
    _forget(ctx, job, src)
    return _set(ctx, job, "scan", f"old copy moved to {dst}")


def _forget(ctx: Ctx, job: dict, src: Path) -> None:
    """beets' index is a disposable cache: a failure is logged, never fatal."""
    if ctx.forget is None:
        return
    try:
        ok = ctx.forget(src)
    except Exception as e:
        ok, why = False, f"{type(e).__name__}: {e}"
    else:
        why = "beet remove failed"
    if not ok:
        ctx.store.log(None, job["old_song_id"], "replace", f"#{job['id']}: beets still lists {job['old_path']} ({why})")
        ctx.store.commit()


def _old_listed(ctx: Ctx, old: str) -> bool:
    m = _media(ctx.navidrome_db, old)
    return m is not None and not m["missing"]


def _scan(job: dict, ctx: Ctx) -> str:
    if ctx.navidrome_db is None:
        return _set(ctx, job, "scan", "waiting: no navidrome.db configured here")
    if _old_listed(ctx, job["old_song_id"]):
        ctx.navidrome.start_scan()
        t0 = time.time()
        while ctx.navidrome.scan_status().get("scanning") and time.time() - t0 < ctx.scan_timeout_s:
            time.sleep(ctx.poll_s)
        if _old_listed(ctx, job["old_song_id"]):
            return _set(ctx, job, "scan", "waiting for Navidrome to see the old copy gone")
    return _set(ctx, job, "done", "Navidrome no longer lists the old copy")


_STEPS = {"repoint": _repoint, "trash": _trash, "scan": _scan}


def _settle(ctx: Ctx, job: dict) -> None:
    """Every playlist now holds the new song: an external row (play-now's provisional copy, Task 11) is done and
    names it; a playlist row's old rows were removed by the reconcile."""
    wid = job["wanted_id"]
    if wid.startswith("ext-") and ctx.store.external(wid) is not None:
        ctx.store.set_library_song(wid, job["new_song_id"])
        ctx.store.set_wanted_status(wid, "ok", f"filed as {job['new_path']}; replaced {job['old_path']}")
