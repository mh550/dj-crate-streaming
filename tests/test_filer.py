"""BeetsFiler: one verified download, imported from its own .staging folder, written only after a match.

The real-beet tests run /usr/bin/beet against a temp library with MusicBrainz pointed at a refused port
(127.0.0.1:9), so every import falls back to as-is offline; BEETSDIR keeps the user's beets config out.
The fake-runner tests cover what an offline beets cannot: an applied match.
"""
import hashlib
import re
import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

import pytest

from sourcing.filer import BeetsFiler, FilingError, fill_missing_tags
from tests.helpers import beets_items_db, fake_beet, make_audio

REPO = Path(__file__).resolve().parent.parent
real_beet = pytest.mark.skipif(shutil.which("beet") is None, reason="beets is not installed")


def real_config(tmp_path) -> tuple[Path, Path, Path]:
    """deploy/beets.yaml with its directory, library, statefile and import log moved into tmp_path."""
    music, library = tmp_path / "music", tmp_path / "beets" / "library.db"
    library.parent.mkdir(parents=True)
    text = (REPO / "deploy" / "beets.yaml").read_text()
    for pattern, value in ((r"^directory:.*$", f"directory: {music}"),
                           (r"^library:.*$", f"library: {library}"),
                           (r"^statefile:.*$", f"statefile: {tmp_path / 'beets' / 'state.pickle'}"),
                           (r"^  log:.*$", f"  log: {tmp_path / 'beets' / 'import.log'}")):
        text, n = re.subn(pattern, value, text, flags=re.M)
        assert n == 1, pattern
    config = tmp_path / "beets.yaml"
    config.write_text(text + "musicbrainz:\n  host: 127.0.0.1:9\n")     # refused at once: offline, as-is
    return config, music, library


@pytest.fixture
def beets_home(tmp_path, monkeypatch):
    monkeypatch.setenv("BEETSDIR", str(tmp_path / "beetsdir"))


def staging_dir(tmp_path, name="ext-1-1") -> Path:
    staging = tmp_path / "dl" / ".staging" / name
    staging.mkdir(parents=True)
    return staging


def tag(path: Path, *tags: str) -> Path:
    subprocess.run(["metaflac", *(f"--set-tag={t}" for t in tags), str(path)], check=True,
                   stdin=subprocess.DEVNULL)
    return path


def good_times(staging: Path, seed=42, *extra: str) -> Path:
    return tag(make_audio(staging / "gt.flac", seconds=3, seed=seed),
               "ARTIST=Chic", "TITLE=Good Times", "GENRE=Disco", "GENRE=Funk", *extra)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tags_of(path: Path) -> list[str]:
    out = subprocess.run(["metaflac", "--export-tags-to=-", str(path)], check=True, capture_output=True,
                         text=True, stdin=subprocess.DEVNULL).stdout
    return out.splitlines()


def audio_in(folder: Path) -> list[Path]:
    return [p for p in folder.iterdir() if p.suffix == ".flac"]


# --- real beets ---------------------------------------------------------------------------------------

@real_beet
def test_real_beet_files_unmatched_download_as_is(tmp_path, beets_home):
    config, music, _ = real_config(tmp_path)
    staging = staging_dir(tmp_path)
    src = good_times(staging)
    digest, tags = sha256(src), tags_of(src)
    item = BeetsFiler(config).file(staging, staging.with_suffix(".log"))
    assert item.path == music / "Chic" / "Singles" / "Good Times.flac"
    assert item.matched is False and item.mb_trackid == ""
    assert (item.artist, item.title) == ("Chic", "Good Times")
    assert sha256(item.path) == digest
    assert tags_of(item.path) == tags
    assert [t for t in tags_of(item.path) if t.startswith("GENRE=")] == ["GENRE=Disco", "GENRE=Funk"]
    assert audio_in(staging) == []


@real_beet
def test_real_beet_keeps_a_second_copy_of_the_same_song(tmp_path, beets_home):
    config, music, _ = real_config(tmp_path)
    filer = BeetsFiler(config)
    first = staging_dir(tmp_path, "ext-1-1")
    good_times(first, 42)
    assert filer.file(first, first.with_suffix(".log")).path == music / "Chic" / "Singles" / "Good Times.flac"
    second = staging_dir(tmp_path, "ext-1-2")
    digest = sha256(good_times(second, 7))
    item = filer.file(second, second.with_suffix(".log"))
    assert item is not None
    assert item.path == music / "Chic" / "Singles" / "Good Times.1.flac"
    assert item.matched is False                      # the log says asis, then duplicate-keep
    assert sha256(item.path) == digest
    assert (music / "Chic" / "Singles" / "Good Times.flac").exists()


@real_beet
def test_real_beet_untagged_download_is_named_from_the_wanted_row(tmp_path, beets_home):
    config, music, _ = real_config(tmp_path)
    staging = staging_dir(tmp_path)
    make_audio(staging / "gt.flac", seconds=3)
    item = BeetsFiler(config).file(staging, staging.with_suffix(".log"),
                                   names={"artist": "Chic", "title": "Good Times"})
    assert item.filled == ["artist", "title"]
    assert item.path == music / "Chic" / "Singles" / "Good Times.flac"
    assert not (music / "_" / "Singles.flac").exists()


def test_tagger_fills_only_empty_fields(tmp_path):
    path = tag(make_audio(tmp_path / "lf.flac", seconds=1), "TITLE=Le Freak")
    assert fill_missing_tags(path, {"artist": "Chic", "title": "Good Times"}) == ["artist"]
    assert "TITLE=Le Freak" in tags_of(path)
    assert "ARTIST=Chic" in tags_of(path)


