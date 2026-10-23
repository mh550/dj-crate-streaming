"""S3-06: scripts/capture_spotify.py against a stub opener only. No test opens a socket; the script never runs for real
in the build run (Michael runs it, checklist step 6)."""
import base64
import email.message
import http.client
import io
import json
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request

import pytest

from scripts import capture_spotify as cs

ID, SECRET, TOKEN = "myclientid", "s3cr3t", "tok_ABC"
ENV = {"SPOTIFY_CLIENT_ID": ID, "SPOTIFY_CLIENT_SECRET": SECRET}
QUERY = "Al Green I'm Still in Love With You"
SEARCH = {"albums": {"items": [{"id": "2nTlIPIQ7fHOnNN7BRch0Z", "name": "I'm Still in Love With You"},
                               {"id": "0000000000000000000000", "name": "Other"}]},
          "tracks": {"items": [{"id": "t1", "name": "Love and Happiness"}]}}
BASIC = base64.b64encode(f"{ID}:{SECRET}".encode()).decode()
ALBUM = {"id": "2nTlIPIQ7fHOnNN7BRch0Z", "name": "I'm Still in Love With You", "tracks": {"items": [{"name": "x"}]}}


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test opened a network socket")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _http_error(req, code, body=b"{}", headers=None):
    msg = email.message.Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError(req.full_url, code, "err", msg, io.BytesIO(body))


class ReadFails(io.BytesIO):
    def __init__(self, exc):
        super().__init__(b"")
        self.exc = exc

    def read(self, *a):
        raise self.exc


