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

An album request's row (S2-06, docs/plans/2026-10-22-S2-album-tags.md) is filed with `album=AlbumIdentity(…)`: the
fields that differ are written on the staged file with write_minimal (after the caller's `on_tagged(old)` has
recorded the old values), and the import gets `--set dj_album=1`, so deploy/beets.yaml's `dj_album:1:` path files it
at `$albumartist/$album ($year)/$track - $title` instead of `$artist/Singles/$title`.
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
    old: dict | None = None     # an album row's fields before the album tags were written ({field: old}); None: none written


@dataclass(frozen=True)
class AlbumIdentity:
    """What an album request's track carries (the plan's ## Fields). None for track/tracktotal: not written; for
    year: cleared with month and day (D51 *default*); for mb_albumid: cleared with mb_albumartistid."""
    album: str
    albumartist: str
    track: int | None
    tracktotal: int | None
    year: int | None
    mb_albumid: str | None


class FilingError(Exception):
    """beets failed, or did something other than file exactly one item. `item` is set when the file was already
    imported into the library before the failure (a failed `beet write`): the caller must not lose its path."""

    def __init__(self, message: str, item: "FiledItem | None" = None):
        super().__init__(message)
        self.item = item


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


def _stray_albumartist(current, albumartist: str) -> bool:
    """Whether a raw album-artist key mediafile does not read says something else: on Vorbis comments (FLAC, ogg)
    mediafile reads the first of ALBUM ARTIST/ALBUMARTIST/ALBUM_ARTIST; on ID3 a TXXX alias beside TPE2."""
    import mutagen.id3
    from mutagen._vorbis import VCommentDict
    from scripts.tag_cleanup import ALIASES

    tags = getattr(current.mgfile, "tags", None)
    if isinstance(tags, mutagen.id3.ID3):
        return any(k.casefold() in {a.casefold() for a in ALIASES["albumartist"]} for k in tags.keys())
    if isinstance(tags, VCommentDict):
        return any(v != albumartist for k in ("ALBUMARTIST", "ALBUM ARTIST", "ALBUM_ARTIST") for v in tags.get(k, []))
    return False


def album_changes(path: Path, identity: AlbumIdentity) -> tuple[dict, dict]:
    """(changes, old) for `path` against `identity`: only the fields whose value differs, and their current values
    (None for an absent field). A written or cleared year takes month and day with it; `comp` is in the diff only
    when the file says True (False on a file without the tag would add COMPILATION=0, measured)."""
    import scripts.tag_cleanup  # noqa: F401  (as fill_missing_tags: it puts Debian's beets and mediafile on sys.path)
    from mediafile import MediaFile

    current = MediaFile(str(path))

    def now(k):                                          # "" and 0 are mediafile's none values: absent
        return getattr(current, k) or None
    want = {"album": identity.album, "albumartist": identity.albumartist}
    for k in ("track", "tracktotal"):
        if getattr(identity, k):
            want[k] = getattr(identity, k)
    if identity.mb_albumid:
        want["mb_albumid"] = identity.mb_albumid
    else:
        want |= {"mb_albumid": None, "mb_albumartistid": None}
    changes = {k: v for k, v in want.items() if now(k) != v}
    if "albumartist" not in changes and _stray_albumartist(current, identity.albumartist):
        changes["albumartist"] = identity.albumartist      # write_minimal writes every key and drops the ID3 aliases
    date = {"year": identity.year or None, "month": None, "day": None}
    if any(now(k) != v for k, v in date.items()):
        changes |= date
    if current.comp:
        changes["comp"] = False
    return changes, {k: True if k == "comp" else now(k) for k in changes}


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
        """The highest items id before an import. Only "no library.db yet" or "no items table yet" mean 0: a
        locked or hot-journalled DB read as 0 would make every existing row look like this import's, so it fails
        here, before beets runs."""
        if not self.library.exists():
            return 0
        try:
            return self._rows("SELECT max(id) FROM items")[0][0] or 0
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                return 0
            raise FilingError(f"library.db unreadable: {e}") from e

    def _beet(self, *args: str) -> subprocess.CompletedProcess:
        cmd = [self.beet, "-c", str(self.config), *args]
        return self.runner(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=self.timeout_s)

    def file(self, folder: Path, log: Path, *, names: dict[str, str] | None = None,
             on_imported: Callable[[FiledItem], None] | None = None, album: AlbumIdentity | None = None,
             on_tagged: Callable[[dict], None] | None = None) -> FiledItem | None:
        """Import the download in `folder` (one file, under `.staging`); None when beets imported nothing
        (the file is still in `folder`). `log` is this call's own beets import log. `on_imported(item)` runs as
        soon as the imported item is known, before the confirmer or `beet write`, so the caller can record the
        library path before anything slow or fallible happens.

        `album` (an album request's row): the fields that differ from it are written on the staged file, and the
        import gets `--set dj_album=1` (the album path). `on_tagged(old)` runs before that write and must make the
        record durable (log and commit): an exception there stops before anything is written. Nothing differs →
        no write, no callback, `old` None."""
        folder, log = Path(folder), Path(log)
        if folder.resolve().parent.name != ".staging":        # resolved, so ".staging/.." or a symlink out fails
            raise ValueError(f"refusing to import {folder}: not a .staging folder")
        audio = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower().lstrip(".") in AUDIO_EXT]
        if len(audio) != 1:                              # one download per folder, so one row to find afterwards
            raise FilingError(f"expected one audio file in {folder}, found {len(audio)}")
        filled = self.tagger(audio[0], names) if names else []
        old = None
        if album is not None and on_tagged is None:
            raise ValueError("album tags need on_tagged: every write has a record first")
        if album is not None:
            changes, old = album_changes(audio[0], album)
            if changes:
                on_tagged(old)                           # the record first: every write has one
                from scripts.tag_cleanup import write_minimal
                write_minimal(audio[0], changes)
            else:
                old = None
        log.unlink(missing_ok=True)                      # beets appends: a stale "asis" line would hide a real match
        before = self._max_id()
        flag = ["--set", "dj_album=1"] if album is not None else []
        done = self._beet("import", "-q", "-s", "-m", "-W", *flag, "-l", str(log), str(folder))
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
        item = FiledItem(path, artist or "", title or "", mb_trackid or "", False, filled, float(length or 0.0), old=old)
        if on_imported is not None:
            on_imported(item)
        if not matched:
            return item
        if self.confirm is None:
            item.note = "beets matched but no confirmer is configured; tags left as-is"
            return item
        ok, item.note = self.confirm(item)
        if ok:
            self._write(item)
            item.matched = True
        return item

    def _write(self, item: FiledItem) -> None:
        """`beet write` on the one file this call imported (a path query names exactly that file). The file is in
        the library already, so a failure carries the item."""
        done = self._beet("write", f"path:{item.path}")
        if done.returncode:
            raise FilingError(f"beet write failed ({done.returncode}): {_tail(done.stderr)}", item)

    def forget(self, path: Path) -> bool:
        """Drop a trashed file from beets' index: `beet remove -f path:<abs>` (no `-d`, so beets never touches a
        file). True when beets exited 0, which includes "nothing matched": the index is a disposable cache, so
        a stale row is the only thing to avoid (it would skew `duplicate_action` and later imports).

        The file must already be gone: handing beets a live path is refused, so a bug elsewhere cannot make
        beets look at, let alone delete, a library file. Only the worker (the one beets writer) calls this."""
        path = Path(path)
        if path.exists():
            raise FilingError(f"refusing to forget {path}: still on disk")
        return self._beet("remove", "-f", f"path:{path}").returncode == 0
