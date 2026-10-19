"""N4: a filed external row goes into its imported playlist at its Spotify position (M9 item 1, D44). The pure
rule first, then place() against the fake Navidrome with its navidrome.db mirror (hidden rows are real there)."""
import pytest

from crates import placement as pl
from crates import playlist_edit as pe
from crates.store import CrateStore
from subsonic.client import SubsonicClient
from subsonic.fake_server import FakeSubsonicServer


# --- insert_index (pure)

def test_after_the_nearest_earlier_neighbour():
    order = [(1, "s1"), (2, None), (3, "s2"), (4, "s3")]
    assert pl.insert_index(order, ["s1", "s2", "s3"], 2) == (1, "after s1")


def test_a_removed_earlier_neighbour_is_skipped_for_the_next_one():
    order = [(1, "s1"), (2, "s2"), (3, None), (4, "s3")]
    assert pl.insert_index(order, ["s1", "s3"], 3) == (1, "after s1")           # s2 removed by Michael


def test_before_the_nearest_later_neighbour_when_no_earlier_one_is_present():
    order = [(1, "s1"), (2, None), (3, "s2"), (4, "s3")]
    assert pl.insert_index(order, ["s2", "s3"], 2) == (0, "before s2")
    assert pl.insert_index(order, ["s3", "s4"], 2) == (0, "before s3")          # s2 removed too: the next later one


def test_append_when_no_neighbour_is_present():
    assert pl.insert_index([(5, None)], ["s4", "s5"], 5) == (2, "append")
    assert pl.insert_index([(1, "s1"), (2, None)], [], 2) == (0, "append")


def test_still_wanted_rows_are_skipped():
    order = [(1, "s1"), (2, None), (3, None), (4, "s3")]
    assert pl.insert_index(order, ["s1", "s3"], 3) == (1, "after s1")
    assert pl.insert_index([(1, None), (2, None), (3, "s3")], ["s3"], 2) == (0, "before s3")


def test_a_duplicated_neighbour_uses_its_last_or_first_occurrence():
    assert pl.insert_index([(1, "s1"), (2, None)], ["s1", "s2", "s1", "s3"], 2) == (3, "after s1")
    assert pl.insert_index([(1, None), (2, "s3")], ["s1", "s3", "s2", "s3"], 1) == (1, "before s3")


def test_positions_may_have_gaps_and_come_unsorted():
    order = [(40, "s3"), (7, "s1"), (12, None), (30, "s2")]
    assert pl.insert_index(order, ["s1", "s2", "s3"], 12) == (1, "after s1")
    assert pl.insert_index(order, ["s2", "s3"], 12) == (0, "before s2")


# --- place() on the fake

@pytest.fixture
def srv(tmp_path):
    with FakeSubsonicServer(db_path=tmp_path / "navidrome.db") as s:
        # s9: the track import-playlist queued as an external row, filed and indexed since
        s.state.songs["s9"] = dict(s.state.songs["s4"], id="s9", title="Love Is the Message", artist="MFSB",
                                   path="MFSB/Love Is the Message/01 - Love Is the Message.flac")
        s.state.sync()
        yield s


@pytest.fixture
def client(srv):
    return SubsonicClient(srv.url, "demo", "demo")


@pytest.fixture
def db(srv):
    return srv.state.db_path


@pytest.fixture
def store():
    """pl-1 "Disco Edits" = [s1, s2, s3] was imported from Spotify as s1, <MFSB>, s2, s3; the MFSB row is filed
    as s9 (ok, not provisional)."""
    st = CrateStore()
    st.mark_playlist_imported("pl-1", "Disco Edits", "spotify:playlist:abc")
    st.mark_imported("pl-1", ["s1", "s2", "s3"])
    ext = st.add_external_wanted("MFSB", "Love Is the Message", playlist_id="pl-1", position=2)
    st.record_import_order("pl-1", [(1, "s1", None), (2, None, ext), (3, "s2", None), (4, "s3", None)])
    st.set_library_song(ext, "s9")
    st.set_external_status(ext, "ok", "filed")
    st.commit()
    st.ext = ext
    return st


def _songs(srv, pid):
    return list(srv.state.playlists[pid]["songs"])


def _updates(srv):
    return [q for m, q in srv.state.requests if m == "updatePlaylist"]


