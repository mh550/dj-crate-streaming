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
from dataclasses import replace
from pathlib import Path

import pytest

from sourcing.filer import AlbumIdentity, BeetsFiler, FilingError, fill_missing_tags
from tests.helpers import beets_items_db, convert, fake_beet, make_audio, make_flac

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


# --- album identity (S2-06b, docs/plans/2026-10-22-S2-album-tags.md) ------------------------------------

AL_GREEN = AlbumIdentity("I'm Still in Love With You", "Al Green", 1, 9, 1972, "rel-1")
ALBUM_FIELDS = ("album", "albumartist", "track", "tracktotal", "year", "mb_albumid")
NO_ALBUM = {"album": None, "albumartist": None, "mb_albumid": None, "track": None, "tracktotal": None, "year": None,
            "month": None, "day": None}


def media(path: Path):
    mf = pytest.importorskip("mediafile")       # scripts.tag_cleanup puts Debian's beets on sys.path first
    return mf.MediaFile(str(path))


def album_tags(path: Path) -> dict:
    m = media(path)
    return {k: getattr(m, k) for k in ALBUM_FIELDS}


def write_minimal(path, changes):
    from scripts.tag_cleanup import write_minimal as write
    write(path, changes)


@pytest.fixture
def album_fake(tmp_path):
    """The fake-runner world with a real (header-only) FLAC in staging, so mediafile can read and write it."""
    pytest.importorskip("scripts.tag_cleanup")
    music, library = tmp_path / "music", beets_items_db(tmp_path / "beets" / "library.db")
    cfg = tmp_path / "beets.yaml"
    cfg.write_text(f"directory: {music}\nlibrary: {library}\n")
    staging = staging_dir(tmp_path)
    src = make_flac(staging / "x.flac")
    write_minimal(src, {"artist": "Al Green", "title": "I'm Still in Love With You"})
    return dict(music=music, library=library, cfg=cfg, staging=staging, log=staging.with_suffix(".log"), src=src)


def noted(old):                                          # an on_tagged that records nowhere (fetch commits an event)
    pass


TARGET_01 = "Al Green/I'm Still in Love With You (1972)/01 - I'm Still in Love With You.flac"


def test_album_identity_is_written_on_the_staged_file_and_imported_with_set_dj_album(album_fake):
    f, seen = album_fake, []
    runner = fake_beet(f["music"], f["library"], TARGET_01, artist="Al Green")

    def on_tagged(old):                                  # before the write and before beets runs
        seen.append((old, album_tags(f["src"]), list(runner.calls)))
    item = BeetsFiler(f["cfg"], runner=runner).file(f["staging"], f["log"], album=AL_GREEN, on_tagged=on_tagged)
    assert runner.calls == [["beet", "-c", str(f["cfg"]), "import", "-q", "-s", "-m", "-W", "--set", "dj_album=1",
                             "-l", str(f["log"]), str(f["staging"])]]
    assert album_tags(item.path) == {"album": "I'm Still in Love With You", "albumartist": "Al Green", "track": 1,
                                     "tracktotal": 9, "year": 1972, "mb_albumid": "rel-1"}
    assert (media(item.path).artist, media(item.path).title) == ("Al Green", "I'm Still in Love With You")
    assert item.old == NO_ALBUM
    assert seen == [(NO_ALBUM, dict.fromkeys(ALBUM_FIELDS), [])]


def test_without_an_album_nothing_is_written_and_no_set_is_passed(album_fake):
    f = album_fake
    digest = sha256(f["src"])
    called = []
    runner = fake_beet(f["music"], f["library"], "Al Green/Singles/I'm Still in Love With You.flac")
    item = BeetsFiler(f["cfg"], runner=runner).file(f["staging"], f["log"], on_tagged=called.append)
    assert runner.calls == [["beet", "-c", str(f["cfg"]), "import", "-q", "-s", "-m", "-W", "-l", str(f["log"]),
                             str(f["staging"])]]
    assert sha256(item.path) == digest and item.old is None and called == []


