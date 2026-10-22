"""The Navidrome duplicate cleanup (D31): keep the best copy of each recording, repoint the playlists, trash the rest.

    docker compose exec -T worker python3 -m scripts.duplicate_cleanup plan [--limit N] [--out DIR]
        → $CLEANUP_DIR/plan.json + report.md (default /data/duplicate-cleanup = /srv/docker/crates/duplicate-cleanup/)

`plan` is read-only: it opens navidrome.db read-only, looks at music_root, and writes only into --out. It recomputes
the groups from the live navidrome.db every run (scripts.duplicate_report.load + duplicate_groups, never from
docs/duplicates-report.md); the first file of a group (keep_rank: lossless, then bit rate, then the properly filed
path) is the keeper. A group is held, listed only, when the keeper's file is not on disk. An extra that is lossless
beside a lossless keeper is acted on like any other, with a "note" on its group (D35, Michael 2026-10-19: trash the
extras); `plan --hold-lossless` holds such a group as "both lossless" instead. `held_by` names
every playlist holding an extra in navidrome.db, hidden rows and other users' playlists included
(crates.playlist_edit.references), because the trash must wait until none does. `playlists` previews each rewrite
(scripts.dedupe_copies.remap); repoint does not replay it. An existing plan.json is copied to plan-<its made_at>.json
first, so a hand-edited hold is never lost to a re-run.

    docker compose exec -T worker python3 -m scripts.duplicate_cleanup repoint [--plan P] [--limit N] [--dry-run]

`repoint` moves every playlist from each extra to its keeper, only through crates.playlist_edit.repoint_everywhere,
which reads each playlist's current entries (the plan's `playlists` preview is not replayed) and refuses on a hidden
row, a smart playlist, another owner or a concurrent edit. Per unheld extra it first re-checks the live navidrome.db
(the keeper is a present row, extra and keeper still one duplicate group). For each playlist that passed its checks,
right before its write, one reverse line {ts, playlist_id, name, extra, keeper, before, after} goes to
repoint-<UTC ts>.jsonl beside the plan (fsynced); `before` is exactly what the write replaces. Replaying the lines
newest first with playlist_edit.rewrite(client, db, id, after, before) undoes it; a line whose write then failed
replays as PlaylistChanged, which changes nothing. Every run that is not a dry run and reached a playlist check ends
with one waited scan (the scan between repoint and trash), so a re-run after a timed-out scan scans again. Exit 1
when any playlist was refused or failed or the scan did not finish: the runbook stops there. `--dry-run` runs the
same checks read-only (repoint_everywhere(dry_run=True)) and names each playlist the real run would refuse, with
why ("dry run: would refuse <playlist>: <why>; …; would repoint <names>"), and exits 1 then too. Each playlist written is
a crates.db event (kind `cleanup`, song_id = the extra, "repointed <playlist> to <keeper>"); a dry run opens no
crates.db.

    docker compose stop worker
    docker compose run --rm worker python3 -m scripts.duplicate_cleanup trash [--plan P] [--limit N] [--dry-run]

`trash` (D36: only with the worker stopped; it holds <dirname(CRATES_DB)>/worker.lock for the whole run, and refuses
while a Navidrome scan runs, checked again before every move, and unless getScanStatus' lastScan is after the newest
repoint-*.jsonl beside the plan was last written) moves each unheld extra to the trash with
crates.trash.move_to_trash, whose reverse `mv` line is in <trash>/<day>/MOVES.txt before the move. Per extra, right
before acting: the keeper is a present row and a file on disk (an unmounted library is never "already gone"), the
extra has not moved since the plan, the pair is still one duplicate group, keeper and extra are different files,
the extra's size on disk is its media_file.size and the plan's (not a new file filed at its path since the plan),
crates.playlist_edit.references(db, extra) is empty (hidden rows and other users' playlists included) and no
crates.db row is still working with it (CrateStore.song_in_use). references() is read again right after the move and
after the closing scan; a row added meanwhile puts the file back (crates.trash.restore). Then beets forgets the old
path (a failure is noted, not fatal) and one line {ts, extra, path, keeper, trash_path, forgotten} goes to
trash-<UTC ts>.jsonl beside the plan. A file already gone is `already gone`; while a playlist row, hidden or not,
still names it, the file goes back from the trash log's trash_path (an earlier run's scan did not finish, so Amperfy
could add it; "refused: … put back", then a scan), or it is `failed` without one; beets forgets it unless the trash log says it did (a crash between the move and forget, or a
forget that failed, heals on the next run). The library and the trash must be mounted. One waited scan after a run
that moved a file, and one more when a file was put back after it (that scan marked it missing). Each move and put-back
is a crates.db event (kind `cleanup`, "trashed to <day>/<path>", "put back from <day>/<path>: …", trash-relative: the
absolute paths are in MOVES.txt). Exit 1 when anything was refused or failed; a refusal mid-run still re-checks the
files it moved (docs/plans/2026-10-17-n1-duplicate-cleanup.md §trash). A scan that starts mid-run, with files moved,
is waited for, then one more scan sees every move, and the moved files are re-read and put back as after the
closing scan (review I3): until a scan marks it missing, Navidrome lists a trashed song and Amperfy can add it. The
closing scan waits out a running scan before it starts its own, and a file that stays moved always gets its trash
line, even when its put-back failed, so a later run puts it back from there.

repoint and trash read SUBSONIC_* through crates.service.Config.from_env and need CRATES_DB set to an existing
crates.db (exit 2 otherwise; never a stray one, never from_env's ./data default). Events are a copy of the jsonl logs:
one that cannot be written is noted on stderr and fails nothing. Every path defaults from the worker's environment
(NAVIDROME_DB, MUSIC_ROOT, TRASH_ROOT, CLEANUP_DIR), so the runbook needs no path flags.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import sys
from contextlib import closing
from functools import partial
from pathlib import Path

try:
    from crates.playlist_edit import references, repoint_everywhere
    from crates.service import Config
    from crates.store import CrateStore
    from crates.trash import free_path, move_to_trash, restore
    from scripts.dedupe_copies import remap
    from scripts.duplicate_report import DEFAULT_DB, LOSSLESS, duplicate_groups, load
    from scripts.export_playlists import open_ro
    from sourcing.worker import WorkerRunning, hold_lock
    from subsonic.client import SubsonicClient, scan_and_wait, wait_for_scan
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from crates.playlist_edit import references, repoint_everywhere
    from crates.service import Config
    from crates.store import CrateStore
    from crates.trash import free_path, move_to_trash, restore
    from scripts.dedupe_copies import remap
    from scripts.duplicate_report import DEFAULT_DB, LOSSLESS, duplicate_groups, load
    from scripts.export_playlists import open_ro
    from sourcing.worker import WorkerRunning, hold_lock
    from subsonic.client import SubsonicClient, scan_and_wait, wait_for_scan

DEFAULT_OUT = Path("/data/duplicate-cleanup")


def _file(row: dict) -> dict:
    return {"id": row["id"], "path": row["path"], "suffix": row["suffix"], "bit_rate": row["bit_rate"],
            "size": row["size"]}


def _lossless(row: dict) -> bool:
    return row["suffix"].lower() in LOSSLESS


LOSSLESS_PAIR = "lossless pair: released by Michael 2026-10-19 (D35)"


def _hold(keep: dict, extras: list[dict], music_root: Path, hold_lossless: bool) -> tuple[str | None, str | None]:
    """(hold, note): hold None acts on the group; a lossless pair is released with a note unless hold_lossless."""
    if not (music_root / keep["path"]).is_file():
        return "keeper missing on disk", None
    if _lossless(keep) and any(_lossless(e) for e in extras):
        return ("both lossless", None) if hold_lossless else (None, LOSSLESS_PAIR)
    return None, None


def build_plan(navidrome_db: Path, music_root: Path, limit: int | None = None, hold_lossless: bool = False) -> dict:
    """The plan for the current navidrome.db; `limit` keeps the first N unheld groups (held ones are all listed);
    `hold_lossless` holds a lossless pair, which D35 otherwise releases."""
    rows, _ = load(navidrome_db)
    picked, unheld = [], 0
    for g in duplicate_groups(rows):
        keep, extras = g[0], g[1:]
        hold, note = _hold(keep, extras, Path(music_root), hold_lossless)
        if hold is None:
            if limit is not None and unheld >= limit:
                continue
            unheld += 1
        picked.append((keep, extras, hold, note))
    with closing(open_ro(navidrome_db)) as con:          # one snapshot: held_by and the previews agree
        names = dict(con.execute("SELECT id, name FROM playlist"))
        tracks: dict[str, list[str]] = {}
        for pid, sid in con.execute("SELECT playlist_id, media_file_id FROM playlist_tracks ORDER BY playlist_id, id"):
            tracks.setdefault(pid, []).append(sid)
    groups, replace, touched = [], {}, {}
    for keep, extras, hold, note in picked:
        pids = [[pid for pid, sids in tracks.items() if e["id"] in sids] for e in extras]   # hidden rows included
        groups.append({"keep": _file(keep), "extras": [
            dict(_file(e), held_by=[names.get(pid) or pid for pid in ps]) for e, ps in zip(extras, pids)], "hold": hold})
        if note:
            groups[-1]["note"] = note
        if hold is None:
            replace.update((e["id"], keep["id"]) for e in extras)
            touched.update(dict.fromkeys(pid for ps in pids for pid in ps))
    playlists = [{"id": pid, "name": names.get(pid) or pid, "before": tracks[pid], "after": remap(tracks[pid], replace)}
                 for pid in touched if pid in tracks]       # one deleted meanwhile has nothing to repoint
    return {"made_at": _now(), "groups": groups, "playlists": playlists}


def _n(k: int, word: str) -> str:
    return f"{k} {word}{'' if k == 1 else 's'}"


def counts(plan: dict) -> str:
    act = [g for g in plan["groups"] if g["hold"] is None]
    extras = [e for g in act for e in g["extras"]]
    return (f"{_n(len(act), 'group')} to act on ({_n(len(extras), 'extra')}, {sum(bool(e['held_by']) for e in extras)} "
            f"in a playlist), {len(plan['groups']) - len(act)} held, {_n(len(plan['playlists']), 'playlist')} to repoint")


def _line(label: str, f: dict) -> str:
    use = f" · in playlists: {', '.join(f['held_by']) or 'none'}" if "held_by" in f else ""
    return f"- {label} `{f['path']}` · {f['suffix']} {f['bit_rate'] or '?'} kbps · {f['id']}{use}"


def render(plan: dict) -> str:
    out = ["# Duplicate cleanup plan", "",
           f"Made {plan['made_at']} by `python3 -m scripts.duplicate_cleanup plan`. Nothing was moved or edited.", "",
           f"- {counts(plan)}", "", "## Groups to act on", "",
           "The keeper stays; every playlist is repointed from each extra to it, then the extras go to the trash.", ""]
    for g in plan["groups"]:
        if g["hold"] is None:
            out += [_line("**keep**", g["keep"])] + [_line("extra", e) for e in g["extras"]] + [""]
    out += ["## Held groups (listed only)", "",
            'Nothing here is touched. To act on a "both lossless" group, set its "hold" to null in plan.json.', ""]
    for g in plan["groups"]:
        if g["hold"] is not None:
            out += [f"**{g['hold']}**", _line("**keep**", g["keep"])] + [_line("extra", e) for e in g["extras"]] + [""]
    out += ["## Playlists to repoint", ""]
    out += [f"- {p['name']}: {len(p['before'])} → {len(p['after'])} entries" for p in plan["playlists"]]
    return "\n".join(out) + "\n"


def write_plan(plan: dict, out_dir: Path) -> Path:
    """out_dir/plan.json and report.md; an existing plan.json (maybe with holds edited by hand) is copied aside to
    plan-<its made_at>.json first, and the new one replaces it atomically."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "plan.json"
    if path.exists():
        try:
            old = re.sub(r"[^0-9TZ-]", "", str(json.loads(path.read_text(encoding="utf-8"))["made_at"])) or "old"
        except (ValueError, KeyError, TypeError):
            old = "old"
        shutil.copy2(path, free_path(out_dir / f"plan-{old}.json"))
    tmp = out_dir / "plan.json.tmp"
    tmp.write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    (out_dir / "report.md").write_text(render(plan), encoding="utf-8")
    return path


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _recheck(rows: list[dict], group_of: dict[str, int], keeper: str, extra: str) -> str | None:
    """Why the live navidrome.db no longer allows acting on extra → keeper, or None (plan §Recompute). `rows` is
    load()'s present rows, `group_of` maps each id to its duplicate_groups index."""
    if keeper == extra:                                  # only a hand-edited plan can say this
        return f"skipped: no longer a duplicate of {keeper}"
    if keeper not in {r["id"] for r in rows}:
        return "skipped: keeper missing"
    if extra not in group_of or group_of.get(keeper) != group_of[extra]:
        return f"skipped: no longer a duplicate of {keeper}"
    return None


