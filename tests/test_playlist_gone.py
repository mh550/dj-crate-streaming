"""N3 (D43): what reconcile does with a playlist crates.db knows but Navidrome no longer lists. The common scenarios
(all rows dropped; in-flight rows wait) run under both owners in test_crates.py and test_app_owner.py; these are the
guards, the reverse log and the wanted rows, under the default owner (app)."""
import json

import pytest

from crates.reconcile import Reconciler
from crates.store import CrateStore
from subsonic.client import SubsonicClient, SubsonicError
from subsonic.fake_server import FakeSubsonicServer
from tests.test_crates import gone_events, vanish


@pytest.fixture
def env():
    with FakeSubsonicServer() as srv:
        client = SubsonicClient(srv.url, "demo", "demo")
        store = CrateStore()
        yield srv, client, store, Reconciler(client, store, owner="app")


def snapshot(store, pid):
    return (store.get(pid), store.tracks(pid, include_removed=True), store.imported(pid),
            [r for r in store.imported_playlists() if r["playlist_id"] == pid], store.external_for_playlist(pid))


def test_an_empty_listing_drops_nothing(env):
    srv, client, store, rec = env
    rec.set_crate("pl-2", True)
    before = snapshot(store, "pl-2")
    for pid in list(srv.state.playlists):
        vanish(srv, pid)
    rep = rec.run()
    assert snapshot(store, "pl-2") == before and gone_events(store) == [] and rep.playlists_gone == []
    assert rep.errors == ["getPlaylists listed no playlist; nothing dropped (1 known: Chicago 86)"]


def test_more_than_three_missing_at_once_drops_nothing(env):
    srv, client, store, rec = env
    rec.set_crate("pl-2", True)
    for n in range(3):
        store.set_enabled(f"pl-x{n}", f"Old {n}", True)
    before = snapshot(store, "pl-2")
    vanish(srv, "pl-2")
    rep = rec.run()
    assert snapshot(store, "pl-2") == before and gone_events(store) == []
    assert rep.errors == ["4 known playlists missing from Navidrome at once (Chicago 86, Old 0, Old 1, Old 2); "
                          "nothing dropped"]
    assert [c.playlist_id for c in store.all()] == ["pl-2", "pl-x0", "pl-x1", "pl-x2"]


def test_missing_from_the_listing_but_readable_is_kept(env, monkeypatch):
    srv, client, store, rec = env
    rec.set_crate("pl-2", True)
    before = snapshot(store, "pl-2")
    real = client.playlists
    monkeypatch.setattr(client, "playlists", lambda: [p for p in real() if p.id != "pl-2"])
    rep = rec.run()
    assert snapshot(store, "pl-2") == before and gone_events(store) == []
    assert rep.errors == ["Chicago 86: missing from getPlaylists but getPlaylist reads it; kept"]


def test_another_error_than_70_is_not_gone(env, monkeypatch):
    srv, client, store, rec = env
    rec.set_crate("pl-2", True)
    before = snapshot(store, "pl-2")
    vanish(srv, "pl-2")

    def down(pid):
        raise SubsonicError(0, "Navidrome is starting")
    monkeypatch.setattr(client, "playlist", down)
    rep = rec.run()
    assert snapshot(store, "pl-2") == before and gone_events(store) == []
    assert rep.errors == ["Chicago 86: missing from getPlaylists but getPlaylist says subsonic error 0: "
                          "Navidrome is starting; kept"]


def test_a_garbled_getplaylist_answer_is_not_gone_and_the_run_finishes(env, monkeypatch):
    srv, client, store, rec = env
    rec.set_crate("pl-2", True)
    before = snapshot(store, "pl-2")
    vanish(srv, "pl-2")

    def garbled(pid):
        raise KeyError("playlist")                    # a response without "playlist", a truncated body, …
    monkeypatch.setattr(client, "playlist", garbled)
    rep = rec.run()
    assert snapshot(store, "pl-2") == before and gone_events(store) == []
    assert rep.errors == ["Chicago 86: missing from getPlaylists but getPlaylist says 'playlist'; kept"]

