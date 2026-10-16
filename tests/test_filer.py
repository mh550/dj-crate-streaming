"""BeetsFiler: one verified download, imported from its own .staging folder, written only after a match.

The real-beet tests run /usr/bin/beet against a temp library with MusicBrainz pointed at a refused port
(127.0.0.1:9), so every import falls back to as-is offline. That setting lives in $BEETSDIR/config.yaml, not
in the -c file: beets 1.6 configures MusicBrainz before it loads -c. BEETSDIR also keeps the user's config out.
The fake-runner tests cover what an offline beets cannot: an applied match.
"""
import hashlib
import os
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
    config.write_text(text)
    return config, music, library


@pytest.fixture
def beets_home(tmp_path, monkeypatch):
    """$BEETSDIR/config.yaml points MusicBrainz at a refused port (offline, as-is). It has to be here: beets 1.6
    calls mb.configure() before it reads the -c file, so a musicbrainz: host: in -c never applies."""
    home = tmp_path / "beetsdir"
    home.mkdir()
    (home / "config.yaml").write_text("musicbrainz:\n  host: 127.0.0.1:9\n")
    monkeypatch.setenv("BEETSDIR", str(home))


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


@real_beet
def test_real_beet_tests_are_offline(tmp_path, beets_home):
    """beets 1.6 configures MusicBrainz (ui._setup calls mb.configure()) before it loads the -c file, so a
    `musicbrainz: host:` there is ignored and the import queries musicbrainz.org. A length-less recording of
    the song then scores distance 0, a strong match, and the import applies it at random (matched=True)."""
    config, _, _ = real_config(tmp_path)
    staging = staging_dir(tmp_path)
    good_times(staging)
    done = subprocess.run(["beet", "-vv", "-c", str(config), "import", "-q", "-s", "-m", "-W",
                           "-l", str(staging.with_suffix(".log")), str(staging)],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)
    out = done.stdout + done.stderr
    assert done.returncode == 0, out[-2000:]
    assert "Connection refused" in out and "Found 0 candidates." in out, out[-2000:]


@real_beet
def test_real_beet_write_touches_only_the_file_it_names(tmp_path, beets_home):
    """`beet write path:<file>` (the filer's write step) writes that one file and no other, even when library.db
    disagrees with both, and an explicit write still writes with `import: write: no` in deploy/beets.yaml."""
    config, music, library = real_config(tmp_path)
    section = re.search(r"^import:\n((?:[ #].*\n|\n)*)", config.read_text(), re.M).group(1)
    assert re.search(r"^  write: no\b", section, re.M), section
    filer = BeetsFiler(config)
    first, second = staging_dir(tmp_path, "ext-1-1"), staging_dir(tmp_path, "ext-1-2")
    good_times(first, 42)
    a = filer.file(first, first.with_suffix(".log"))
    good_times(second, 7)
    b = filer.file(second, second.with_suffix(".log"))
    assert (a.path, b.path) == (music / "Chic" / "Singles" / "Good Times.flac", music / "Chic" / "Singles" / "Good Times.1.flac")
    with closing(sqlite3.connect(library)) as db, db:
        assert db.execute("UPDATE items SET title = 'Good Times (written)'").rowcount == 2
    untouched = sha256(b.path)
    filer._write(a)
    assert [t for t in tags_of(a.path) if t.startswith("TITLE=")] == ["TITLE=Good Times (written)"]
    assert sha256(b.path) == untouched


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
    item = BeetsFiler(cfg, runner=runner, confirm=lambda i: (True, "")).file(staging, log)
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


def test_a_stale_log_cannot_hide_a_real_match(fake):
    fake["log"].write_text("asis x\n")                 # left over from an earlier attempt at this path
    runner = fake_beet(fake["music"], fake["library"], "Chic/Singles/Good Times.flac", mb_trackid="rec-1",
                       matched=True)
    item = BeetsFiler(fake["cfg"], runner=runner, confirm=lambda i: (True, "")).file(fake["staging"], fake["log"])
    assert item.matched is True
    assert runner.calls[1][3] == "write"


