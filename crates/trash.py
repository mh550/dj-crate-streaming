"""What the trash holds, for `crates.cli status` (spec §4.3: never auto-emptied; Michael empties it).

Trash is `/srv/docker/_trash/<YYYY-MM-DD>/<path relative to /srv/music>` (the runbook's /srv/_trash needs
root to create); each dated folder has a MOVES.txt of reverse `mv` commands, which is not counted.
The crates container sees it read-only at $CRATES_TRASH (compose mounts it at /trash); the worker mounts it
read-write at the same path and is the only code that moves a library file into it (`move_to_trash`).

A move must survive a crash at any instant with the file in one place or the other, never neither: within one
filesystem a hard link (which never overwrites) then an unlink; across filesystems a copy to a `.partial-<uuid>-`
name in the destination folder, fsynced, linked to its final name, then the source unlinked, each folder fsynced.
A `.partial-` file is never trash: `summary` ignores it and the next move of the same file removes it.
"""
from __future__ import annotations

import datetime
import errno
import os
import re
import shlex
import shutil
import uuid
from pathlib import Path

_DATED = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PARTIAL = ".partial-"            # a copy in progress (cross-filesystem move); never trash, never a free_path hit


def human(n: int) -> str:
    for unit, size in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if n >= size:
            return f"{n / size:.1f} {unit}"
    return f"{n} B"


def summary(root) -> dict:
    if root is None or not Path(root).is_dir():
        return {"mounted": False}
    root = Path(root)
    files = [p for p in root.rglob("*") if p.is_file() and p.name != "MOVES.txt" and not p.name.startswith(PARTIAL)]
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


def _fsync_dir(d: Path) -> None:
    fd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _same_fs(a: Path, b: Path) -> bool:
    return a.stat().st_dev == b.stat().st_dev


def _place(src: Path, dst: Path) -> None:
    """Give `src`'s file the name `dst` without ever overwriting: a hard link (FileExistsError when taken); where the
    filesystem has no hard links, a rename after checking the name is free."""
    try:
        os.link(src, dst)
    except FileExistsError:
        raise
    except OSError:
        if dst.exists():
            raise FileExistsError(dst) from None
        os.rename(src, dst)
        return
    src.unlink()


def durable_move(src: Path, dst: Path) -> None:
    """Move one file to `dst` (whose folder exists and whose name must be free) so that a crash leaves it at `src`,
    at `dst`, or (between the steps of a same-filesystem move) at both, never nowhere; see the module docstring.
    Two Docker bind mounts of one host filesystem share st_dev but refuse links and renames between them (EXDEV):
    that is a cross-filesystem move, so the copy path is taken."""
    src, dst = Path(src), Path(dst)
    for old in dst.parent.glob(f"{PARTIAL}*-{src.name}"):      # an earlier attempt's half copy of this file
        old.unlink(missing_ok=True)
    if _same_fs(src, dst.parent):
        try:
            _place(src, dst)                                   # link, unlink: one inode, two names for a moment
        except OSError as e:
            if e.errno != errno.EXDEV:
                raise
        else:
            _fsync_dir(dst.parent)
            _fsync_dir(src.parent)
            return
    tmp = dst.parent / f"{PARTIAL}{uuid.uuid4().hex}-{src.name}"
    try:
        shutil.copy2(src, tmp)                                 # data and mtime
        with tmp.open("rb") as fh:
            os.fsync(fh.fileno())
        _place(tmp, dst)                                       # within the destination folder
    except BaseException:
        if tmp.exists() and dst.exists() and os.path.samefile(tmp, dst):
            tmp.unlink()                                       # placed: only the temp name is left over
        raise
    _fsync_dir(dst.parent)                                     # the copy is durable under its name...
    src.unlink()                                               # ...before the original goes
    _fsync_dir(src.parent)


def move_to_trash(rel: str, music_root, trash_root, day: str | None = None, before=None) -> Path:
    """Move `<music_root>/<rel>` to `<trash_root>/<day>/<rel>` (never overwriting: see `free_path`) and return
    where it went. Nothing in this project deletes a library file; this is the only way one leaves it.

    `rel` must be a plain relative path inside the library that names an existing file: `..`, an absolute path,
    an empty string, a directory or a path that resolves outside the library (a symlinked folder) raises ValueError
    before anything moves. The reverse `mv <dst> <src>` is appended to `<trash_root>/<day>/MOVES.txt`
    (shell-quoted, so it can be pasted) BEFORE the move, as its intent; a move that then fails appends "# not moved"
    and re-raises. `before(dst)` is called after that line and before the move (the caller records where it goes)."""
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
    if not src.resolve().is_relative_to(music_root.resolve()):
        raise ValueError(f"{rel!r} resolves outside the library ({src.resolve()})")
    dst = free_path(trash_root / day / path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    log = trash_root / day / "MOVES.txt"
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"mv {shlex.quote(str(dst))} {shlex.quote(str(src))}\n")
        fh.flush()
        os.fsync(fh.fileno())
    try:
        if before is not None:
            before(dst)
        durable_move(src, dst)
    except BaseException as e:
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"# not moved ({type(e).__name__}): the line above did not happen\n")
        raise
    return dst


def restore(trashed: Path, rel: str, music_root) -> Path:
    """Put a file `move_to_trash` moved back at `<music_root>/<rel>`; FileExistsError when that path is taken (a
    new file there is never overwritten). Logged in the trash day's MOVES.txt as a comment."""
    trashed, music_root, path = Path(trashed), Path(music_root), Path(rel)
    if not path.parts or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"not a path inside the library: {rel!r}")
    dst = music_root / path
    if dst.exists():
        raise FileExistsError(f"{rel} is taken; {trashed} stays in the trash")
    dst.parent.mkdir(parents=True, exist_ok=True)
    durable_move(trashed, dst)
    with _day_log(trashed) as fh:
        fh.write(f"# restored {shlex.quote(str(trashed))} -> {shlex.quote(str(dst))}\n")
    return dst


def _day_log(trashed: Path):
    """MOVES.txt of the dated folder holding `trashed` (its nearest dated ancestor)."""
    day = next((d for d in trashed.parents if _DATED.match(d.name)), trashed.parent)
    return (day / "MOVES.txt").open("a", encoding="utf-8")
