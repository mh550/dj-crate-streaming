"""The fake Navidrome mirrors navidrome.db and hides missing songs (Navidrome v0.64.2, M8 measured facts 4-5)."""
import sqlite3
from contextlib import closing

import pytest

from subsonic.client import SubsonicClient, SubsonicError
from subsonic.fake_server import FakeSubsonicServer


@pytest.fixture
def srv(tmp_path):
    with FakeSubsonicServer(db_path=tmp_path / "navidrome.db") as s:
        yield s


def _rows(srv, sql, *args):
    with closing(sqlite3.connect(f"file:{srv.state.db_path}?mode=ro", uri=True)) as con:
        return con.execute(sql, args).fetchall()


def _positions(srv, pid):
    return _rows(srv, "SELECT id, media_file_id FROM playlist_tracks WHERE playlist_id = ? ORDER BY id", pid)


def _client(srv):
    return SubsonicClient(srv.url, "demo", "demo")


def test_db_mirrors_playlists_and_positions(srv):
    assert _positions(srv, "pl-1") == [(1, "s1"), (2, "s2"), (3, "s3")]
    for sid, path in _rows(srv, "SELECT id, path FROM media_file"):
        assert path == srv.state.songs[sid]["path"]
    assert _rows(srv, "SELECT comment, rules FROM playlist WHERE id = 'pl-2'") == [("warmup #crate", None)]
    assert _rows(srv, "SELECT missing FROM media_file WHERE id = 's1'") == [(0,)]


def test_db_follows_every_update(srv):
    c = _client(srv)

    def check():
        for pid, p in srv.state.playlists.items():
            assert [sid for _, sid in _positions(srv, pid)] == [s.id for s in c.playlist(pid).entries]
            assert _rows(srv, "SELECT name, comment FROM playlist WHERE id = ?", pid) == [(p["name"], p["comment"])]
        assert {r[0] for r in _rows(srv, "SELECT id FROM playlist")} == set(srv.state.playlists)

    pl = c.create_playlist("New", ["s1", "s4"])
    check()
    c.update_playlist(pl.id, add_song_ids=["s5"], comment="hello #crate")
    check()
    c.update_playlist(pl.id, remove_indexes=[0], name="Renamed")
    check()
    assert _positions(srv, pl.id) == [(1, "s4"), (2, "s5")]
    c.delete_playlist(pl.id)
    check()
    assert _positions(srv, pl.id) == []


def test_missing_song_is_hidden_but_keeps_its_position(srv):
    c = _client(srv)
    srv.state.missing.add("s2")
    srv.state.sync()
    assert [s.id for s in c.playlist("pl-1").entries] == ["s1", "s3"]
    assert [p for p in c.playlists() if p.id == "pl-1"][0].song_count == 2
    assert [p for p in c.playlists() if p.id == "pl-1"][0].duration == 501 + 383   # the hidden s2 (356 s) is not summed
    assert _positions(srv, "pl-1") == [(1, "s1"), (2, "s2"), (3, "s3")]
    assert _rows(srv, "SELECT missing FROM media_file WHERE id = 's2'") == [(1,)]
    assert "s2" not in [s.id for s in c.search_songs("feel love")]
    with pytest.raises(SubsonicError) as ei:
        c.song("s2")
    assert ei.value.code == 70
    # the trap: visible index 1 is s3, but the position arithmetic counts the hidden s2 and removes it
    c.update_playlist("pl-1", remove_indexes=[1])
    assert srv.state.playlists["pl-1"]["songs"] == ["s1", "s3"]
    assert [s.id for s in c.playlist("pl-1").entries] == ["s1", "s3"]
    assert _positions(srv, "pl-1") == [(1, "s1"), (2, "s3")]


def test_smart_playlist_tracks_cannot_be_edited(srv):
    c = _client(srv)
    srv.state.smart.add("pl-1")
    srv.state.sync()
    assert _rows(srv, "SELECT rules FROM playlist WHERE id = 'pl-1'") != [(None,)]
    c.update_playlist("pl-1", comment="still editable")
    assert srv.state.playlists["pl-1"]["comment"] == "still editable"
    for kw in ({"add_song_ids": ["s4"]}, {"remove_indexes": [0]}):
        with pytest.raises(SubsonicError) as ei:
            c.update_playlist("pl-1", **kw)
        assert ei.value.code == 50
    assert srv.state.playlists["pl-1"]["songs"] == ["s1", "s2", "s3"]


def test_without_db_path_nothing_is_written_and_missing_still_hides():
    with FakeSubsonicServer() as s:
        assert s.state.db_path is None
        s.state.sync()                                   # no-op
        s.state.missing.add("s1")
        assert [x.id for x in _client(s).playlist("pl-1").entries] == ["s2", "s3"]


def test_media_file_mirrors_album_artist_and_year(srv):
    """dedupe_copies.py and tag_cleanup.py select these two columns; "" / 0 when the song has none."""
    srv.state.songs["s1"]["albumArtist"] = "Chic & Co"
    srv.state.sync()
    assert _rows(srv, "SELECT album_artist, year FROM media_file WHERE id = 's1'") == [("Chic & Co", 1979)]
    srv.state.songs["s3"].pop("year", None)
    srv.state.sync()
    assert _rows(srv, "SELECT album_artist, year FROM media_file WHERE id = 's3'") == [("", 0)]
