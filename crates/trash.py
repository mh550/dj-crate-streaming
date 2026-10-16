"""What the trash holds, for `crates.cli status` (spec §4.3: never auto-emptied; Michael empties it).

Trash is `/srv/docker/_trash/<YYYY-MM-DD>/<path relative to /srv/music>` (the runbook's /srv/_trash needs
root to create); each dated folder has a MOVES.txt of reverse `mv` commands, which is not counted.
The crates container sees it read-only at $CRATES_TRASH (compose mounts it at /trash); the worker mounts it
read-write at the same path and is the only code that moves a library file into it (`move_to_trash`).
"""
from __future__ import annotations

import datetime
import re
import shlex
import shutil
from pathlib import Path

_DATED = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def human(n: int) -> str:
    for unit, size in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if n >= size:
            return f"{n / size:.1f} {unit}"
    return f"{n} B"


def summary(root) -> dict:
    if root is None or not Path(root).is_dir():
        return {"mounted": False}
    root = Path(root)
    files = [p for p in root.rglob("*") if p.is_file() and p.name != "MOVES.txt"]
    total = sum(p.stat().st_size for p in files)
    folders = sorted(p.name for p in root.iterdir() if p.is_dir() and _DATED.match(p.name))
    return {"mounted": True, "files": len(files), "bytes": total, "size": human(total),
            "oldest": folders[0] if folders else None, "folders": folders}


def free_path(target: Path) -> Path:
    """`target`, or "name (2).ext", "name (3).ext"…: trash never overwrites what it already holds."""
    target, n = Path(target), 2
    candidate = target
    while candidate.exists():
        candidate = target.with_name(f"{target.stem} ({n}){target.suffix}")
        n += 1
    return candidate


def move_to_trash(rel: str, music_root, trash_root, day: str | None = None) -> Path:
    """Move `<music_root>/<rel>` to `<trash_root>/<day>/<rel>` (never overwriting: see `free_path`) and return
    where it went. Nothing in this project deletes a library file; this is the only way one leaves it.

    `rel` must be a plain relative path inside the library that names an existing file: `..`, an absolute path,
    an empty string or a directory raises ValueError before anything moves. The reverse `mv <dst> <src>` is
    appended to `<trash_root>/<day>/MOVES.txt` (shell-quoted, so it can be pasted) before this returns."""
    day = day or datetime.date.today().isoformat()
    if not _DATED.match(day):
        raise ValueError(f"not a trash day: {day!r}")
    path = Path(rel)
    if not path.parts or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"not a path inside the library: {rel!r}")
    music_root, trash_root = Path(music_root), Path(trash_root)
    src = music_root / path
    if not src.is_file():
        raise ValueError(f"not a file in the library: {rel!r}")
    dst = free_path(trash_root / day / path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(src, dst)
    with (trash_root / day / "MOVES.txt").open("a", encoding="utf-8") as log:
        log.write(f"mv {shlex.quote(str(dst))} {shlex.quote(str(src))}\n")
    return dst