def _in_scope(plan: dict, limit: int | None):
    """The plan's groups in order; `limit` counts the groups to act on, held ones are always reported."""
    n = 0
    for g in plan["groups"]:
        if g["hold"] is None:
            if limit is not None and n >= limit:
                continue
            n += 1
        yield g


def _summary(results: dict[str, str]) -> str:
    """One value for an extra from repoint_everywhere's {playlist: result}."""
    done = sum(v == "repointed" for v in results.values())
    bad = {k: v for k, v in results.items() if v != "repointed"}
    if not bad:
        return f"repointed {_n(done, 'playlist')}"
    kind = "failed" if any(v.startswith("failed") for v in bad.values()) else "refused"
    parts = [f"{k}: {v.removeprefix('refused: ')}" for k, v in bad.items()]
    return f"{kind}: {'; '.join(parts)}; repointed {_n(done, 'playlist')}"


def _preview(results: dict[str, str]) -> str:
    """One value for an extra from a dry-run repoint_everywhere: what the real run would refuse first, with why."""
    ok = [k for k, v in results.items() if v == "would repoint"]
    bad = [f"{k}: {v.removeprefix('refused: ')}" for k, v in results.items() if v != "would repoint"]
    would = f"would repoint {', '.join(ok) or 'nothing'}"
    return f"dry run: would refuse {'; '.join(bad)}; {would}" if bad else f"dry run: {would}"


