"""Library map: remember which curated folder every track came from.

Michael organises his music by genre/vibe folders. beets re-files everything as
Artist/Album (Year)/NN - Title, so before importing we record each audio file's
original relative path plus a *tag-independent* hash of its audio stream; after
the import we hash /srv/music the same way and fill in the new path. Tags may be
rewritten by beets, the audio bytes are not, so the hash survives the move.

    python3 -m scripts.library_map build /srv/incoming/library-import docs/library-map.csv
    python3 -m scripts.library_map fill  docs/library-map.csv /srv/music

stdlib + ffmpeg (for the hash).
"""
from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable

AUDIO_EXT = {"flac", "mp3", "m4a", "wav", "aiff", "aif", "ogg", "opus", "alac", "wma"}
SKIP_DIRS = ("_Serato_", "_Serato_Backup")
FIELDS = ["original_path", "folder", "ext", "size", "audio_md5", "new_path"]

Hasher = Callable[[Path], str]


def audio_md5(path: Path) -> str:
    """MD5 of the raw audio packets (no container metadata/tags)."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-c", "copy", "-f", "md5", "-"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return out.removeprefix("MD5=")


def audio_files(root: Path) -> Iterable[Path]:
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower().lstrip(".") not in AUDIO_EXT:
            continue
        rel = p.relative_to(root)
        if rel.parts and rel.parts[0] in SKIP_DIRS:
            continue
        yield rel


def build_rows(root: Path, hasher: Hasher = audio_md5) -> list[dict]:
    rows = []
    for rel in audio_files(root):
        rows.append({
            "original_path": rel.as_posix(),
            "folder": rel.parent.as_posix() if rel.parent != Path(".") else "",
            "ext": rel.suffix.lower().lstrip("."),
            "size": str((root / rel).stat().st_size),
            "audio_md5": hasher(root / rel),
            "new_path": "",
        })
    return rows


def fill_rows(rows: list[dict], music_root: Path, hasher: Hasher = audio_md5) -> dict:
    by_hash: dict[str, str] = {}
    for rel in audio_files(music_root):
        by_hash.setdefault(hasher(music_root / rel), rel.as_posix())
    seen: set[str] = set()
    report = {"matched": 0, "unmatched_originals": [], "unmatched_new": [], "collapsed_duplicates": []}
    used: set[str] = set()
    for r in rows:
        new = by_hash.get(r["audio_md5"], "")
        r["new_path"] = new
        if not new:
            report["unmatched_originals"].append(r["original_path"])
            continue
        report["matched"] += 1
        used.add(new)
        if r["audio_md5"] in seen:
            report["collapsed_duplicates"].append(r["original_path"])
        seen.add(r["audio_md5"])
    report["unmatched_new"] = sorted(set(by_hash.values()) - used)
    return report


def write_csv(rows: list[dict], out: Path) -> None:
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "build":
        rows = build_rows(Path(argv[1]))
        write_csv(rows, Path(argv[2]))
        print(f"{len(rows)} audio files mapped → {argv[2]}")
        return 0
    if len(argv) == 3 and argv[0] == "fill":
        rows = read_csv(Path(argv[1]))
        report = fill_rows(rows, Path(argv[2]))
        write_csv(rows, Path(argv[1]))
        print(f"matched {report['matched']}/{len(rows)}; "
              f"unmatched originals {len(report['unmatched_originals'])}; "
              f"new files with no origin {len(report['unmatched_new'])}; "
              f"duplicates collapsed {len(report['collapsed_duplicates'])}")
        for k in ("unmatched_originals", "unmatched_new", "collapsed_duplicates"):
            for item in report[k]:
                print(f"  {k}: {item}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
