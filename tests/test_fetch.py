import json
from pathlib import Path

import pytest

from crates.reconcile import Reconciler
from crates.store import CrateStore
from sourcing.fake_slskd import FakeSlskdServer
from sourcing.fetch import fetch
from sourcing.slskd_client import SlskdClient
from subsonic.client import SubsonicClient
from subsonic.fake_server import FakeSubsonicServer
from tests.helpers import make_flac

RESPONSES = json.loads(Path("fixtures/search_responses.sample.json").read_text())
GOOD = RESPONSES[0]["files"][0]["filename"]      # Chic — Good Times FLAC, 501 s


def good_flac_bytes(tmp_path) -> bytes:
    return make_flac(tmp_path / "src.flac", total=44100 * 501, pad_bytes=501 * 900_000 // 8).read_bytes()


def new_song(nd):
    """What Navidrome will 'find' after the rescan: the filed FLAC."""
    nd.state.songs["s9"] = dict(nd.state.songs["s1"], id="s9", title="Good Times", artist="Chic", album="Risqué",
                                suffix="flac", bitRate=880, samplingRate=44100, bitDepth=16,
                                path="Chic/Risqué (1979)/03 - Good Times.flac")


@pytest.fixture
def world(tmp_path):
    """Fake Navidrome whose crate 'Chicago 86' (pl-2) contains s4, a 128 kbps MP3 → needs_source;
    we make the wanted track *Chic — Good Times* by relabelling s4 so the fixture search matches."""
    with FakeSubsonicServer() as nd:
        nd.state.songs["s4"].update(title="Good Times", artist="Chic", album="Risqué", year=1979, track=3, duration=501)
        nd.state.songs["s1"].update(title="Everybody Dance")   # the sample library's own Good Times FLAC would collide
        store = CrateStore()
        client = SubsonicClient(nd.url, "demo", "demo")
        rec = Reconciler(client, store)
        rec.set_crate("pl-2", True)
        wanted = [w for w in store.wanted() if w["song_id"] == "s4"]
        assert wanted and wanted[0]["status"] == "needs_source"
        yield dict(nd=nd, store=store, client=client, rec=rec, music=tmp_path / "music", dl=tmp_path / "dl")


def run(world, srv, approve, wanted_id="s4", **kw):
    return fetch(wanted_id, store=world["store"], slskd=SlskdClient(srv.url, "k"), navidrome=world["client"],
                 reconciler=world["rec"], music_root=world["music"], downloads_root=world["dl"],
                 approve=approve, poll_s=0.01, download_timeout_s=kw.pop("download_timeout_s", 1),
                 scan_timeout_s=1, **kw)


def test_without_approve_only_scores_and_prints_pick(world, tmp_path):
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        r = run(world, srv, approve=False)
    assert r.status == "needs_source" and r.pick.username == "vinylhead77" and "Good Times" in r.explain
    assert srv.enqueued == [] and world["store"].track_status_map("pl-2")["s4"]["status"] == "needs_source"


def test_approved_fetch_runs_to_ok(world, tmp_path):
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"])
        r = run(world, srv, approve=True)
    assert r.status == "ok", r.reason
    assert r.filed == world["music"] / "Chic" / "Risqué (1979)" / "03 - Good Times.flac" and r.filed.read_bytes() == flac
    assert r.new_song_id == "s9"
    pl = world["client"].playlist("pl-2")
    assert [e.id for e in pl.entries] == ["s3", "s9", "s5"]           # swapped in place
    st = world["store"].track_status_map("pl-2")
    assert st["s9"]["status"] == "ok" and st["s4"]["status"] == "removed"
    assert not (world["dl"] / "vinylhead77" / "03 - Good Times.flac").exists()


def test_bad_download_is_failed_and_not_filed(world, tmp_path):
    fake_lossless = make_flac(tmp_path / "bad.flac", total=44100 * 501, pad_bytes=10_000).read_bytes()
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: fake_lossless}) as srv:
        r = run(world, srv, approve=True)
    assert r.status == "failed" and "transcode" in r.reason
    assert world["store"].track_status_map("pl-2")["s4"]["status"] == "failed"
    assert not world["music"].exists()


def test_fetch_download_timeout_fails_cleanly(world, tmp_path):
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: b"x"}, complete=False) as srv:
        r = run(world, srv, approve=True, download_timeout_s=0.05)
    assert r.status == "failed" and "timed out" in r.reason
    assert not world["music"].exists()


def test_fetch_no_acceptable_candidate_leaves_needs_source(world):
    locked = [dict(r, files=[dict(f, isLocked=True) for f in r["files"]]) for r in RESPONSES]
    with FakeSlskdServer(locked, world["dl"], files={}) as srv:
        r = run(world, srv, approve=True)
    assert r.status == "needs_source" and "no acceptable candidate" in r.reason and srv.enqueued == []


def test_fetch_filed_but_not_found_after_rescan(world, tmp_path):
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        r = run(world, srv, approve=True)                  # no s9 registered → Navidrome never sees it
    assert r.status == "verify" and "03 - Good Times.flac" in r.reason
    assert r.filed.exists()
    assert world["store"].track_status_map("pl-2")["s4"]["status"] == "verify"


def test_fetch_swaps_song_in_every_crate(world, tmp_path):
    world["client"].update_playlist("pl-1", add_song_ids=["s4"])   # second crate holding the same song
    world["rec"].set_crate("pl-1", True); world["rec"].run()
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"])
        r = run(world, srv, approve=True)
    assert r.status == "ok"
    for pl_id in ("pl-1", "pl-2"):
        ids = [e.id for e in world["client"].playlist(pl_id).entries]
        assert "s9" in ids and "s4" not in ids
        assert world["store"].track_status_map(pl_id)["s9"]["status"] == "ok"


def test_external_wanted_row_files_without_playlist_swap(world, tmp_path):
    ext = world["store"].add_external_wanted("Chic", "Good Times", album="Risqué", duration_s=501, year=1979)
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"])
        r = run(world, srv, approve=True, wanted_id=ext)
    assert r.status == "ok" and world["store"].external(ext)["status"] == "ok"
    assert [e.id for e in world["client"].playlist("pl-2").entries] == ["s3", "s4", "s5"]   # untouched
