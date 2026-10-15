"""Clean the tags Amperfy shows, in two passes Navidrome survives (spec §3 backfill).

    /usr/bin/python3 -m scripts.tag_cleanup plan     # dry run on a copy of the beets DB → docs/tag-cleanup-report.md
    /usr/bin/python3 -m scripts.tag_cleanup retag    # pass 1: write tags in place, no moves (backs up library.db)
      … wait for Navidrome's scan (its folder watcher picks the changes up within seconds) …
    /usr/bin/python3 -m scripts.tag_cleanup move     # pass 2: re-file the changed songs; refuses until pass 1 is scanned

Why two passes: on Navidrome 0.64 a retag keeps the song id and a move with unchanged tags keeps
it, but a retag *and* a move between two scans gives a new id and the song silently drops out of
every playlist (tested 2026-10-15 on a throwaway instance). Every item is re-read from its file
first: the beets DB drifted from the files during last night's as-is import, and the files are
what Navidrome shows (D5: file tags win). The rules themselves are in tag_rules.py.
Operates on /srv/music (copies) only; the originals in /srv/incoming are never opened for writing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

for _p in ("/usr/share/beets", "/usr/lib/python3/dist-packages"):      # Debian's beets package
    if _p not in sys.path:
        sys.path.append(_p)

from beets import config as beets_config, ui as beets_ui                # noqa: E402
from beets.util import displayable_path                                 # noqa: E402

try:
    from scripts.tag_rules import clean                                  # python3 -m scripts.tag_cleanup
except ImportError:                                                      # python3 scripts/tag_cleanup.py
    from tag_rules import clean

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO / "deploy" / "beets.yaml"
DEFAULT_MANIFEST = Path("/srv/docker/beets/tag-cleanup-manifest.json")
DEFAULT_NAVIDROME_DB = Path("/srv/docker/navidrome/navidrome.db")
KEYS = ("title", "artist", "albumartist", "album", "comp", "comments")


class NotScanned(Exception):
    """Navidrome has not yet seen pass 1's tags; moving now would give those songs new ids."""


def open_lib(config_path, library=None):
    beets_config.clear()
    beets_config.read(user=False, defaults=True)
    beets_config.set_file(str(config_path))
    if library:
        beets_config["library"].set(str(library))
    return beets_ui._open_library(beets_config)


@dataclass
class Record:
    item: object
    path_before: bytes
    before: dict
    changes: dict
    rules: list[str]
    in_comp: bool


def _fields(item) -> dict:
    return {k: (bool(item.get(k)) if k == "comp" else (item.get(k) or "")) for k in KEYS}


def _needs_regroup(lib, item) -> bool:
    album = item.get_album()
    if not item.album:
        return album is not None                                         # no album tag → a singleton
    return album is None or album.albumartist != item.albumartist or album.album != item.album or bool(album.comp)


def _scan(lib) -> list[Record]:
    comp_root = os.path.join(lib.directory, b"Compilations") + b"/"
    out = []
    for item in lib.items():
        path = item.path
        item.read()                                                      # the file is the truth (the DB drifted)
        before = _fields(item)
        in_comp = path.startswith(comp_root)
        changes, rules = clean(dict(before, in_compilations=in_comp))
        item.update(changes)
        if changes or (in_comp and _needs_regroup(lib, item)):
            out.append(Record(item, path, before, changes, rules or ["regroup"], in_comp))
    return out


def _apply(lib, recs: list[Record], write: bool) -> None:
    groups, singles, old_albums = defaultdict(list), [], set()
    for r in recs:
        if r.in_comp:
            old_albums.add(r.item.album_id)
            (groups[(r.item.albumartist, r.item.album)] if r.item.album else singles).append(r.item)
    with lib.transaction():
        for r in recs:
            r.item.store()
        for items in groups.values():                                    # one real album per (albumartist, album)
            lib.add_album(items)
        for it in singles:
            it.album_id = None
            it.store()
        for aid in old_albums - {None}:
            album = lib.get_album(aid)
            if album is not None and not list(album.items()):
                album.remove(with_items=False)
    if write:
        for r in recs:
            r.item.write()


def _rel(lib, path: bytes) -> str:
    return displayable_path(os.path.relpath(path, lib.directory))


@dataclass
class Plan:
    counts: Counter = field(default_factory=Counter)
    moves: int = 0
    collisions: list[str] = field(default_factory=list)


