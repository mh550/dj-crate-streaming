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

repoint and trash follow (docs/plans/2026-10-17-n1-duplicate-cleanup.md).
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
from pathlib import Path

try:
    from crates.playlist_edit import references
    from crates.trash import free_path
    from scripts.dedupe_copies import remap
    from scripts.duplicate_report import DEFAULT_DB, LOSSLESS, duplicate_groups, load
    from scripts.export_playlists import open_ro
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from crates.playlist_edit import references
    from crates.trash import free_path
    from scripts.dedupe_copies import remap
    from scripts.duplicate_report import DEFAULT_DB, LOSSLESS, duplicate_groups, load
    from scripts.export_playlists import open_ro

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
    a = ap.parse_args(argv)
    plan = build_plan(a.navidrome_db, a.music_root, a.limit)
    print(f"{counts(plan)} → {write_plan(plan, a.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
