import json
from pathlib import Path

from sourcing.fake_slskd import FakeSlskdServer
from sourcing.slskd_client import SlskdClient

RESPONSES = json.loads(Path("fixtures/search_responses.sample.json").read_text())
GOOD = RESPONSES[0]["files"][0]["filename"]          # vinylhead77's Good Times FLAC


def test_search_round_trip_serves_fixture_responses(tmp_path):
    with FakeSlskdServer(RESPONSES, tmp_path, files={GOOD: b"x"}) as srv:
        c = SlskdClient(srv.url, "k")
        sid = c.search("Chic Good Times")
        assert c.wait_search(sid, poll_s=0.01, max_s=1)["state"].startswith("Completed")
        resp = c.search_responses(sid)
        assert [r["username"] for r in resp] == [r["username"] for r in RESPONSES]
        c.delete_search(sid)


def test_enqueue_writes_file_and_reports_completed(tmp_path):
    with FakeSlskdServer(RESPONSES, tmp_path, files={GOOD: b"FLACBYTES"}) as srv:
        c = SlskdClient(srv.url, "k")
        c.enqueue("vinylhead77", [{"filename": GOOD, "size": 9}])
        assert srv.enqueued == [("vinylhead77", GOOD)]
        landed = tmp_path / "vinylhead77" / "03 - Good Times.flac"
        assert landed.read_bytes() == b"FLACBYTES"
        d = c.downloads()
        assert d[0]["state"] == "Completed, Succeeded" and d[0]["filename"] == GOOD


def test_incomplete_mode_never_finishes(tmp_path):
    with FakeSlskdServer(RESPONSES, tmp_path, files={GOOD: b"x"}, complete=False) as srv:
        c = SlskdClient(srv.url, "k")
        c.enqueue("vinylhead77", [{"filename": GOOD, "size": 1}])
        assert c.downloads()[0]["state"] == "InProgress"
        assert not (tmp_path / "vinylhead77").exists()


def test_wrong_api_key_is_401(tmp_path):
    import urllib.error
    with FakeSlskdServer(RESPONSES, tmp_path, files={}) as srv:
        try:
            SlskdClient(srv.url, "wrong").downloads()
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 401
