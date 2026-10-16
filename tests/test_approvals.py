"""M6 task 1: approval and preview records, POST /api/wanted/<id>/preview|approve, the Wanted tab's buttons."""
import json
import re
import urllib.error
import urllib.request

import pytest

from crates.service import Config, CrateApp, CrateServer
from crates.store import CrateStore
from sourcing.fake_slskd import FakeSlskdServer
from sourcing.slskd_client import SlskdClient
from subsonic.fake_server import FakeSubsonicServer
from tests.helpers import load_responses
from tests.test_service import get, post


@pytest.fixture
def svc_slskd(tmp_path):
    """Fake Navidrome + fake slskd; crate pl-2 holds s4, relabelled so the fixture search matches it."""
    with FakeSubsonicServer() as fake, FakeSlskdServer(load_responses(), tmp_path / "dl", files={}) as srv:
        fake.state.songs["s4"].update(title="Good Times", artist="Chic", album="Risqué", year=1979, track=3, duration=501)
        cfg = Config(subsonic_url=fake.url, username="demo", password="demo", db_path=":memory:", port=0)
        app = CrateApp(cfg, store=CrateStore(), slskd=SlskdClient(srv.url, "k"))
        app.set_crate("pl-2", True)
        with CrateServer(app) as web:
            yield fake, srv, app, web


def test_approve_records_and_supersedes():
    store = CrateStore()
    first = store.approve("s4", "michael", None, "crate")
    second = store.approve("s4", "michael", {"username": "u", "filename": "f"}, "crate")
    assert [a["id"] for a in store.pending_approvals()] == [second]
    assert store.approval("s4")["candidate"] == {"username": "u", "filename": "f"}
    old = next(a for a in store.db.execute("SELECT * FROM approvals WHERE id=?", (first,)))
    assert old["result"] == f"superseded by #{second}" and old["used_at"] is not None
    store.mark_approval_used(second, "ok: x")
    assert store.pending_approvals() == []
    assert store.approval("s4")["result"] == "ok: x" and store.approval("s4")["used_at"] is not None
    assert set(store.approval("s4")) == {"id", "wanted_id", "approved_by", "candidate", "tier", "ts", "used_at", "result"}
    assert store.approval("nope") is None


def test_approved_event_never_names_the_peer():
    store = CrateStore()
    store.approve("s4", "michael", {"username": "vinylhead77", "filename": "a\\b\\03 - Good Times.flac",
                                     "basename": "03 - Good Times.flac"}, "crate")
    details = [e["detail"] or "" for e in store.events()]
    assert not any("vinylhead77" in d for d in details)
    assert any(e["kind"] == "approved" and "03 - Good Times.flac" in e["detail"] and "michael at crate" in e["detail"]
               for e in store.events())


def test_preview_endpoint_returns_and_caches_the_pick(svc_slskd):
    fake, srv, app, web = svc_slskd
    s, pv = post(web.url + "/api/wanted/s4/preview", {})
    assert s == 200 and pv["pick"]["username"] == "vinylhead77" and "Good Times" in pv["explain"]
    assert srv.enqueued == []
    # no peer is named: every ranked line's user column is a pN label (a plain word like "locked" may
    # still appear in a rejection reason, so the usernames are checked in that column, not by substring)
    heads = [ln.split()[1] for ln in pv["explain"].splitlines() if not ln.startswith(" " * 9)]
    assert heads and all(re.fullmatch(r"p\d+", h) for h in heads) and heads[0] == "p1"
    assert "vinylhead77" not in pv["explain"]
    _, _, w = get(web.url + "/api/wanted")
    row = next(t for t in w if t["song_id"] == "s4")
    assert row["preview"]["pick"]["basename"] == "03 - Good Times.flac" and row["approval"] is None


def test_approve_endpoint_uses_the_previewed_pick(svc_slskd):
    fake, srv, app, web = svc_slskd
    _, pv = post(web.url + "/api/wanted/s4/preview", {})
    s, a = post(web.url + "/api/wanted/s4/approve", {})
    assert s == 200 and a["approved_by"] == "michael" and a["tier"] == "crate" and a["used_at"] is None
    assert a["candidate"]["filename"] == pv["pick"]["filename"]
    _, _, w = get(web.url + "/api/wanted")
    assert next(t for t in w if t["song_id"] == "s4")["approval"]["id"] == a["id"]


def test_approve_with_body_candidate(svc_slskd):
    fake, srv, app, web = svc_slskd
    cand = {"username": "u", "filename": "f"}
    s, a = post(web.url + "/api/wanted/s4/approve", {"candidate": cand})
    assert s == 200 and a["candidate"] == cand


def test_approve_unknown_id_is_404_and_bad_candidate_400(svc_slskd):
    fake, srv, app, web = svc_slskd
    assert post(web.url + "/api/wanted/nope/approve", {})[0] == 404
    assert post(web.url + "/api/wanted/s4/approve", {"candidate": {"username": 3}})[0] == 400


def test_preview_unknown_id_is_404(svc_slskd):
    fake, srv, app, web = svc_slskd
    assert post(web.url + "/api/wanted/nope/preview", {})[0] == 404


def test_preview_without_slskd_is_503():
    with FakeSubsonicServer() as fake:
        cfg = Config(subsonic_url=fake.url, username="demo", password="demo", db_path=":memory:", port=0)
        with CrateServer(CrateApp(cfg, store=CrateStore())) as web:
            s, body = post(web.url + "/api/wanted/s4/preview", {})
    assert s == 503 and body == {"error": "slskd is not configured"}


def test_config_builds_slskd_from_env(monkeypatch):
    monkeypatch.setenv("SLSKD_URL", "http://127.0.0.1:5030")
    monkeypatch.setenv("SLSKD_API_KEY", "k")
    cfg = Config.from_env()
    assert (cfg.slskd_url, cfg.slskd_key) == ("http://127.0.0.1:5030", "k")
    assert CrateApp(cfg, store=CrateStore()).slskd is not None


def test_web_client_offers_preview_and_approve(svc_slskd):
    fake, srv, app, web = svc_slskd
    _, _, js = get(web.url + "/app.js", raw=True)
    js = js.decode()
    assert "/preview" in js and "/approve" in js and "waiting for worker" in js


@pytest.mark.parametrize("status", ["sourcing", "verify"])
def test_preview_and_approve_of_a_row_in_progress_is_409(svc_slskd, status):
    fake, srv, app, web = svc_slskd
    app.store.set_wanted_status("s4", status, "filed as x but Navidrome has not picked it up yet")
    for action in ("preview", "approve"):
        code, body = post(web.url + f"/api/wanted/s4/{action}", {})
        assert code == 409 and status in body["error"]
    assert app.store.approval("s4") is None and app.store.preview("s4") is None
