import os

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
