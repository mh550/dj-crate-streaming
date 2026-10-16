"""Guarded playlist index edits (M8 Task 6): Navidrome hides missing songs from getPlaylist but keeps their rows, and
songIndexToRemove counts those hidden rows, so an edit by the visible index can remove the wrong song (measured fact 5).
Every edit here runs against the fake Navidrome with its navidrome.db mirror, which reproduces that trap."""
import sqlite3
from contextlib import closing

import pytest

from crates import playlist_edit as pe
from subsonic.client import SubsonicClient
from subsonic.fake_server import FakeSubsonicServer


@pytest.fixture
def srv(tmp_path):
    with FakeSubsonicServer(db_path=tmp_path / "navidrome.db") as s:
        # s9: a better copy of s3 ("Move Your Body"), already indexed by its own scan
        s.state.songs["s9"] = dict(s.state.songs["s3"], id="s9", suffix="flac",
                                   path="Marshall Jefferson/The House Music Anthem/01 - Move Your Body.flac")
        s.state.sync()
        yield s


@pytest.fixture
def db(srv):
    return srv.state.db_path


def _client(srv):
    return SubsonicClient(srv.url, "demo", "demo")


def _songs(srv, pid):
    return list(srv.state.playlists[pid]["songs"])


def _positions(db, pid):
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as con:
        return [m for (m,) in con.execute(
            "SELECT media_file_id FROM playlist_tracks WHERE playlist_id = ? ORDER BY id", (pid,))]


def _updates(srv, pid=None):
    return [q for m, q in srv.state.requests if m == "updatePlaylist" and (pid is None or q.get("playlistId") == pid)]


def _hide(srv, sid):
    srv.state.missing.add(sid)
    srv.state.sync()


def test_checked_entries_match_the_db(srv, db):
    c = _client(srv)
    for pid in srv.state.playlists:
        assert pe.checked_entries(c, db, pid) == _positions(db, pid) == _songs(srv, pid)
    assert pe.checked_entries(c, db, "pl-1") == ["s1", "s2", "s3"]


def test_hidden_missing_entry_is_refused(srv, db):
    c = _client(srv)
    _hide(srv, "s2")
    assert [s.id for s in c.playlist("pl-1").entries] == ["s1", "s3"]          # what a client sees
    with pytest.raises(pe.PlaylistSkew, match="Disco Edits"):
        pe.checked_entries(c, db, "pl-1")
    with pytest.raises(pe.PlaylistSkew):
        pe.rewrite(c, db, "pl-1", ["s1", "s3"], ["s1", "s9"])
    with pytest.raises(pe.PlaylistSkew):
        pe.replace_slot(c, db, "pl-1", 1, "s3", "s9")                         # visible index 1 is s3; position 2 is s2
    out = pe.repoint_everywhere(c, db, "s3", "s9")
    assert out["Disco Edits"].startswith("refused: ") and "Disco Edits" in out["Disco Edits"]
    assert out["Chicago 86"] == "repointed"                                   # the healthy playlist is still repointed
    assert _updates(srv, "pl-1") == []
    assert _songs(srv, "pl-1") == ["s1", "s2", "s3"]


def test_entry_without_a_media_file_row_is_refused(srv, db):
    """A playlist_tracks row whose song Navidrome no longer has at all is hidden the same way."""
    srv.state.playlists["pl-1"]["songs"].insert(0, "gone")
    srv.state.sync()
    c = _client(srv)
    assert [s.id for s in c.playlist("pl-1").entries] == ["s1", "s2", "s3"]
    with pytest.raises(pe.PlaylistSkew, match="gone"):
        pe.checked_entries(c, db, "pl-1")


def test_rewrite_is_one_call_and_verified(srv, db):
    c = _client(srv)
    pe.rewrite(c, db, "pl-2", ["s3", "s4", "s5"], ["s3", "s9", "s5", "s1"])
    ups = _updates(srv)
    assert len(ups) == 1
    assert ups[0]["playlistId"] == "pl-2"
    assert pe.checked_entries(c, db, "pl-2") == ["s3", "s9", "s5", "s1"] == _positions(db, "pl-2")


def test_rewrite_without_a_change_writes_nothing(srv, db):
    c = _client(srv)
    pe.rewrite(c, db, "pl-2", ["s3", "s4", "s5"], ["s3", "s4", "s5"])
    assert _updates(srv) == []


def test_rewrite_detects_a_concurrent_edit(srv, db):
    c = _client(srv)
    with pytest.raises(pe.PlaylistChanged):
        pe.rewrite(c, db, "pl-2", ["s3", "s4"], ["s9", "s4"])                  # the caller read an older pl-2
    assert _updates(srv) == []
    assert _songs(srv, "pl-2") == ["s3", "s4", "s5"]


def test_rewrite_reports_a_readback_that_differs(srv, db):
    """Another client edits right after our write: the edit was made, so this is not a refusal; the caller is told."""
    class Racing(SubsonicClient):
        def update_playlist(self, playlist_id, **kw):
            super().update_playlist(playlist_id, **kw)
            srv.state.playlists[playlist_id]["songs"].append("s1")
            srv.state.sync()

    c = Racing(srv.url, "demo", "demo")
    with pytest.raises(pe.EditNotKept, match="Chicago 86"):
        pe.rewrite(c, db, "pl-2", ["s3", "s4", "s5"], ["s9", "s4", "s5"])
    assert not issubclass(pe.EditNotKept, pe.EditRefused)


