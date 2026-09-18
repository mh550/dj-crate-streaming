import pytest

from crates.reconcile import Reconciler, judge, with_crate_tag, has_crate_tag
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
