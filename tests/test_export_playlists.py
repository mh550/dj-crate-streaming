import os
import sqlite3
from datetime import date
from pathlib import Path

from scripts import export_playlists as ep

# Column names copied from the live navidrome.db schema (2026-10-14); only the ones the script reads.
SCHEMA = """
CREATE TABLE playlist (id varchar(255) not null primary key, name varchar(255) collate NOCASE default '' not null,
                       owner_id varchar(255) not null default '');
CREATE TABLE playlist_tracks (id integer default 0 not null, playlist_id varchar(255) not null, media_file_id varchar(255) not null);
CREATE TABLE media_file (id varchar(255) not null primary key, path varchar(255) default '' not null,
                         title varchar(255) default '' not null, artist varchar(255) default '' not null,
                         duration real default 0 not null, missing bool default false);
"""


def lib(tmp_path):
    music = tmp_path / "music"
    songs = {"a": ("Chic/Risqué (1979)/03 - Good Times.flac", "Good Times", "Chic", 501.2),
             "b": ("Digable Planets/Blowout Comb (1994)/04 - Jettin’.flac", "Jettin’", "Digable Planets", 279.0),
             "c": ("#1 Crush/Singles/It's #1, Baby.mp3", "It's #1, Baby", "#1 Crush", 200.4)}
    for p, *_ in songs.values():
        (music / p).parent.mkdir(parents=True, exist_ok=True); (music / p).write_bytes(b"x")
    db = tmp_path / "navidrome.db"
    con = sqlite3.connect(db); con.executescript(SCHEMA)
    con.executemany("insert into media_file(id,path,title,artist,duration) values(?,?,?,?,?)", [(k, *v) for k, v in songs.items()])
    con.executemany("insert into playlist(id,name) values(?,?)", [("p1", "playlists / perfect songs"), ("p2", "firstset？"), ("p3", "empty")])
    con.executemany("insert into playlist_tracks(id,playlist_id,media_file_id) values(?,?,?)",
                    [(1, "p1", "b"), (2, "p1", "a"), (3, "p1", "c"), (1, "p2", "a")])
    con.commit(); con.close()
    return db, music, music / "_playlists"


def test_export_writes_one_relative_m3u8_per_playlist(tmp_path):
    db, music, out = lib(tmp_path)
    s = ep.export(db, music, out)
    assert s.written == 3 and s.unchanged == 0
    assert sorted(p.name for p in out.iterdir()) == ["empty.m3u8", "firstset？.m3u8", "playlists - perfect songs.m3u8"]
    text = (out / "playlists - perfect songs.m3u8").read_text(encoding="utf-8")
    assert text.splitlines() == [
        "#EXTM3U", "#PLAYLIST:playlists / perfect songs",
        "#EXTINF:279,Digable Planets - Jettin’", "../Digable Planets/Blowout Comb (1994)/04 - Jettin’.flac",
        "#EXTINF:501,Chic - Good Times", "../Chic/Risqué (1979)/03 - Good Times.flac",
        "#EXTINF:200,#1 Crush - It's #1, Baby", "../#1 Crush/Singles/It's #1, Baby.mp3"]
    for line in text.splitlines()[3::2]:                        # every entry resolves from the file's own folder
        assert (out / line).resolve().is_file()


def test_rerun_rewrites_nothing_and_check_passes(tmp_path):
    db, music, out = lib(tmp_path)
    ep.export(db, music, out)
    before = {p.name: p.stat().st_mtime_ns for p in out.iterdir()}
    s = ep.export(db, music, out)
    assert s.written == 0 and s.unchanged == 3
    assert {p.name: p.stat().st_mtime_ns for p in out.iterdir()} == before
    assert ep.check(db, music, out) == []


def test_check_reports_a_moved_file_and_a_stale_playlist(tmp_path):
    db, music, out = lib(tmp_path)
    ep.export(db, music, out)
    (music / "Chic/Risqué (1979)/03 - Good Times.flac").unlink()
    con = sqlite3.connect(db); con.execute("update playlist_tracks set id=9 where playlist_id='p1' and media_file_id='b'"); con.commit(); con.close()
    problems = ep.check(db, music, out)
    assert any("firstset？" in p and "missing file" in p and "Good Times" in p for p in problems)
    assert any("playlists / perfect songs" in p and "stale" in p for p in problems)
    s = ep.export(db, music, out)                               # export refreshes the stale one
    assert s.written == 1


def test_stale_files_are_reported_never_deleted(tmp_path):
    db, music, out = lib(tmp_path)
    ep.export(db, music, out)
    con = sqlite3.connect(db); con.execute("delete from playlist where id='p3'"); con.commit(); con.close()
    s = ep.export(db, music, out)
    assert s.stale == ["empty.m3u8"] and (out / "empty.m3u8").exists()