# --- D22: a match is confident only when a confirmer (MusicBrainz length) agrees -----------------------

def matched_runner(fake, **kw):
    return fake_beet(fake["music"], fake["library"], "Chic/Singles/Good Times.flac", artist="Chic", title="Good Times",
                     mb_trackid="rec-1", matched=True, **kw)


def test_matched_without_a_confirmer_is_not_written(fake):
    runner = matched_runner(fake)
    item = BeetsFiler(fake["cfg"], runner=runner).file(fake["staging"], fake["log"])
    assert len(runner.calls) == 1
    assert item.matched is False and "no confirmer" in item.note


def test_confirmed_match_runs_beet_write(fake):
    runner = matched_runner(fake)
    item = BeetsFiler(fake["cfg"], runner=runner, confirm=lambda i: (True, "ok")).file(fake["staging"], fake["log"])
    assert len(runner.calls) == 2 and runner.calls[1][3] == "write"
    assert item.matched is True and item.note == "ok"


def test_rejected_match_is_not_written(fake):
    runner = matched_runner(fake)
    item = BeetsFiler(fake["cfg"], runner=runner, confirm=lambda i: (False, "Δ79 s")).file(fake["staging"], fake["log"])
    assert len(runner.calls) == 1
    assert item.matched is False and item.note == "Δ79 s"


def test_confirmer_sees_the_filed_item(fake):
    seen = []
    BeetsFiler(fake["cfg"], runner=matched_runner(fake, length=333.0),
               confirm=lambda i: seen.append(i) or (False, "")).file(fake["staging"], fake["log"])
    assert [(i.mb_trackid, i.length, i.matched) for i in seen] == [("rec-1", 333.0, False)]


def test_as_is_import_never_asks_the_confirmer(fake):
    runner = fake_beet(fake["music"], fake["library"], "Chic/Singles/Good Times.flac")
    item = BeetsFiler(fake["cfg"], runner=runner, confirm=lambda i: 1 / 0).file(fake["staging"], fake["log"])
    assert item.matched is False and item.note == "" and len(runner.calls) == 1


def test_item_length_comes_from_library_db(fake):
    runner = fake_beet(fake["music"], fake["library"], "Chic/Singles/Good Times.flac", length=333.0)
    assert BeetsFiler(fake["cfg"], runner=runner).file(fake["staging"], fake["log"]).length == 333.0


def test_refuses_a_folder_without_exactly_one_audio_file(fake):
    (fake["staging"] / "gt2.flac").write_bytes(b"fLaC")
    runner = fake_beet(fake["music"], fake["library"], "Chic/Singles/Good Times.flac")
    tagged = []
    with pytest.raises(FilingError, match="expected one audio file .* found 2"):
        BeetsFiler(fake["cfg"], runner=runner, tagger=lambda p, n: tagged.append(p) or []).file(
            fake["staging"], fake["log"], names={"artist": "Chic"})
    assert runner.calls == [] and tagged == []


@pytest.mark.parametrize("where", ["library-import", "dl/.staging/.."])
def test_refuses_a_folder_outside_staging(fake, tmp_path, where):
    runner = fake_beet(fake["music"], fake["library"], "Chic/Singles/Good Times.flac")
    with pytest.raises(ValueError):
        BeetsFiler(fake["cfg"], runner=runner).file(tmp_path / where, fake["log"])
    assert runner.calls == []


def test_library_path_comes_from_the_config():
    assert BeetsFiler(REPO / "deploy" / "beets.yaml").library == Path("/srv/docker/beets/library.db")


