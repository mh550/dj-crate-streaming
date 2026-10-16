import os
from pathlib import Path

import pytest

from crates import trash


def test_summary_counts_files_size_and_the_oldest_dated_folder(tmp_path):
    (tmp_path / "2026-10-15/Compilations/x").mkdir(parents=True)
    (tmp_path / "2026-10-15/Compilations/x/a.flac").write_bytes(b"0" * 20)
    (tmp_path / "2026-10-15/MOVES.txt").write_text("mv a b\n")             # the log is not trash
    (tmp_path / "2026-10-13").mkdir()
    (tmp_path / "2026-10-13/b.mp3").write_bytes(b"0" * 10)
    s = trash.summary(tmp_path)
    assert s == {"mounted": True, "files": 2, "bytes": 30, "size": "30 B", "oldest": "2026-10-13", "folders": ["2026-10-13", "2026-10-15"]}


def test_summary_when_not_mounted_or_empty(tmp_path):
    assert trash.summary(None) == {"mounted": False}
    assert trash.summary(tmp_path / "nope") == {"mounted": False}
    assert trash.summary(tmp_path) == {"mounted": True, "files": 0, "bytes": 0, "size": "0 B", "oldest": None, "folders": []}


def test_human_sizes():
    assert [trash.human(n) for n in (0, 1023, 1024 * 1024 * 810, 3 * 1024 ** 3)] == ["0 B", "1023 B", "810.0 MB", "3.0 GB"]


def _library(tmp_path, *rels):
    music = tmp_path / "music"
    for rel in rels:
        (music / rel).parent.mkdir(parents=True, exist_ok=True)
        (music / rel).write_text(rel)
    return music


def test_move_to_trash_never_overwrites_and_logs_the_reverse_move(tmp_path):
    import shlex
    music, tr = _library(tmp_path, "A/x.flac"), tmp_path / "trash"
    first = trash.move_to_trash("A/x.flac", music, tr, day="2026-10-16")
    (music / "A/x.flac").write_text("a second, later copy")             # filed again under the same name
    second = trash.move_to_trash("A/x.flac", music, tr, day="2026-10-16")
    assert first == tr / "2026-10-16/A/x.flac" and second == tr / "2026-10-16/A/x (2).flac"
    assert first.read_text() == "A/x.flac" and second.read_text() == "a second, later copy"
    assert not (music / "A/x.flac").exists()
    lines = (tr / "2026-10-16/MOVES.txt").read_text().splitlines()
    assert [shlex.split(line) for line in lines] == [["mv", str(first), str(music / "A/x.flac")],
                                                     ["mv", str(second), str(music / "A/x.flac")]]


def test_move_to_trash_quotes_awkward_names_and_defaults_to_today(tmp_path):
    import datetime
    import shlex
    rel = "Beyoncé/It's a 'quote' & more.flac"
    music, tr = _library(tmp_path, rel), tmp_path / "trash"
    dst = trash.move_to_trash(rel, music, tr)
    day = datetime.date.today().isoformat()
    assert dst == tr / day / rel and dst.is_file()
    assert shlex.split((tr / day / "MOVES.txt").read_text()) == ["mv", str(dst), str(music / rel)]


@pytest.mark.parametrize("rel", ["../x.flac", "A/../../x.flac", "/etc/passwd", "", "A/missing.flac"])
def test_move_to_trash_refuses_paths_outside_the_library(tmp_path, rel):
    music, tr = _library(tmp_path, "A/x.flac"), tmp_path / "trash"
    (tmp_path / "x.flac").write_text("outside the library")
    with pytest.raises(ValueError):
        trash.move_to_trash(rel, music, tr, day="2026-10-16")
    assert (tmp_path / "x.flac").exists() and (music / "A/x.flac").exists() and not tr.exists()


def test_move_to_trash_refuses_a_directory(tmp_path):
    music, tr = _library(tmp_path, "A/x.flac"), tmp_path / "trash"
    with pytest.raises(ValueError):
        trash.move_to_trash("A", music, tr, day="2026-10-16")
    assert (music / "A/x.flac").exists()


# --- Task 8 review: a durable move, the intent logged first, nothing outside the library --------------------------

def test_move_to_trash_refuses_a_symlinked_parent_outside_the_library(tmp_path):
    music, tr = _library(tmp_path, "A/x.flac"), tmp_path / "trash"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "y.flac").write_text("not in the library")
    (music / "B").symlink_to(outside)                                     # music/B/y.flac resolves outside
    with pytest.raises(ValueError, match="outside the library"):
        trash.move_to_trash("B/y.flac", music, tr, day="2026-10-16")
    assert (outside / "y.flac").exists() and not tr.exists()


