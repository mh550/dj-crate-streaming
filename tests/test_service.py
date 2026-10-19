import json
import urllib.error
import urllib.request

import pytest

from crates.service import Config, CrateApp, CrateServer
from crates.store import CrateStore
from subsonic.fake_server import FakeSubsonicServer


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


@pytest.fixture
def svc():
    with FakeSubsonicServer() as fake:
        cfg = Config(subsonic_url=fake.url, username="demo", password="demo", db_path=":memory:", port=0,
                     public_url="http://phone-reachable.example:4533")
        app = CrateApp(cfg, store=CrateStore())
        with CrateServer(app) as srv:
            yield fake, app, srv


def get(url, raw=False):
    opener = urllib.request.build_opener(NoRedirect)
    try:
        r = opener.open(url)
    except urllib.error.HTTPError as e:
        r = e
    body = r.read()
    return r.status, r.headers, (body if raw else (json.loads(body) if body else None))


def post(url, obj):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        r = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        r = e
    return r.status, json.loads(r.read() or b"null")


def test_status_and_playlists(svc):
    fake, app, srv = svc
    s, _, st = get(srv.url + "/api/status")
    assert s == 200 and st["serverType"] == "fake-navidrome" and st["crates"] == 0
    s, _, pls = get(srv.url + "/api/playlists")
    assert [p["name"] for p in pls] == ["Disco Edits", "Chicago 86", "Sunday Listening"]
    assert not any(p["crate"] for p in pls)      # nothing reconciled yet


def test_toggle_crate_and_detail(svc):
    fake, app, srv = svc
    s, v = post(srv.url + "/api/playlists/pl-1/crate", {"enabled": True})
    assert s == 200 and v["crate"] and v["summary"]["total"] == 3
    s, _, d = get(srv.url + "/api/playlists/pl-1")
    assert [e["crateStatus"] for e in d["entries"]] == ["ok", "ok", "needs_source"]
    assert "#crate" in fake.state.playlists["pl-1"]["comment"]
    s, _, w = get(srv.url + "/api/wanted")
    assert [t["title"] for t in w] == ["Move Your Body"]
    s, _, st = get(srv.url + "/api/status")
    assert st["crates"] == 1 and st["wanted"] == 1


def test_reconcile_endpoint(svc):
    fake, app, srv = svc
    s, r = post(srv.url + "/api/reconcile", {})
    assert s == 200 and r["toggled_from_comment"] == ["Chicago 86"]


def test_stream_redirects_to_signed_public_url(svc):
    fake, app, srv = svc
    s, h, _ = get(srv.url + "/api/stream/s1?format=opus&maxBitRate=128", raw=True)
    assert s == 302
    loc = h["Location"]
    assert loc.startswith("http://phone-reachable.example:4533/rest/stream.view?")
    assert "format=opus" in loc and "maxBitRate=128" in loc and "c=dj-crates-web" in loc and "t=" in loc and "s=" in loc
    assert "demo" not in loc.split("u=demo")[1]   # password never appears
    s, h, _ = get(srv.url + "/api/download/s1", raw=True)
    assert s == 302 and "/rest/download.view?" in h["Location"] and "format=raw" in h["Location"]


def test_static_and_404s(svc):
    fake, app, srv = svc
    s, h, body = get(srv.url + "/", raw=True)
    assert s == 200 and b"<title>Crates</title>" in body and h["Content-Type"].startswith("text/html")
    assert get(srv.url + "/app.js", raw=True)[0] == 200
    assert get(srv.url + "/../README.md", raw=True)[0] in (400, 404)
    assert get(srv.url + "/api/nope")[0] == 404
    assert get(srv.url + "/api/playlists/does-not-exist")[0] == 400


def test_search_and_add_to_playlist(svc):
    fake, app, srv = svc
    s, _, res = get(srv.url + "/api/search?q=strings")
    assert [r["id"] for r in res] == ["s5"]
    post(srv.url + "/api/playlists/pl-3/crate", {"enabled": True})
    s, d = post(srv.url + "/api/playlists/pl-3/songs", {"songIds": ["s4"]})
    assert s == 200 and d["summary"]["needs_source"] == 1
    s, d = post(srv.url + "/api/playlists", {"name": "Fresh", "songIds": ["s1"], "crate": True})
    assert s == 201 and d["crate"] and d["summary"]["ok"] == 1