def test_a_file_that_already_agrees_is_not_saved_and_logs_nothing(album_fake):
    f = album_fake
    write_minimal(f["src"], {"album": AL_GREEN.album, "albumartist": "Al Green", "track": 1, "tracktotal": 9,
                             "year": 1972, "mb_albumid": "rel-1"})
    digest, called = sha256(f["src"]), []
    runner = fake_beet(f["music"], f["library"], TARGET_01)
    item = BeetsFiler(f["cfg"], runner=runner).file(f["staging"], f["log"], album=AL_GREEN, on_tagged=called.append)
    assert sha256(item.path) == digest and item.old is None and called == []
    assert "--set" in runner.calls[0]                    # still filed on the album path


def test_only_the_fields_that_differ_are_written_and_recorded(album_fake):
    f = album_fake
    write_minimal(f["src"], {"album": AL_GREEN.album, "albumartist": "Al Green", "track": 1, "tracktotal": 9,
                             "year": 1972, "mb_albumid": "rel-1"})
    item = BeetsFiler(f["cfg"], runner=fake_beet(f["music"], f["library"], TARGET_01)).file(
        f["staging"], f["log"], album=replace(AL_GREEN, track=4), on_tagged=noted)
    assert item.old == {"track": 1}
    assert album_tags(item.path)["track"] == 4


def test_unknown_year_and_release_clear_the_uploaders_values(album_fake):
    """D51 *default*: a request without a year clears year, month and day (one folder for the album); without a
    release id the uploader's album and album-artist ids go too (Navidrome's album PID)."""
    f = album_fake
    write_minimal(f["src"], {"year": 1971, "month": 5, "day": 1, "mb_albumid": "uploader-rel",
                             "mb_albumartistid": "uploader-artist"})
    unknown = replace(AL_GREEN, year=None, mb_albumid=None)
    item = BeetsFiler(f["cfg"], runner=fake_beet(f["music"], f["library"], TARGET_01)).file(
        f["staging"], f["log"], album=unknown, on_tagged=noted)
    m = media(item.path)
    assert (m.year, m.month, m.day, m.mb_albumid or None, m.mb_albumartistid or None) == (None,) * 5
    assert not [t for t in tags_of(item.path) if t.split("=")[0] in ("DATE", "YEAR")]
    assert item.old == {"album": None, "albumartist": None, "track": None, "tracktotal": None, "year": 1971,
                        "month": 5, "day": 1, "mb_albumid": "uploader-rel", "mb_albumartistid": "uploader-artist"}


def test_a_written_year_clears_month_and_day(album_fake):
    f = album_fake
    write_minimal(f["src"], {"year": 1971, "month": 5, "day": 1})
    item = BeetsFiler(f["cfg"], runner=fake_beet(f["music"], f["library"], TARGET_01)).file(
        f["staging"], f["log"], album=AL_GREEN, on_tagged=noted)
    m = media(item.path)
    assert (m.year, m.month, m.day) == (1972, None, None)
    assert (item.old["year"], item.old["month"], item.old["day"]) == (1971, 5, 1)


def test_comp_is_cleared_only_when_the_file_says_true(album_fake):
    f = album_fake
    item = BeetsFiler(f["cfg"], runner=fake_beet(f["music"], f["library"], TARGET_01)).file(
        f["staging"], f["log"], album=AL_GREEN, on_tagged=noted)
    assert "comp" not in item.old
    assert not [t for t in tags_of(item.path) if t.startswith("COMPILATION=")]       # no COMPILATION=0 added
    staging2 = staging_dir(f["staging"].parent.parent.parent, "ext-1-2")
    src2 = make_flac(staging2 / "y.flac")
    write_minimal(src2, {"comp": True})
    item2 = BeetsFiler(f["cfg"], runner=fake_beet(f["music"], f["library"], TARGET_01.replace("01", "02"))).file(
        staging2, staging2.with_suffix(".log"), album=replace(AL_GREEN, track=2), on_tagged=noted)
    assert item2.old["comp"] is True and not media(item2.path).comp


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
@pytest.mark.parametrize("ext", ["mp3", "m4a", "ogg"])
def test_album_identity_on_other_formats(album_fake, tmp_path, ext):
    f = album_fake
    src = convert(make_audio(tmp_path / "src.wav", seconds=1), f["staging"] / f"x.{ext}")
    f["src"].unlink()
    write_minimal(src, {"artist": "Al Green", "title": "I'm Still in Love With You", "year": 1971})
    item = BeetsFiler(f["cfg"], runner=fake_beet(f["music"], f["library"], TARGET_01.replace(".flac", f".{ext}"))).file(
        f["staging"], f["log"], album=AL_GREEN, on_tagged=noted)
    assert album_tags(item.path) == {"album": "I'm Still in Love With You", "albumartist": "Al Green", "track": 1,
                                     "tracktotal": 9, "year": 1972, "mb_albumid": "rel-1"}
    assert media(item.path).title == "I'm Still in Love With You"
    assert item.old["year"] == 1971 and item.old["album"] is None


