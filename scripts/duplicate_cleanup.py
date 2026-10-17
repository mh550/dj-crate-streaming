"""The Navidrome duplicate cleanup (D31): keep the best copy of each recording, repoint the playlists, trash the rest.

    docker compose exec -T worker python3 -m scripts.duplicate_cleanup plan [--limit N] [--out DIR]
        → $CLEANUP_DIR/plan.json + report.md (default /data/duplicate-cleanup = /srv/docker/crates/duplicate-cleanup/)

`plan` is read-only: it opens navidrome.db read-only, looks at music_root, and writes only into --out. It recomputes
the groups from the live navidrome.db every run (scripts.duplicate_report.load + duplicate_groups, never from
docs/duplicates-report.md); the first file of a group (keep_rank: lossless, then bit rate, then the properly filed
path) is the keeper. A group is held, listed only, when the keeper's file is not on disk or when an extra is lossless
beside a lossless keeper (D35: Michael clears that hold by setting "hold" to null in plan.json). `held_by` names
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
when any playlist was refused or failed or the scan did not finish: the runbook stops there.

trash follows (docs/plans/2026-10-17-n1-duplicate-cleanup.md).
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
    from crates.trash import free_path
    from scripts.dedupe_copies import remap
    from scripts.duplicate_report import DEFAULT_DB, LOSSLESS, duplicate_groups, load
    from scripts.export_playlists import open_ro
    from subsonic.client import SubsonicClient, scan_and_wait
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from crates.playlist_edit import references, repoint_everywhere
    from crates.trash import free_path
    from scripts.dedupe_copies import remap
    from scripts.duplicate_report import DEFAULT_DB, LOSSLESS, duplicate_groups, load
    from scripts.export_playlists import open_ro
    from subsonic.client import SubsonicClient, scan_and_wait

DEFAULT_OUT = Path("/data/duplicate-cleanup")


def _file(row: dict) -> dict:
    return {"id": row["id"], "path": row["path"], "suffix": row["suffix"], "bit_rate": row["bit_rate"]}


def _lossless(row: dict) -> bool:
    return row["suffix"].lower() in LOSSLESS


def _hold(keep: dict, extras: list[dict], music_root: Path) -> str | None:
    if not (music_root / keep["path"]).is_file():
        return "keeper missing on disk"
    if _lossless(keep) and any(_lossless(e) for e in extras):
        return "both lossless"
    return None


def build_plan(navidrome_db: Path, music_root: Path, limit: int | None = None) -> dict:
    """The plan for the current navidrome.db; `limit` keeps the first N unheld groups (held ones are all listed)."""
    rows, _ = load(navidrome_db)
    picked, unheld = [], 0
    for g in duplicate_groups(rows):
        keep, extras = g[0], g[1:]
        hold = _hold(keep, extras, Path(music_root))
        if hold is None:
            if limit is not None and unheld >= limit:
                continue
            unheld += 1
        pids = [list(dict.fromkeys(pid for pid, _ in references(navidrome_db, e["id"]))) for e in extras]
        picked.append((keep, extras, pids, hold))
    with closing(open_ro(navidrome_db)) as con:          # read after references(): a playlist made since is just new
        names = dict(con.execute("SELECT id, name FROM playlist"))
        tracks: dict[str, list[str]] = {}
        for pid, sid in con.execute("SELECT playlist_id, media_file_id FROM playlist_tracks ORDER BY playlist_id, id"):
            tracks.setdefault(pid, []).append(sid)
    groups, replace, touched = [], {}, {}
    for keep, extras, pids, hold in picked:
        groups.append({"keep": _file(keep), "extras": [
            dict(_file(e), held_by=[names.get(pid) or pid for pid in ps]) for e, ps in zip(extras, pids)], "hold": hold})
        if hold is None:
            replace.update((e["id"], keep["id"]) for e in extras)
            touched.update(dict.fromkeys(pid for ps in pids for pid in ps))
    playlists = [{"id": pid, "name": names.get(pid) or pid, "before": tracks[pid], "after": remap(tracks[pid], replace)}
                 for pid in touched if pid in tracks]       # one deleted meanwhile has nothing to repoint
    made_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"made_at": made_at, "groups": groups, "playlists": playlists}


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


def _reverse(log_path: Path, extra: str, keeper: str, pid: str, name: str, before: list, after: list) -> None:
    """repoint_everywhere's before_write: the reverse line, on disk before the playlist's write."""
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": _now(), "playlist_id": pid, "name": name, "extra": extra, "keeper": keeper,
                            "before": before, "after": after}, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def failed(out: dict[str, str]) -> bool:
    """True when a repoint value needs Michael: a playlist refused or failed, or the scan did not finish."""
    return any(v.startswith(("refused:", "failed:")) for v in out.values())


def repoint(plan: dict, client, navidrome_db: Path, log_path: Path, limit: int | None = None, dry_run: bool = False,
            scan_timeout_s: float = 600, poll_s: float = 2) -> dict[str, str]:
    """{extra id: "repointed N playlists" | "skipped: held (<why>)" | "skipped: no longer a duplicate of <keeper>" |
    "skipped: keeper missing" | "refused: <playlist>: <why>; …" | "failed: <playlist>: <why>; …" | "dry run: would
    repoint <names>" | "failed: <error>"}, plus "(scan)": "done" | "failed: <problem>" when an extra reached
    repoint_everywhere (not on a dry run). `limit` counts the groups to act on (plan order)."""
    rows, _ = load(navidrome_db)
    group_of = {r["id"]: i for i, grp in enumerate(duplicate_groups(rows)) for r in grp}
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
                if dry_run:
                    pids = dict.fromkeys(pid for pid, _ in references(navidrome_db, extra))
                    with closing(open_ro(navidrome_db)) as con:
                        names = [(con.execute("SELECT name FROM playlist WHERE id = ?", (pid,)).fetchone()
                                  or [None])[0] or pid for pid in pids]
                    out[extra] = f"dry run: would repoint {', '.join(names) or 'nothing'}"
                    continue
                scan = True
                out[extra] = _summary(repoint_everywhere(client, navidrome_db, extra, keeper,
                                                         before_write=partial(_reverse, log_path, extra, keeper)))
            except Exception as ex:                          # recorded; the other groups and the scan still run
                out[extra] = f"failed: {ex!r}"
    if scan:
        problem = scan_and_wait(client, scan_timeout_s, poll_s)
        out["(scan)"] = f"failed: {problem}" if problem else "done"
    return out


def _count(text: str) -> int:
    n = int(text)
    if n < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="read-only: write plan.json and report.md")
    p.add_argument("--navidrome-db", type=Path, default=Path(os.environ.get("NAVIDROME_DB") or DEFAULT_DB))
    p.add_argument("--music-root", type=Path, default=Path(os.environ.get("MUSIC_ROOT") or "/srv/music"))
    p.add_argument("--out", type=Path, default=Path(os.environ.get("CLEANUP_DIR") or DEFAULT_OUT))
    p.add_argument("--limit", type=_count, default=None, help="keep only the first N groups to act on")
    r = sub.add_parser("repoint", help="repoint every playlist from each extra to its keeper, then scan")
    r.add_argument("--plan", type=Path, default=Path(os.environ.get("CLEANUP_DIR") or DEFAULT_OUT) / "plan.json")
    r.add_argument("--navidrome-db", type=Path, default=Path(os.environ.get("NAVIDROME_DB") or DEFAULT_DB))
    r.add_argument("--limit", type=_count, default=None, help="act on the first N groups to act on")
    r.add_argument("--dry-run", action="store_true", help="say what would be repointed; write nothing")
    r.add_argument("--poll-s", type=float, default=2.0, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.cmd == "plan":
        plan = build_plan(a.navidrome_db, a.music_root, a.limit)
        print(f"{counts(plan)} → {write_plan(plan, a.out)}")
        return 0
    client = SubsonicClient(os.environ.get("SUBSONIC_URL", "http://127.0.0.1:4533"), os.environ.get("SUBSONIC_USER", ""),
                            os.environ.get("SUBSONIC_PASS", ""))
    log = a.plan.parent / f"repoint-{datetime.datetime.now(datetime.timezone.utc):%Y%m%dT%H%M%SZ}.jsonl"
    out = repoint(json.loads(a.plan.read_text(encoding="utf-8")), client, a.navidrome_db, log, a.limit, a.dry_run,
                  poll_s=a.poll_s)
    for k, v in out.items():
        print(f"{k}: {v}")
    if log.exists():
        print(f"reverse log: {log}")
    return 1 if failed(out) else 0


if __name__ == "__main__":
    raise SystemExit(main())
