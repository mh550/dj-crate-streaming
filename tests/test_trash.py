import os

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