def _append(log_path: Path, line: dict) -> None:
    """One JSON line, fsynced, stamped with ts."""
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(ts=_now(), **line), ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _group_of(rows: list[dict]) -> dict[str, int]:
    """song id → its duplicate group's index, from navidrome.db as it is now (groups are recomputed before acting)."""
    return {r["id"]: i for i, grp in enumerate(duplicate_groups(rows)) for r in grp}


def _restored(log_path: Path, extra: str, rel: str, dst: Path) -> None:
    """The trash line of a put-back: that move is undone (a later run reads the extra as never moved)."""
    _append(log_path, {"extra": extra, "path": rel, "keeper": None, "trash_path": str(dst), "restored": True})


def _reverse(log_path: Path, extra: str, keeper: str, pid: str, name: str, before: list, after: list) -> None:
    """repoint_everywhere's before_write: the reverse line, on disk before the playlist's write."""
    _append(log_path, {"playlist_id": pid, "name": name, "extra": extra, "keeper": keeper, "before": before,
                       "after": after})


def failed(out: dict[str, str]) -> bool:
    """True when a value needs Michael: a playlist or a move refused or failed (or, in a dry run, would be), or the
    scan did not finish."""
    return any(v.startswith(("refused:", "failed:", "dry run: would refuse")) for v in out.values())


