"""What the trash holds, for `crates.cli status` (spec §4.3: never auto-emptied; Michael empties it).

Trash is `/srv/docker/_trash/<YYYY-MM-DD>/<path relative to /srv/music>` (the runbook's /srv/_trash needs
root to create); each dated folder has a MOVES.txt of reverse `mv` commands, which is not counted.
The crates container sees it read-only at $CRATES_TRASH (compose mounts it at /trash).
"""
from __future__ import annotations

import re
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
