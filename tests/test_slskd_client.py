"""slskd errors name the step and the endpoint (spec S1-05): never the peer's name, the URL or the API key."""
import pytest

from sourcing.fake_slskd import FakeSlskdServer
from sourcing.slskd_client import SlskdClient, SlskdError
from tests.helpers import load_responses

RESPONSES = load_responses()
GOOD = RESPONSES[0]["files"][0]["filename"]          # vinylhead77's Good Times FLAC


def test_an_http_error_names_the_method_and_the_endpoint_template(tmp_path):
    with FakeSlskdServer(RESPONSES, tmp_path, files={}) as srv:
        with pytest.raises(SlskdError) as e:
            SlskdClient(srv.url, "k").search_state("nope")
    assert str(e.value) == "slskd GET /searches/<id>: HTTP 404"
    assert (e.value.method, e.value.endpoint, e.value.status) == ("GET", "/searches/<id>", 404)


def test_an_enqueue_error_names_the_endpoint_not_the_peer(tmp_path):
    with FakeSlskdServer(RESPONSES, tmp_path, files={GOOD: b"x"}, fail_enqueue=True) as srv:
        with pytest.raises(SlskdError) as e:
            SlskdClient(srv.url, "k").enqueue("vinylhead77", [{"filename": GOOD, "size": 1}])
    assert str(e.value) == "slskd POST /transfers/downloads/<peer>: HTTP 500" and e.value.status == 500


def test_a_wrong_api_key_is_401_and_the_key_is_not_in_the_message(tmp_path):
    with FakeSlskdServer(RESPONSES, tmp_path, files={}) as srv:
        with pytest.raises(SlskdError) as e:
            SlskdClient(srv.url, "wrong-key-91c2").downloads()
    assert str(e.value) == "slskd GET /transfers/downloads: HTTP 401" and "wrong-key-91c2" not in str(e.value)


def test_a_connection_error_names_the_endpoint_and_has_no_status():
    with pytest.raises(SlskdError) as e:
        SlskdClient("http://127.0.0.1:1", "secret-key-7f3a", timeout=5).search("Chic Good Times")
    msg = str(e.value)
    assert msg.startswith("slskd POST /searches: ") and len(msg) > len("slskd POST /searches: ")
    assert e.value.status is None
    assert "secret-key-7f3a" not in msg and "127.0.0.1" not in msg and "/api/v0" not in msg


def test_every_endpoint_has_its_template(tmp_path):
    """No peer name, search id or transfer id in any message: each call names its template."""
    with FakeSlskdServer(RESPONSES, tmp_path, files={}, api_key="right") as srv:
        c = SlskdClient(srv.url, "wrong")
        calls = [(lambda: c.search("x"), "POST /searches"),
                 (lambda: c.search_state("sid-1"), "GET /searches/<id>"),
                 (lambda: c.search_responses("sid-1"), "GET /searches/<id>/responses"),
                 (lambda: c.delete_search("sid-1"), "DELETE /searches/<id>"),
                 (lambda: c.enqueue("vinylhead77", []), "POST /transfers/downloads/<peer>"),
                 (lambda: c.downloads(), "GET /transfers/downloads"),
                 (lambda: c.downloads("vinylhead77"), "GET /transfers/downloads/<peer>"),
                 (lambda: c.remove_download("vinylhead77", "t1"), "DELETE /transfers/downloads/<peer>/<id>")]
        for call, want in calls:
            with pytest.raises(SlskdError) as e:
                call()
            assert str(e.value) == f"slskd {want}: HTTP 401"


def test_a_slskd_error_is_an_os_error():
    """Callers that read an outage as OSError (the worker's tick, the service) keep doing so."""
    assert issubclass(SlskdError, OSError)


def test_an_ssl_error_names_its_kind_not_the_host():
    """A certificate mismatch's text names the host ("certificate is not valid for 'slskd.home'")."""
    import ssl
    import urllib.error
    from sourcing.slskd_client import _why
    e = ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Hostname "
                                        "mismatch, certificate is not valid for 'slskd.home'.")
    assert "slskd.home" not in _why(urllib.error.URLError(e)) and _why(urllib.error.URLError(e))
    assert _why(urllib.error.URLError("unknown url type: slskd.home")) == "invalid URL"


@pytest.mark.parametrize("base", ["slskd.home:5030", "slskd.home", "http://slskd.home:port"])
def test_a_bad_base_url_names_neither_the_host_nor_the_peer(base):
    with pytest.raises(SlskdError) as e:
        SlskdClient(base, "k").downloads("vinylhead77")
    assert str(e.value) == "slskd GET /transfers/downloads/<peer>: invalid URL" and e.value.status is None


@pytest.mark.parametrize("raised, why", [(TimeoutError("timed out"), "timed out"),
                                         ("incomplete", "IncompleteRead"),
                                         ("remote", "Remote end closed connection without response")])
def test_a_dropped_connection_is_a_slskd_error(monkeypatch, raised, why):
    """A VPN drop mid-call: a read timeout, a cut-off body, a peer that hangs up."""
    import http.client
    import urllib.request
    raised = {"incomplete": http.client.IncompleteRead(b"x", 10),
              "remote": http.client.RemoteDisconnected("Remote end closed connection without response")}.get(raised, raised)

    def boom(*a, **kw):
        raise raised
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(SlskdError) as e:
        SlskdClient("http://127.0.0.1:5030", "k").search_state("sid-1")
    assert str(e.value) == f"slskd GET /searches/<id>: {why}" and e.value.status is None