def test_a_stray_album_artist_key_is_a_difference(album_fake, tmp_path):
    """mediafile reads only the first album-artist key; another key with another value would still split the album
    (Navidrome reads the raw tags), so any differing key (FLAC) or ID3 alias (MP3) writes albumartist again."""
    from mutagen.flac import FLAC
    f = album_fake
    write_minimal(f["src"], {"album": AL_GREEN.album, "albumartist": "Al Green", "track": 1, "tracktotal": 9,
                             "year": 1972, "mb_albumid": "rel-1"})
    tags = FLAC(f["src"]); tags["ALBUMARTIST"] = ["Various"]; tags["ALBUM ARTIST"] = ["Al Green"]; tags.save()
    item = BeetsFiler(f["cfg"], runner=fake_beet(f["music"], f["library"], TARGET_01)).file(
        f["staging"], f["log"], album=AL_GREEN, on_tagged=lambda old: None)
    assert "albumartist" in item.old
    t = FLAC(item.path)
    assert [t.get(k) for k in ("ALBUMARTIST", "ALBUM ARTIST", "ALBUM_ARTIST")] == [["Al Green"]] * 3


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_an_id3_album_artist_alias_is_a_difference(album_fake, tmp_path):
    from mutagen.id3 import ID3, TXXX
    f = album_fake
    src = convert(make_audio(tmp_path / "src.wav", seconds=1), f["staging"] / "x.mp3")
    f["src"].unlink()
    write_minimal(src, {"album": AL_GREEN.album, "albumartist": "Al Green", "track": 1, "tracktotal": 9,
                        "year": 1972, "mb_albumid": "rel-1"})
    id3 = ID3(src); id3.add(TXXX(encoding=3, desc="ALBUM ARTIST", text="Various")); id3.save(src)
    item = BeetsFiler(f["cfg"], runner=fake_beet(f["music"], f["library"], TARGET_01.replace(".flac", ".mp3"))).file(
        f["staging"], f["log"], album=AL_GREEN, on_tagged=lambda old: None)
    assert "albumartist" in item.old
    assert not [k for k in ID3(item.path).keys() if k.casefold() == "txxx:album artist"]
    assert str(ID3(item.path)["TPE2"]) == "Al Green"


def test_an_album_without_a_record_keeper_is_refused_before_anything_is_written(album_fake):
    f = album_fake
    runner = fake_beet(f["music"], f["library"], TARGET_01)
    with pytest.raises(ValueError, match="on_tagged"):
        BeetsFiler(f["cfg"], runner=runner).file(f["staging"], f["log"], album=AL_GREEN)
    assert album_tags(f["src"])["album"] is None and runner.calls == []


def test_the_recorded_old_values_reverse_the_write(album_fake):
    """album_changes' own record, fed to scripts.tag_cleanup.restore_fields, gives the file's tags back."""
    from mutagen.flac import FLAC
    from scripts.tag_cleanup import restore_fields
    f = album_fake
    tags = FLAC(f["src"]); tags["DATE"] = "1971-05-01"; tags["COMPILATION"] = "1"; tags["ALBUM"] = "Greatest Hits"
    tags["MUSICBRAINZ_ALBUMID"] = "uploader-rel"; tags.save()
    before = sorted(FLAC(f["src"]).tags)
    item = BeetsFiler(f["cfg"], runner=fake_beet(f["music"], f["library"], TARGET_01)).file(
        f["staging"], f["log"], album=replace(AL_GREEN, year=None, mb_albumid=None), on_tagged=lambda old: None)
    restore_fields(item.path, item.old)
    assert sorted(FLAC(item.path).tags) == sorted(before + [("YEAR", "1971")])     # a restored year: DATE and YEAR


