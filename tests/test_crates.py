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


def test_store_migrates_old_db_to_requests(tmp_path):
    # S2-01: an old db (no requests table, no request columns) gains both, additively, and keeps its row.
    import sqlite3
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""CREATE TABLE external_wanted (id INTEGER PRIMARY KEY, artist TEXT NOT NULL, title TEXT NOT NULL,
        album TEXT, year INTEGER, duration INTEGER, source TEXT, status TEXT NOT NULL DEFAULT 'needs_source', reason TEXT,
        created_at REAL NOT NULL, updated_at REAL NOT NULL);
        INSERT INTO external_wanted(artist,title,created_at,updated_at) VALUES('A','B',0,0);""")
    con.commit(); con.close()
    store = CrateStore(db)
    cols = {r[1]: r[2] for r in store.db.execute("PRAGMA table_info(external_wanted)")}
    assert (cols["request_id"], cols["track_no"], cols["mb_recording_id"]) == ("INTEGER", "INTEGER", "TEXT")
    req = {r[1] for r in store.db.execute("PRAGMA table_info(requests)")}
    assert req == {"id", "kind", "source", "artist", "album", "year", "mb_release_id", "created_at"}
    assert store.external("ext-1")["request_id"] is None and store.external_count() == 1
    CrateStore(db)                              # a second open adds nothing and fails nothing


AL_GREEN = ("Al Green", "I'm Still in Love With You")
ALBUM_URL = "https://open.spotify.com/album/1PTmGlxdkjqqh3nyRmdM8i"


def _album(s, titles=("I'm Still in Love With You", "I'm Glad You're Mine", "Love and Happiness")):
    rid = s.add_request(kind="album", source=ALBUM_URL, artist=AL_GREEN[0], album=AL_GREEN[1], year=None)
    exts = [s.add_external_wanted(AL_GREEN[0], t, album=AL_GREEN[1], source=ALBUM_URL, request_id=rid, track_no=n)
            for n, t in enumerate(titles, 1)]
    return rid, exts


def test_request_round_trip():
    s = CrateStore()
    rid, (e1, e2, e3) = _album(s, titles=("Love and Happiness", "I'm Glad You're Mine", "I'm Still in Love With You"))
    assert isinstance(rid, int)
    assert (s.find_wanted(e1)["request_id"], s.find_wanted(e1)["track_no"]) == (rid, 1)
    s.set_recording_id(e1, "cdac1a50-8ba6-4edd-8137-618928580d38")
    s.set_release_id(rid, "3c9a52ee-0000-0000-0000-000000000000")
    assert s.find_wanted(e1)["mb_recording_id"] == "cdac1a50-8ba6-4edd-8137-618928580d38"
    r = s.request(rid)
    assert (r["id"], r["kind"], r["source"], r["artist"], r["album"], r["year"]) == (rid, "album", ALBUM_URL, *AL_GREEN, None)
    assert r["mb_release_id"] == "3c9a52ee-0000-0000-0000-000000000000" and r["created_at"] > 0
    assert [w["song_id"] for w in r["rows"]] == [e1, e2, e3] and [w["track_no"] for w in r["rows"]] == [1, 2, 3]
    assert r["status"] == "open" and "approval" in r["rows"][0]          # rows are wanted-shaped (wanted_row)
    assert s.request(rid + 1) is None


def test_request_rows_ordered_by_track_no_not_insert_order():
    s = CrateStore()
    rid = s.add_request(kind="album", source="search", artist=AL_GREEN[0], album=AL_GREEN[1], year=1972)
    late = s.add_external_wanted("Al Green", "Look What You Done for Me", request_id=rid, track_no=3)
    early = s.add_external_wanted("Al Green", "Simply Beautiful", request_id=rid, track_no=1)
    s.add_external_wanted("Chic", "Le Freak")                             # not this request's
    assert [w["song_id"] for w in s.request(rid)["rows"]] == [early, late]
    assert s.request(rid)["year"] == 1972


def test_requests_newest_first_and_kind_checked():
    s = CrateStore()
    a = s.add_request(kind="album", source=ALBUM_URL, artist="Al Green", album="Call Me", year=1973)
    t = s.add_request(kind="track", source="search", artist="Chic", album=None, year=None)
    p = s.add_request(kind="playlist", source="https://open.spotify.com/playlist/x", artist=None, album=None, year=None)
    assert [r["id"] for r in s.requests()] == [p, t, a]
    assert all("status" in r and "rows" in r for r in s.requests())
    with pytest.raises(ValueError):
        s.add_request(kind="podcast", source="search", artist=None, album=None, year=None)


def test_find_request_by_source():
    s = CrateStore()
    assert s.find_request(ALBUM_URL) is None
    a = s.add_request(kind="album", source=ALBUM_URL, artist="Al Green", album="Call Me", year=1973)
    s.add_request(kind="track", source="search", artist="Chic", album=None, year=None)
    assert s.find_request(ALBUM_URL) == a and s.find_request(ALBUM_URL + "x") is None


def test_rerun_of_a_request_adds_no_row_and_keeps_its_request():
    s = CrateStore()
    rid, (e1, _, _) = _album(s)
    other = s.add_request(kind="playlist", source="search", artist=None, album=None, year=None)
    assert s.add_external_wanted("Al Green", "I'm Still in Love With You", request_id=rid, track_no=1) == e1
    assert s.add_external_wanted("Al Green", "I'm Still in Love With You", request_id=other, track_no=7) == e1
    assert (s.external(e1)["request_id"], s.external(e1)["track_no"]) == (rid, 1)    # the first request keeps it
    assert len(s.request(rid)["rows"]) == 3 and s.request(other)["rows"] == []


def test_an_old_row_joins_a_request_that_asks_for_it():
    s = CrateStore()
    old = s.add_external_wanted("Al Green", "Love and Happiness")          # seeded before requests existed
    rid, exts = _album(s)
    assert old in exts and s.external(old)["request_id"] == rid and s.external(old)["track_no"] == 3


def test_request_status_is_not_stored():
    s = CrateStore()
    assert "status" not in {r[1] for r in s.db.execute("PRAGMA table_info(requests)")}


def _row(status, approval=None):
    return {"status": status, "approval": approval}


WAITING = {"used_at": None, "result": None}
STARTED = {"used_at": 1.0, "result": "started"}
SPENT = {"used_at": 1.0, "result": "failed: no source"}


@pytest.mark.parametrize("rows,want", [
    ([_row("ok"), _row("ok")], "done"),
    ([_row("ok"), _row("ok"), _row("removed")], "done"),                 # a superseded row is not the request's any more
    ([_row("failed", SPENT), _row("failed", SPENT)], "failed"),
    ([_row("failed", SPENT), _row("removed")], "failed"),
    ([_row("ok"), _row("failed", SPENT)], "partly"),
    ([_row("ok"), _row("needs_source")], "partly"),
    ([_row("ok"), _row("sourcing", STARTED)], "partly"),
    ([_row("needs_source", WAITING), _row("needs_source")], "approved"),
    ([_row("sourcing", STARTED), _row("failed", SPENT)], "approved"),
    ([_row("verify", SPENT), _row("needs_source")], "approved"),          # filed, waiting for Navidrome
    ([_row("needs_source"), _row("failed", SPENT)], "open"),
    ([_row("needs_source", SPENT), _row("review")], "open"),              # a spent approval approves nothing now
    ([_row("failed", WAITING), _row("failed", SPENT)], "approved"),       # approved again after failing (review)
    ([{"status": "failed", "approval": SPENT,                            # filed, never indexed: in the library
       "reason": "Navidrome never indexed Al Green/Singles/x.flac; file is in the library"}], "approved"),
    ([], "open"),
])
def test_request_status_first_rule_that_applies(rows, want):
    from crates.store import REQUEST_STATUSES, request_status
    assert request_status(rows) == want and want in REQUEST_STATUSES


def test_request_status_follows_its_rows():
    s = CrateStore()
    rid, (e1, e2, e3) = _album(s)
    assert s.request(rid)["status"] == "open"
    s.approve(e1, "michael", None, "crate")
    assert s.request(rid)["status"] == "approved"
    s.set_external_status(e1, "ok", None)
    assert s.request(rid)["status"] == "partly"
    s.set_external_status(e2, "ok", None); s.set_external_status(e3, "ok", None)
    assert s.request(rid)["status"] == "done"


def test_request_never_takes_a_removed_row():
    # S2-01 review: find_external answers a `removed` row (superseded) to a plain seed; a request asking the same
    # song gets a fresh row instead, or the track would drop out of the request unseen.
    s = CrateStore()
    gone = s.add_external_wanted("Al Green", "Love and Happiness")
    s.set_external_status(gone, "removed", "superseded by ext-9")
    rid, exts = _album(s)
    assert gone not in exts and s.external(exts[2])["status"] == "needs_source"
    assert s.external(gone)["request_id"] is None and len(s.request(rid)["rows"]) == 3


def test_public_request_names_no_peer_and_no_absolute_path():
    from crates.store import public
    s = CrateStore()
    rid, (e1, e2, _) = _album(s)
    s.set_preview(e1, {"pick": {"username": "peer-x", "filename": "@@abc\\Al Green\\01.flac", "basename": "01.flac"}})
    s.set_external_status(e2, "verify", "filed as Al Green/Singles/x.flac but Navidrome has not picked it up yet "
                                        "(/srv/music/Al Green/Singles/x.flac)")
    out = public(s.request(rid))
    text = repr(out)
    assert "peer-x" not in text and "username" not in text and "/srv/music" not in text
    assert out["source"] == ALBUM_URL                                       # a URL is not a path
    assert out["rows"][0]["preview"]["pick"]["basename"] == "01.flac"


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


def test_repoint_song_logs_the_rows_it_changed_beside_crates_db_and_unrepoint_puts_them_back(tmp_path):
    # N5-02 review I2: the repoint is destructive (old ids overwritten); its reverse is a JSON line naming each row.
    # Rows that already named the new copy (pl-2's import order, its imported entry) are not in it, so the undo
    # leaves them alone.
    import json
    s = CrateStore(tmp_path / "crates.db")
    filed = _filed_ext(s, song="s4")
    s.record_import_order("pl-1", [(1, "s4", None), (2, None, filed)])
    s.record_import_order("pl-2", [(1, "s9", None), (2, "s4", None)])
    s.mark_imported("pl-1", ["s4"])
    s.mark_imported("pl-2", ["s4", "s9"])
    s.note_placement("ext-1", "pl-1", "open", None, song_id="s4")
    s.commit()
    s.repoint_song("s4", "s9")
    s.commit()
    lines = [json.loads(x) for x in (tmp_path / "songs-repointed.jsonl").read_text().splitlines()]
    assert len(lines) == 1 and (lines[0]["old"], lines[0]["new"]) == ("s4", "s9")
    assert lines[0]["rows"] == {"import_order": [["pl-1", 1], ["pl-2", 2]], "imported_entries": ["pl-1"],
                                "external_wanted": [int(filed.split("-")[1])], "placements": [["ext-1", "pl-1"]]}
    s.repoint_song("s4", "s9")                                          # nothing left to change: no line
    assert len((tmp_path / "songs-repointed.jsonl").read_text().splitlines()) == 1
    s.unrepoint_song(lines[0])
    s.commit()
    assert [r["song_id"] for r in s.import_order("pl-1")] == ["s4", None]
    assert [r["song_id"] for r in s.import_order("pl-2")] == ["s9", "s4"]
    assert s.imported("pl-1") == {"s4"} and s.imported("pl-2") == {"s4", "s9"}
    assert s.external(filed)["library_song_id"] == "s4" and s.placement("ext-1", "pl-1")["song_id"] == "s4"


def test_an_in_memory_store_writes_no_repoint_log():
    s = CrateStore()
    s.record_import_order("pl-1", [(1, "s4", None)])
    assert s.repoint_song("s4", "s9")["import_order"] == 1


def test_repoint_song_moves_an_unfinished_placement_so_the_look_finds_the_new_song():
    # second review of N4-05 M-a: a `writing` row's look reads placements.song_id; after a repoint the playlist holds
    # the new song, so looking for the old one would say "not placed" although it is there.
    s = CrateStore()
    for state, wid in (("writing", "ext-1"), ("open", "ext-2"), ("done", "ext-3")):
        s.note_placement(wid, "pl-1", state, None, song_id="s4")
    assert s.repoint_song("s4", "s9")["placements"] == 2
    assert [s.placement(w, "pl-1")["song_id"] for w in ("ext-1", "ext-2", "ext-3")] == ["s9", "s9", "s4"]


def _events(s, wanted_id, kind):
    return [tuple(r) for r in s.db.execute("SELECT playlist_id, detail FROM events WHERE song_id=? AND kind=?",
                                           (wanted_id, kind))]


def test_a_reask_reuses_a_failed_unfiled_row():
    # M9 §8h (R6-03): a re-import puts the failed row back to needs_source, same id, instead of queuing a second one.
    s = CrateStore()
    ext = s.add_external_wanted("Chic", "Good Times", playlist_id="pl-1", position=2, tier="medium")
    s.set_wanted_status(ext, "failed", "download timed out")
    assert s.find_external("Chic", "Good Times") is None                       # as before: failed is not live
    assert s.find_external("Chic", "Good Times", include_failed=True)["song_id"] == ext
    again = s.add_external_wanted("chic", "good times!", playlist_id="pl-3", position=5, reask="Tea tent")
    row = s.external(ext)
    assert again == ext and s.external_count() == 1
    assert (row["status"], row["reason"]) == ("needs_source", "re-asked by import of Tea tent")
    assert (row["playlist_id"], row["position"], row["tier"]) == ("pl-3", 5, "crate")    # as a new row: default_tier
    assert _events(s, ext, "reasked") == [("pl-3", "was failed: download timed out")]
    assert s.add_external_wanted("Chic", "Good Times", reask="Tea tent") == ext                # live now: no-op
    assert len(_events(s, ext, "reasked")) == 1 and s.external(ext)["position"] == 5


def test_a_reask_prefers_a_live_row_and_never_revives_a_filed_or_removed_one():
    s = CrateStore()
    failed = s.add_external_wanted("Chic", "Le Freak")
    s.set_wanted_status(failed, "failed", "download timed out")
    live = s.add_external_wanted("Chic", "Le Freak")                       # an earlier import's duplicate
    assert live != failed and s.add_external_wanted("Chic", "Le Freak", reask="Tea tent") == live
    assert s.external(failed)["status"] == "failed" and _events(s, failed, "reasked") == []
    filed = s.add_external_wanted("Chic", "Good Times")
    s.set_wanted_status(filed, "failed", "Navidrome never indexed A/B/x.flac; file is in the library")
    assert s.add_external_wanted("Chic", "Good Times", reask="Tea tent") == filed
    assert s.external(filed)["status"] == "failed" and _events(s, filed, "reasked") == []
    gone = s.add_external_wanted("Sade", "Smooth Operator", playlist_id="pl-3", position=1)
    s.forget_playlist("pl-3")
    fresh = s.add_external_wanted("Sade", "Smooth Operator", playlist_id="pl-9", position=4, reask="Tea tent")
    assert fresh != gone and s.external(fresh)["status"] == "needs_source"     # R6 review: an import asks again
    row = s.external(gone)
    assert (row["status"], row["reason"], row["playlist_id"], row["position"]) == ("removed", "playlist deleted", "pl-3", 1)
    assert _events(s, gone, "reasked") == []
    assert s.add_external_wanted("Sade", "Smooth Operator") == fresh                     # and once only


def test_a_reask_revives_the_newest_of_several_failed_rows_and_supersedes_the_rest():
    # R6-03 review: a live crates.db may hold duplicates from before §8h; the newest is the one import_order names.
    s = CrateStore()
    old = s.add_external_wanted("Chic", "Good Times", playlist_id="pl-1", position=2)
    s.set_wanted_status(old, "failed", "download timed out")
    new = s.add_external_wanted("Chic", "Good Times", playlist_id="pl-1", position=2)
    s.set_wanted_status(new, "failed", "no candidate")
    assert s.add_external_wanted("Chic", "Good Times", playlist_id="pl-1", position=2, reask="Tea tent") == new
    assert s.external(new)["status"] == "needs_source"
    assert (s.external(old)["status"], s.external(old)["reason"]) == ("removed", f"superseded by {new}")
    assert _events(s, old, "superseded") == [("pl-1", f"by {new}; was failed: download timed out")]
    assert [r["song_id"] for r in s.wanted()] == [new]
    assert s.add_external_wanted("Chic", "Good Times", reask="Tea tent") == new    # the removed row never shadows it


def test_a_reask_keeps_an_older_duplicate_with_a_waiting_approval_and_repoints_import_order():
    # R6 review: Michael's yes is never superseded (as forget_playlist and upgrade_busy keep it), and another
    # playlist's import_order follows the surviving row.
    s = CrateStore()
    old = s.add_external_wanted("Chic", "Good Times", playlist_id="pl-1", position=2)
    s.set_wanted_status(old, "failed", "download timed out")
    approved = s.add_external_wanted("Chic", "Le Freak", playlist_id="pl-1", position=3)
    s.set_wanted_status(approved, "failed", "download timed out")
    s.record_import_order("pl-1", [(2, None, old), (3, None, approved)])
    new = s.add_external_wanted("Chic", "Good Times", playlist_id="pl-3", position=1)
    s.set_wanted_status(new, "failed", "no candidate")
    newer = s.add_external_wanted("Chic", "Le Freak", playlist_id="pl-3", position=2)
    s.set_wanted_status(newer, "failed", "no candidate")
    s.approve(approved, "michael", None, "medium")
    s.add_external_wanted("Chic", "Good Times", playlist_id="pl-3", position=1, reask="Tea tent")
    s.add_external_wanted("Chic", "Le Freak", playlist_id="pl-3", position=2, reask="Tea tent")
    assert s.external(old)["status"] == "removed" and s.external(approved)["status"] == "failed"
    assert [(r["position"], r["wanted_id"]) for r in s.import_order("pl-1")] == [(2, new), (3, approved)]


def test_a_newer_failed_row_is_reasked_past_an_older_removed_one():
    s = CrateStore()
    gone = s.add_external_wanted("Chic", "Good Times", playlist_id="pl-1", position=2)
    s.set_wanted_status(gone, "failed", "download timed out")
    failed = s.add_external_wanted("Chic", "Good Times", playlist_id="pl-3", position=1)    # queued before §8h
    s.set_wanted_status(gone, "removed", "playlist deleted")
    s.set_wanted_status(failed, "failed", "download timed out")
    assert s.add_external_wanted("Chic", "Good Times", playlist_id="pl-3", position=1, reask="Tea tent") == failed
    assert s.external(gone)["status"] == "removed" and s.external(failed)["status"] == "needs_source"


def test_a_reasked_row_drops_its_old_preview_and_takes_the_imports_tier_and_length():
    s = CrateStore()
    ext = s.add_external_wanted("Chic", "Good Times", duration_s=200, tier="crate")
    s.set_preview(ext, {"status": "ok", "pick": {"username": "u", "filename": "f.flac"}})
    s.set_wanted_status(ext, "failed", "download timed out")
    s.add_external_wanted("Chic", "Good Times", album="Risqué", duration_s=501, reask="Tea tent", default_tier="medium")
    row = s.external(ext)
    assert s.preview(ext) is None and (row["tier"], row["duration"], row["album"]) == ("medium", 501, "Risqué")
    assert ("None", "needs_source") in [(str(p), d) for p, d in _events(s, ext, "status")]