def _event(store, playlist_id: str | None, song_id: str, detail: str) -> None:
    """A crates.db event, kind `cleanup` (None: no crates.db here), committed at once so no write lock is held over
    a scan. A copy of the jsonl logs, which stay the record: one that cannot be written (crates.db busy) is noted on
    stderr and never fails the repoint or the move it describes."""
    if store is None:
        return
    try:
        store.log(playlist_id, song_id, "cleanup", detail)
        store.commit()
    except Exception as ex:
        print(f"event not logged ({detail}): {ex!r}", file=sys.stderr)


def _repoint_store(store, navidrome_db: Path, extra: str, keeper: str) -> str | None:
    """Once no playlist holds the extra (hidden rows included): crates.db's import orders, imported_entries, filed
    rows and unfinished placements name the keeper (CrateStore.repoint_song, review N4-05 I2), with a `cleanup`
    event naming both ids when anything changed. Called after each repoint and by trash right before the move (a
    trashed extra is no longer a duplicate, so no later repoint reaches it). The two are copies of one version, so a
    playlist reverse-repointed later keeps a correct, if less exact, record; the rows changed are in
    songs-repointed.jsonl beside crates.db. A failure (crates.db busy, navidrome.db unreadable) is rolled back,
    noted on stderr like _event's and returned: it never fails the repoint (trash repoints again before the move),
    but trash then leaves the file (review N5-02 I1), since nothing reaches a trashed extra later."""
    if store is None:
        return None
    try:
        if references(navidrome_db, extra):
            return None
        n = store.repoint_song(extra, keeper)
        if any(n.values()):
            store.log(None, extra, "cleanup", f"crates.db now names {keeper}: {n['import_order']} import order, "
                      f"{n['imported_entries']} imported, {n['external_wanted']} filed rows, "
                      f"{n['placements']} placements")
        store.commit()
    except Exception as ex:
        try:
            store.db.rollback()                  # never hold crates.db's write lock over the scan that follows
        except Exception:
            pass
        print(f"crates.db not repointed ({extra} -> {keeper}): {ex!r}", file=sys.stderr)
        return repr(ex)
    return None


def _fresh_scan(client, timeout_s: float, poll_s: float) -> str:
    """A scan that starts after now: one already running (Navidrome's hourly one, started mid-run, maybe before a
    playlist write, a move or a put-back; reviews I3 and N5-02 M5) is waited out first, because startScan does
    nothing while it runs, and its lastScan would pass trash's "scanned since the repoint" check."""
    return wait_for_scan(client, timeout_s, poll_s) or scan_and_wait(client, timeout_s, poll_s)