def test_a_failing_listing_raises_and_changes_nothing(env, monkeypatch):
    srv, client, store, rec = env
    rec.set_crate("pl-2", True)
    before = snapshot(store, "pl-2")

    def fail():
        raise OSError("connection refused")
    monkeypatch.setattr(client, "playlists", fail)
    with pytest.raises(OSError):
        rec.run()
    assert snapshot(store, "pl-2") == before


def test_review_questions_and_filed_failures_do_not_wait(env):
    srv, client, store, rec = env
    rec.set_crate("pl-2", True)
    store.set_track_status("pl-2", "s3", "review", "ambiguous: 2 library versions")
    store.set_track_status("pl-2", "s4", "failed", "Navidrome never indexed a/b.flac; file is in the library")
    vanish(srv, "pl-2")
    rep = rec.run()
    assert store.get("pl-2") is None and store.tracks("pl-2", include_removed=True) == []
    assert rep.tracks_removed == 3


def test_a_row_with_an_approval_in_progress_waits(env):
    srv, client, store, rec = env
    rec.set_crate("pl-2", True)
    store.approve("s4", "michael", None, "crate")
    vanish(srv, "pl-2")
    rep = rec.run()
    assert [t["song_id"] for t in store.tracks("pl-2")] == ["s4"]
    assert rep.playlists_gone == ["Chicago 86: playlist no longer exists in Navidrome; 2 rows dropped, 1 in flight kept"]


def test_an_imported_playlists_wanted_rows_keep_their_history(env):
    srv, client, store, rec = env
    store.mark_playlist_imported("pl-3", "Sunday Listening", "sunday.csv")
    store.mark_imported("pl-3", ["s2"])
    queued = store.add_external_wanted("Sade", "Cherish the Day", playlist_id="pl-3", position=1, tier="medium")
    done = store.add_external_wanted("Sade", "Smooth Operator", playlist_id="pl-3", position=2)
    store.set_external_status(done, "ok")
    store.commit()
    vanish(srv, "pl-3")
    rep = rec.run()
    assert not store.is_playlist_imported("pl-3") and store.imported("pl-3") == set()
    q = store.external(queued)
    assert (q["status"], q["reason"], q["playlist_id"], q["position"], q["tier"]) == (
        "removed", "playlist deleted", "pl-3", 1, "medium")
    assert store.external(done)["status"] == "ok"
    assert rep.playlists_gone == ["Sunday Listening: playlist no longer exists in Navidrome; 0 rows dropped"]
    [ev] = gone_events(store)
    assert ev["playlist_id"] == "pl-3"


def test_an_in_flight_wanted_row_waits_with_its_playlist(env):
    # Not the plan's "left alone, import rows go": while a download for the playlist is under way its import rows
    # stay, so a later reconcile still knows the id and retires the row if the download fails.
    srv, client, store, rec = env
    store.mark_playlist_imported("pl-3", "Sunday Listening", "sunday.csv")
    busy = store.add_external_wanted("Sade", "Cherish the Day", playlist_id="pl-3", position=1)
    store.set_external_status(busy, "sourcing", "downloading")
    store.commit()
    vanish(srv, "pl-3")
    rep = rec.run()
    assert store.external(busy)["status"] == "sourcing" and store.is_playlist_imported("pl-3")
    assert rep.playlists_gone == ["Sunday Listening: playlist no longer exists in Navidrome; 0 rows dropped, "
                                  "1 in flight kept"]
    store.set_external_status(busy, "failed", "no candidates")
    store.commit()
    rec.run()
    assert store.external(busy)["status"] == "removed" and not store.is_playlist_imported("pl-3")