def test_unreadable_library_db_fails_before_the_import(fake):
    """Only a missing library.db or a missing items table means "no items yet"; a locked one (a beet process mid-write)
    must not count as 0, or every existing row would look new after the import."""
    runner = fake_beet(fake["music"], fake["library"], "Chic/Singles/Good Times.flac")
    lock = sqlite3.connect(fake["library"], isolation_level=None)
    lock.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(FilingError, match="library.db unreadable"):
            BeetsFiler(fake["cfg"], runner=runner).file(fake["staging"], fake["log"])
    finally:
        lock.execute("ROLLBACK"); lock.close()
    assert runner.calls == []


def test_missing_library_db_or_table_counts_as_empty(tmp_path):
    staging = staging_dir(tmp_path)
    (staging / "gt.flac").write_bytes(b"fLaC")
    library = tmp_path / "beets" / "library.db"
    runner_calls = []

    def runner(cmd, **kw):                             # beets creates library.db and its table on the first import
        runner_calls.append(cmd)
        beets_items_db(library)
        return fake_beet(tmp_path / "music", library, "Chic/Singles/Good Times.flac")(cmd, **kw)

    item = BeetsFiler(tmp_path / "beets.yaml", library=library, runner=runner).file(staging, staging.with_suffix(".log"))
    assert item.path == tmp_path / "music" / "Chic" / "Singles" / "Good Times.flac"
    library.unlink()
    with closing(sqlite3.connect(library)) as db:      # a library.db without an items table
        db.execute("CREATE TABLE other(x)")
    assert BeetsFiler(tmp_path / "beets.yaml", library=library)._max_id() == 0


# --- forget (M8 Task 7): the worker tells beets a trashed file is gone ------------------------------------

def _item_paths(library: Path) -> list[str]:
    with closing(sqlite3.connect(library)) as db:
        return sorted(os.fsdecode(p) for (p,) in db.execute("SELECT path FROM items"))


@real_beet
def test_forget_removes_the_item_but_not_the_file(tmp_path, beets_home):
    config, music, library = real_config(tmp_path)
    filer = BeetsFiler(config)
    a, b = staging_dir(tmp_path, "a"), staging_dir(tmp_path, "b")
    good_times(a, seed=1)
    tag(make_audio(b / "o.flac", seconds=3, seed=2), "ARTIST=Chic", "TITLE=Le Freak")
    old = filer.file(a, tmp_path / "a.log").path
    other = filer.file(b, tmp_path / "b.log").path
    assert _item_paths(library) == sorted([str(old), str(other)])
    trashed = tmp_path / "trash" / old.name
    trashed.parent.mkdir()
    shutil.move(old, trashed)
    assert filer.forget(old) is True
    assert _item_paths(library) == [str(other)]
    assert trashed.is_file() and other.is_file()                    # no -d: beets never touched a file


def test_forget_refuses_a_file_still_on_disk(fake):
    present = fake["music"] / "Chic" / "Good Times.flac"
    present.parent.mkdir(parents=True)
    present.write_bytes(b"fLaC")
    runner = fake_beet(fake["music"], fake["library"], "x.flac")
    with pytest.raises(FilingError, match="still on disk"):
        BeetsFiler(fake["cfg"], runner=runner).forget(present)
    assert runner.calls == []                                       # `beet remove -f` is never given a live file


def test_forget_runs_with_stdin_devnull_and_no_delete_flag(fake):
    seen = []

    def runner(cmd, **kwargs):
        seen.append((list(cmd), kwargs))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    gone = fake["music"] / "Chic" / "Good Times.flac"
    assert BeetsFiler(fake["cfg"], runner=runner).forget(gone) is True
    cmd, kw = seen[0]
    assert cmd == ["beet", "-c", str(fake["cfg"]), "remove", "-f", f"path:{gone}"]
    assert "-d" not in cmd and kw["stdin"] is subprocess.DEVNULL
    assert kw["encoding"] == "utf-8" and kw["errors"] == "replace"


def test_forget_reports_a_beets_failure_as_false(fake):
    runner = fake_beet(fake["music"], fake["library"], "x.flac", rc=1)
    assert BeetsFiler(fake["cfg"], runner=runner).forget(fake["music"] / "gone.flac") is False
