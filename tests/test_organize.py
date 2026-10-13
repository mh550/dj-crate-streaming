from pathlib import Path

from sourcing.organize import file_into, target_path


def test_target_path_matches_beets_layout(tmp_path):
    p = target_path(tmp_path, "Chic", "Good Times", "flac", album="Risqué", year=1979, track=3)
    assert p == tmp_path / "Chic" / "Risqué (1979)" / "03 - Good Times.flac"


def test_target_path_without_album_or_year(tmp_path):
    assert target_path(tmp_path, "Chic", "Good Times", "flac") == tmp_path / "Chic" / "Singles" / "00 - Good Times.flac"
    assert target_path(tmp_path, "Chic", "Good Times", "flac", album="Risqué") == tmp_path / "Chic" / "Risqué" / "00 - Good Times.flac"


def test_target_path_sanitises_components(tmp_path):
    p = target_path(tmp_path, "AC/DC", "Back: In .Black.", "mp3", album="../Evil", year=1980, track=1)
    assert p.parent.parent.name == "AC_DC"
    assert p.parent.name == "_Evil (1980)"            # "../Evil" → "/" becomes "_", leading dots stripped
    assert p.name == "01 - Back_ In .Black.mp3"
    assert tmp_path in p.parents and ".." not in p.parts


def test_target_path_avoids_collisions(tmp_path):
    first = tmp_path / "Chic" / "Risqué (1979)" / "03 - Good Times.flac"
    first.parent.mkdir(parents=True); first.write_bytes(b"old")
    p = target_path(tmp_path, "Chic", "Good Times", "flac", album="Risqué", year=1979, track=3)
    assert p == first.parent / "03 - Good Times (2).flac"


def test_file_into_moves_and_never_overwrites(tmp_path):
    src = tmp_path / "dl" / "x.flac"; src.parent.mkdir(); src.write_bytes(b"new")
    music = tmp_path / "music"
    out = file_into(src, music, artist="Chic", title="Good Times", album="Risqué", year=1979, track=3)
    assert out.read_bytes() == b"new" and not src.exists()
    src.write_bytes(b"again")
    out2 = file_into(src, music, artist="Chic", title="Good Times", album="Risqué", year=1979, track=3)
    assert out2 != out and out.read_bytes() == b"new" and out2.read_bytes() == b"again"