def repoint(plan: dict, client, navidrome_db: Path, log_path: Path, limit: int | None = None, dry_run: bool = False,
            scan_timeout_s: float = 600, poll_s: float = 2, store=None) -> dict[str, str]:
    """{extra id: "repointed N playlists" | "skipped: held (<why>)" | "skipped: no longer a duplicate of <keeper>" |
    "skipped: keeper missing" | "refused: <playlist>: <why>; …" | "failed: <playlist>: <why>; …" | "dry run: would
    repoint <names>" | "dry run: would refuse <playlist>: <why>; …; would repoint <names>" | "failed: <error>"}, plus "(scan)": "done" | "failed: <problem>" when an extra reached
    repoint_everywhere (not on a dry run). `limit` counts the groups to act on (plan order). Each playlist written
    is an event in `store` (crates.db)."""
    rows, _ = load(navidrome_db)
    group_of = _group_of(rows)
    out: dict[str, str] = {}
    scan = False
    for g in _in_scope(plan, limit):
        keeper = g["keep"]["id"]
        for e in g["extras"]:
            extra = e["id"]
            if g["hold"] is not None:
                out[extra] = f"skipped: held ({g['hold']})"
                continue
            why = _recheck(rows, group_of, keeper, extra)
            if why:
                out[extra] = why
                continue
            try:
                if dry_run:                                  # the real run's checks, read-only (review I4)
                    out[extra] = _preview(repoint_everywhere(client, navidrome_db, extra, keeper, dry_run=True))
                    continue
                scan = True
                out[extra] = _summary(repoint_everywhere(
                    client, navidrome_db, extra, keeper, before_write=partial(_reverse, log_path, extra, keeper),
                    after_write=lambda pid, name: _event(store, pid, extra, f"repointed {name} to {keeper}")))
                _repoint_store(store, navidrome_db, extra, keeper)
            except Exception as ex:                          # recorded; the other groups and the scan still run
                out[extra] = f"failed: {ex!r}"
    if scan:
        problem = _fresh_scan(client, scan_timeout_s, poll_s)
        out["(scan)"] = f"failed: {problem}" if problem else "done"
    return out


class CleanupRefused(Exception):
    """trash must not run, or go on, now (the worker holds its lock, a Navidrome scan is running, the library or the
    trash is not mounted). Nothing more moves; `results` holds what happened so far (also in MOVES.txt and the trash
    log), and a re-run finds the moved files `already gone`."""

    def __init__(self, why: str, results: dict | None = None):
        super().__init__(why)
        self.results = results or {}


def _entries(n: int) -> str:
    return f"{n} playlist entr{'y' if n == 1 else 'ies'}"


def _no_scan(client) -> dict:
    """getScanStatus, refused while a scan runs."""
    status = client.scan_status()
    if status.get("scanning"):
        raise CleanupRefused("a Navidrome scan is running: navidrome.db is mid-update; run trash again when it is over")
    return status


def _scan_time(text) -> float | None:
    """Navidrome's lastScan (Go's time.Time in JSON: RFC 3339, up to nanoseconds, Z or an offset) as a Unix time;
    None when it is absent or not such a time."""
    m = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]\d\d:\d\d)", text or "")
    if not m:
        return None
    t = datetime.datetime.fromisoformat(m[1] + m[3].replace("Z", "+00:00"))
    return t.timestamp() + float("0." + (m[2] or "0"))


