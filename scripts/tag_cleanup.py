"""Clean the tags Amperfy shows, in two passes Navidrome survives (spec §3 backfill).

    /usr/bin/python3 -m scripts.tag_cleanup plan     # dry run on a copy of the beets DB → docs/tag-cleanup-report.md
    /usr/bin/python3 -m scripts.tag_cleanup retag    # pass 1: write tags in place, no moves (backs up library.db)
      … wait for Navidrome's scan (its folder watcher picks the changes up within seconds) …
    /usr/bin/python3 -m scripts.tag_cleanup move     # pass 2: re-file the changed songs; refuses until pass 1 is scanned
    (scripts/tag_repair.py: the one-off repair of the first live run's full-field beets writes)
    /usr/bin/python3 -m scripts.tag_cleanup refresh-map   # docs/library-map.csv follows the moves

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
import sys
import tempfile
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

for _p in ("/usr/share/beets", "/usr/lib/python3/dist-packages"):      # Debian's beets package
    if _p not in sys.path:
        sys.path.append(_p)

import mutagen.id3                                                      # noqa: E402
from beets import config as beets_config, ui as beets_ui                # noqa: E402
from beets.util import displayable_path                                 # noqa: E402
from mediafile import MediaFile                                         # noqa: E402

try:
    from scripts.export_playlists import open_ro                         # python3 -m scripts.tag_cleanup
    from scripts.library_map import read_csv, write_csv
    from scripts.tag_rules import blank, clean, usable_artist
except ImportError:                                                      # python3 scripts/tag_cleanup.py
    from export_playlists import open_ro
    from library_map import read_csv, write_csv
    from tag_rules import blank, clean, usable_artist

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO / "deploy" / "beets.yaml"
DEFAULT_MANIFEST = Path("/srv/docker/beets/tag-cleanup-manifest.json")
DEFAULT_NAVIDROME_DB = Path("/srv/docker/navidrome/navidrome.db")
KEYS = ("title", "artist", "albumartist", "album", "comp", "comments")
SHOWN = ("title", "artist", "albumartist", "album")      # the KEYS a navidrome.db media_file row shows
# ID3 frames that carry the same field under another name. mediafile writes only the standard frame
# (TPE2), so an alias would keep the old value beside it: Navidrome showed "X • VA" (2026-10-15).
ALIASES = {"albumartist": ("TXXX:ALBUM ARTIST", "TXXX:ALBUMARTIST", "TXXX:ALBUM_ARTIST")}


def _id3_v23(path: str) -> bool:
    try:
        return mutagen.id3.ID3(path).version[:2] == (2, 3)
    except Exception:                                    # not an ID3 file (FLAC, MP4…) or no ID3 tag yet
        return False


def write_minimal(path, changes: dict) -> None:
    """Write only `changes` into the file. beets' item.write() rewrites every field it knows, which
    collapsed multi-valued GENRE/ISRC, garbled RELEASETYPE and added zero DISCTOTAL/TRACKTOTAL on the
    live run (2026-10-15, Opus review); mediafile saves only the fields set here. The ID3 version is
    kept, and ID3 aliases of a changed field are dropped, all in one save."""
    path = str(path)
    m = MediaFile(path, id3v23=_id3_v23(path))
    for k, v in changes.items():
        setattr(m, k, (bool(v) or None) if k == "comp" else (v or None))     # comp off / "" = remove the tag
    tags = getattr(m.mgfile, "tags", None)
    if isinstance(tags, mutagen.id3.ID3):
        stale = {a.casefold() for k in changes for a in ALIASES.get(k, ())}
        for key in [key for key in tags.keys() if key.casefold() in stale]:
            del tags[key]
    m.save()


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


def _needs_regroup(item) -> bool:
    album = item.get_album()
    if not item.album:
        return album is not None                                         # no album tag → a singleton
    return album is None or album.albumartist != item.albumartist or album.album != item.album or bool(album.comp)


def _scan(lib) -> tuple[list[Record], list[str]]:
    """Records for every item that changes, and the Compilations files left alone (no usable artist)."""
    comp_root = os.path.join(lib.directory, b"Compilations") + b"/"
    out, left = [], []
    for item in lib.items():
        path = item.path
        item.read()                                                      # the file is the truth (the DB drifted)
        before = _fields(item)
        in_comp = path.startswith(comp_root)
        changes, rules = clean(dict(before, in_compilations=in_comp))
        item.update(changes)
        if in_comp and not usable_artist(item.artist):
            in_comp = False                                              # nothing to file it under: stays where it is
            left.append(_rel(lib, path))
        if changes or (in_comp and _needs_regroup(item)):
            out.append(Record(item, path, before, changes, rules or ["regroup"], in_comp))
    return out, left


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
            if r.changes:
                write_minimal(displayable_path(r.item.path), r.changes)


def _rel(lib, path: bytes) -> str:
    return displayable_path(os.path.relpath(path, lib.directory))


@dataclass
class Plan:
    counts: Counter = field(default_factory=Counter)
    moves: int = 0
    collisions: list[str] = field(default_factory=list)
    left: list[str] = field(default_factory=list)       # Compilations files with no usable artist tag
    drift: list[str] = field(default_factory=list)      # untouched songs whose beets destination ≠ their path


def plan(config_path, report_path) -> Plan:
    real = open_lib(config_path)
    tmp = Path(tempfile.mkdtemp(prefix="tag-cleanup-"))
    try:
        shutil.copy2(displayable_path(real.path), tmp / "library.db")
        real._close()
        lib = open_lib(config_path, library=tmp / "library.db")
        result, rows, moves, seen = Plan(), [], [], Counter()
        recs, result.left = _scan(lib)
        _apply(lib, recs, write=False)
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
        touched = {r.item.id for r in recs}
        for item in lib.items():                         # what a later `beet move` / `beet import -L` would also do
            if item.id not in touched and item.destination() != item.path:
                result.drift.append(f"{_rel(lib, item.path)} → {_rel(lib, item.destination())}")
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
    if result.left:
        md += ["## Left in Compilations (no usable artist tag: a person has to look)", "", *[f"- {c}" for c in result.left], ""]
    if result.drift:
        md += ["## Untouched songs beets would re-file", "",
               "Not changed by this cleanup, but `beet move` or `beet import -L` would move them (collisions left in "
               "place by an earlier `move`, or songs beets filed differently at import). Nothing here is moved.", "",
               *[f"- {c}" for c in result.drift], ""]
    path.write_text("\n".join(md), encoding="utf-8")


def _save_manifest(path: Path, entries: list) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(entries, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def retag(config_path, manifest_path) -> int:
    """Pass 1. The manifest (before/after per song) is saved before any file is touched and after every
    file written, so a crash part-way leaves a record that a re-run completes."""
    lib = open_lib(config_path)
    db = Path(displayable_path(lib.path))
    backup = db.with_name(db.name + ".bak-tag-cleanup")
    if not backup.exists():
        shutil.copy2(db, backup)
    recs, _ = _scan(lib)
    manifest = Path(manifest_path)
    entries = json.loads(manifest.read_text()) if manifest.exists() else []
    by_id = {e["id"]: e for e in entries}
    for r in recs:
        e = by_id.get(r.item.id)
        if e is None:
            e = {"id": r.item.id, "path_before": displayable_path(r.path_before), "rules": r.rules, "before": r.before}
            entries.append(e)
            by_id[r.item.id] = e
        else:                                            # keep the first run's `before`: that is the true original
            e["rules"] = sorted(set(e["rules"]) | set(r.rules))
        e["after"] = _fields(r.item)
        e["written"] = not r.changes                     # regroup-only: nothing to write into the file
    _save_manifest(manifest, entries)
    _apply(lib, recs, write=False)
    for r in recs:
        if r.changes:
            write_minimal(displayable_path(r.item.path), r.changes)
            by_id[r.item.id]["written"] = True
            _save_manifest(manifest, entries)
    lib._close()
    return len(recs)


def _norm(s) -> str:
    return re.sub(r"\W+", "", str(s or "").casefold())


def _same_shown(shown, wanted) -> bool:
    """Navidrome 0.64 shows an empty album/artist tag as "[Unknown Album]"/"[Unknown Artist]"."""
    return (blank(shown) and blank(wanted)) or _norm(shown) == _norm(wanted)


def _scanned(row, after: dict, before: dict) -> bool:
    """Navidrome shows the values pass 1 wrote. Only the keys that changed are compared (Navidrome joins
    multi-valued artists differently from beets), and they must be *equal*: a substring test accepted
    "Cameo feat. Larry Blackmon" for "Cameo" before any scan (Opus review)."""
    if row is None:
        return False
    shown = dict(zip(SHOWN, row))
    return all(_same_shown(shown[k], after[k]) for k in SHOWN if after[k] != before.get(k))


def move(config_path, manifest_path, navidrome_db) -> list[tuple[str, str]]:
    """Pass 2. Progress is saved after every move; a song beets already moved but the manifest missed
    (crash) is checked and recorded at its current path."""
    manifest = Path(manifest_path)
    entries = json.loads(manifest.read_text())
    pending = [e for e in entries if not e.get("path_after")]
    if not pending:
        return []
    lib = open_lib(config_path)
    with closing(open_ro(navidrome_db)) as con:
        rows = {p: r for p, *r in con.execute("SELECT path, title, artist, album_artist, album FROM media_file WHERE NOT missing")}
    items = {e["id"]: lib.get_item(e["id"]) for e in pending}
    late = [e for e in pending if not e.get("written", True)
            or not _scanned(rows.get(_rel(lib, items[e["id"]].path)), e["after"], e["before"])]
    if late:
        lib._close()
        raise NotScanned(f"{len(late)} of {len(pending)} retagged files not yet rescanned by Navidrome "
                         f"(e.g. {_rel(lib, items[late[0]['id']].path)}); wait for the scan and run move again")
    moved = []
    try:
        for e in pending:
            item = items[e["id"]]
            dest = item.destination()
            if dest != item.path:
                if os.path.exists(dest):
                    e["skipped"] = f"destination exists: {_rel(lib, dest)}"
                    continue
                item.move()
                moved.append((e["path_before"], displayable_path(item.path)))
            e["path_after"] = displayable_path(item.path)
            _save_manifest(manifest, entries)
    finally:
        _save_manifest(manifest, entries)
        lib._close()
    return moved


def refresh_library_map(csv_path, manifest: list, music_root) -> int:
    """Point docs/library-map.csv's new_path/other_copies at where the songs live after `move`."""
    moved = {os.path.relpath(e["path_before"], music_root): os.path.relpath(e["path_after"], music_root)
             for e in manifest if e.get("path_after") and e["path_after"] != e["path_before"]}
    rows, changed = read_csv(Path(csv_path)), 0
    for r in rows:
        new = moved.get(r["new_path"], r["new_path"])
        others = "|".join(moved.get(o, o) for o in r["other_copies"].split("|")) if r["other_copies"] else ""
        if (new, others) != (r["new_path"], r["other_copies"]):
            r["new_path"], r["other_copies"] = new, others
            changed += 1
    write_csv(rows, Path(csv_path))
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "retag", "move", "refresh-map"])
    ap.add_argument("--music", type=Path, default=Path("/srv/music"))
    ap.add_argument("--library-map", type=Path, default=REPO / "docs" / "library-map.csv")
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
    elif a.cmd == "refresh-map":
        n = refresh_library_map(a.library_map, json.loads(a.manifest.read_text()), a.music)
        print(f"{n} library-map rows now point at the moved files ({a.library_map})")
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
