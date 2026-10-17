"""Guarded playlist index edits (M8 Task 6): Navidrome hides missing songs from getPlaylist but keeps their rows, and
songIndexToRemove counts those hidden rows, so an edit by the visible index can remove the wrong song (measured fact 5).
Every edit here runs against the fake Navidrome with its navidrome.db mirror, which reproduces that trap."""
import http.client
import sqlite3
import urllib.error
from contextlib import closing

import pytest

from crates import playlist_edit as pe
from subsonic.client import SubsonicClient, SubsonicError
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


def test_repoint_calls_before_write_with_the_exact_entries_it_replaces(srv, db):
    """The caller's reverse log: called after the playlist passed its checks and before its write, never for a
    refused one; when it raises, that playlist is not written."""
    c = _client(srv)
    srv.state.smart.add("pl-2")
    srv.state.sync()
    seen = []

    def hook(pid, name, before, after):
        seen.append((pid, name, before, after, list(srv.state.playlists[pid]["songs"])))
    out = pe.repoint_everywhere(c, db, "s3", "s9", before_write=hook)
    assert out == {"Disco Edits": "repointed", "Chicago 86": "skipped: smart playlist"}
    assert seen == [("pl-1", "Disco Edits", ["s1", "s2", "s3"], ["s1", "s2", "s9"], ["s1", "s2", "s3"])]

    srv.state.smart.clear()
    srv.state.sync()

    def broken(*a):
        raise OSError("disk full")
    out = pe.repoint_everywhere(c, db, "s3", "s9", before_write=broken)
    assert out["Chicago 86"].startswith("failed: ") and "disk full" in out["Chicago 86"]
    assert _songs(srv, "pl-2") == ["s3", "s4", "s5"]


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


# --- review fixes: each guard has a test that fails without it

def _db_exec(db, sql, *args):
    with closing(sqlite3.connect(db)) as con, con:
        con.execute(sql, args)


def test_a_gap_in_the_db_positions_is_refused(srv, db):
    """Same ids in the same order, but positions 1,2,4: songIndexToRemove arithmetic would no longer match."""
    _db_exec(db, "UPDATE playlist_tracks SET id = 4 WHERE playlist_id = 'pl-2' AND id = 3")
    with pytest.raises(pe.PlaylistSkew, match="Chicago 86"):
        pe.checked_entries(_client(srv), db, "pl-2")


def test_a_db_row_the_api_still_shows_is_refused(srv, db):
    """No missing song anywhere; the two views simply differ (the db read raced an edit)."""
    _db_exec(db, "DELETE FROM playlist_tracks WHERE playlist_id = 'pl-2' AND id = 3")
    with pytest.raises(pe.PlaylistSkew, match="Chicago 86"):
        pe.checked_entries(_client(srv), db, "pl-2")


def test_a_playlist_absent_from_the_db_is_refused(srv, db):
    _db_exec(db, "DELETE FROM playlist WHERE id = 'pl-2'")
    with pytest.raises(pe.PlaylistSkew, match="pl-2"):
        pe.checked_entries(_client(srv), db, "pl-2")


@pytest.mark.parametrize("exc", [http.client.IncompleteRead(b""), ValueError("bad JSON"), KeyError("playlist"),
                                 sqlite3.OperationalError("database is locked"), urllib.error.URLError("timed out")])
def test_repoint_keeps_going_after_any_error_in_one_playlist(srv, db, exc):
    class Flaky(SubsonicClient):
        def update_playlist(self, playlist_id, **kw):
            if playlist_id == "pl-1":
                raise exc
            return super().update_playlist(playlist_id, **kw)

    out = pe.repoint_everywhere(Flaky(srv.url, "demo", "demo"), db, "s3", "s9")
    assert out["Disco Edits"].startswith("failed: ")
    assert out["Chicago 86"] == "repointed"
    assert _songs(srv, "pl-2") == ["s9", "s4", "s5"]


def test_repoint_survives_a_db_error_looking_up_a_name(srv, db, monkeypatch):
    real, calls = pe.open_ro, {"n": 0}

    def flaky(path):
        calls["n"] += 1
        if calls["n"] == 2:                                                   # 1: references; 2: pl-1's name
            raise sqlite3.OperationalError("database is locked")
        return real(path)

    monkeypatch.setattr(pe, "open_ro", flaky)
    out = pe.repoint_everywhere(_client(srv), db, "s3", "s9")
    assert out["pl-1"].startswith("failed: ")
    assert out["Chicago 86"] == "repointed"
    assert _songs(srv, "pl-1") == ["s1", "s2", "s3"]


def test_repoint_reports_a_db_playlist_the_api_does_not_have(srv, db):
    # pl-0 sorts first: the fake rewrites its mirror (dropping Ghost) on the first edit
    _db_exec(db, "INSERT INTO playlist (id, name) VALUES ('pl-0', 'Ghost')")
    _db_exec(db, "INSERT INTO playlist_tracks VALUES (1, 'pl-0', 's3')")
    out = pe.repoint_everywhere(_client(srv), db, "s3", "s9")
    assert out["Ghost"].startswith("failed: ")
    assert out["Disco Edits"] == out["Chicago 86"] == "repointed"


def test_a_transport_error_on_the_readback_is_edit_not_kept(srv, db):
    class LostReadback(SubsonicClient):
        reads = 0

        def playlist(self, playlist_id):
            LostReadback.reads += 1
            if LostReadback.reads == 2:                                       # 1: the check; 2: the readback
                raise SubsonicError(0, "HTTP 502 from getPlaylist")
            return super().playlist(playlist_id)

    with pytest.raises(pe.EditNotKept, match="502"):
        pe.rewrite(LostReadback(srv.url, "demo", "demo"), db, "pl-2", ["s3", "s4", "s5"], ["s9", "s4", "s5"])
    assert _songs(srv, "pl-2") == ["s9", "s4", "s5"]                          # the write did happen


def test_another_users_playlist_is_never_edited(srv, db):
    """Runbook: never touch the amperfy account's playlists, even though Navidrome lets an admin edit them."""
    c = _client(srv)
    srv.state.playlists["pl-1"]["owner"] = "amperfy"
    srv.state.sync()
    assert c.playlist("pl-1").owner == "amperfy"
    out = pe.repoint_everywhere(c, db, "s3", "s9")
    assert out == {"Disco Edits": "refused: owned by amperfy", "Chicago 86": "repointed"}
    with pytest.raises(pe.NotOwned):
        pe.replace_slot(c, db, "pl-1", 2, "s3", "s9")
    with pytest.raises(pe.NotOwned):
        pe.rewrite(c, db, "pl-1", ["s1", "s2", "s3"], ["s1", "s2", "s9"])
    assert _updates(srv, "pl-1") == []
    assert pe.references(db, "s3") == [("pl-1", 3)]                          # stays referenced: never trashed
    assert issubclass(pe.NotOwned, pe.EditRefused)