def _scanned_since_repoint(status: dict, log_dir: Path) -> None:
    """Refused unless a Navidrome scan finished after the newest repoint-*.jsonl in log_dir was last written (its
    mtime: the reverse line right before that run's last playlist write), so trash reads a navidrome.db that has seen
    every repoint (review I1). No repoint log: nothing was repointed, and references() decides alone."""
    logs = list(log_dir.glob("repoint-*.jsonl"))
    if not logs:
        return
    newest = max(logs, key=lambda f: f.stat().st_mtime)
    written = newest.stat().st_mtime
    last = _scan_time(status.get("lastScan"))
    if last is None or last <= written:
        at = datetime.datetime.fromtimestamp(written, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        raise CleanupRefused(f"no Navidrome scan finished after the newest repoint log {newest.name} (written {at}; "
                             f"lastScan {status.get('lastScan')!r}): start a scan (or run repoint again, which scans) "
                             f"and run trash when it is over")


def _trash_lines(log_dir: Path, extra: str, rel: str):
    """The trash-*.jsonl lines in log_dir for this extra at this path, oldest first."""
    for f in sorted(log_dir.glob("trash-*.jsonl")):
        for text in f.read_text(encoding="utf-8").splitlines():
            try:
                x = json.loads(text)
            except ValueError:
                continue
            if x.get("extra") == extra and x.get("path") == rel:
                yield x


def _forgotten(log_dir: Path, extra: str, rel: str) -> bool:
    """The trash logs say beets forgot this extra at this path, and the file was not put back since: a failed or
    skipped forget, or a put-back, leaves it to the next run."""
    done = False
    for x in _trash_lines(log_dir, extra, rel):
        done = not x.get("restored") and x.get("forgotten") is True
    return done


def _trashed_to(log_dir: Path, extra: str, rel: str) -> Path | None:
    """Where the trash logs say an earlier run moved this extra (and nothing put it back since), or None."""
    at = None
    for x in _trash_lines(log_dir, extra, rel):
        at = None if x.get("restored") else Path(x["trash_path"]) if x.get("trash_path") else at
    return at


def _beets(forgotten: bool | None) -> str:
    """What a put-back says of beets: a forgotten path is gone from its index, else beets still lists it."""
    return "beets no longer lists it" if forgotten is True else "beets still lists it"


def _forget(forget, path: Path) -> bool | None:
    """beets drops the trashed path; True, False on a failure (beets' index is a cache: noted, not fatal), None
    without beets here."""
    if forget is None:
        return None
    try:
        return bool(forget(path))
    except Exception:
        return False


def _put_back(navidrome_db: Path, extra: str, rel: str, dst: Path, music_root: Path, trash_root: Path, when: str,
              store) -> str | None:
    """The value for an extra a playlist took again after its file moved, having put the file back; None when no
    playlist holds it."""
    left = references(navidrome_db, extra)
    if not left:
        return None
    try:
        restore(dst, rel, music_root)
    except Exception as ex:
        return f"failed: added to {_entries(len(left))} {when}, not put back ({ex!r}); the file is at {dst}"
    _event(store, None, extra, f"put back from {_in_trash(dst, trash_root)}: in {_entries(len(left))} {when}")
    return f"refused: added to {_entries(len(left))} {when}; put back"


def _in_trash(dst: Path, trash_root: Path) -> str:
    """The trash path an event names: relative to the trash root (the absolute one is in MOVES.txt)."""
    return Path(dst).relative_to(trash_root).as_posix()


def trash(plan: dict, client, navidrome_db: Path, music_root: Path, trash_root: Path, lock_path: Path, forget,
          log_path: Path, limit: int | None = None, dry_run: bool = False, crates_db: Path | None = None,
          scan_timeout_s: float = 600, poll_s: float = 2) -> dict[str, str]:
    """{extra id: "moved to <trash path>" | "already gone" | "skipped: held (<why>)" | "skipped: moved since the plan
    (now <path>)" | "skipped: keeper missing" | "skipped: no longer a duplicate of <keeper>" | "refused: …" | "failed:
    …" | "dry run: would move"}, plus "(scan)" when a file moved. Raises CleanupRefused while the worker holds
    lock_path, a scan runs, no scan finished after the newest repoint log in log_path's folder, or the library or the
    trash is not mounted. `forget(abs path)` is BeetsFiler.forget (None:
    no beets here); crates.db (opened only under the lock) keeps the songs its in-flight rows use (None: not checked)."""
    try:
        fd = hold_lock(Path(lock_path))
    except WorkerRunning:
        raise CleanupRefused(f"stop the worker first (docker compose stop worker): it holds {lock_path}") from None
    store = None
    try:
        music_root, trash_root = Path(music_root).absolute(), Path(trash_root)
        if not music_root.is_dir() or not any(music_root.iterdir()):     # every extra would look already gone
            raise CleanupRefused(f"the library is not mounted: {music_root} is empty or absent")
        if not trash_root.is_dir():                         # move_to_trash would make it inside the container
            raise CleanupRefused(f"the trash is not mounted: {trash_root} is absent")
        store = CrateStore(crates_db) if crates_db is not None else None
        return _trash(plan, client, Path(navidrome_db), music_root, trash_root, forget, Path(log_path), limit,
                      dry_run, store, scan_timeout_s, poll_s)
    finally:
        if store is not None:
            store.db.close()
        os.close(fd)


def _trash(plan, client, navidrome_db, music_root, trash_root, forget, log_path, limit, dry_run, store,
           scan_timeout_s, poll_s) -> dict[str, str]:
    _scanned_since_repoint(_no_scan(client), log_path.parent)
    rows, _ = load(navidrome_db)
    group_of = _group_of(rows)
    path_of = {r["id"]: r["path"] for r in rows}
    size_of = {r["id"]: r["size"] for r in rows}
    out: dict[str, str] = {}
    moved: dict[str, tuple[str, Path, bool | None]] = {}    # extra → (path, trash path, forgotten)
    earlier: list[str] = []                              # put back from an earlier run's trash: a scan lists them

    def one(keeper: str, extra: str, rel: str, planned_size: int | None) -> str:
        now = path_of.get(extra)
        if now is not None and now != rel:
            return f"skipped: moved since the plan (now {now})"
        keep_file = music_root / path_of[keeper] if keeper in path_of else None
        if keep_file is None or not keep_file.is_file():
            return "skipped: keeper missing"
        src = music_root / rel
        if not src.exists():
            left = references(navidrome_db, extra)
            if left:                                         # a row on a trashed song: never a success
                dst = _trashed_to(log_path.parent, extra, rel)
                if dst is None or not dst.is_file():
                    return f"failed: gone from the library but still in {_entries(len(left))}"
                at = _in_trash(dst, trash_root)          # an earlier run could not scan, and a playlist took it
                if dry_run:
                    return f"refused: still in {_entries(len(left))}; would put back from {at}"
                forgot = _forgotten(log_path.parent, extra, rel)
                restore(dst, rel, music_root)
                _restored(log_path, extra, rel, dst)
                _event(store, None, extra, f"put back from {at}: in {_entries(len(left))} after an earlier run")
                earlier.append(extra)
                return f"refused: still in {_entries(len(left))}; put back from {at}; {_beets(forgot)}"
            if not dry_run and forget is not None and not _forgotten(log_path.parent, extra, rel):
                _append(log_path, {"extra": extra, "path": rel, "keeper": keeper, "trash_path": None,
                                   "forgotten": _forget(forget, src)})   # moved, then the run died before forget
            return "already gone"
        why = _recheck(rows, group_of, keeper, extra)
        if why:
            return why
        if os.path.samefile(src, keep_file):
            return f"refused: the same file as the keeper {keeper}"
        on_disk = src.stat().st_size                     # a new file filed at its path since the plan (review I2);
        sizes = {"navidrome.db": size_of[extra]}         # once scanned, only the plan's size still tells
        if planned_size is not None:                     # an N1 plan has none
            sizes["the plan"] = planned_size
        says = [f"{who} says {n}" for who, n in sizes.items() if n != on_disk]
        if says:
            return f"refused: {rel} is {on_disk} bytes on disk, {', '.join(says)}: not the planned file"
        if not dry_run:
            _scanned_since_repoint(_no_scan(client), log_path.parent)     # a repoint since the start (N5-02 M4)
        left = references(navidrome_db, extra)
        if left:
            return f"refused: still in {_entries(len(left))}"
        busy = store.song_in_use(extra) if store is not None else None
        if busy:
            return f"refused: in use by {busy}"
        if dry_run:
            return "dry run: would move"
        failed = _repoint_store(store, navidrome_db, extra, keeper)
        if failed:
            return f"refused: crates.db not repointed ({failed}); run again"
        dst = move_to_trash(rel, music_root, trash_root)
        moved[extra] = (rel, dst, None)
        try:                         # every file that stays moved gets its trash line, so a later run can put it back
            back = _put_back(navidrome_db, extra, rel, dst, music_root, trash_root, "during the move", store)
            if back and back.startswith("refused"):          # it is back in the library: nothing to log
                del moved[extra]
            if back:                                         # not put back: re-tried after the closing scan
                return back
            moved[extra] = (rel, dst, _forget(forget, src))
        finally:
            if extra in moved:
                _append(log_path, {"extra": extra, "path": rel, "keeper": keeper, "trash_path": str(dst),
                                   "forgotten": moved[extra][2]})
        forgotten = moved[extra][2]
        _event(store, None, extra, f"trashed to {_in_trash(dst, trash_root)}")
        return f"moved to {dst}" + (" (beets still lists it)" if forgotten is False else "")

    def recheck_moved() -> bool:
        """A row added between a move and now (the scan, or a refusal) puts the file back; True when one did."""
        put = False
        for extra, (rel, dst, forgotten) in list(moved.items()):
            try:
                back = _put_back(navidrome_db, extra, rel, dst, music_root, trash_root, "after the move", store)
            except Exception as ex:
                back = f"failed: re-checking its playlists after the move: {ex!r}"
            if back:
                if back.startswith("refused"):
                    _restored(log_path, extra, rel, dst)
                    back += f"; {_beets(forgotten)}; Navidrome lists it again after the next scan"
                    put = True
                    del moved[extra]
                out[extra] = back
        return put

    def closing_scan() -> None:
        """A scan that sees every move, then the re-read of each moved file; a put-back gets one more scan, because
        that scan marked it missing: hidden until the next one."""
        problem = _fresh_scan(client, scan_timeout_s, poll_s)
        if recheck_moved() and not problem:
            problem = _fresh_scan(client, scan_timeout_s, poll_s)
        out["(scan)"] = f"failed: {problem}" if problem else "done"

    try:
        for g in _in_scope(plan, limit):
            for e in g["extras"]:
                if g["hold"] is not None:
                    out[e["id"]] = f"skipped: held ({g['hold']})"
                    continue
                try:
                    out[e["id"]] = one(g["keep"]["id"], e["id"], e["path"], e.get("size"))   # N1 plans: no size
                except CleanupRefused:
                    raise
                except Exception as ex:                      # recorded; the other groups and the scan still run
                    out[e["id"]] = f"failed: {ex!r}"
    except CleanupRefused as e:
        if moved or earlier:
            closing_scan()
        raise CleanupRefused(str(e), out) from None
    if moved or earlier:
        closing_scan()
    return out


def _count(text: str) -> int:
    n = int(text)
    if n < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return n


def main(argv=None) -> int:
    """Defaults come from the worker's environment (deploy/compose.yml): NAVIDROME_DB, MUSIC_ROOT, TRASH_ROOT,
    CLEANUP_DIR, and through crates.service.Config.from_env SUBSONIC_* and CRATES_DB (events; its folder holds
    worker.lock)."""
    env = os.environ
    out_dir = Path(env.get("CLEANUP_DIR") or DEFAULT_OUT)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="read-only: write plan.json and report.md")
    p.add_argument("--out", type=Path, default=out_dir)
    p.add_argument("--hold-lossless", action="store_true",
                   help='hold a group whose extra is lossless beside a lossless keeper ("both lossless"; D35 acts on it)')
    r = sub.add_parser("repoint", help="repoint every playlist from each extra to its keeper, then scan")
    t = sub.add_parser("trash", help="with the worker stopped: move each extra no playlist holds to the trash, then scan")
    for x in (p, r, t):
        x.add_argument("--navidrome-db", type=Path, default=Path(env.get("NAVIDROME_DB") or DEFAULT_DB))
        x.add_argument("--limit", type=_count, default=None, help="only the first N groups to act on")
    for x in (p, t):
        x.add_argument("--music-root", type=Path, default=Path(env.get("MUSIC_ROOT") or "/srv/music"))
    t.add_argument("--trash-root", type=Path, default=Path(env.get("TRASH_ROOT") or "/srv/_trash"))
    for x in (r, t):
        x.add_argument("--plan", type=Path, default=out_dir / "plan.json")
        x.add_argument("--dry-run", action="store_true", help="say what would happen; write nothing")
        x.add_argument("--poll-s", type=float, default=2.0, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.cmd == "plan":
        plan = build_plan(a.navidrome_db, a.music_root, a.limit, a.hold_lossless)
        print(f"{counts(plan)} → {write_plan(plan, a.out)}")
        return 0
    cfg = Config.from_env()
    crates_db = Path(cfg.db_path)
    if not env.get("CRATES_DB") or not crates_db.is_file():  # not from_env's ./data default; never a stray one
        print("set CRATES_DB to the crate service's database (events; its folder holds worker.lock)", file=sys.stderr)
        return 2
    client = SubsonicClient(cfg.subsonic_url, cfg.username, cfg.password)
    stamp = f"{datetime.datetime.now(datetime.timezone.utc):%Y%m%dT%H%M%SZ}"
    plan = json.loads(a.plan.read_text(encoding="utf-8"))
    if a.cmd == "repoint":
        log = a.plan.parent / f"repoint-{stamp}.jsonl"
        store = None if a.dry_run else CrateStore(crates_db)    # opening it may migrate it: not on a dry run
        try:
            out = repoint(plan, client, a.navidrome_db, log, a.limit, a.dry_run, poll_s=a.poll_s, store=store)
        finally:
            if store is not None:
                store.db.close()
    else:
        from sourcing.cli import DEFAULT_BEETS_CONFIG
        from sourcing.filer import BeetsFiler
        forget = (BeetsFiler(Path(env.get("BEETS_CONFIG") or DEFAULT_BEETS_CONFIG)).forget
                  if env.get("DJ_WORKER") == "1" else None)       # beets lives in the worker image only
        if forget is None:
            print("no beets here (DJ_WORKER is not 1): beets keeps rows for the trashed paths", file=sys.stderr)
        log = a.plan.parent / f"trash-{stamp}.jsonl"
        try:
            out = trash(plan, client, a.navidrome_db, a.music_root, a.trash_root, crates_db.parent / "worker.lock",
                        forget, log, a.limit, a.dry_run, crates_db, poll_s=a.poll_s)
        except CleanupRefused as e:
            for k, v in e.results.items():
                print(f"{k}: {v}")
            print(f"refused: {e}" + (f" (trash log: {log})" if log.exists() else ""))
            return 1
    for k, v in out.items():
        print(f"{k}: {v}")
    if log.exists():
        print(f"{'reverse' if a.cmd == 'repoint' else 'trash'} log: {log}")
    return 1 if failed(out) else 0


if __name__ == "__main__":
    raise SystemExit(main())
