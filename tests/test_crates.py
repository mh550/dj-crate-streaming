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
    assert judge(song(suffix="mp3", bit_rate=320))[0] == "needs_source"       # allowed but lossless preferred
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
    assert store.wanted() == []                      # in flight → not offered again
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
