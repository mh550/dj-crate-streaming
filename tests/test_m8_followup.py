"""M8 follow-up: review rows in Wanted, retryable replacement reviews, summaries of tier-only playlists.

The backend half of what the web client (web/app.js) already renders: replacement and proposal code leave rows in
`review` with a reason; the ones that say "approve a different candidate" must be approvable, the ones that wait
for a pick between library versions (import: "ambiguous: ...") must not."""
import json
import urllib.request

import pytest

from crates.reconcile import Reconciler
from crates.store import CrateStore, retryable_review
from sourcing.fake_slskd import FakeSlskdServer
from subsonic.client import SubsonicClient
from subsonic.fake_server import FakeSubsonicServer
from tests.test_fetch import GOOD, RESPONSES, good_flac_bytes, new_song, run, world  # noqa: F401  (world: fixture)
from tests.test_service import get, post, svc  # noqa: F401  (svc: fixture)
from tests.test_worker import worker

RETRYABLE = [
    "kept beside A/B/x.mp3: not proven the same recording (no fingerprint); the new copy is A/B/x.flac",
    "declined replacement #3; approve a different candidate to retry (the new copy stays in the library as A/B/x.flac)",
    "replacement #2 not made: slot 1 no longer holds s4; approve a different candidate to retry",
    "filed beside A/B/x.mp3; request withdrawn, both copies kept (the new copy is A/B/x.flac)",
]
NOT_RETRYABLE = [
    None, "", "keep both?", "ambiguous (3 library versions): A, B, C",
    "replacement #1 blocked: trash failed",                  # the job is the worker's, not a download to retry
    "replacement #1 continues in the worker",
    "needs a pick first (ambiguous)", "declined", "my kept beside note",
]


@pytest.mark.parametrize("reason", RETRYABLE)
def test_replacement_reasons_are_retryable(reason):
    assert retryable_review(reason)


@pytest.mark.parametrize("reason", NOT_RETRYABLE)
def test_other_review_reasons_are_not(reason):
    assert not retryable_review(reason)


# --- 1. Wanted lists review rows
def test_wanted_lists_review_rows_with_their_reason(world):  # noqa: F811
    store = world["store"]
    store.set_track_status("pl-2", "s4", "review", RETRYABLE[0])
    ext = store.add_external_wanted("Twain", "The Magician")
    store.set_external_status(ext, "review", "ambiguous (2 library versions): a, b")
    store.commit()
    w = {t["song_id"]: t for t in store.wanted()}
    assert w["s4"]["status"] == "review" and w["s4"]["reason"] == RETRYABLE[0]
    assert w[ext]["status"] == "review" and w[ext]["reason"].startswith("ambiguous")
    assert w["s4"]["crates"] == ["Chicago 86"]


def test_status_wanted_count_includes_review_rows(svc):  # noqa: F811
    fake, app, srv = svc
    post(srv.url + "/api/playlists/pl-2/crate", {"enabled": True})
    before = get(srv.url + "/api/status")[2]["wanted"]
    app.store.set_track_status("pl-2", "s4", "review", RETRYABLE[1]); app.store.commit()
    app.store.set_external_status(app.store.add_external_wanted("Twain", "Magician"), "review", "ambiguous (2): a, b")
    app.store.commit()
    assert get(srv.url + "/api/status")[2]["wanted"] == before + 1      # s4 was needs_source already; the external is new
    assert {t["status"] for t in get(srv.url + "/api/wanted")[2]} >= {"review"}


# --- 2. approving a retryable review row is a fresh download attempt
def test_preview_of_a_retryable_review_row_searches(world):  # noqa: F811
    world["store"].set_track_status("pl-2", "s4", "review", RETRYABLE[1])
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        r = run(world, srv, approve=False)
    assert r.pick is not None and r.pick.username == "vinylhead77"
    assert world["store"].track_status_map("pl-2")["s4"]["status"] == "review"      # a preview changes nothing


