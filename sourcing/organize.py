"""File a verified download into the library the way beets lays it out.

    Artist/Album (Year)/NN - Title.ext      (deploy/beets.yaml `paths.default`)
    Artist/Singles/NN - Title.ext           when there is no album

Names come from the *wanted* record (what the crate asked for), not from the file's own
tags, so the result is deterministic and never depends on a stranger's tagging. Never
overwrites: an existing target gets " (2)", " (3)" … before the extension.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _safe(s: str) -> str:
    s = _BAD.sub("_", (s or "").strip())
    return s.strip(". ") or "_"                # no hidden, "..", or trailing-dot components


def target_path(music_root: Path, artist: str, title: str, ext: str, album: str | None = None,
                year: int | None = None, track: int | None = None) -> Path:
    album_dir = _safe(album) if album else "Singles"
    if album and year:
        album_dir = f"{album_dir} ({year})"
    stem = f"{track or 0:02d} - {_safe(title)}"
    ext = ext.lower().lstrip(".")
    folder = Path(music_root) / _safe(artist) / album_dir
    candidate = folder / f"{stem}.{ext}"
    n = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({n}).{ext}"
        n += 1
    return candidate


def file_into(src: Path, music_root: Path, *, artist: str, title: str, album: str | None = None,
              year: int | None = None, track: int | None = None) -> Path:
    dest = target_path(music_root, artist, title, src.suffix, album, year, track)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return dest
