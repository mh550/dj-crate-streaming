import csv
from pathlib import Path

from scripts import library_map as lm


def test_audio_files_skips_serato_and_non_audio(tmp_path):
    (tmp_path / "Tea tent").mkdir()
    (tmp_path / "Tea tent" / "a.flac").write_bytes(b"x")
    (tmp_path / "Tea tent" / "cover.jpg").write_bytes(b"x")
    (tmp_path / "_Serato_").mkdir()
    (tmp_path / "_Serato_" / "b.mp3").write_bytes(b"x")
    (tmp_path / "root.MP3").write_bytes(b"x")
    rels = sorted(str(p) for p in lm.audio_files(tmp_path))
    assert rels == ["Tea tent/a.flac", "root.MP3"]


def test_build_rows_records_folder_ext_size(tmp_path):
    (tmp_path / "Haus" / "DnB").mkdir(parents=True)
    f = tmp_path / "Haus" / "DnB" / "t.flac"
    f.write_bytes(b"abcd")
    rows = lm.build_rows(tmp_path, hasher=lambda p: "h1")
    assert rows == [{
        "original_path": "Haus/DnB/t.flac", "folder": "Haus/DnB", "ext": "flac",
        "size": "4", "audio_md5": "h1", "new_path": "",
    }]


def test_fill_matches_by_hash_and_reports_leftovers(tmp_path):
    rows = [
        {"original_path": "a.flac", "folder": "", "ext": "flac", "size": "1", "audio_md5": "h1", "new_path": ""},
        {"original_path": "b.flac", "folder": "", "ext": "flac", "size": "1", "audio_md5": "h2", "new_path": ""},
        {"original_path": "b2.flac", "folder": "", "ext": "flac", "size": "1", "audio_md5": "h2", "new_path": ""},
        {"original_path": "c.flac", "folder": "", "ext": "flac", "size": "1", "audio_md5": "h3", "new_path": ""},
    ]
    music = tmp_path / "music"; (music / "A").mkdir(parents=True)
    (music / "A" / "01.flac").write_bytes(b"x"); (music / "A" / "02.flac").write_bytes(b"x")
    hashes = {str(music / "A" / "01.flac"): "h1", str(music / "A" / "02.flac"): "h2"}
    report = lm.fill_rows(rows, music, hasher=lambda p: hashes[str(p)])
    assert rows[0]["new_path"] == "A/01.flac"
    assert rows[1]["new_path"] == "A/02.flac" and rows[2]["new_path"] == "A/02.flac"
    assert rows[3]["new_path"] == ""
    assert report == {"matched": 3, "unmatched_originals": ["c.flac"], "unmatched_new": [], "collapsed_duplicates": ["b2.flac"]}


def test_csv_roundtrip(tmp_path):
    rows = [{"original_path": "x.mp3", "folder": "", "ext": "mp3", "size": "9", "audio_md5": "h", "new_path": ""}]
    out = tmp_path / "map.csv"
    lm.write_csv(rows, out)
    assert lm.read_csv(out) == rows
    with out.open(newline="") as fh:
        assert next(csv.reader(fh)) == lm.FIELDS