def test_navidrome_down_is_502():
    cfg = Config(subsonic_url="http://127.0.0.1:1", username="x", password="y", db_path=":memory:", port=0)
    with CrateServer(CrateApp(cfg, store=CrateStore())) as srv:
        assert get(srv.url + "/api/status")[0] == 502


def test_status_reports_trash(tmp_path):
    from crates.service import Config, CrateApp
    (tmp_path / "2026-10-15").mkdir(); (tmp_path / "2026-10-15/x.flac").write_bytes(b"0" * 5)
    with FakeSubsonicServer() as fake:
        cfg = Config(subsonic_url=fake.url, username="demo", password="demo", db_path=":memory:", port=0, trash_dir=str(tmp_path))
        st = CrateApp(cfg, store=CrateStore()).status()
    assert st["trash"]["files"] == 1 and st["trash"]["oldest"] == "2026-10-15"
    with FakeSubsonicServer() as fake:
        cfg = Config(subsonic_url=fake.url, username="demo", password="demo", db_path=":memory:", port=0)
        assert CrateApp(cfg, store=CrateStore()).status()["trash"] == {"mounted": False}


def test_config_reads_crates_trash(monkeypatch):
    from crates.service import Config
    monkeypatch.setenv("CRATES_TRASH", "/trash")
    assert Config.from_env().trash_dir == "/trash"


def test_status_reports_the_worker_heartbeat_age(tmp_path):
    import os
    import time
    with FakeSubsonicServer() as fake:
        cfg = Config(subsonic_url=fake.url, username="demo", password="demo", db_path=str(tmp_path / "crates.db"), port=0)
        with CrateServer(CrateApp(cfg, store=CrateStore())) as srv:
            assert get(srv.url + "/api/status")[2]["workerHeartbeatAge"] is None          # no heartbeat yet
            hb = tmp_path / "worker.heartbeat"
            hb.touch()
            assert 0 <= get(srv.url + "/api/status")[2]["workerHeartbeatAge"] < 10
            old = time.time() - 300
            os.utime(hb, (old, old))
            assert 295 < get(srv.url + "/api/status")[2]["workerHeartbeatAge"] < 320


def test_a_gone_playlists_crate_row_does_not_break_the_views(svc):
    # N3: between the delete in Navidrome and the next reconcile, and while an in-flight row waits after it, the
    # crates row has no playlist behind it. status, playlists, crates and wanted still answer.
    fake, app, srv = svc
    app.set_crate("pl-2", True)
    app.store.set_track_status("pl-2", "s3", "sourcing", "downloading")
    del fake.state.playlists["pl-2"]
    wanted = []
    for _ in range(2):                                    # before the reconcile, then after it (the row waits)
        for path in ("status", "playlists", "crates", "wanted"):
            s, _, body = get(srv.url + "/api/" + path)
            assert s == 200, (path, body)
        s, _, crates = get(srv.url + "/api/crates")
        assert crates == []
        s, _, w = get(srv.url + "/api/wanted")
        wanted.append([t["song_id"] for t in w])
        s, r = post(srv.url + "/api/reconcile", {})
        assert s == 200
    assert wanted == [["s3", "s4"], ["s3"]]               # s4 queued until the reconcile drops it; s3 is downloading
    assert r["playlists_gone"] == ["Chicago 86: playlist no longer exists in Navidrome; 0 rows dropped, 1 in flight kept"]


def test_events_show_no_absolute_path(svc):
    # N5-02 review M7: an import from a file names it in its `imported` event, and a replacement names /trash and
    # /music; /api/events goes through public() like the wanted rows, so only the file name is shown.
    fake, app, srv = svc
    app.store.mark_playlist_imported("pl-9", "Tea", "/home/mh550/exports/tea tent.csv")
    app.store.log(None, "s1", "replace", "old copy moved to /trash/2026-10-19/a/b.mp3")
    app.store.commit()
    s, _, ev = get(srv.url + "/api/events")
    assert s == 200
    assert [e["detail"] for e in ev[:2]] == ["old copy moved to b.mp3", "made by import-playlist: tea tent.csv"]