def test_file_names_are_safe_and_unique():
    taken = set()
    assert ep.file_name("a / b", taken) == "a - b.m3u8"
    assert ep.file_name("a - b", taken) != "a - b.m3u8"           # would collide: made unique
    assert ep.file_name(".hidden", set()) == "hidden.m3u8" and ep.file_name("x:y*?", set()) == "x_y__.m3u8"


def test_database_is_opened_read_only(tmp_path):
    db, music, out = lib(tmp_path)
    os.chmod(db, 0o444)
    try:
        assert ep.export(db, music, out).written == 3
    finally:
        os.chmod(db, 0o644)


# --- R5-01: playlist health (M9 §7) -------------------------------------------------------------------------------

def fake_mirror(tmp_path, missing=()):
    from subsonic.fake_server import FakeState
    state = FakeState(db_path=tmp_path / "fake-navidrome.db")
    state.missing = set(missing)
    state.sync()
    return state.db_path


def test_playlist_health_counts_entries_on_missing_files_per_playlist(tmp_path):
    db = fake_mirror(tmp_path, missing={"s2"})
    assert ep.playlist_health(db) == [{"id": "pl-1", "name": "Disco Edits", "missing": 1},
                                      {"id": "pl-3", "name": "Sunday Listening", "missing": 1}]


def test_playlist_health_counts_an_entry_whose_song_navidrome_no_longer_has(tmp_path):
    db = fake_mirror(tmp_path)
    assert ep.playlist_health(db) == []
    con = sqlite3.connect(db)
    con.executemany("INSERT INTO playlist_tracks (id, playlist_id, media_file_id) VALUES (?,?,?)",
                    [(4, "pl-2", "gone-1"), (5, "pl-2", "gone-2")])
    con.commit(); con.close()
    assert ep.playlist_health(db) == [{"id": "pl-2", "name": "Chicago 86", "missing": 2}]


def test_playlist_health_opens_the_database_read_only(tmp_path):
    db = fake_mirror(tmp_path, missing={"s2"})
    os.chmod(db, 0o444)
    try:
        assert [r["id"] for r in ep.playlist_health(db)] == ["pl-1", "pl-3"]
    finally:
        os.chmod(db, 0o644)


# --- R5-02: .m3u8 history before each rewrite, pruned after 30 days (M9 §7) ----------------------------------------

DAY = date(2026, 10, 21)


def _rename_track(db, title):
    con = sqlite3.connect(db); con.execute("update media_file set title=? where id='a'", (title,)); con.commit(); con.close()


def test_a_changed_playlist_keeps_its_previous_file_in_todays_history(tmp_path):
    db, music, out = lib(tmp_path)
    ep.export(db, music, out, today=DAY)
    assert not (out / ".history").exists()                     # new playlists make no history
    first = (out / "firstset？.m3u8").read_text(encoding="utf-8")
    _rename_track(db, "Good Times (Edit)")
    assert ep.export(db, music, out, today=DAY).written == 2
    day = out / ".history" / "2026-10-21"
    assert sorted(p.name for p in day.iterdir()) == ["firstset？.m3u8", "playlists - perfect songs.m3u8"]
    assert (day / "firstset？.m3u8").read_text(encoding="utf-8") == first      # "empty" was unchanged: not copied
    _rename_track(db, "Good Times (Dub)")                       # a third version the same day keeps the first
    ep.export(db, music, out, today=DAY)
    assert (day / "firstset？.m3u8").read_text(encoding="utf-8") == first
    assert "Good Times (Dub)" in (out / "firstset？.m3u8").read_text(encoding="utf-8")
    _rename_track(db, "Good Times (Live)")                      # the next day starts its own folder
    ep.export(db, music, out, today=date(2026, 10, 22))
    assert "Good Times (Dub)" in (out / ".history" / "2026-10-22" / "firstset？.m3u8").read_text(encoding="utf-8")
    assert not list(out.rglob("*.tmp"))


def test_an_unchanged_export_makes_no_history(tmp_path):
    db, music, out = lib(tmp_path)
    ep.export(db, music, out, today=DAY)
    ep.export(db, music, out, today=DAY)
    assert not (out / ".history").exists()


def test_history_files_are_neither_stale_nor_checked(tmp_path):
    db, music, out = lib(tmp_path)
    ep.export(db, music, out, today=DAY)
    _rename_track(db, "Good Times (Edit)")
    s = ep.export(db, music, out, today=DAY)
    assert (out / ".history" / "2026-10-21" / "firstset？.m3u8").exists()
    assert s.stale == [] and ep.check(db, music, out) == []


def _tree(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() and not p.is_symlink() else None)
            for p in sorted(root.rglob("*"))}