@pytest.mark.parametrize("reason", RETRYABLE)
def test_approving_a_replacement_review_row_downloads_again(world, tmp_path, reason):  # noqa: F811
    store = world["store"]
    store.set_track_status("pl-2", "s4", "review", reason)
    store.approve("s4", "michael", None, "crate"); store.commit()
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        report = worker(world, srv).tick()
        assert srv.enqueued                                         # it fetched
    assert report.results[0].startswith("s4: ok:"), report.results
    assert [e.id for e in world["client"].playlist("pl-2").entries] == ["s3", "s9", "s5"]


def test_approving_an_ambiguous_import_review_row_is_still_refused(world):  # noqa: F811
    store = world["store"]
    ext = store.add_external_wanted("Chic", "Good Times")
    store.set_external_status(ext, "review", "ambiguous (2 library versions): a, b")
    store.approve(ext, "michael", None, "crate"); store.commit()
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        report = worker(world, srv).tick()
        assert srv.enqueued == []
    assert report.results[0].startswith(f"{ext}: review: needs a pick first")
    assert store.external(ext)["status"] == "review"


def test_a_crate_review_row_with_another_reason_is_still_refused(world):  # noqa: F811
    store = world["store"]
    store.set_track_status("pl-2", "s4", "review", "keep both?")
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        r = run(world, srv, approve=True)
        assert srv.enqueued == []
    assert r.status == "review" and "needs a pick first" in r.reason


# --- 3. summaries follow the effective tier
def test_a_tier_only_playlist_has_a_summary_and_entry_statuses(svc):  # noqa: F811
    fake, app, srv = svc
    s, v = post(srv.url + "/api/playlists/pl-1/tier", {"tier": "medium"})
    assert s == 200 and v["tier"] == "medium" and not v["crate"]
    assert v["summary"] is not None and v["summary"]["total"] == 3
    s, _, d = get(srv.url + "/api/playlists/pl-1")
    assert d["summary"] == v["summary"] and d["summary"]["ok"] + d["summary"]["needs_source"] == 3
    assert all(e["crateStatus"] is not None for e in d["entries"])
    _, _, pls = get(srv.url + "/api/playlists")
    assert next(p for p in pls if p["id"] == "pl-1")["summary"]["total"] == 3
    assert next(p for p in pls if p["id"] == "pl-3")["summary"] is None            # untiered: none
    _, _, d3 = get(srv.url + "/api/playlists/pl-3")
    assert d3["summary"] is None and all(e["crateStatus"] is None for e in d3["entries"])


# --- 4. counts add up to the track count
def test_summary_counts_review_rows(world):  # noqa: F811
    store = world["store"]
    before = store.summary("pl-2")
    assert "review" not in before                                       # unchanged shape while there is none
    store.set_track_status("pl-2", "s4", "review", RETRYABLE[0]); store.commit()
    s = store.summary("pl-2")
    assert s["review"] == 1 and s["total"] == before["total"]
    assert s["needs_source"] == before["needs_source"] - 1
    assert sum(v for k, v in s.items() if k != "total") == s["total"]


# --- 3. POST approve on a review row that is not retryable is a 409 and records nothing
@pytest.mark.parametrize("reason", ["ambiguous (2 library versions): a, b", "keep both?", None])
def test_approve_endpoint_refuses_a_non_retryable_review_row(svc, reason):  # noqa: F811
    fake, app, srv = svc
    ext = app.store.add_external_wanted("Twain", "The Magician")
    app.store.set_external_status(ext, "review", reason); app.store.commit()
    code, body = post(srv.url + f"/api/wanted/{ext}/approve", {})
    assert code == 409 and "needs a pick first" in body["error"]
    assert app.store.approval(ext) is None


def test_approve_endpoint_refuses_a_non_retryable_crate_review_row(svc):  # noqa: F811
    fake, app, srv = svc
    post(srv.url + "/api/playlists/pl-2/crate", {"enabled": True})
    app.store.set_track_status("pl-2", "s4", "review", "ambiguous (3 library versions): a, b, c"); app.store.commit()
    code, body = post(srv.url + "/api/wanted/s4/approve", {})
    assert code == 409 and "ambiguous" in body["error"]
    assert app.store.approval("s4") is None


