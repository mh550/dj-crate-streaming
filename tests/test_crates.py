import pytest

from crates.reconcile import Reconciler, judge, with_crate_tag, has_crate_tag, has_name_marker, is_marked
from crates.store import CrateStore
from sourcing.policy import QualityPolicy
from subsonic.client import Song, SubsonicClient
from subsonic.fake_server import FakeSubsonicServer


@pytest.fixture
def env():
    with FakeSubsonicServer() as srv:
        client = SubsonicClient(srv.url, "demo", "demo")
        store = CrateStore()
        yield srv, client, store, Reconciler(client, store)


def song(**kw):
    base = dict(id="x", title="t", artist="a", album=None, duration=300, bit_rate=None, suffix=None, content_type=None, size=None, path=None)
    base.update(kw)
    return Song(**base)


def test_judge_policy():
    assert judge(song(suffix="flac", bit_rate=900, sample_rate=44100, bit_depth=16))[0] == "ok"
    assert judge(song(suffix="mp3", bit_rate=320))[0] == "ok"                 # lossy at/above the floor is kept (2026-10-17)
    assert judge(song(suffix="mp3", bit_rate=128))[0] == "needs_source"
    assert judge(song(suffix="wma", bit_rate=320))[0] == "needs_source"
    assert judge(song(suffix="flac", bit_rate=200))[0] == "needs_source"      # fake lossless
    assert "transcode" in judge(song(suffix="flac", bit_rate=200))[1]
    lossy_ok = QualityPolicy(preferred=["mp3", "flac"])
    assert judge(song(suffix="mp3", bit_rate=320), lossy_ok)[0] == "ok"


def test_crate_tag_helpers():
    assert has_crate_tag("warmup #CRATE") and not has_crate_tag("crate digging")
    assert with_crate_tag("", True) == "#crate"
    assert with_crate_tag("warmup #crate", False) == "warmup"
    assert with_crate_tag("warmup", True) == "warmup #crate"


def test_reconcile_picks_up_comment_tag(env):
    srv, client, store, rec = env
    rep = rec.run()
    assert rep.crates_enabled == 1 and rep.toggled_from_comment == ["Chicago 86"]
    assert store.summary("pl-2") == {"ok": 1, "needs_source": 2, "sourcing": 0, "verify": 0, "failed": 0, "total": 3}
    # removing the tag in Navidrome turns a comment-enabled crate off again
    client.update_playlist("pl-2", comment="warmup")
    rec.run()
    assert not store.get("pl-2").enabled


def test_toggle_mirrors_tag_and_tracks_status(env):
    srv, client, store, rec = env
    v = rec.set_crate("pl-1", True)
    assert v["crate"] and v["summary"]["ok"] == 2 and v["summary"]["needs_source"] == 1
    assert has_crate_tag(client.playlist("pl-1").comment)
    # an in-app toggle is not undone by the reconciler even though we mirrored the tag
    rec.run()
    assert store.get("pl-1").enabled
    rec.set_crate("pl-1", False)
    assert not has_crate_tag(client.playlist("pl-1").comment)
    assert store.tracks("pl-1") == []      # all marked removed


def test_playlist_edits_flow_through(env):
    srv, client, store, rec = env
    rec.set_crate("pl-1", True)
    client.update_playlist("pl-1", add_song_ids=["s4"], remove_indexes=[0])   # drop Good Times, add 128k mp3
    rep = rec.run()
    assert rep.tracks_removed == 1
    ids = {t["song_id"]: t["status"] for t in store.tracks("pl-1")}
    assert "s1" not in ids and ids["s4"] == "needs_source"


def test_in_flight_sourcing_is_not_clobbered(env):
    srv, client, store, rec = env
    rec.set_crate("pl-2", True)
    store.set_track_status("pl-2", "s4", "sourcing", "enqueued from vinylhead77")
    rec.run()
    assert store.track_status_map("pl-2")["s4"]["status"] == "sourcing"