def _placed(store):
    return [e for e in store.events(200) if e["kind"] == "placed"]


def _place(store, client, db, song="s9", pid="pl-1"):
    return pl.place(store, client, db, pid, store.ext, song)


def test_place_inserts_after_the_earlier_neighbour(srv, client, db, store):
    assert _place(store, client, db) == "placed at 1 (after s1)"
    assert _songs(srv, "pl-1") == ["s1", "s9", "s2", "s3"]
    assert pe.checked_entries(client, db, "pl-1") == ["s1", "s9", "s2", "s3"]
    assert "s9" in store.imported("pl-1")
    [ev] = _placed(store)
    assert ev["playlist_id"] == "pl-1" and ev["song_id"] == store.ext
    assert ev["detail"] == "Disco Edits: MFSB – Love Is the Message at 2 (after s1)"


def test_the_edit_is_one_update_that_only_inserts(srv, db, store):
    calls = []

    class Recording(SubsonicClient):
        def update_playlist(self, playlist_id, **kw):
            calls.append((playlist_id, kw))
            super().update_playlist(playlist_id, **kw)

    before = _songs(srv, "pl-1")
    _place(store, Recording(srv.url, "demo", "demo"), db)
    assert calls == [("pl-1", {"remove_indexes": [1, 2], "add_song_ids": ["s9", "s2", "s3"]})]   # as rewrite does
    assert len(_updates(srv)) == 1
    after = _songs(srv, "pl-1")
    assert after[:1] == before[:1] and after[1] == "s9" and after[2:] == before[1:]      # nothing moved or removed


def test_with_the_earlier_neighbour_removed_it_goes_before_the_later_one(srv, client, db, store):
    srv.state.playlists["pl-1"]["songs"].remove("s1")                           # Michael removed s1
    srv.state.sync()
    assert _place(store, client, db) == "placed at 0 (before s2)"
    assert _songs(srv, "pl-1") == ["s9", "s2", "s3"]


def test_with_no_neighbour_present_it_appends(srv, client, db, store):
    srv.state.playlists["pl-1"]["songs"] = ["s4"]                               # s4 is not in the import
    srv.state.sync()
    assert _place(store, client, db) == "placed at 1 (append)"
    assert _songs(srv, "pl-1") == ["s4", "s9"]
    assert _placed(store)[0]["detail"].endswith("at 2 (append)")


def test_only_its_own_row_in_the_order_appends(srv, client, db, store):
    store.record_import_order("pl-1", [(1, None, store.ext)])
    assert _place(store, client, db) == "placed at 3 (append)"
    assert _songs(srv, "pl-1") == ["s1", "s2", "s3", "s9"]


def test_a_neighbour_filed_earlier_counts_as_present(srv, client, db, store):
    """An order row that queued a wanted row which is filed since (ok, its song in the playlist) is a neighbour."""
    srv.state.songs["s8"] = dict(srv.state.songs["s5"], id="s8", title="Ten Percent", artist="Double Exposure")
    srv.state.playlists["pl-1"]["songs"] = ["s1", "s8", "s2", "s3"]
    srv.state.sync()
    other = store.add_external_wanted("Double Exposure", "Ten Percent", playlist_id="pl-1", position=2)
    store.set_library_song(other, "s8")
    store.set_external_status(other, "ok")
    store.record_import_order("pl-1", [(1, "s1", None), (2, None, other), (3, None, store.ext), (4, "s2", None),
                                       (5, "s3", None)])
    assert _place(store, client, db) == "placed at 2 (after s8)"
    assert _songs(srv, "pl-1") == ["s1", "s8", "s9", "s2", "s3"]


def test_a_neighbour_still_wanted_or_provisional_is_skipped(srv, client, db, store):
    wanted = store.add_external_wanted("Double Exposure", "Ten Percent", playlist_id="pl-1", position=1)
    store.set_library_song(wanted, "s1")                                        # still sourcing a better file
    store.set_external_status(wanted, "sourcing")
    legacy = store.add_external_wanted("Loleatta Holloway", "Hit and Run", playlist_id="pl-1", position=2)
    store.set_external_song(legacy, "s1", True)                                 # play-now's copy, not its file yet
    store.set_external_status(legacy, "ok")
    store.record_import_order("pl-1", [(1, None, wanted), (2, None, legacy), (3, None, store.ext), (4, "s2", None)])
    assert _place(store, client, db) == "placed at 1 (before s2)"