def test_prune_history_removes_only_dated_folders_older_than_30_days(tmp_path):
    db, music, out = lib(tmp_path)
    ep.export(db, music, out, today=DAY)
    hist = out / ".history"
    for name in ("2026-09-20", "2026-09-21", "2026-09-22", "notes", "2026-13-45"):      # 31, 30, 29 days old
        (hist / name).mkdir(parents=True); (hist / name / "x.m3u8").write_text("#EXTM3U\n")
    (hist / "2026-09-01.m3u8").write_text("a file named like a date")
    old = out / "playlists - perfect songs.m3u8"
    os.utime(old, (0, 0))                                       # an old live file: not history, never pruned
    outside = tmp_path / "elsewhere" / "2026-01-01"
    outside.mkdir(parents=True); (outside / "keep.flac").write_bytes(b"x")
    (hist / "2026-01-02").symlink_to(outside, target_is_directory=True)               # old-dated link: not followed
    music_before = {k: v for k, v in _tree(music).items() if not k.startswith("_playlists/.history")}
    ep.prune_history(out, DAY)
    assert sorted(p.name for p in hist.iterdir()) == ["2026-01-02", "2026-09-01.m3u8", "2026-09-21", "2026-09-22",
                                                      "2026-13-45", "notes"]
    assert (outside / "keep.flac").read_bytes() == b"x" and (hist / "2026-01-02").is_symlink()
    assert {k: v for k, v in _tree(music).items() if not k.startswith("_playlists/.history")} == music_before
    assert old.exists()


def test_prune_history_without_history_and_through_a_linked_history_does_nothing(tmp_path):
    out = tmp_path / "_playlists"
    out.mkdir()
    ep.prune_history(out, DAY)                                  # no .history yet: fine
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "2020-01-01").mkdir(parents=True)
    (out / ".history").symlink_to(elsewhere, target_is_directory=True)
    ep.prune_history(out, DAY)
    assert (elsewhere / "2020-01-01").is_dir()


def test_export_prunes_old_history(tmp_path, capsys):
    db, music, out = lib(tmp_path)
    (out / ".history" / "2026-09-01").mkdir(parents=True)
    (out / ".history" / "2026-10-01").mkdir(parents=True)
    assert ep.export(db, music, out, today=DAY).pruned == ["2026-09-01"]
    assert sorted(p.name for p in (out / ".history").iterdir()) == ["2026-10-01"]
    assert "history pruned" not in capsys.readouterr().out
    (out / ".history" / "2000-01-01").mkdir()
    assert ep.main(["export", "--db", str(db), "--music", str(music)]) == 0
    assert "history pruned: .history/2000-01-01" in capsys.readouterr().out


def test_an_old_day_folder_holding_links_is_removed_without_following_them(tmp_path):
    out, outside = tmp_path / "_playlists", tmp_path / "music"
    (outside / "Album").mkdir(parents=True); (outside / "Album" / "song.flac").write_bytes(b"x")
    day = out / ".history" / "2026-01-01"
    day.mkdir(parents=True)
    (day / "dir-link").symlink_to(outside / "Album", target_is_directory=True)
    (day / "file-link.flac").symlink_to(outside / "Album" / "song.flac")
    assert ep.prune_history(out, DAY) == ["2026-01-01"]
    assert not day.exists() and (outside / "Album" / "song.flac").read_bytes() == b"x"


def test_a_failing_history_never_stops_the_export(tmp_path, monkeypatch, capsys):
    db, music, out = lib(tmp_path)
    ep.export(db, music, out, today=DAY)
    (out / ".history").write_text("not a folder")               # history cannot be written
    (tmp_path / "elsewhere").mkdir()
    _rename_track(db, "Good Times (Edit)")
    s = ep.export(db, music, out, today=DAY)
    assert s.written == 2 and "Good Times (Edit)" in (out / "firstset？.m3u8").read_text(encoding="utf-8")
    assert len(s.errors) == 2 and all("history" in e for e in s.errors)
    (out / ".history").unlink()                                 # a linked .history is not written through
    (out / ".history").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    _rename_track(db, "Good Times (Dub)")
    s = ep.export(db, music, out, today=DAY)
    assert s.written == 2 and list((tmp_path / "elsewhere").iterdir()) == []
    assert s.errors and all("link" in e for e in s.errors)
    (out / ".history").unlink()                                 # a prune that fails is reported, not raised
    (out / ".history" / "2026-01-01").mkdir(parents=True)
    monkeypatch.setattr(ep.shutil, "rmtree", lambda p: (_ for _ in ()).throw(PermissionError(13, "denied", str(p))))
    s = ep.export(db, music, out, today=DAY)
    assert s.pruned == [] and any("prune" in e and "denied" in e for e in s.errors)
    assert ep.main(["export", "--db", str(db), "--music", str(music), "--out", str(out)]) == 0
    assert "history: prune" in capsys.readouterr().out