def test_cross_filesystem_move_is_copied_synced_and_renamed(tmp_path, monkeypatch):
    music, tr = _library(tmp_path, "A/x.flac"), tmp_path / "trash"
    synced = []
    real_fsync = os.fsync
    monkeypatch.setattr(trash, "_same_fs", lambda a, b: False)
    monkeypatch.setattr(trash.os, "fsync", lambda fd: synced.append(os.readlink(f"/proc/self/fd/{fd}")) or real_fsync(fd))
    dst = trash.move_to_trash("A/x.flac", music, tr, day="2026-10-16")
    assert dst == tr / "2026-10-16/A/x.flac" and dst.read_text() == "A/x.flac" and not (music / "A/x.flac").exists()
    names = [Path(x).name for x in synced]
    copy = next(i for i, x in enumerate(names) if x.startswith(".partial-"))   # the copy's data, before its rename
    assert names[copy + 1:] == ["A", "A"] and synced[copy + 1] == str(dst.parent) and synced[-1] == str(music / "A")
    assert [p.name for p in dst.parent.iterdir()] == ["x.flac"]           # no temp file left


def test_a_partial_copy_left_by_a_crash_is_ignored_and_cleaned_on_retry(tmp_path, monkeypatch):
    music, tr = _library(tmp_path, "A/x.flac"), tmp_path / "trash"
    monkeypatch.setattr(trash, "_same_fs", lambda a, b: False)
    real_copy = trash.shutil.copy2

    def crash(*a, **kw):
        real_copy(*a, **kw)
        raise OSError("killed mid-copy")
    monkeypatch.setattr(trash.shutil, "copy2", crash)
    with pytest.raises(OSError):
        trash.move_to_trash("A/x.flac", music, tr, day="2026-10-16")
    left = list((tr / "2026-10-16/A").iterdir())
    assert len(left) == 1 and left[0].name.startswith(".partial-") and (music / "A/x.flac").exists()
    assert trash.summary(tr)["files"] == 0                                # a partial copy is not trash
    monkeypatch.setattr(trash.shutil, "copy2", real_copy)
    dst = trash.move_to_trash("A/x.flac", music, tr, day="2026-10-16")
    assert dst == tr / "2026-10-16/A/x.flac"                              # not "x (2).flac"
    assert [p.name for p in dst.parent.iterdir()] == ["x.flac"]


def test_the_reverse_move_is_logged_before_the_move_and_a_failed_move_says_so(tmp_path, monkeypatch):
    import shlex
    music, tr = _library(tmp_path, "A/x.flac"), tmp_path / "trash"
    seen = []

    def link(a, b):
        seen.append((tr / "2026-10-16/MOVES.txt").read_text())
        raise PermissionError("read-only")
    monkeypatch.setattr(trash.os, "link", link)
    monkeypatch.setattr(trash.os, "rename", link)
    with pytest.raises(PermissionError):
        trash.move_to_trash("A/x.flac", music, tr, day="2026-10-16")
    dst = tr / "2026-10-16/A/x.flac"
    assert shlex.split(seen[0]) == ["mv", str(dst), str(music / "A/x.flac")]
    assert (tr / "2026-10-16/MOVES.txt").read_text().splitlines()[-1].startswith("# not moved")
    assert (music / "A/x.flac").exists() and not dst.exists()


def test_move_to_trash_calls_before_with_the_destination_before_moving(tmp_path):
    music, tr = _library(tmp_path, "A/x.flac"), tmp_path / "trash"
    seen = []
    dst = trash.move_to_trash("A/x.flac", music, tr, day="2026-10-16",
                              before=lambda d: seen.append((d, (music / "A/x.flac").exists())))
    assert seen == [(dst, True)]


def test_restore_puts_a_trashed_file_back_and_never_overwrites(tmp_path):
    music, tr = _library(tmp_path, "A/x.flac"), tmp_path / "trash"
    dst = trash.move_to_trash("A/x.flac", music, tr, day="2026-10-16")
    assert trash.restore(dst, "A/x.flac", music) == music / "A/x.flac"
    assert (music / "A/x.flac").read_text() == "A/x.flac" and not dst.exists()
    dst = trash.move_to_trash("A/x.flac", music, tr, day="2026-10-16")
    (music / "A/x.flac").write_text("someone filed another file here")
    with pytest.raises(FileExistsError):
        trash.restore(dst, "A/x.flac", music)
    assert dst.exists() and (music / "A/x.flac").read_text() == "someone filed another file here"


def test_exdev_between_bind_mounts_of_one_filesystem_takes_the_copy_path(tmp_path, monkeypatch):
    """Docker bind mounts of one host filesystem share st_dev, yet link/rename across them fail with EXDEV."""
    import errno
    import shlex
    music, tr = _library(tmp_path, "A/x.flac"), tmp_path / "trash"
    real_link, real_rename = os.link, os.rename

    def across(a, b) -> bool:
        return Path(a).relative_to(tmp_path).parts[0] != Path(b).relative_to(tmp_path).parts[0]

    def link(a, b):
        if across(a, b):
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real_link(a, b)

    def rename(a, b):
        if across(a, b):
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real_rename(a, b)
    monkeypatch.setattr(trash.os, "link", link)
    monkeypatch.setattr(trash.os, "rename", rename)
    dst = trash.move_to_trash("A/x.flac", music, tr, day="2026-10-16")
    assert dst == tr / "2026-10-16/A/x.flac" and dst.read_text() == "A/x.flac"
    assert not (music / "A/x.flac").exists()
    assert [p.name for p in dst.parent.iterdir()] == ["x.flac"]
    assert shlex.split((tr / "2026-10-16/MOVES.txt").read_text()) == ["mv", str(dst), str(music / "A/x.flac")]