def test_rewrite_refuses_to_add_a_song_navidrome_would_hide(srv, db):
    c = _client(srv)
    _hide(srv, "s1")
    for new in ("s1", "nope"):                                                # missing; unknown to Navidrome
        with pytest.raises(pe.PlaylistSkew, match=new):
            pe.rewrite(c, db, "pl-2", ["s3", "s4", "s5"], ["s3", "s4", "s5", new])
    assert _updates(srv) == []


def test_repoint_everywhere_replaces_in_place_in_every_playlist(srv, db):
    c = _client(srv)
    out = pe.repoint_everywhere(c, db, "s3", "s9")
    assert out == {"Disco Edits": "repointed", "Chicago 86": "repointed"}      # pl-1 is not a crate: repointed too
    assert _songs(srv, "pl-1") == ["s1", "s2", "s9"]
    assert _songs(srv, "pl-2") == ["s9", "s4", "s5"]
    assert _songs(srv, "pl-3") == ["s2"]
    assert pe.references(db, "s3") == []
    assert pe.references(db, "s9") == [("pl-1", 3), ("pl-2", 1)]


def test_repoint_drops_a_duplicate_when_the_new_song_is_already_there(srv, db):
    c = _client(srv)
    out = pe.repoint_everywhere(c, db, "s3", "s5")                            # pl-2 already holds s5
    assert out == {"Disco Edits": "repointed", "Chicago 86": "repointed"}
    assert _songs(srv, "pl-2") == ["s4", "s5"]
    assert _songs(srv, "pl-1") == ["s1", "s2", "s5"]


def test_repoint_keeps_playlists_with_the_same_name_apart(srv, db):
    c = _client(srv)
    twin = c.create_playlist("Disco Edits", ["s3"]).id
    out = pe.repoint_everywhere(c, db, "s3", "s9")
    assert len(out) == 3 and set(out.values()) == {"repointed"}
    assert _songs(srv, twin) == ["s9"]


def test_repoint_to_itself_is_an_error(srv, db):
    with pytest.raises(ValueError):
        pe.repoint_everywhere(_client(srv), db, "s3", "s3")


def test_references_counts_hidden_rows(srv, db):
    _hide(srv, "s2")
    assert pe.references(db, "s2") == [("pl-1", 2), ("pl-3", 1)]
    srv.state.playlists["pl-3"]["songs"] = []
    srv.state.sync()
    assert pe.references(db, "s2") == [("pl-1", 2)]
    assert pe.references(db, "nope") == []


def test_replace_slot_touches_only_that_slot(srv, db):
    c = _client(srv)
    pid = c.create_playlist("Twice", ["s3", "s1", "s3"]).id
    pe.replace_slot(c, db, pid, 2, "s3", "s9")
    assert _songs(srv, pid) == ["s3", "s1", "s9"]
    assert _songs(srv, "pl-2") == ["s3", "s4", "s5"]
    assert len(_updates(srv)) == 1


def test_replace_slot_allows_the_new_song_elsewhere(srv, db):
    c = _client(srv)
    pe.replace_slot(c, db, "pl-2", 0, "s3", "s5")
    assert _songs(srv, "pl-2") == ["s5", "s4", "s5"]


def test_replace_slot_refuses_a_stale_slot(srv, db):
    c = _client(srv)
    with pytest.raises(pe.StaleSlot):
        pe.replace_slot(c, db, "pl-1", 0, "s3", "s9")                         # slot 0 holds s1
    with pytest.raises(pe.StaleSlot):
        pe.replace_slot(c, db, "pl-1", 3, "s3", "s9")                         # past the end
    with pytest.raises(pe.StaleSlot):
        pe.replace_slot(c, db, "pl-1", -1, "s3", "s9")                        # no negative indexes
    assert _updates(srv) == []


def test_smart_playlist_is_skipped(srv, db):
    c = _client(srv)
    srv.state.smart.add("pl-1")
    srv.state.sync()
    out = pe.repoint_everywhere(c, db, "s3", "s9")
    assert out == {"Disco Edits": "skipped: smart playlist", "Chicago 86": "repointed"}
    with pytest.raises(pe.NotEditable):
        pe.replace_slot(c, db, "pl-1", 2, "s3", "s9")
    with pytest.raises(pe.NotEditable):
        pe.rewrite(c, db, "pl-1", ["s1", "s2", "s3"], ["s1", "s2", "s9"])
    assert _updates(srv, "pl-1") == []
    assert _songs(srv, "pl-1") == ["s1", "s2", "s3"]


def test_refusals_share_one_base_class():
    for exc in (pe.PlaylistSkew, pe.PlaylistChanged, pe.NotEditable, pe.StaleSlot):
        assert issubclass(exc, pe.EditRefused)


def test_config_reads_navidrome_db(monkeypatch):
    from crates.service import Config
    monkeypatch.delenv("NAVIDROME_DB", raising=False)
    assert Config.from_env().navidrome_db is None
    monkeypatch.setenv("NAVIDROME_DB", "/srv/docker/navidrome/navidrome.db")
    assert Config.from_env().navidrome_db == "/srv/docker/navidrome/navidrome.db"