class Stub:
    """opener(req, timeout): records each Request and answers the next canned reply (bytes, dict or an HTTP code)."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, req, timeout=None):
        assert timeout, "every request has a timeout"
        self.calls.append(req)
        r = self.replies.pop(0)
        if isinstance(r, tuple):                                  # (code, body, headers)
            raise _http_error(req, *r)
        if isinstance(r, Exception):
            raise r
        if isinstance(r, io.BytesIO):
            return r
        return io.BytesIO(r if isinstance(r, bytes) else json.dumps(r).encode())


def ok_stub():
    return Stub({"access_token": TOKEN, "token_type": "Bearer", "expires_in": 3600}, SEARCH, ALBUM)


def run(stub, tmp_path, argv=(QUERY,), env=ENV):
    """main's exit code, or the exception it raised (so a test can check the exception's message too)."""
    try:
        return cs.main(list(argv), opener=stub, env=dict(env), out_dir=tmp_path)
    except BaseException as e:                                   # noqa: BLE001 — the secrecy tests read it
        return e


def assert_no_secret(capsys, tmp_path, result):
    out = capsys.readouterr()
    texts = [out.out, out.err] + [p.read_text() for p in tmp_path.rglob("*") if p.is_file()]
    if isinstance(result, BaseException):
        texts += [str(result), repr(result), repr(result.args)]
    for t in texts:
        for bad in (SECRET, TOKEN, BASIC, "Basic ", "Bearer ", "Authorization"):
            assert bad not in t
    return out


def test_captures_search_and_first_album(tmp_path, capsys):
    stub = ok_stub()
    assert run(stub, tmp_path) == 0
    tok, search, album = stub.calls
    assert tok.full_url == "https://accounts.spotify.com/api/token" and tok.get_method() == "POST"
    assert urllib.parse.parse_qs(tok.data.decode()) == {"grant_type": ["client_credentials"]}
    assert tok.get_header("Authorization") == "Basic " + base64.b64encode(f"{ID}:{SECRET}".encode()).decode()
    assert tok.get_header("Content-type") == "application/x-www-form-urlencoded"
    prefix = "https://api.spotify.com/v1/search?type=album,track&limit=10&q="
    assert search.full_url.startswith(prefix) and search.get_method() == "GET"
    assert urllib.parse.unquote_plus(search.full_url[len(prefix):]) == QUERY
    assert album.full_url == "https://api.spotify.com/v1/albums/2nTlIPIQ7fHOnNN7BRch0Z" and album.get_method() == "GET"
    for r in (search, album):
        assert r.get_header("Authorization") == f"Bearer {TOKEN}"
    s = tmp_path / "fixtures" / "spotify_search.captured.json"
    a = tmp_path / "fixtures" / "spotify_album.captured.json"
    assert json.loads(s.read_text()) == SEARCH and json.loads(a.read_text()) == ALBUM
    assert s.read_text() == json.dumps(SEARCH, indent=2, ensure_ascii=False) + "\n"       # pretty-printed
    out = assert_no_secret(capsys, tmp_path, 0)
    assert "spotify_search.captured.json" in out.out and "spotify_album.captured.json" in out.out


def test_words_are_joined_into_one_query(tmp_path):
    stub = ok_stub()
    assert run(stub, tmp_path, argv=["Al", "Green"]) == 0
    assert stub.calls[1].full_url.endswith("&q=Al+Green")


def test_verbose_prints_urls_only(tmp_path, capsys):
    stub = ok_stub()
    assert run(stub, tmp_path, argv=["--verbose", QUERY]) == 0
    out = assert_no_secret(capsys, tmp_path, 0)
    for r in stub.calls:
        assert r.full_url in out.out
    assert "Authorization" not in out.out + out.err and "Bearer" not in out.out + out.err
    assert "Basic" not in out.out + out.err and ID not in out.out + out.err


@pytest.mark.parametrize("env", [{}, {"SPOTIFY_CLIENT_ID": ID}, {"SPOTIFY_CLIENT_SECRET": SECRET},
                                 {"SPOTIFY_CLIENT_ID": "", "SPOTIFY_CLIENT_SECRET": SECRET}])
def test_refuses_without_both_variables(tmp_path, capsys, env):
    stub = ok_stub()
    assert run(stub, tmp_path, env=env) == 2
    out = assert_no_secret(capsys, tmp_path, 2)
    assert "set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET (read -rs " in out.out + out.err
    assert stub.calls == [] and not (tmp_path / "fixtures").exists()


@pytest.mark.parametrize("call", [0, 1, 2])
def test_429_on_any_call_stops_without_retry(tmp_path, capsys, monkeypatch, call):
    monkeypatch.setattr("time.sleep", lambda s: pytest.fail("slept"))
    replies = list(ok_stub().replies)
    replies[call] = (429, b"{}", {"Retry-After": "17"})
    stub = Stub(*replies)
    assert run(stub, tmp_path) == 3
    out = assert_no_secret(capsys, tmp_path, 3)
    assert "rate limited; Retry-After: 17" in out.err
    assert len(stub.calls) == call + 1 and stub.replies == replies[call + 1:]
    assert not (tmp_path / "fixtures").exists()


@pytest.mark.parametrize("headers,shown", [({}, "?"), ({"Retry-After": f"soon {TOKEN}"}, "?")])
def test_429_with_an_odd_retry_after_echoes_nothing(tmp_path, capsys, headers, shown):
    stub = Stub({"access_token": TOKEN}, (429, f"slow down {SECRET}".encode(), headers))
    assert run(stub, tmp_path) == 3
    assert f"rate limited; Retry-After: {shown}" in assert_no_secret(capsys, tmp_path, 3).err


def _echo(code):
    """An error body that repeats the secret and the token, as a hostile or careless server might."""
    return (code, json.dumps({"error": {"status": code, "message": f"bad {SECRET} {TOKEN}"}}).encode(), {})


FAILURES = {
    "token 401": [(401, json.dumps({"error": "invalid_client", "error_description": f"Invalid {SECRET}"}).encode(), {})],
    "token bad JSON": [f"not json {TOKEN}".encode()],
    "token without access_token": [{"token_type": "Bearer"}],
    "search 500": [{"access_token": TOKEN}, _echo(500)],
    "search bad JSON": [{"access_token": TOKEN}, f"<html>{TOKEN}".encode()],
    "search without albums": [{"access_token": TOKEN}, {"tracks": {"items": []}}],
    "album 404": [{"access_token": TOKEN}, SEARCH, _echo(404)],
    "album bad JSON": [{"access_token": TOKEN}, SEARCH, b"{"],
    "unreachable": [urllib.error.URLError(f"refused {SECRET}")],
    "timeout": [{"access_token": TOKEN}, TimeoutError(f"timed out {TOKEN}")],
    "search echoes the token": [{"access_token": TOKEN}, {"albums": {"items": [{"id": "abc", "name": TOKEN}]}}, ALBUM],
    "odd album id": [{"access_token": TOKEN}, {"albums": {"items": [{"id": "../me"}]}}],
    "album echoes the secret": [{"access_token": TOKEN}, SEARCH, {"id": "x", "name": SECRET}],
    "album echoes the Basic value": [{"access_token": TOKEN}, SEARCH, {"id": "x", "name": BASIC}],
    "bad header value": [ValueError(f"Invalid header value b'Bearer {TOKEN}\\n'")],
    "http.client error": [{"access_token": TOKEN}, http.client.RemoteDisconnected(f"closed {TOKEN}")],
    "ssl error": [ssl.SSLError(1, f"bad cert {SECRET}")],
    "read fails": [{"access_token": TOKEN}, ReadFails(http.client.IncompleteRead(TOKEN.encode()))],
    "redirect refused": [(302, b"", {"Location": "https://evil.example/"})],
}


@pytest.mark.parametrize("name", FAILURES)
def test_failures_exit_1_and_leak_nothing(tmp_path, capsys, name):
    stub = Stub(*FAILURES[name])
    result = run(stub, tmp_path)
    out = assert_no_secret(capsys, tmp_path, result)
    assert result == 1, result
    assert out.err.strip()
    assert not (tmp_path / "fixtures").exists()                  # both files or neither


def test_http_error_says_which_call_and_status(tmp_path, capsys):
    assert run(Stub({"access_token": TOKEN}, SEARCH, _echo(404)), tmp_path) == 1
    err = capsys.readouterr().err
    assert "album" in err and "404" in err


@pytest.mark.parametrize("replies,shown", [
    ([(401, json.dumps({"error": "invalid_client", "error_description": "Invalid client"}).encode(), {})],
     "token: HTTP 401 (invalid_client)"),
    ([{"access_token": TOKEN}, (403, json.dumps({"error": {"status": 403, "message":
      "Active premium subscription required for the owner of the app."}}).encode(), {})],
     "search: HTTP 403 (Active premium subscription required for the owner of the app.)"),
    ([{"access_token": TOKEN}, (500, b"<html>oops</html>", {})], "search: HTTP 500"),
])
def test_http_error_shows_spotifys_short_reason(tmp_path, capsys, replies, shown):
    assert run(Stub(*replies), tmp_path) == 1
    assert assert_no_secret(capsys, tmp_path, 1).err.strip().endswith(shown)


def test_skips_a_null_first_album(tmp_path):
    search = {"albums": {"items": [None, {"id": "2nTlIPIQ7fHOnNN7BRch0Z"}]}}
    stub = Stub({"access_token": TOKEN}, search, ALBUM)
    assert run(stub, tmp_path) == 0
    assert stub.calls[2].full_url.endswith("/albums/2nTlIPIQ7fHOnNN7BRch0Z")


def test_second_write_failing_leaves_neither_file(tmp_path, capsys, monkeypatch):
    real = cs.Path.replace
    def fail_album(self, target):
        if "album" in str(target):
            raise OSError("disk full")
        return real(self, target)
    monkeypatch.setattr(cs.Path, "replace", fail_album)
    assert run(ok_stub(), tmp_path) == 1
    assert "disk full" in assert_no_secret(capsys, tmp_path, 1).err
    assert [p.name for p in (tmp_path / "fixtures").iterdir()] == []


def test_default_out_dir_is_the_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "REPO", tmp_path)
    assert cs.main([QUERY], opener=ok_stub(), env=ENV) == 0
    assert (tmp_path / "fixtures" / "spotify_album.captured.json").is_file()


def test_the_default_opener_refuses_redirects():
    """urllib would carry the Authorization header to a redirect's host; the script's own opener follows none."""
    assert any(isinstance(h, cs.NoRedirect) for h in cs.OPENER.handlers)
    req = urllib.request.Request("https://api.spotify.com/v1/albums/x", headers={"Authorization": "Bearer t"})
    with pytest.raises(urllib.error.HTTPError) as e:
        cs.NoRedirect().redirect_request(req, io.BytesIO(), 302, "Found", {}, "https://evil.example/")
    assert e.value.code == 302


def test_docstring_has_the_morning_usage():
    doc = cs.__doc__
    assert ("read -rs SPOTIFY_CLIENT_SECRET; export SPOTIFY_CLIENT_SECRET SPOTIFY_CLIENT_ID=<id>; "
            "python3 -m scripts.capture_spotify \"Al Green I'm Still in Love With You\"") in doc
    assert "catalog data only" in doc and "Michael" in doc and "commit" in doc
