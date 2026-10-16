"""File one verified download into the library with beets, as its own singleton import (D18, D22).

    <downloads>/.staging/<id>-<ts>/<file>  ──beet import -q -s -m -W -l <log>──▶  /srv/music/<beets path>
                                            └─ matched? ──beet write path:<that file>──▶ full tags

The D22 rule: beets writes full tags only after it applied a MusicBrainz match, and only to the file this
call just imported. A match is confident only when it is confirmed: beets applies a length-less MusicBrainz
recording on artist + title alone, which for a DJ library (radio edit vs 12") is a guess, so `beet write`
runs only when the `confirm` hook says the recording's length agrees with the file (sourcing.musicbrainz).
With no confirmer, nothing is ever written. An as-is import is never rewritten: `-W` keeps the import
itself from writing, and the file lands byte-identical (measured on beets 1.6.0). beets 1.6 rewrites every
field it knows when it writes, which collapses multi-valued GENRE/ISRC/ARTIST (the M2 trap, see deploy/beets.yaml), so writing
an unmatched file would only do damage.

Why the import log, not `mb_trackid`, says "matched": an uploader's file that already carries
MUSICBRAINZ_TRACKID imports as-is with that id in `items.mb_trackid` (measured). beets'
ImportSession.log_choice writes `asis <path>` for an as-is choice and nothing for an applied match; a kept
duplicate adds `duplicate-keep <path>` after the `asis` line. So each call gets its own `-l` log, and
"matched" means: a new `items` row and no line starting `asis `.

This module drives `beet` as a subprocess and reads library.db read-only; it never imports beets itself.
fill_missing_tags imports scripts.tag_cleanup.write_minimal (the one field-by-field tag writer) lazily,
because scripts.tag_cleanup pulls in the beets package at import time; only the worker image, which
installs beets 1.6.0, reaches that import.
Only a folder under `.staging` is accepted, which keeps beets away from the originals and the library.
"""
from __future__ import annotations

import os
import re
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from scripts.library_map import AUDIO_EXT


@dataclass
class FiledItem:
    path: Path          # absolute, as beets filed it (decoded from the items.path BLOB)
    artist: str
    title: str
    mb_trackid: str     # "" when none
    matched: bool       # beets applied a MusicBrainz match (no "asis " line in this call's import log)
    filled: list[str] = field(default_factory=list)   # tag fields filled from the wanted row before import
    length: float = 0.0     # beets items.length, seconds
    note: str = ""          # why a beets match was or was not confirmed ("" for an as-is import)


class FilingError(Exception):
    """beets failed, or did something other than file exactly one item."""


def fill_missing_tags(path: Path, names: dict[str, str]) -> list[str]:
    """Write each of `names` (keys "artist", "title") whose tag in `path` is empty, via
    scripts.tag_cleanup.write_minimal (imported lazily); return the fields written. Reads with mediafile.MediaFile.

    An untagged download would otherwise be filed as `_/Singles.flac` (measured). The file is our fresh
    download in staging, never a library file, and only the empty fields are written."""
    # Lazily: scripts.tag_cleanup imports the beets package at its top (and sets up the sys.path for
    # mediafile), so only a caller that actually fills tags (the worker, with beets 1.6.0) pays for it.
    from scripts.tag_cleanup import write_minimal
    from mediafile import MediaFile

    current = MediaFile(str(path))
    changes = {k: v for k, v in names.items() if k in ("artist", "title") and v and not (getattr(current, k) or "").strip()}
    if changes:
        write_minimal(path, changes)
    return list(changes)


def _tail(text: str, n=3) -> str:
    return "\n".join((text or "").strip().splitlines()[-n:])


class BeetsFiler:
    def __init__(self, config: Path, *, library: Path | None = None, beet: str = "beet",
                 runner=subprocess.run, tagger=fill_missing_tags, timeout_s: float = 600,
                 confirm: Callable[[FiledItem], tuple[bool, str]] | None = None):
        self.config, self.beet, self.runner, self.tagger, self.timeout_s = Path(config), beet, runner, tagger, timeout_s
        self.confirm = confirm
        if library is None:
            m = re.search(r"^library:\s*(\S+)", self.config.read_text(encoding="utf-8"), re.M)
            if not m:
                raise ValueError(f"no top-level library: in {self.config}")
            library = Path(m.group(1)).expanduser()
        self.library = Path(library)

    def _rows(self, sql: str, args=()) -> list[tuple]:
        """Read-only: the worker's beets owns library.db; this never takes a write lock on it."""
        with closing(sqlite3.connect(f"{self.library.absolute().as_uri()}?mode=ro", uri=True)) as db:
            return db.execute(sql, args).fetchall()

    def _max_id(self) -> int:
        try:
            return self._rows("SELECT max(id) FROM items")[0][0] or 0
        except sqlite3.OperationalError:                 # no library.db yet, or no items table
            return 0

    def _beet(self, *args: str) -> subprocess.CompletedProcess:
        cmd = [self.beet, "-c", str(self.config), *args]
        return self.runner(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=self.timeout_s)

    def file(self, folder: Path, log: Path, *, names: dict[str, str] | None = None) -> FiledItem | None:
        """Import the download in `folder` (one file, under `.staging`); None when beets imported nothing
        (the file is still in `folder`). `log` is this call's own beets import log."""
        folder, log = Path(folder), Path(log)
        if folder.resolve().parent.name != ".staging":        # resolved, so ".staging/.." or a symlink out fails
            raise ValueError(f"refusing to import {folder}: not a .staging folder")
        audio = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower().lstrip(".") in AUDIO_EXT]
        if len(audio) != 1:                              # one download per folder, so one row to find afterwards
            raise FilingError(f"expected one audio file in {folder}, found {len(audio)}")
        filled = self.tagger(audio[0], names) if names else []
        log.unlink(missing_ok=True)                      # beets appends: a stale "asis" line would hide a real match
        before = self._max_id()
        done = self._beet("import", "-q", "-s", "-m", "-W", "-l", str(log), str(folder))
        if done.returncode:
            raise FilingError(f"beet import failed ({done.returncode}): {_tail(done.stderr)}")
        rows = self._rows("SELECT id, path, mb_trackid, artist, title, length FROM items WHERE id > ? ORDER BY id", (before,))
        if not rows:
            return None
        if len(rows) > 1:
            raise FilingError(f"beets imported {len(rows)} items from {folder}")
        _, raw, mb_trackid, artist, title, length = rows[0]
        path = Path(os.fsdecode(raw))
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines() if log.exists() else None
        matched = lines is not None and not any(line.startswith("asis ") for line in lines)
        item = FiledItem(path, artist or "", title or "", mb_trackid or "", False, filled, float(length or 0.0))
        if not matched:
            return item
        if self.confirm is None:
            item.note = "beets matched but no confirmer is configured; tags left as-is"
            return item
        ok, item.note = self.confirm(item)
        if ok:
            done = self._beet("write", f"path:{path}")
            if done.returncode:
                raise FilingError(f"beet write failed ({done.returncode}): {_tail(done.stderr)}")
            item.matched = True
        return item
