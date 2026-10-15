import os
import sqlite3
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