def test_the_reverse_log_puts_every_row_back(tmp_path):
    with FakeSubsonicServer() as srv:
        client = SubsonicClient(srv.url, "demo", "demo")
        store = CrateStore(tmp_path / "crates.db")
        rec = Reconciler(client, store, owner="app")
        rec.set_crate("pl-2", True)
        store.set_track_status("pl-2", "s5", "removed", "dropped by hand")
        store.mark_playlist_imported("pl-2", "Chicago 86", "chicago.csv")
        store.mark_imported("pl-2", ["s3", "s4"])
        store.add_external_wanted("Ten City", "Devotion", playlist_id="pl-2", position=3)
        store.commit()
        before = snapshot(store, "pl-2")
        vanish(srv, "pl-2")
        rep = rec.run()
        assert rep.tracks_removed == 2                     # s5 was removed already: counted when it was
        assert store.get("pl-2") is None
        [line] = (tmp_path / "playlists-gone.jsonl").read_text().splitlines()
        rec_ = json.loads(line)
        assert rec_["playlist_id"] == "pl-2" and rec_["name"] == "Chicago 86" and rec_["ts"] > 0
        f = rec_["forgotten"]
        db = store.db
        for table, rows in (("crate_tracks", f["dropped"]), ("crates", [f["crate"]]),
                            ("imported_playlists", [f["imported_playlist"]]), ("external_wanted", f["wanted_removed"])):
            for r in rows:
                db.execute(f"INSERT OR REPLACE INTO {table}({','.join(r)}) VALUES({','.join('?' * len(r))})",
                           list(r.values()))
        db.executemany("INSERT INTO imported_entries(playlist_id, song_id) VALUES(?,?)",
                       [("pl-2", s) for s in f["imported_entries"]])
        db.commit()
        assert snapshot(store, "pl-2") == before


def test_in_memory_store_writes_no_reverse_log(env, tmp_path, monkeypatch):
    srv, client, store, rec = env
    monkeypatch.chdir(tmp_path)
    rec.set_crate("pl-2", True)
    vanish(srv, "pl-2")
    rec.run()
    assert list(tmp_path.iterdir()) == []


def test_forget_playlist_touches_only_its_playlist():
    s = CrateStore()
    for pid in ("pl-1", "pl-2"):
        s.set_enabled(pid, pid.upper(), True)
        s.upsert_track(pid, "s1", 0, {"title": "t"}, "ok", None)
        s.mark_imported(pid, ["s1"])
        s.note_problems(pid, "attrs_problem", [f"{pid}: unknown tier"])
    s.commit()
    events = len(s.events(1000))
    out = s.forget_playlist("pl-1")
    s.commit()
    assert [t["song_id"] for t in out["dropped"]] == ["s1"] and out["live"] == 1 and out["kept"] == 0
    assert out["problems"] == '["pl-1: unknown tier"]'
    assert out["crate"]["playlist_id"] == "pl-1" and out["imported_entries"] == ["s1"]
    assert s.get("pl-1") is None and s.get("pl-2") is not None
    assert s.tracks("pl-2") and s.imported("pl-2") == {"s1"}
    keys = [r[0] for r in s.db.execute("SELECT key FROM settings")]
    assert keys == ["problems:attrs_problem:pl-2"]
    assert len(s.events(1000)) == events                  # history stays; forget_playlist logs no event itself
    assert s.forget_playlist("pl-1") == {"dropped": [], "live": 0, "kept": 0, "crate": None, "imported_entries": [],
                                         "imported_playlist": None, "wanted_removed": [], "problems": None,
                                         "import_order": [], "placements": []}


def test_no_reverse_log_no_delete(tmp_path):
    with FakeSubsonicServer() as srv:
        client = SubsonicClient(srv.url, "demo", "demo")
        store = CrateStore(tmp_path / "crates.db")
        rec = Reconciler(client, store, owner="app")
        rec.set_crate("pl-2", True)
        before = snapshot(store, "pl-2")
        (tmp_path / "playlists-gone.jsonl").mkdir()                # open() for append fails
        vanish(srv, "pl-2")
        rep = rec.run()
        assert snapshot(store, "pl-2") == before and gone_events(store) == [] and rep.playlists_gone == []
        assert len(rep.errors) == 1 and rep.errors[0].startswith(
            "Chicago 86: playlist no longer exists in Navidrome; kept: reverse log not written")
        assert snapshot(CrateStore(tmp_path / "crates.db"), "pl-2") == before     # nothing left uncommitted either