def test_failed_never_indexed_row_is_not_reset_for_a_second_download(env):
    """M6: a failed never-indexed row is re-checked, never re-downloaded, so reconcile keeps it as it is."""
    from crates.store import never_indexed
    srv, client, store, rec = env
    rec.set_crate("pl-2", True)
    reason = never_indexed("Artist/Album/04 t.flac")
    store.set_track_status("pl-2", "s4", "failed", reason)
    rec.run()
    row = store.track_status_map("pl-2")["s4"]
    assert (row["status"], row["reason"]) == ("failed", reason)


def test_plain_failed_row_still_becomes_needs_source(env):
    srv, client, store, rec = env
    rec.set_crate("pl-2", True)
    store.set_track_status("pl-2", "s4", "failed", "no acceptable result")
    rec.run()
    assert store.track_status_map("pl-2")["s4"]["status"] == "needs_source"


def test_wanted_is_deduped_across_crates(env):
    srv, client, store, rec = env
    rec.run(); rec.set_crate("pl-1", True)
    w = store.wanted()
    titles = [t["title"] for t in w]
    assert titles.count("Move Your Body") == 1
    assert sorted(next(t for t in w if t["title"] == "Move Your Body")["crates"]) == ["Chicago 86", "Disco Edits"]
    wants = rec.wanted()
    assert {x.title for x in wants} == {"Move Your Body", "Can You Feel It"} and all(x.duration_s for x in wants)


def test_store_persists(tmp_path):
    p = tmp_path / "c.db"
    CrateStore(p).set_enabled("pl-9", "Nine", True)
    assert CrateStore(p).get("pl-9").enabled


def test_name_marker_helpers():
    assert has_name_marker("Disco Edits [crate]") and has_name_marker("🎛 Disco Edits") and has_name_marker("Late Night [CRATE]")
    assert not has_name_marker("crate digging") and not has_name_marker("")
    assert is_marked("x", "#crate") and is_marked("x [crate]", None) and not is_marked("x", "")


def test_rename_from_any_client_toggles_crate(env):
    srv, client, store, rec = env
    client.update_playlist("pl-3", name="Sunday Listening [crate]")
    rep = rec.run()
    assert "Sunday Listening [crate]" in rep.toggled_from_comment
    assert store.get("pl-3").enabled and store.get("pl-3").source == "comment"
    client.update_playlist("pl-3", name="Sunday Listening")
    rec.run()
    assert not store.get("pl-3").enabled


def test_external_wanted_rows_join_the_queue():
    store = CrateStore()
    ext = store.add_external_wanted("Chic", "Good Times", album="Risqué", duration_s=501, year=1979, source="spotify:abc")
    assert ext.startswith("ext-")
    w = store.wanted()
    assert [x["song_id"] for x in w] == [ext]
    assert w[0]["external"] is True and w[0]["crates"] == [] and w[0]["duration"] == 501
    store.set_external_status(ext, "sourcing")
    assert store.external(ext)["status"] == "sourcing"
    assert [x["status"] for x in store.wanted()] == ["sourcing"]   # in flight: listed (no Preview/Approve in the UI)
    store.set_external_status(ext, "failed", "download timed out")
    assert store.wanted()[0]["reason"] == "download timed out"


def test_external_status_names_are_validated():
    store = CrateStore()
    ext = store.add_external_wanted("A", "B")
    import pytest
    with pytest.raises(AssertionError):
        store.set_external_status(ext, "verifying")


def test_external_wanted_remembers_playlist_and_position(tmp_path):
    store = CrateStore(tmp_path / "c.db")
    ext = store.add_external_wanted("Chic", "Good Times", duration_s=501, source="report", playlist_id="pl-9", position=3)
    row = store.external(ext)
    assert row["playlist_id"] == "pl-9" and row["position"] == 3
    # same artist/title again from another playlist position → same row, position updated, still one row
    assert store.add_external_wanted("chic", "good times!", playlist_id="pl-9", position=7) == ext
    assert store.external_count() == 1 and store.external(ext)["position"] == 7
    # re-adding without a playlist leaves the remembered one alone
    store.add_external_wanted("Chic", "Good Times")
    assert store.external(ext)["playlist_id"] == "pl-9"
    assert [r["song_id"] for r in store.external_for_playlist("pl-9")] == [ext]