def test_a_hidden_missing_row_refuses_and_writes_nothing(srv, client, db, store):
    srv.state.missing.add("s2")
    srv.state.sync()
    with pytest.raises(pe.PlaylistSkew):
        _place(store, client, db)
    assert _updates(srv) == []
    assert _songs(srv, "pl-1") == ["s1", "s2", "s3"]
    assert "s9" not in store.imported("pl-1") and _placed(store) == []


@pytest.mark.parametrize("why", ["changed", "owner", "smart"])
def test_refusals_propagate_as_edit_refused(srv, client, db, store, why):
    if why == "owner":
        srv.state.playlists["pl-1"]["owner"] = "amperfy"
    elif why == "smart":
        srv.state.smart.add("pl-1")
    srv.state.sync()
    if why == "changed":                                                        # another client edits mid-way
        class Racing(SubsonicClient):
            reads = 0

            def playlist(self, playlist_id):
                Racing.reads += 1
                if Racing.reads == 2:                                           # between place's read and rewrite's
                    srv.state.playlists["pl-1"]["songs"].append("s5")
                    srv.state.sync()
                return super().playlist(playlist_id)
        client = Racing(srv.url, "demo", "demo")
    expected = {"changed": pe.PlaylistChanged, "owner": pe.NotOwned, "smart": pe.NotEditable}[why]
    with pytest.raises(expected):
        _place(store, client, db)
    assert _updates(srv) == []
    assert "s9" not in store.imported("pl-1")


def test_a_song_not_in_the_library_now_is_refused_before_any_write(srv, client, db, store):
    srv.state.missing.add("s9")                                                 # trashed, or retagged under a new id
    srv.state.sync()
    with pytest.raises(pe.EditRefused, match="s9 is not in the library"):
        _place(store, client, db)
    assert _updates(srv) == []


def test_already_in_the_playlist_is_skipped_without_a_write(srv, client, db, store):
    srv.state.playlists["pl-1"]["songs"].append("s9")
    srv.state.sync()
    assert _place(store, client, db) == "skipped: already in playlist"
    assert _updates(srv) == []
    assert "s9" in store.imported("pl-1")                                       # removed later, stays removed
    assert _placed(store) == []


def test_a_second_place_is_skipped_as_added_before(srv, client, db, store):
    _place(store, client, db)
    srv.state.playlists["pl-1"]["songs"].remove("s9")                           # Michael removes it again
    srv.state.sync()
    assert _place(store, client, db) == "skipped: added before (removed stays removed)"
    assert _songs(srv, "pl-1") == ["s1", "s2", "s3"]
    assert len(_updates(srv)) == 1


def test_not_an_imported_playlist_is_skipped(srv, client, db, store):
    store.record_import_order("pl-3", [(1, None, store.ext)])
    assert pl.place(store, client, db, "pl-3", store.ext, "s9") == "skipped: not an imported playlist"
    assert _updates(srv) == [] and _songs(srv, "pl-3") == ["s2"]


def test_a_gone_playlist_is_skipped(srv, client, db, store):
    del srv.state.playlists["pl-1"]
    srv.state.sync()
    assert _place(store, client, db) == "skipped: playlist gone"
    assert _updates(srv) == []


def test_a_row_no_longer_in_the_import_is_skipped(srv, client, db, store):
    store.record_import_order("pl-1", [(1, "s1", None), (2, "s2", None), (3, "s3", None)])
    assert _place(store, client, db) == "skipped: no longer in the import"
    assert _updates(srv) == []


def test_before_write_runs_once_checks_pass_and_can_stop_the_write(srv, client, db, store):
    """The worker's intent row (N4-04) is written here: after every check, right before the write."""
    seen = []

    def stop(index, how, n):
        seen.append((index, how, n))
        raise RuntimeError("intent not saved")

    with pytest.raises(RuntimeError):
        pl.place(store, client, db, "pl-1", store.ext, "s9", before_write=stop)
    assert seen == [(1, "after s1", 3)]
    assert _updates(srv) == []