@pytest.mark.parametrize("reason", RETRYABLE)
def test_approve_endpoint_accepts_a_retryable_review_row(svc, reason):  # noqa: F811
    fake, app, srv = svc
    post(srv.url + "/api/playlists/pl-2/crate", {"enabled": True})
    app.store.set_track_status("pl-2", "s4", "review", reason); app.store.commit()
    code, body = post(srv.url + "/api/wanted/s4/approve", {})
    assert code == 200, body
    assert app.store.approval("s4") is not None


# --- 4. playlist detail lists the playlist's queued rows the library does not have yet
def test_playlist_detail_lists_its_external_rows_not_yet_in_the_library(svc):  # noqa: F811
    fake, app, srv = svc
    a = app.store.add_external_wanted("Twain", "The Magician", playlist_id="pl-2", position=3)
    b = app.store.add_external_wanted("Chic", "Everybody Dance", playlist_id="pl-2", position=4)
    done = app.store.add_external_wanted("Sade", "Smooth Operator", playlist_id="pl-2", position=5)
    elsewhere = app.store.add_external_wanted("Yes", "Roundabout", playlist_id="pl-1", position=0)
    app.store.set_external_status(a, "failed", "no acceptable candidate on /srv/incoming/soulseek/vinylhead77/x.flac")
    app.store.set_external_status(done, "ok", "filed")
    app.store.db.execute("UPDATE external_wanted SET library_song_id='s1' WHERE id=?", (int(done[4:]),))
    app.store.db.execute("UPDATE external_wanted SET provisional=1 WHERE id=?", (int(b[4:]),))
    app.store.commit()
    code, _, body = get(srv.url + "/api/playlists/pl-2")
    assert code == 200
    rows = {w["id"]: w for w in body["wanted"]}
    assert set(rows) == {a, b}                                  # not the finished row, not another playlist's
    assert list(rows) == [a, b]                                 # in playlist order
    assert rows[a]["artist"] == "Twain" and rows[a]["title"] == "The Magician" and rows[a]["status"] == "failed"
    assert rows[b]["provisional"] is True and rows[a]["provisional"] is False
    assert rows[a]["library_song_id"] is None and rows[a]["filed"] is False
    assert "/srv" not in json.dumps(body) and "vinylhead77" not in json.dumps(body)     # no peer, no absolute path
    assert "x.flac" in rows[a]["reason"]                        # the basename stays


def test_playlist_detail_wanted_is_empty_without_external_rows(svc):  # noqa: F811
    fake, app, srv = svc
    assert get(srv.url + "/api/playlists/pl-2")[2]["wanted"] == []


# --- R6-03 (M9 §8h): a re-import's reused failed row is one Wanted row, and approvable
def test_wanted_lists_a_reimported_failed_row_once_and_approve_accepts_it(svc):  # noqa: F811
    from sourcing import import_playlist as ip
    from tests.test_import_playlist import ROWS, _lib
    fake, app, srv = svc
    _lib(fake)
    c = SubsonicClient(fake.url, "demo", "demo")
    first = ip.import_playlist("Tea tent", ROWS, c, app.store, source="s")
    [ext] = [r["song_id"] for r in app.store.external_for_playlist(first.playlist_id) if r["position"] == 2]
    app.store.set_wanted_status(ext, "failed", "download timed out")
    ip.import_playlist("Tea tent", ROWS, c, app.store, source="s")
    rows = [t for t in get(srv.url + "/api/wanted")[2] if t["title"].startswith("Piano Joint")]
    assert [(t["song_id"], t["status"]) for t in rows] == [(ext, "needs_source")]
    code, body = post(srv.url + f"/api/wanted/{ext}/approve", {})
    assert code == 200, body
    assert app.store.approval(ext)["wanted_id"] == ext