def test_untiered_rows_do_not_count_toward_the_limit(env):
    # A playlist switched off long ago keeps its untiered `crates` row; four of them gone must not stop every drop.
    srv, client, store, rec = env
    rec.set_crate("pl-2", True)
    for n in range(4):
        store.set_enabled(f"pl-x{n}", f"Old {n}", False)
    vanish(srv, "pl-2")
    rep = rec.run()
    assert rep.errors == [] and [c.playlist_id for c in store.all()] == []
    assert len(rep.playlists_gone) == 5 and len(gone_events(store)) == 5
    assert [e["detail"] for e in gone_events(store) if e["playlist_id"] == "pl-2"] == [
        "Chicago 86: playlist no longer exists in Navidrome; 3 rows dropped; was crate=on tier=none"]
    assert [e["detail"] for e in gone_events(store) if e["playlist_id"] == "pl-x0"] == [
        "Old 0: playlist no longer exists in Navidrome; 0 rows dropped"]


def test_questions_and_filed_failures_of_wanted_rows_do_not_wait(env):
    srv, client, store, rec = env
    store.mark_playlist_imported("pl-3", "Sunday Listening", "sunday.csv")
    asked = store.add_external_wanted("Sade", "Cherish the Day", playlist_id="pl-3", position=1)
    filed = store.add_external_wanted("Sade", "Smooth Operator", playlist_id="pl-3", position=2)
    store.set_external_status(asked, "review", "kept beside Sade/x.mp3")
    store.set_external_status(filed, "failed", "Navidrome never indexed Sade/y.flac; file is in the library")
    store.commit()
    vanish(srv, "pl-3")
    rep = rec.run()
    assert not store.is_playlist_imported("pl-3")
    assert [store.external(i)["status"] for i in (asked, filed)] == ["removed", "removed"]
    assert rep.playlists_gone == ["Sunday Listening: playlist no longer exists in Navidrome; 0 rows dropped"]


def test_any_other_failure_rolls_the_forget_back(tmp_path, monkeypatch):
    with FakeSubsonicServer() as srv:
        client = SubsonicClient(srv.url, "demo", "demo")
        store = CrateStore(tmp_path / "crates.db")
        rec = Reconciler(client, store, owner="app")
        rec.set_crate("pl-2", True)
        before = snapshot(store, "pl-2")

        def boom(*a):
            raise ValueError("not JSON")
        monkeypatch.setattr(rec, "_log_forgotten", boom)
        vanish(srv, "pl-2")
        with pytest.raises(ValueError):
            rec.run()
        store.commit()                                            # a later commit by anyone commits nothing of it
        assert snapshot(CrateStore(tmp_path / "crates.db"), "pl-2") == before


def test_after_a_wait_the_lines_replayed_newest_first_restore_the_crate(tmp_path):
    with FakeSubsonicServer() as srv:
        client = SubsonicClient(srv.url, "demo", "demo")
        store = CrateStore(tmp_path / "crates.db")
        rec = Reconciler(client, store, owner="app")
        rec.set_crate("pl-2", True)
        before = store.get("pl-2")
        store.set_track_status("pl-2", "s3", "sourcing", "downloading")
        vanish(srv, "pl-2")
        rec.run()
        store.set_track_status("pl-2", "s3", "failed", "no file")
        rec.run()
        assert store.get("pl-2") is None
        lines = [json.loads(x) for x in (tmp_path / "playlists-gone.jsonl").read_text().splitlines()]
        assert len(lines) == 2
        for line in reversed(lines):
            r = line["forgotten"]["crate"]
            store.db.execute(f"INSERT OR REPLACE INTO crates({','.join(r)}) VALUES({','.join('?' * len(r))})",
                             list(r.values()))
        assert store.get("pl-2") == before
        details = [e["detail"] for e in reversed(gone_events(store))]           # oldest first
        assert details[0].endswith("; was crate=on tier=none") and "; was" not in details[1]


def test_a_wanted_row_with_an_approval_in_progress_waits(env):
    srv, client, store, rec = env
    store.mark_playlist_imported("pl-3", "Sunday Listening", "sunday.csv")
    other = store.add_external_wanted("Sade", "Smooth Operator", playlist_id="pl-3", position=2)
    approved = store.add_external_wanted("Sade", "Cherish the Day", playlist_id="pl-3", position=1)
    store.approve(approved, "michael", None, "crate")
    store.approve(other, "michael", None, "crate")
    store.mark_approval_used(store.approval(other)["id"], "failed: no candidates")    # spent: does not wait
    store.commit()
    vanish(srv, "pl-3")
    rep = rec.run()
    assert store.external(approved)["status"] == "needs_source" and store.external(other)["status"] == "removed"
    assert store.is_playlist_imported("pl-3")
    assert rep.playlists_gone == ["Sunday Listening: playlist no longer exists in Navidrome; 0 rows dropped, "
                                  "1 in flight kept"]