@real_beet
def test_real_beet_as_is_with_uploader_recording_id_is_not_rewritten(tmp_path, beets_home):
    config, music, _ = real_config(tmp_path)
    staging = staging_dir(tmp_path)
    src = good_times(staging, 42, "MUSICBRAINZ_TRACKID=0a1b2c3d-0000-0000-0000-000000000001")
    digest = sha256(src)
    item = BeetsFiler(config).file(staging, staging.with_suffix(".log"))
    assert item.matched is False
    assert item.mb_trackid == "0a1b2c3d-0000-0000-0000-000000000001"
    assert sha256(item.path) == digest


# --- fake runner ------------------------------------------------------------------------------------

@pytest.fixture
def fake(tmp_path):
    music, library = tmp_path / "music", beets_items_db(tmp_path / "beets" / "library.db")
    cfg = tmp_path / "beets.yaml"
    cfg.write_text(f"directory: {music}\nlibrary: {library}\n")
    staging = staging_dir(tmp_path)
    (staging / "gt.flac").write_bytes(b"fLaC")
    return dict(music=music, library=library, cfg=cfg, staging=staging, log=staging.with_suffix(".log"))


def test_confident_match_runs_beet_write_on_the_new_file_only(fake):
    music, cfg, staging, log = fake["music"], fake["cfg"], fake["staging"], fake["log"]
    runner = fake_beet(music, fake["library"], "Chic/Singles/Good Times.flac", artist="Chic", title="Good Times",
                       mb_trackid="rec-1", matched=True)
    item = BeetsFiler(cfg, runner=runner).file(staging, log)
    assert runner.calls[0] == ["beet", "-c", str(cfg), "import", "-q", "-s", "-m", "-W", "-l", str(log), str(staging)]
    assert runner.calls[1] == ["beet", "-c", str(cfg), "write", f"path:{music / 'Chic/Singles/Good Times.flac'}"]
    assert len(runner.calls) == 2
    assert item.matched and item.mb_trackid == "rec-1"
    assert item.path == music / "Chic" / "Singles" / "Good Times.flac"
    assert (item.artist, item.title, item.filled) == ("Chic", "Good Times", [])


def test_as_is_never_runs_beet_write(fake):
    runner = fake_beet(fake["music"], fake["library"], "Chic/Singles/Good Times.flac", mb_trackid="uploader-id")
    item = BeetsFiler(fake["cfg"], runner=runner).file(fake["staging"], fake["log"])
    assert len(runner.calls) == 1
    assert item.matched is False and item.mb_trackid == "uploader-id"


def test_nothing_imported_returns_none(fake):
    runner = fake_beet(fake["music"], fake["library"], "Chic/Singles/Good Times.flac", import_nothing=True)
    assert BeetsFiler(fake["cfg"], runner=runner).file(fake["staging"], fake["log"]) is None
    assert len(runner.calls) == 1
    assert audio_in(fake["staging"])                   # the file stays in staging


def test_beets_error_raises(fake):
    runner = fake_beet(fake["music"], fake["library"], "Chic/Singles/Good Times.flac", rc=1)
    with pytest.raises(FilingError, match="boom"):
        BeetsFiler(fake["cfg"], runner=runner).file(fake["staging"], fake["log"])


def test_more_than_one_new_item_raises(fake):
    runner = fake_beet(fake["music"], fake["library"], "Chic/Singles/Good Times.flac")

    def two_rows(cmd, **kwargs):                       # a stray second row, as if beets imported two files
        result = runner(cmd, **kwargs)
        with closing(sqlite3.connect(fake["library"])) as db, db:
            db.execute("INSERT INTO items(path, mb_trackid, artist, title) VALUES (?, '', '', '')", (b"/x.flac",))
        return result
    with pytest.raises(FilingError, match="imported 2 items"):
        BeetsFiler(fake["cfg"], runner=two_rows).file(fake["staging"], fake["log"])


def test_tagger_runs_only_when_names_are_given(fake):
    seen = []
    runner = fake_beet(fake["music"], fake["library"], "Chic/Singles/Good Times.flac")
    tagger = lambda path, names: seen.append((path.name, names)) or ["title"]       # noqa: E731
    item = BeetsFiler(fake["cfg"], runner=runner, tagger=tagger).file(
        fake["staging"], fake["log"], names={"artist": "Chic", "title": "Good Times"})
    assert seen == [("gt.flac", {"artist": "Chic", "title": "Good Times"})]
    assert item.filled == ["title"]
    staging2 = fake["staging"].parent / "ext-1-2"
    staging2.mkdir()
    (staging2 / "gt.flac").write_bytes(b"fLaC")
    BeetsFiler(fake["cfg"], runner=fake_beet(fake["music"], fake["library"], "Chic/Singles/Good Times.1.flac"),
               tagger=tagger).file(staging2, staging2.with_suffix(".log"))
    assert len(seen) == 1


@pytest.mark.parametrize("where", ["library-import", "dl/.staging/.."])
def test_refuses_a_folder_outside_staging(fake, tmp_path, where):
    runner = fake_beet(fake["music"], fake["library"], "Chic/Singles/Good Times.flac")
    with pytest.raises(ValueError):
        BeetsFiler(fake["cfg"], runner=runner).file(tmp_path / where, fake["log"])
    assert runner.calls == []


def test_library_path_comes_from_the_config():
    assert BeetsFiler(REPO / "deploy" / "beets.yaml").library == Path("/srv/docker/beets/library.db")