def test_a_kill_during_the_import_comes_after_the_record_and_the_write(album_fake):
    f, seen = album_fake, []
    runner = fake_beet(f["music"], f["library"], TARGET_01, fail_import=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        BeetsFiler(f["cfg"], runner=runner).file(f["staging"], f["log"], album=AL_GREEN, on_tagged=seen.append)
    assert seen == [NO_ALBUM]
    assert album_tags(f["src"])["album"] == AL_GREEN.album     # tagged, still in staging (not library material)


def test_a_failing_record_stops_before_the_write(album_fake):
    f = album_fake
    runner = fake_beet(f["music"], f["library"], TARGET_01)

    def on_tagged(old):
        raise RuntimeError("store is locked")
    with pytest.raises(RuntimeError):
        BeetsFiler(f["cfg"], runner=runner).file(f["staging"], f["log"], album=AL_GREEN, on_tagged=on_tagged)
    assert album_tags(f["src"])["album"] is None and runner.calls == []


def test_a_confirmed_match_keeps_beet_write_the_only_writer_after_the_import(album_fake):
    """D22 unchanged: the album fields go in before beets sees the file; after the import `beet write` (which writes
    library.db's values, read from our tags) is the only write, as for any matched download."""
    f = album_fake
    runner = fake_beet(f["music"], f["library"], TARGET_01, matched=True)
    item = BeetsFiler(f["cfg"], runner=runner, confirm=lambda i: (True, "")).file(f["staging"], f["log"], album=AL_GREEN, on_tagged=noted)
    assert [c[3] for c in runner.calls] == ["import", "write"]
    assert runner.calls[1] == ["beet", "-c", str(f["cfg"]), "write", f"path:{item.path}"]
    assert album_tags(item.path)["album"] == AL_GREEN.album and item.matched


@real_beet
def test_real_beet_files_an_album_row_on_the_album_path_and_a_plain_row_in_singles(tmp_path, beets_home):
    pytest.importorskip("scripts.tag_cleanup")
    config, music, library = real_config(tmp_path)
    filer = BeetsFiler(config)
    first, second, plain = (staging_dir(tmp_path, n) for n in ("ext-1-1", "ext-2-1", "ext-3-1"))
    write_minimal(make_flac(first / "a.flac"), {"artist": "Al Green", "title": "I'm Still in Love With You"})
    write_minimal(make_flac(second / "b.flac"), {"artist": "Al Green", "title": "One of These Good Old Days", "year": 1999})
    write_minimal(make_flac(plain / "c.flac"), {"artist": "Al Green", "title": "Plain Song"})
    a = filer.file(first, first.with_suffix(".log"), album=AL_GREEN, on_tagged=noted)
    b = filer.file(second, second.with_suffix(".log"), album=replace(AL_GREEN, track=9, year=None, mb_albumid=None), on_tagged=noted)
    c = filer.file(plain, plain.with_suffix(".log"))
    assert a.path == music / "Al Green" / "I'm Still in Love With You (1972)" / "01 - I'm Still in Love With You.flac"
    assert b.path == music / "Al Green" / "I'm Still in Love With You" / "09 - One of These Good Old Days.flac"
    assert c.path == music / "Al Green" / "Singles" / "Plain Song.flac"
    with closing(sqlite3.connect(library)) as db:
        flagged = db.execute("SELECT i.path FROM items i JOIN item_attributes a ON a.entity_id = i.id "
                             "WHERE a.key = 'dj_album' AND a.value = '1' ORDER BY i.id").fetchall()
    assert [os.fsdecode(p) for (p,) in flagged] == [str(a.path), str(b.path)]


def test_beets_yaml_puts_the_album_key_before_singleton():
    """beets matches path formats in yaml order, so `dj_album:1:` must come before `singleton:` (S2-06a measured)."""
    text = (REPO / "deploy" / "beets.yaml").read_text()
    paths = re.search(r"^paths:\n((?:[ #].*\n|\n)*)", text, re.M).group(1)
    keys = [m.group(1) for m in re.finditer(r"^  ([^\s#][^:]*(?::1)?):", paths, re.M)]
    assert keys.index("dj_album:1") < keys.index("singleton")
    assert "  dj_album:1: $albumartist/%if{$year,$album ($year),$album}/$track - $title\n" in paths
