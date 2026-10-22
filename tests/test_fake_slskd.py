from pathlib import Path

from sourcing.fake_slskd import FakeSlskdServer
from sourcing.slskd_client import SlskdClient
from tests.helpers import load_responses

RESPONSES = load_responses()
GOOD = RESPONSES[0]["files"][0]["filename"]          # vinylhead77's Good Times FLAC


def test_search_round_trip_serves_fixture_responses(tmp_path):
    with FakeSlskdServer(RESPONSES, tmp_path, files={GOOD: b"x"}) as srv:
        c = SlskdClient(srv.url, "k")
        sid = c.search("Chic Good Times")
        assert c.wait_search(sid, poll_s=0.01, max_s=1)["state"].startswith("Completed")
        resp = c.search_responses(sid)
        assert [r["username"] for r in resp] == [r["username"] for r in RESPONSES]
        c.delete_search(sid)


def test_enqueue_writes_file_under_remote_folder_and_reports_nested(tmp_path):
    """slskd lands files at <downloads>/<remote parent folder>/<basename> and reports transfers as
    {username, directories:[{directory, files:[{id, filename, state, size}]}]} per user."""
    with FakeSlskdServer(RESPONSES, tmp_path, files={GOOD: b"FLACBYTES"}) as srv:
        c = SlskdClient(srv.url, "k")
        c.enqueue("vinylhead77", [{"filename": GOOD, "size": 9}])
        assert srv.enqueued == [("vinylhead77", GOOD)]
        landed = tmp_path / "Risqué (1979) [FLAC]" / "03 - Good Times.flac"
        assert landed.read_bytes() == b"FLACBYTES"
        u = c.downloads("vinylhead77")
        assert u["username"] == "vinylhead77"
        f = u["directories"][0]["files"][0]
        assert f["state"] == "Completed, Succeeded" and f["filename"] == GOOD and f["id"]
        assert c.downloads()[0]["username"] == "vinylhead77"      # all-users form is a list of the same objects


def test_incomplete_mode_never_finishes(tmp_path):
    with FakeSlskdServer(RESPONSES, tmp_path, files={GOOD: b"x"}, complete=False) as srv:
        c = SlskdClient(srv.url, "k")
        c.enqueue("vinylhead77", [{"filename": GOOD, "size": 1}])
        assert c.downloads("vinylhead77")["directories"][0]["files"][0]["state"] == "InProgress"
        assert list(tmp_path.iterdir()) == []


def test_remove_download_deletes_the_record(tmp_path):
    """The client's forget is DELETE …?remove=true: the only form slskd 0.26.1 deletes the record on."""
    with FakeSlskdServer(RESPONSES, tmp_path, files={GOOD: b"x"}) as srv:
        c = SlskdClient(srv.url, "k")
        c.enqueue("vinylhead77", [{"filename": GOOD, "size": 1}])
        tid = c.downloads("vinylhead77")["directories"][0]["files"][0]["id"]
        c.remove_download("vinylhead77", tid)
        assert c.downloads("vinylhead77")["directories"] == [] and srv.transfers == []


def _delete(srv, path):
    import urllib.request
    req = urllib.request.Request(srv.url + path, method="DELETE", headers={"X-API-Key": "k"})
    with urllib.request.urlopen(req) as r:
        return r.status, r.read()


def test_a_plain_delete_keeps_the_record_as_slskd_does(tmp_path):
    """slskd 0.26.1: DELETE without remove=true cancels an InProgress transfer and keeps every record, 204 no body."""
    with FakeSlskdServer(RESPONSES, tmp_path, files={GOOD: b"x"}) as srv:
        running = srv.seed_transfer("vinylhead77", GOOD, "InProgress")
        done = srv.seed_transfer("vinylhead77", GOOD, "Completed, Succeeded")
        assert _delete(srv, f"/api/v0/transfers/downloads/vinylhead77/{running['id']}") == (204, b"")
        assert _delete(srv, f"/api/v0/transfers/downloads/vinylhead77/{done['id']}") == (204, b"")
        assert [t["state"] for t in srv.transfers] == ["Completed, Cancelled", "Completed, Succeeded"]
        assert _delete(srv, f"/api/v0/transfers/downloads/vinylhead77/{done['id']}?remove=true") == (204, b"")
        assert [t["id"] for t in srv.transfers] == [running["id"]]


def test_an_unknown_transfer_id_is_404_and_the_client_reads_it_as_gone(tmp_path):
    import urllib.error
    with FakeSlskdServer(RESPONSES, tmp_path, files={GOOD: b"x"}) as srv:
        srv.seed_transfer("vinylhead77", GOOD, "Completed, Errored", transfer_id="t1")
        try:
            _delete(srv, "/api/v0/transfers/downloads/vinylhead77/nope?remove=true")
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 404
        SlskdClient(srv.url, "k").remove_download("vinylhead77", "nope")      # already gone: no error
        assert [t["id"] for t in srv.transfers] == ["t1"]


def test_a_user_s_transfers_are_listed_by_id_not_by_age(tmp_path):
    """slskd's real order isn't captured; the fake sorts by id so nothing can lean on "the last one is the newest"."""
    with FakeSlskdServer(RESPONSES, tmp_path, files={GOOD: b"x"}) as srv:
        srv.seed_transfer("vinylhead77", GOOD, "Completed, Errored", transfer_id="~stale")
        c = SlskdClient(srv.url, "k")
        c.enqueue("vinylhead77", [{"filename": GOOD, "size": 1}])
        ids = [f["id"] for f in c.downloads("vinylhead77")["directories"][0]["files"]]
        assert ids == sorted(ids) and ids[-1] == "~stale"


def test_a_peer_with_no_transfers_is_404_and_the_client_reads_it_as_empty(tmp_path):
    """Live slskd 0.26 (2026-10-21): GET /transfers/downloads/<peer> is 404 until that peer has a transfer. The worker
    asks it right before every first enqueue, so the client must read 404 as "no transfers", not fail the fetch."""
    import urllib.error
    import urllib.request
    with FakeSlskdServer(RESPONSES, tmp_path, files={GOOD: b"x"}) as srv:
        req = urllib.request.Request(srv.url + "/api/v0/transfers/downloads/vinylhead77", headers={"X-API-Key": "k"})
        try:
            urllib.request.urlopen(req)
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 404
        assert SlskdClient(srv.url, "k").downloads("vinylhead77") == {"username": "vinylhead77", "directories": []}


def test_fail_enqueue_mode_returns_500(tmp_path):
    import urllib.error
    with FakeSlskdServer(RESPONSES, tmp_path, files={GOOD: b"x"}, fail_enqueue=True) as srv:
        try:
            SlskdClient(srv.url, "k").enqueue("vinylhead77", [{"filename": GOOD, "size": 1}])
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 500


def test_wrong_api_key_is_401(tmp_path):
    import urllib.error
    with FakeSlskdServer(RESPONSES, tmp_path, files={}) as srv:
        try:
            SlskdClient(srv.url, "wrong").downloads()
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 401
