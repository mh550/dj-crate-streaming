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
        "size": "4", "audio_md5": "h1", "new_path": "", "other_copies": "",
    }]


def _row(orig, h):
    return {"original_path": orig, "folder": "", "ext": "flac", "size": "1", "audio_md5": h, "new_path": "", "other_copies": ""}


def test_fill_matches_by_hash_and_reports_leftovers(tmp_path):
    rows = [_row("a.flac", "h1"), _row("b.flac", "h2"), _row("b2.flac", "h2"), _row("c.flac", "h3")]
    music = tmp_path / "music"; (music / "A").mkdir(parents=True)
    for n in ("01.flac", "02.flac", "09.flac"): (music / "A" / n).write_bytes(b"x")
    hashes = {str(music / "A" / "01.flac"): "h1", str(music / "A" / "02.flac"): "h2", str(music / "A" / "09.flac"): "h9"}
    report = lm.fill_rows(rows, music, hasher=lambda p: hashes[str(p)])
    assert rows[0]["new_path"] == "A/01.flac"
    assert rows[1]["new_path"] == "A/02.flac" and rows[2]["new_path"] == "A/02.flac"
    assert rows[3]["new_path"] == ""
    assert report == {"matched": 3, "unmatched_originals": ["c.flac"], "unmatched_new": ["A/09.flac"],
                      "collapsed_duplicates": ["b2.flac"], "extra_copies": []}


def test_fill_prefers_the_properly_filed_copy_and_records_the_others(tmp_path):
    rows = [_row("x.flac", "h1")]
    music = tmp_path / "music"
    for rel in ("Compilations/Intuition (1981)/01 - Blue Bossa.flac", "Joe Henderson/Page One (1963)/01 - Blue Bossa.flac",
                "Joe Henderson/Page One (1963)/01 - Blue Bossa.1.flac"):
        (music / rel).parent.mkdir(parents=True, exist_ok=True); (music / rel).write_bytes(b"x")
    report = lm.fill_rows(rows, music, hasher=lambda p: "h1")
    assert rows[0]["new_path"] == "Joe Henderson/Page One (1963)/01 - Blue Bossa.flac"
    assert rows[0]["other_copies"] == "Compilations/Intuition (1981)/01 - Blue Bossa.flac|Joe Henderson/Page One (1963)/01 - Blue Bossa.1.flac"
    assert report["extra_copies"] == ["Compilations/Intuition (1981)/01 - Blue Bossa.flac", "Joe Henderson/Page One (1963)/01 - Blue Bossa.1.flac"]
    assert report["unmatched_new"] == []


def test_nested_serato_dirs_are_skipped(tmp_path):
    (tmp_path / "a" / "_Serato_").mkdir(parents=True); (tmp_path / "a" / "_Serato_" / "x.mp3").write_bytes(b"x")
    assert list(lm.audio_files(tmp_path)) == []


def test_csv_roundtrip(tmp_path):
    rows = [{"original_path": "x.mp3", "folder": "", "ext": "mp3", "size": "9", "audio_md5": "h", "new_path": "", "other_copies": ""}]
    out = tmp_path / "map.csv"
    lm.write_csv(rows, out)
    assert lm.read_csv(out) == rows
    with out.open(newline="") as fh:
        assert next(csv.reader(fh)) == lm.FIELDS