def test_a_still_listed_playlists_hidden_rows_are_untouched(env):
    srv, client, store, rec = env
    rec.set_crate("pl-1", True)
    rec.set_crate("pl-2", True)
    gone = srv.state.playlists["pl-1"]["songs"].pop()          # a song taken out of pl-1: its row becomes `removed`
    srv.state.sync()
    rec.run()
    rows = lambda: [{k: v for k, v in t.items() if k != "updated_at"} for t in store.tracks("pl-1", include_removed=True)]
    before = rows()
    assert [t["status"] for t in before if t["song_id"] == gone] == ["removed"]
    vanish(srv, "pl-2")
    rep = rec.run()
    assert rep.playlists_gone and store.get("pl-2") is None
    assert rows() == before and store.get("pl-1").enabled


def test_a_row_finishing_while_forget_reads_is_logged_or_kept(tmp_path):
    """Fetch and the web write from other processes: a row that leaves `sourcing` between forget_playlist's read and
    its delete must not be deleted unlogged. The forget holds the write lock from its first read."""
    import sqlite3
    s = CrateStore(tmp_path / "crates.db")
    s.set_enabled("pl-1", "PL-1", True)
    s.upsert_track("pl-1", "s1", 0, {"title": "a"}, "ok", None)
    s.upsert_track("pl-1", "s2", 1, {"title": "b"}, "sourcing", None)
    s.commit()
    other = sqlite3.connect(tmp_path / "crates.db", timeout=0)
    raced = []

    def finish_s2_meanwhile(sql):
        if not raced and sql.lstrip().startswith("SELECT * FROM crate_tracks"):
            try:
                other.execute("UPDATE crate_tracks SET status='ok' WHERE song_id='s2'")
                other.commit()
                raced.append("committed")
            except sqlite3.OperationalError:            # locked: the forget holds the write lock
                raced.append("locked")
    s.db.set_trace_callback(finish_s2_meanwhile)
    out = s.forget_playlist("pl-1")
    s.db.set_trace_callback(None)
    s.commit()
    left = [r[0] for r in s.db.execute("SELECT song_id FROM crate_tracks WHERE playlist_id='pl-1'")]
    assert raced == ["locked"]
    assert [t["song_id"] for t in out["dropped"]] == ["s1"] and left == ["s2"] and out["kept"] == 1


def test_forget_playlist_drops_its_import_order_and_placements_and_keeps_a_shared_wanted_row():
    # N4: import_order makes wanted row × playlist many-to-many; a row another playlist's order names stays wanted.
    s = CrateStore()
    for pid in ("pl-1", "pl-2"):
        s.mark_playlist_imported(pid, pid.upper(), "spotify")
    shared = s.add_external_wanted("Chic", "Good Times", playlist_id="pl-1", position=2)    # last slot: pl-1
    own = s.add_external_wanted("MFSB", "Love Is the Message", playlist_id="pl-1", position=3)
    s.record_import_order("pl-1", [(1, "s1", None), (2, None, shared), (3, None, own)])
    s.record_import_order("pl-2", [(1, None, shared)])
    s.note_placement(shared, "pl-1", "open", "refused")
    s.note_placement(shared, "pl-2", "open", "refused")
    s.commit()
    out = s.forget_playlist("pl-1")
    s.commit()
    assert [(r["position"], r["wanted_id"]) for r in out["import_order"]] == [(1, None), (2, shared), (3, own)]
    assert [(r["wanted_id"], r["state"]) for r in out["placements"]] == [(shared, "open")]
    assert s.import_order("pl-1") == [] and s.placement(shared, "pl-1") is None
    assert s.import_order("pl-2") and s.placement(shared, "pl-2")["state"] == "open"
    assert s.external(shared)["status"] == "needs_source"                  # pl-2 still wants it
    assert s.external(own)["status"] == "removed" and [f"ext-{r['id']}" for r in out["wanted_removed"]] == [own]