def plan(config_path, report_path) -> Plan:
    real = open_lib(config_path)
    tmp = Path(tempfile.mkdtemp(prefix="tag-cleanup-"))
    try:
        shutil.copy2(displayable_path(real.path), tmp / "library.db")
        real._close()
        lib = open_lib(config_path, library=tmp / "library.db")
        recs = _scan(lib)
        _apply(lib, recs, write=False)
        result, rows, moves, seen = Plan(), [], [], Counter()
        for r in recs:
            result.counts.update(r.rules)
            dest = r.item.destination()
            seen[dest] += 1
            changes = "; ".join(f"{k}: {r.before[k]!r} → {v!r}" for k, v in r.changes.items()) or "(regroup only)"
            rows.append(f"| {_rel(lib, r.path_before)} | {', '.join(r.rules)} | {changes} |")
            if dest != r.path_before:
                moves.append((r.path_before, dest))
        for old, dest in moves:
            if seen[dest] > 1 or os.path.exists(dest):
                result.collisions.append(f"{_rel(lib, old)} → {_rel(lib, dest)}")
        result.moves = len(moves)
        lib._close()
        _write_report(Path(report_path), lib, result, rows, moves)
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _write_report(path: Path, lib, result: Plan, rows: list[str], moves: list) -> None:
    md = ["# Tag cleanup report", "",
          "Generated by `scripts/tag_cleanup.py plan` (dry run: no file and no database changed).", "",
          "| rule | songs |", "|---|---|", *[f"| {k} | {v} |" for k, v in sorted(result.counts.items())], "",
          f"**{len(rows)} songs change, {result.moves} move, {len(result.collisions)} would collide** "
          "(a collision is left in place by `move` and listed again).", "",
          "## Tag changes", "", "| file (before) | rules | changes |", "|---|---|---|", *rows, "",
          "## Moves", "", "| from | to |", "|---|---|", *[f"| {_rel(lib, a)} | {_rel(lib, b)} |" for a, b in moves], ""]
    if result.collisions:
        md += ["## Collisions (skipped by `move`)", "", *[f"- {c}" for c in result.collisions], ""]
    path.write_text("\n".join(md), encoding="utf-8")


def retag(config_path, manifest_path) -> int:
    lib = open_lib(config_path)
    db = Path(displayable_path(lib.path))
    backup = db.with_name(db.name + ".bak-tag-cleanup")
    if not backup.exists():
        shutil.copy2(db, backup)
    recs = _scan(lib)
    _apply(lib, recs, write=True)
    manifest = Path(manifest_path)
    entries = json.loads(manifest.read_text()) if manifest.exists() else []
    known = {e["id"] for e in entries}
    for r in recs:
        if r.item.id not in known:
            entries.append({"id": r.item.id, "path_before": displayable_path(r.path_before), "rules": r.rules,
                            "before": r.before, "after": _fields(r.item)})
    manifest.write_text(json.dumps(entries, indent=1, ensure_ascii=False), encoding="utf-8")
    lib._close()
    return len(recs)


def _norm(s) -> str:
    return re.sub(r"\W+", "", str(s or "").casefold())


def _scanned(row, after: dict) -> bool:
    if row is None:
        return False
    title, artist, album_artist, album = row
    return (_norm(title) == _norm(after["title"]) and _norm(album) == _norm(after["album"])
            and (not after["artist"] or _norm(after["artist"]) in _norm(artist))
            and (not after["albumartist"] or _norm(after["albumartist"]) in _norm(album_artist)))


def move(config_path, manifest_path, navidrome_db) -> list[tuple[str, str]]:
    manifest = Path(manifest_path)
    entries = json.loads(manifest.read_text())
    pending = [e for e in entries if not e.get("path_after")]
    if not pending:
        return []
    lib = open_lib(config_path)
    root = displayable_path(lib.directory)
    con = sqlite3.connect(f"{Path(navidrome_db).resolve().as_uri()}?mode=ro", uri=True)
    rows = {p: (t, a, aa, al) for p, t, a, aa, al in con.execute("SELECT path, title, artist, album_artist, album FROM media_file WHERE NOT missing")}
    con.close()
    late = [e for e in pending if not _scanned(rows.get(os.path.relpath(e["path_before"], root)), e["after"])]
    if late:
        lib._close()
        raise NotScanned(f"{len(late)} of {len(pending)} retagged files not yet rescanned by Navidrome "
                         f"(e.g. {os.path.relpath(late[0]['path_before'], root)}); wait for the scan and run move again")
    moved = []
    for e in pending:
        item = lib.get_item(e["id"])
        dest = item.destination()
        if dest != item.path and os.path.exists(dest):
            e["skipped"] = f"destination exists: {_rel(lib, dest)}"
            continue
        if dest != item.path:
            item.move()
            moved.append((e["path_before"], displayable_path(item.path)))
        e["path_after"] = displayable_path(item.path)
    manifest.write_text(json.dumps(entries, indent=1, ensure_ascii=False), encoding="utf-8")
    lib._close()
    return moved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "retag", "move"])
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--report", type=Path, default=REPO / "docs" / "tag-cleanup-report.md")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--navidrome-db", type=Path, default=DEFAULT_NAVIDROME_DB)
    a = ap.parse_args(argv)
    if a.cmd == "plan":
        p = plan(a.config, a.report)
        print(f"{sum(p.counts.values())} rule hits {dict(p.counts)}; {p.moves} moves; {len(p.collisions)} collisions → {a.report}")
    elif a.cmd == "retag":
        print(f"{retag(a.config, a.manifest)} songs retagged in place (manifest: {a.manifest})")
    else:
        try:
            moved = move(a.config, a.manifest, a.navidrome_db)
        except NotScanned as e:
            print(e, file=sys.stderr)
            return 1
        print(f"{len(moved)} songs moved (manifest: {a.manifest})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
