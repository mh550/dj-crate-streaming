"""Trash the redundant copies in /srv/music and repoint the playlists (spec §4.2, D3).

    /usr/bin/python3 -m scripts.dedupe_copies plan       # host: decide, write the plan + docs/dedupe-report.md
    docker compose exec -T crates python3 -m scripts.dedupe_copies repoint --plan /data/dedupe-plan.json
                                                          # container (Navidrome credentials): playlists → kept copy
    /usr/bin/python3 -m scripts.dedupe_copies trash      # host: refuses while a playlist still has a copy

A group from docs/library-map.csv (`new_path` + `other_copies`) is deduped automatically only when every
file decodes to the same audio (a *decoded* md5: the library map's stream hash moves when an mp3's
ID3v1 tag changes) and the titles agree; anything else is listed for a person. The kept copy is the
properly filed one (keep_rank). Every move is logged with its reverse `mv`. Trash is
never emptied by these scripts.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shlex
import shutil
import subprocess
import sys
from contextlib import closing
from pathlib import Path

try:
    from scripts.export_playlists import open_ro                         # python3 -m scripts.dedupe_copies
    from scripts.library_map import _copy_rank, read_csv, write_csv
    from sourcing.identity import loose
except ImportError:                                                      # python3 scripts/dedupe_copies.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sourcing.identity import loose
    from export_playlists import open_ro
    from library_map import _copy_rank, read_csv, write_csv

REPO = Path(__file__).resolve().parent.parent
DEFAULT_PLAN = Path("/srv/docker/crates/dedupe-plan.json")              # /data/dedupe-plan.json in the crates container
DEFAULT_NAVIDROME_DB = Path("/srv/docker/navidrome/navidrome.db")


class StillReferenced(Exception):
    """A playlist still has a copy that is about to be trashed: run repoint (and a scan) first."""


def decoded_md5(path) -> str:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "md5", "-"],
                         capture_output=True, text=True, check=True).stdout
    return out.strip().removeprefix("MD5=")


_norm = loose                     # identity owns "is this the same text"


def free_path(target: Path) -> Path:
    """`target`, or "name (2).ext", "name (3).ext"…: trash never overwrites what it already holds."""
    target, n = Path(target), 2
    candidate = target
    while candidate.exists():
        candidate = target.with_name(f"{target.stem} ({n}){target.suffix}")
        n += 1
    return candidate


def keep_rank(path: str, album_artist: str | None, year: int | None) -> tuple:
    """Which copy of identical audio to keep (smallest wins), after library_map._copy_rank's rules
    (no beets ".1", not Compilations/Singles/_): the copy filed under its own album artist (a folder
    that disagrees with the file's tag is mis-filed); then the shorter artist folder (the main artist,
    not a credit string glued together); then the earliest known year (the original release); then
    alphabetical. Navidrome shows several album artists as "A • B": the first one counts."""
    uniquified, catch_all, _ = _copy_rank(path)
    folder = path.split("/", 1)[0]
    own = (album_artist or "").split(" • ")[0]
    return (uniquified, catch_all, _norm(folder) != _norm(own), len(folder), year or 9999, path)


def remap(entries: list[str], replace: dict[str, str]) -> list[str]:
    """Each copy becomes its kept song in place; dropped instead when the kept song is already there."""
    out: list[str] = []
    for e in entries:
        k = replace.get(e)
        if k is None:
            out.append(e)
        elif k not in entries and k not in out:
            out.append(k)
    return out


def _groups(map_rows: list[dict]) -> list[list[str]]:
    seen, out = set(), []
    for r in map_rows:
        paths = sorted({r["new_path"], *[p for p in r["other_copies"].split("|") if p]} - {""})
        if len(paths) > 1 and tuple(paths) not in seen:
            seen.add(tuple(paths))
            out.append(paths)
    return out


def plan(library_map, music, navidrome_db, plan_path, report_path) -> dict:
    music = Path(music)
    with closing(open_ro(navidrome_db)) as con:
        songs = {p: (i, t, aa, y) for i, p, t, aa, y in con.execute(
            "SELECT id, path, title, album_artist, year FROM media_file WHERE NOT missing")}
        playlists = []
        for pid, name in con.execute("SELECT id, name FROM playlist ORDER BY name").fetchall():
            ids = [m for (m,) in con.execute("SELECT media_file_id FROM playlist_tracks WHERE playlist_id = ? ORDER BY id", (pid,))]
            playlists.append((pid, name, ids))
    trash, person, replace = [], [], {}
    for paths in _groups(read_csv(Path(library_map))):
        if not all(p in songs and (music / p).is_file() for p in paths):
            person.append(paths)
            continue
        same_audio = len({decoded_md5(music / p) for p in paths}) == 1
        same_title = len({_norm(songs[p][1]) for p in paths}) == 1
        if not (same_audio and same_title):
            person.append(paths)
            continue
        keep = min(paths, key=lambda p: keep_rank(p, songs[p][2], songs[p][3]))
        for p in paths:
            if p != keep:
                trash.append({"path": p, "id": songs[p][0], "keep_path": keep, "keep_id": songs[keep][0]})
                replace[songs[p][0]] = songs[keep][0]
    changed = [{"id": pid, "name": name, "before": ids, "after": remap(ids, replace)}
               for pid, name, ids in playlists if remap(ids, replace) != ids]
    result = {"trash": trash, "person": person, "playlists": changed}
    Path(plan_path).write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    _write_report(Path(report_path), result)
    return result


def _write_report(path: Path, p: dict) -> None:
    md = ["# Dedupe report", "", "Generated by `scripts/dedupe_copies.py plan` (nothing moved yet).", "",
          f"**{len(p['trash'])} copies to trash, {len(p['playlists'])} playlists to repoint, {len(p['person'])} groups need a person.**", "",
          "## Copies to trash (kept copy on the right)", "", "| trash | keep |", "|---|---|",
          *[f"| {t['path']} | {t['keep_path']} |" for t in p["trash"]], "",
          "## Playlists repointed", "", "| playlist | entries before → after |", "|---|---|",
          *[f"| {pl['name']} | {len(pl['before'])} → {len(pl['after'])} |" for pl in p["playlists"]], ""]
    if p["person"]:
        md += ["## Needs a person (same group in the library map, but the audio or the titles differ)", "",
               *[f"- {' · '.join(g)}" for g in p["person"]], ""]
    path.write_text("\n".join(md), encoding="utf-8")


def repoint(p: dict, client) -> tuple[list[str], list[str]]:
    """(playlists updated, playlists refused because they changed since the plan)."""
    done, refused = [], []
    for pl in p["playlists"]:
        cur = [e.id for e in client.playlist(pl["id"]).entries]
        if cur == pl["after"]:
            continue
        if cur != pl["before"]:
            refused.append(pl["name"])
            continue
        first = next((i for i, (a, b) in enumerate(zip(pl["before"], pl["after"])) if a != b), min(len(pl["before"]), len(pl["after"])))
        # Subsonic removes by index and only appends: drop the tail and re-add it in ONE call (atomic in Navidrome).
        client.update_playlist(pl["id"], remove_indexes=list(range(first, len(cur))), add_song_ids=pl["after"][first:])
        done.append(pl["name"])
    return done, refused


def _forget_in_beets(paths: list[str], config) -> None:
    try:
        from scripts.tag_cleanup import open_lib
    except ImportError:
        from tag_cleanup import open_lib
    lib = open_lib(config)
    wanted = {os.fsencode(p) for p in paths}
    for item in lib.items():
        if item.path in wanted:
            item.remove(delete=False)
    lib._close()


def trash(p: dict, music, trash_root, navidrome_db, library_map, config) -> tuple[list[str], list[str]]:
    """(moved, skipped). Refuses while a playlist still has a copy; re-checks each kept copy first."""
    music, trash_root = Path(music), Path(trash_root)
    ids = {t["id"] for t in p["trash"]}
    with closing(open_ro(navidrome_db)) as con:
        still = [m for (m,) in con.execute("SELECT DISTINCT media_file_id FROM playlist_tracks") if m in ids]
    if still:
        raise StillReferenced(f"{len(still)} copies are still in a playlist: run repoint, wait for the scan, then trash")
    moved, skipped = [], []
    for t in p["trash"]:
        src, keep = music / t["path"], music / t["keep_path"]
        if not src.exists():
            continue
        if not keep.is_file() or decoded_md5(src) != decoded_md5(keep):
            skipped.append(t["path"])                    # never move the only copy: the plan is stale for this one
            continue
        dst = free_path(trash_root / t["path"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(src, dst)
        with (trash_root / "MOVES.txt").open("a", encoding="utf-8") as log:   # logged before the next move
            log.write(f"mv {shlex.quote(str(dst))} {shlex.quote(str(src))}\n")
        moved.append(t["path"])
    # Bookkeeping for every planned copy that is gone, moved now or by an earlier run that died
    # part-way (both steps are idempotent), so a re-run always finishes the job.
    gone = {t["path"]: t["keep_path"] for t in p["trash"] if not (music / t["path"]).exists()}
    if gone:
        _forget_in_beets([str(music / g) for g in gone], config)
        rows = read_csv(Path(library_map))
        for r in rows:
            if r["new_path"] in gone:
                r["new_path"] = gone[r["new_path"]]
            r["other_copies"] = "|".join(o for o in r["other_copies"].split("|") if o and o not in gone and o != r["new_path"])
        write_csv(rows, Path(library_map))
    return moved, skipped


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "repoint", "trash"])
    ap.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    ap.add_argument("--library-map", type=Path, default=REPO / "docs" / "library-map.csv")
    ap.add_argument("--music", type=Path, default=Path("/srv/music"))
    ap.add_argument("--navidrome-db", type=Path, default=DEFAULT_NAVIDROME_DB)
    ap.add_argument("--report", type=Path, default=REPO / "docs" / "dedupe-report.md")
    ap.add_argument("--trash", type=Path, default=Path("/srv/docker/_trash") / datetime.date.today().isoformat())
    ap.add_argument("--config", type=Path, default=REPO / "deploy" / "beets.yaml")
    a = ap.parse_args(argv)
    if a.cmd == "plan":
        p = plan(a.library_map, a.music, a.navidrome_db, a.plan, a.report)
        print(f"{len(p['trash'])} copies to trash, {len(p['playlists'])} playlists to repoint, {len(p['person'])} groups need a person → {a.report}")
    elif a.cmd == "repoint":
        from crates.service import Config
        from subsonic.client import SubsonicClient
        cfg = Config.from_env()
        done, refused = repoint(json.loads(a.plan.read_text()), SubsonicClient(cfg.subsonic_url, cfg.username, cfg.password))
        print(f"{len(done)} playlists repointed; {len(refused)} refused (changed since the plan): {refused}")
        return 1 if refused else 0
    else:
        try:
            moved, skipped = trash(json.loads(a.plan.read_text()), a.music, a.trash, a.navidrome_db, a.library_map, a.config)
        except StillReferenced as e:
            print(e, file=sys.stderr)
            return 1
        print(f"{len(moved)} copies moved to {a.trash} (reverse commands in {a.trash / 'MOVES.txt'})")
        for s_ in skipped:
            print(f"  skipped (kept copy missing or different audio; re-run plan): {s_}")
        return 1 if skipped else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