def test_store_migrates_old_external_wanted_table(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""CREATE TABLE external_wanted (id INTEGER PRIMARY KEY, artist TEXT NOT NULL, title TEXT NOT NULL,
        album TEXT, year INTEGER, duration INTEGER, source TEXT, status TEXT NOT NULL DEFAULT 'needs_source', reason TEXT,
        created_at REAL NOT NULL, updated_at REAL NOT NULL);
        INSERT INTO external_wanted(artist,title,created_at,updated_at) VALUES('A','B',0,0);""")
    con.commit(); con.close()
    store = CrateStore(db)                      # must add the two columns without losing the row
    assert store.external("ext-1")["playlist_id"] is None and store.external_count() == 1


def test_publish_makes_playlists_public(env, monkeypatch, tmp_path, capsys):
    srv, _, _, _ = env
    monkeypatch.setenv("SUBSONIC_URL", srv.url); monkeypatch.setenv("SUBSONIC_USER", "demo"); monkeypatch.setenv("SUBSONIC_PASS", "demo")
    monkeypatch.setenv("CRATES_DB", str(tmp_path / "c.db"))
    from crates.cli import main
    assert main(["publish", "Disco Edits"]) == 0
    st = srv.state.playlists
    assert st["pl-1"]["public"] is True and st["pl-2"]["public"] is False
    assert main(["publish"]) == 0 and all(p["public"] for p in st.values())
    assert "public already" in capsys.readouterr().out


def test_find_external_compares_lead_artists():
    # Task 4 review: an old "Chic feat. Nile Rodgers" row and a new "Chic" ask are one song, both ways round.
    s = CrateStore()
    old = s.add_external_wanted("Chic feat. Nile Rodgers", "Good Times")
    assert s.find_external("Chic", "Good Times")["song_id"] == old
    assert s.add_external_wanted("Chic", "Good Times") == old
    s2 = CrateStore()
    new = s2.add_external_wanted("Chic", "Le Freak")
    assert s2.find_external("Chic feat. Nile Rodgers", "Le Freak")["song_id"] == new
    assert s2.find_external("Sister Sledge", "Le Freak") is None


def test_imported_playlists_table_survives_reopening(tmp_path):
    # N2 (D33): "made by import-playlist" is a crates.db row, not `#imported` in the playlist comment.
    p = tmp_path / "c.db"
    s = CrateStore(p)
    assert s.imported_playlists() == [] and not s.is_playlist_imported("pl-1")
    assert s.mark_playlist_imported("pl-1", "Tea tent", "spotify:abc") is True
    s.commit()
    s2 = CrateStore(p)
    assert s2.is_playlist_imported("pl-1") and not s2.is_playlist_imported("pl-2")
    [row] = s2.imported_playlists()
    assert (row["playlist_id"], row["name"], row["source"]) == ("pl-1", "Tea tent", "spotify:abc")
    assert row["imported_at"] > 0


def test_mark_playlist_imported_keeps_the_first_source_and_refreshes_the_name():
    s = CrateStore()
    assert s.mark_playlist_imported("pl-1", "Tea", "a.csv") is True
    first = s.imported_playlists()[0]["imported_at"]
    assert s.mark_playlist_imported("pl-1", "Tea tent", "b.csv") is False
    s.mark_playlist_imported("pl-0", "Alpha", "migrated", detail="migrated from comment '#imported'")
    rows = s.imported_playlists()
    assert [(r["playlist_id"], r["name"], r["source"]) for r in rows] == [
        ("pl-0", "Alpha", "migrated"), ("pl-1", "Tea tent", "a.csv")]
    assert rows[1]["imported_at"] == first
    ev = [(e["playlist_id"], e["detail"]) for e in s.events() if e["kind"] == "imported"]
    assert sorted(ev) == [("pl-0", "migrated from comment '#imported'"), ("pl-1", "made by import-playlist: a.csv")]


# N3 (D43): a playlist deleted in Navidrome loses its crates.db rows at the next reconcile. These two scenarios run
# under both owners: here (owner comment) and in test_app_owner.py (owner app).
def vanish(srv, pid):
    del srv.state.playlists[pid]
    srv.state.sync()


def gone_events(store):
    return [e for e in store.events(1000) if e["kind"] == "playlist_gone"]


def check_a_vanished_playlist_is_forgotten(env):
    srv, client, store, rec = env
    rec.set_crate("pl-2", True)
    store.mark_playlist_imported("pl-2", "Chicago 86", "test.csv")
    store.mark_imported("pl-2", ["s3", "s4"])
    store.commit()
    rec.run()
    assert len(store.tracks("pl-2")) == 3
    vanish(srv, "pl-2")
    rep = rec.run()
    assert store.get("pl-2") is None
    assert store.tracks("pl-2", include_removed=True) == []
    assert store.imported("pl-2") == set() and not store.is_playlist_imported("pl-2")
    assert rep.errors == [] and rep.tracks_removed == 3
    assert rep.playlists_gone == ["Chicago 86: playlist no longer exists in Navidrome; 3 rows dropped"]
    [ev] = gone_events(store)
    assert ev["playlist_id"] == "pl-2" and "Chicago 86" in ev["detail"] and "3 rows dropped" in ev["detail"]
    rep = rec.run()
    assert rep.playlists_gone == [] and rep.errors == [] and len(gone_events(store)) == 1


def check_in_flight_rows_wait(env):
    srv, client, store, rec = env
    rec.set_crate("pl-2", True)
    rec.run()
    store.set_track_status("pl-2", "s3", "sourcing", "downloading")
    vanish(srv, "pl-2")
    rep = rec.run()
    assert [t["song_id"] for t in store.tracks("pl-2", include_removed=True)] == ["s3"]
    c = store.get("pl-2")
    assert c is not None and not c.enabled and c.tier is None
    assert "pl-2" not in store.playlists_holding(["s3"])            # fetch takes the "request withdrawn" path
    assert rep.errors == [] and rep.tracks_removed == 2
    [ev] = gone_events(store)
    assert "2 rows dropped, 1 in flight kept" in ev["detail"]
    rep = rec.run()                                                  # still waiting: listed, nothing logged
    assert rep.playlists_gone == ["Chicago 86: playlist no longer exists in Navidrome; 0 rows dropped, 1 in flight kept"]
    assert len(gone_events(store)) == 1 and rep.tracks_removed == 0
    store.set_track_status("pl-2", "s3", "failed", "no file")
    rep = rec.run()
    assert store.get("pl-2") is None and store.tracks("pl-2", include_removed=True) == []
    assert rep.playlists_gone == ["Chicago 86: playlist no longer exists in Navidrome; 1 row dropped"]
    assert len(gone_events(store)) == 2


def test_a_vanished_playlist_is_forgotten(env):
    check_a_vanished_playlist_is_forgotten(env)


def test_a_vanished_playlists_in_flight_rows_wait(env):
    check_in_flight_rows_wait(env)


def test_import_order_is_replaced_per_playlist_and_found_by_wanted_id(tmp_path):
    # N4-02 (M9 §1): the last real import's Spotify order, one row per position; a wanted id may sit in several.
    p = tmp_path / "c.db"
    s = CrateStore(p)
    assert s.import_order("pl-1") == [] and s.import_order_for("ext-1") == []
    s.record_import_order("pl-1", [(2, None, "ext-1"), (1, "s1", None), (3, "s2", None)])
    s.record_import_order("pl-2", [(1, None, "ext-1")])
    s.commit()
    s = CrateStore(p)                                   # the table is in SCHEMA: it survives reopening
    assert [(r["position"], r["song_id"], r["wanted_id"]) for r in s.import_order("pl-1")] == [
        (1, "s1", None), (2, None, "ext-1"), (3, "s2", None)]
    assert [(r["playlist_id"], r["position"]) for r in s.import_order_for("ext-1")] == [("pl-1", 2), ("pl-2", 1)]
    s.record_import_order("pl-1", [(1, "s1", None), (2, "s9", None)])          # a re-run replaces the record
    assert [(r["position"], r["song_id"], r["wanted_id"]) for r in s.import_order("pl-1")] == [
        (1, "s1", None), (2, "s9", None)]
    assert [r["playlist_id"] for r in s.import_order_for("ext-1")] == ["pl-2"]  # other playlists untouched


def test_record_import_order_is_one_transaction():
    import sqlite3
    s = CrateStore()
    s.record_import_order("pl-1", [(1, "s1", None)])
    s.commit()
    with pytest.raises(sqlite3.IntegrityError):         # a bad row: the old record must survive, not half the new one
        s.record_import_order("pl-1", [(1, "s2", None), (1, "s3", None)])
    assert [r["song_id"] for r in s.import_order("pl-1")] == ["s1"]


def test_record_import_order_inside_the_callers_transaction_commits_nothing_early():
    # import_playlist calls it among its other writes and commits once at the end.
    import sqlite3
    s = CrateStore()
    s.mark_imported("pl-1", ["s1"])
    s.record_import_order("pl-1", [(1, "s1", None)])
    with pytest.raises(sqlite3.IntegrityError):
        s.record_import_order("pl-1", [(1, "s2", None), (1, "s3", None)])
    assert s.db.in_transaction and s.imported("pl-1") == {"s1"}       # still pending, the failed record undone
    assert [r["song_id"] for r in s.import_order("pl-1")] == ["s1"]
    s.db.rollback()
    assert s.imported("pl-1") == set() and s.import_order("pl-1") == []


def test_record_import_order_keeps_the_real_error_when_sqlite_already_rolled_back(monkeypatch):
    # A disk-full or I/O error rolls the whole transaction back, savepoint included: report that, not "no such savepoint".
    import sqlite3
    s = CrateStore()
    real = s.db

    class Full:
        in_transaction = property(lambda self: real.in_transaction)

        def execute(self, sql, *a):
            return real.execute(sql, *a)

        def executemany(self, sql, *a):
            real.rollback()
            raise sqlite3.OperationalError("database or disk is full")
    monkeypatch.setattr(s, "db", Full())
    with pytest.raises(sqlite3.OperationalError, match="disk is full"):
        s.record_import_order("pl-1", [(1, "s1", None)])


def _filed_ext(s, pid="pl-1", position=2, song="s9", status="ok", provisional=False):
    ext = s.add_external_wanted("MFSB", f"Track {position}", playlist_id=pid, position=position)
    s.set_external_song(ext, song, provisional)
    s.set_external_status(ext, status)
    return ext


def test_placements_table_survives_reopening_and_note_placement_counts(tmp_path):
    # N4-04: one row per (wanted, playlist); attempts counts the failures toward the limit, updated_at always moves.
    p = tmp_path / "c.db"
    s = CrateStore(p)
    assert s.placement("ext-1", "pl-1") is None
    s.note_placement("ext-1", "pl-1", "open", "refused: hidden row", song_id="s9", now=100.0)
    s.commit()
    s = CrateStore(p)
    r = s.placement("ext-1", "pl-1")
    assert (r["state"], r["attempts"], r["detail"], r["song_id"], r["updated_at"]) == (
        "open", 1, "refused: hidden row", "s9", 100.0)
    s.note_placement("ext-1", "pl-1", "open", "Navidrome down", count=False, now=200.0)
    s.note_placement("ext-1", "pl-1", "given_up", "still refused", now=300.0)
    r = s.placement("ext-1", "pl-1")
    assert (r["state"], r["attempts"], r["detail"], r["song_id"], r["updated_at"]) == (
        "given_up", 2, "still refused", "s9", 300.0)                               # the song id stays when not given
    assert s.placement("ext-1", "pl-2") is None


def test_due_placements_are_derived_from_state():
    s = CrateStore()
    ok = _filed_ext(s)                                                  # filed, in pl-1's order: due
    sourcing = _filed_ext(s, position=3, song="s7", status="sourcing")  # still being fetched
    legacy = _filed_ext(s, position=4, song="s6", provisional=True)     # play-now's copy, its upgrade pending
    nosong = s.add_external_wanted("MFSB", "Track 5", playlist_id="pl-1", position=5)
    s.set_external_status(nosong, "ok", "in library: s5")               # a re-run matched it: no library_song_id
    elsewhere = _filed_ext(s, pid="pl-2", position=1, song="s8")        # wanted row whose order is not recorded
    s.record_import_order("pl-1", [(1, "s1", None), (2, None, ok), (3, None, sourcing), (4, None, legacy),
                                   (5, None, nosong), (6, None, ok)])   # the same wanted row twice: one pair
    s.record_import_order("pl-3", [(7, None, ok)])                      # wanted by a second playlist too
    assert [(d["wanted_id"], d["playlist_id"], d["song_id"], d["position"]) for d in s.due_placements()] == [
        (ok, "pl-1", "s9", 2), (ok, "pl-3", "s9", 7)]
    assert elsewhere not in {d["wanted_id"] for d in s.due_placements()}
    s.mark_imported("pl-3", ["s9"])                                     # appended by a re-run, or removed after
    assert [d["playlist_id"] for d in s.due_placements()] == ["pl-1"]
    for state, due in (("open", True), ("writing", True), ("done", False), ("given_up", False)):
        s.note_placement(ok, "pl-1", state, None)
        assert bool(s.due_placements()) is due, state


def test_repoint_song_moves_what_crates_db_says_about_a_song_to_its_new_copy():
    # review N4-05 I2: a copy replacement or the duplicate cleanup repoints old -> new in every playlist; the import
    # order, removed-stays-removed and filed rows must follow, or placement loses neighbours / re-inserts the old copy.
    s = CrateStore()
    filed = _filed_ext(s, song="s4")                                    # filed as the old copy, not placed yet
    waiting = _filed_ext(s, position=3, song="s4", status="verify")     # still in flight: left to its own flow
    legacy = _filed_ext(s, position=4, song="s4", provisional=True)     # play-now's copy: its upgrade replaces it
    s.record_import_order("pl-1", [(1, "s4", None), (2, None, filed), (3, "s2", None)])
    s.record_import_order("pl-2", [(1, "s4", None)])
    s.mark_imported("pl-1", ["s4", "s2"])
    s.mark_imported("pl-2", ["s9"])                                     # already holds the new copy
    assert s.repoint_song("s4", "s9") == {"import_order": 2, "imported_entries": 1, "external_wanted": 1,
                                          "placements": 0}
    s.commit()
    assert [r["song_id"] for r in s.import_order("pl-1")] == ["s9", None, "s2"]
    assert [r["song_id"] for r in s.import_order("pl-2")] == ["s9"]
    assert s.imported("pl-1") == {"s4", "s9", "s2"} and s.imported("pl-2") == {"s9"}    # the old id stays too
    assert s.external(filed)["library_song_id"] == "s9"
    assert s.external(waiting)["library_song_id"] == "s4" and s.external(legacy)["library_song_id"] == "s4"
    assert s.repoint_song("s4", "s9") == {"import_order": 0, "imported_entries": 0, "external_wanted": 0,
                                          "placements": 0}


def test_repoint_song_moves_an_unfinished_placement_so_the_look_finds_the_new_song():
    # second review of N4-05 M-a: a `writing` row's look reads placements.song_id; after a repoint the playlist holds
    # the new song, so looking for the old one would say "not placed" although it is there.
    s = CrateStore()
    for state, wid in (("writing", "ext-1"), ("open", "ext-2"), ("done", "ext-3")):
        s.note_placement(wid, "pl-1", state, None, song_id="s4")
    assert s.repoint_song("s4", "s9")["placements"] == 2
    assert [s.placement(w, "pl-1")["song_id"] for w in ("ext-1", "ext-2", "ext-3")] == ["s9", "s9", "s4"]
