"""One-off repair of the first live tag-cleanup run (2026-10-15): beets' item.write() had rewritten
every field of the 376 retagged files, collapsing multi-valued GENRE/ISRC, garbling RELEASETYPE and
adding zero DISCTOTAL/TRACKTOTAL. `repair` puts each file's original bytes back (from /srv/incoming,
read-only) and applies only the intended changes from the manifest; the damaged copy goes to trash.

    /usr/bin/python3 -m scripts.tag_repair      # done once on 2026-10-15; re-running skips restored songs

Kept as a tool because the same restore applies to any future write that went wrong.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

try:
    from scripts.dedupe_copies import free_path                          # python3 -m scripts.tag_repair
    from scripts.export_playlists import open_ro
    from scripts.library_map import audio_md5, read_csv
    from scripts.tag_cleanup import DEFAULT_MANIFEST, REPO, MediaFile, _norm, _save_manifest, write_minimal
except ImportError:                                                      # python3 scripts/tag_repair.py
    from dedupe_copies import free_path
    from export_playlists import open_ro
    from library_map import audio_md5, read_csv
    from tag_cleanup import DEFAULT_MANIFEST, REPO, MediaFile, _norm, _save_manifest, write_minimal


def restore(entry: dict, original, music_root, trash_root) -> None:
    """Put the original file's bytes back (audio and every tag as downloaded), then apply only the
    intended changes. The current file is copied to trash first; the swap is one rename, so the path
    never disappears and Navidrome keeps the song id. The original is only read."""
    cur = Path(entry.get("path_after") or entry["path_before"])
    tmp = cur.with_name(".restore." + cur.name)          # keep the extension: mediafile picks the format by it
    shutil.copyfile(original, tmp)                       # fresh mtime: Navidrome re-reads it
    changes = {k: v for k, v in entry["after"].items() if entry["before"].get(k) != v}
    if changes:
        write_minimal(tmp, changes)
    kept = free_path(Path(trash_root) / cur.relative_to(music_root))
    kept.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cur, kept)
    os.replace(tmp, cur)
    entry["restored_from"] = str(original)


def _genre_set(values) -> list[str]:
    return sorted({_norm(g) for v in values for g in re.split(r"[;/,]", v or "") if _norm(g)})


def find_original(entry: dict, md5_now: str, map_rows: list[dict], pre: dict, music_root) -> str | None:
    """The original in /srv/incoming this /srv/music copy was made from. First choice: same audio hash
    *and* the title/genres Navidrome showed before the cleanup (`pre`: rel path → (title, genres));
    else the one library-map row filed at the song's old path (an ID3v1 rewrite changes an mp3's hash)."""
    rel = os.path.relpath(entry["path_before"], music_root)
    title, genres = pre.get(rel, (None, []))
    for r in (r for r in map_rows if r["audio_md5"] == md5_now):
        m = MediaFile(r["original_path"])
        if _norm(m.title) == _norm(title) and _genre_set(m.genres or []) == _genre_set(genres):
            return r["original_path"]
    at_path = [r for r in map_rows if r["new_path"] == rel]
    return at_path[0]["original_path"] if len(at_path) == 1 else None


def repair(a) -> int:
    """Undo beets' full-field writes from the first live run: original bytes + only the intended changes."""
    entries = json.loads(a.manifest.read_text())
    todo = [e for e in entries if e.get("written", True) and not e.get("restored_from")]
    rows = [dict(r, original_path=r["original_path"] if r["original_path"].startswith("/")
                 else f"/srv/incoming/library-import/{r['original_path']}") for r in read_csv(a.library_map)]
    with closing(open_ro(a.pre_db)) as con:
        pre = {p: (t, [g["value"] for g in json.loads(tags or "{}").get("genre", [])])
               for p, t, tags in con.execute("SELECT path, title, tags FROM media_file")}
    with ThreadPoolExecutor(8) as ex:
        hashes = list(ex.map(lambda e: audio_md5(Path(e.get("path_after") or e["path_before"])), todo))
    done = missing = 0
    for e, h in zip(todo, hashes):
        src = find_original(e, h, rows, pre, a.music)
        if src is None:
            e["restore_skipped"] = "no original found"
            missing += 1
        else:
            restore(e, src, a.music, a.trash)
            done += 1
        _save_manifest(a.manifest, entries)
    print(f"{done} files restored from their originals with only the intended changes; {missing} without an original; "
          f"previous versions kept in {a.trash}")
    return 0 if not missing else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--music", type=Path, default=Path("/srv/music"))
    ap.add_argument("--library-map", type=Path, default=REPO / "docs" / "library-map.csv")
    ap.add_argument("--pre-db", type=Path, default=Path("/srv/docker/navidrome/navidrome.db.bak-2026-10-15-pre-tagcleanup"),
                    help="navidrome.db as it was before the cleanup (originals are matched against it)")
    ap.add_argument("--trash", type=Path, default=Path("/srv/docker/_trash") / datetime.date.today().isoformat())
    return repair(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
