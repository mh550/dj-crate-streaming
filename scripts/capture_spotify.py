"""Capture real Spotify Web API responses for the next provider's fixtures (spec S3-06, morning checklist step 6).

Michael runs it once, on the host, from a checkout of the run's branch, with his own developer app (Web API):

    read -rs SPOTIFY_CLIENT_SECRET; export SPOTIFY_CLIENT_SECRET SPOTIFY_CLIENT_ID=<id>; python3 -m scripts.capture_spotify "Al Green I'm Still in Love With You"

It makes three requests and stops: one Client Credentials token (POST https://accounts.spotify.com/api/token), one
GET /v1/search?type=album,track&limit=10&q=<query>, and one GET /v1/albums/<first album id>. It then writes the two
bodies, pretty-printed, to fixtures/spotify_search.captured.json and fixtures/spotify_album.captured.json (both or
neither). They are catalog data only (no account, no token), and Michael reads and commits them himself; the build
run never runs this script.

The secret and the token are sent in the Authorization header and nowhere else: they are never printed (`--verbose`
prints the URLs only), never written, and never in an error message; a reply that repeats either one is refused,
and a redirect is an error (urllib would carry the Authorization header to the new host).

Exit 0 written, 1 a failed call or an unexpected reply (one line on stderr), 2 SPOTIFY_CLIENT_ID or
SPOTIFY_CLIENT_SECRET unset (before any request), 3 rate limited (HTTP 429: it prints Retry-After and does not wait
or retry). Stdlib only.
"""
from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
TIMEOUT_S = 15
SEARCH_FILE = "fixtures/spotify_search.captured.json"
ALBUM_FILE = "fixtures/spotify_album.captured.json"
REPO = Path(__file__).resolve().parent.parent
SPOTIFY_ID = re.compile(r"[A-Za-z0-9]{1,64}")
REASON = re.compile(r"[A-Za-z0-9_ .,'()-]{1,120}")
ENV_HINT = ("set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET (read -rs SPOTIFY_CLIENT_SECRET; "
            "export SPOTIFY_CLIENT_SECRET SPOTIFY_CLIENT_ID=<id>)")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib copies the Authorization header to a redirect's host; a redirect here is an HTTP error instead."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


OPENER = urllib.request.build_opener(NoRedirect)


class Stop(Exception):
    """One line for stderr (already free of the secret and the token) and the exit code."""

    def __init__(self, line: str, code: int = 1):
        super().__init__(line)
        self.code = code


def _call(what: str, req: urllib.request.Request, opener, verbose: bool, secrets: tuple[str, ...]) -> dict:
    """The JSON body of one request. Errors carry the call's name, the status and Spotify's short reason (when it is
    plain words and repeats no secret), never a header."""
    if verbose:
        print(f"{req.get_method()} {req.full_url}")
    try:
        with opener(req, timeout=TIMEOUT_S) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise Stop(f"rate limited; Retry-After: {_retry_after(e)}", 3) from None
        reason = _reason(e, secrets)
        raise Stop(f"{what}: HTTP {e.code}" + (f" ({reason})" if reason else "")) from None
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:
        raise Stop(f"{what}: request failed ({type(e).__name__})") from None
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Stop(f"{what}: the reply is not JSON") from None
    if not isinstance(body, dict):
        raise Stop(f"{what}: the reply is not a JSON object")
    return body


def _reason(e: urllib.error.HTTPError, secrets: tuple[str, ...]) -> str:
    """The token endpoint's `error` ("invalid_client") or the Web API's `error.message`, else ""."""
    try:
        body = json.loads(e.read(4096).decode("utf-8"))
    except Exception:                                   # noqa: BLE001 — any unreadable body means no reason
        return ""
    err = body.get("error") if isinstance(body, dict) else None
    text = err.get("message") if isinstance(err, dict) else err
    if not isinstance(text, str) or not REASON.fullmatch(text) or any(x in text for x in secrets):
        return ""
    return text


def _retry_after(e: urllib.error.HTTPError) -> str:
    value = (e.headers.get("Retry-After") if e.headers is not None else None) or "?"
    return value if value.isdigit() else "?"            # seconds; anything else is not echoed


def capture(query: str, client_id: str, secret: str, opener, verbose: bool) -> tuple[str, str]:
    """The search and album bodies as the text to write."""
    basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    token_req = urllib.request.Request(
        TOKEN_URL, data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(), method="POST",
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"})
    secrets = (secret, basic)
    token = _call("token", token_req, opener, verbose, secrets).get("access_token")
    if not isinstance(token, str) or not token:
        raise Stop("token: the reply has no access_token")
    secrets += (token,)
    bearer = {"Authorization": f"Bearer {token}"}
    url = f"{API}/search?type=album,track&limit=10&" + urllib.parse.urlencode({"q": query})
    search = _call("search", urllib.request.Request(url, headers=bearer), opener, verbose, secrets)
    albums = search.get("albums")
    items = albums.get("items") if isinstance(albums, dict) else None
    first = next((i for i in items if isinstance(i, dict)), None) if isinstance(items, list) else None
    if first is None:
        raise Stop("search: no album in the results; try other words")
    album_id = first.get("id")
    if not isinstance(album_id, str) or not SPOTIFY_ID.fullmatch(album_id):
        raise Stop("search: the first album's id is not a Spotify id")
    album = _call("album", urllib.request.Request(f"{API}/albums/{album_id}", headers=bearer), opener, verbose,
                  secrets)
    texts = {}
    for name, body in (("search", search), ("album", album)):
        texts[name] = json.dumps(body, indent=2, ensure_ascii=False) + "\n"      # checked as written
        if any(x in texts[name] for x in secrets):
            raise Stop(f"{name}: the reply repeats the secret or the token; nothing written")
    return texts["search"], texts["album"]


def write_both(out: Path, texts: list[tuple[str, str]]) -> list[Path]:
    """Each file to `<name>.tmp` first, renamed only when both are written: both files or neither."""
    tmps = []
    try:
        for rel, text in texts:
            tmp = out / (rel + ".tmp")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(text, encoding="utf-8")
            tmps.append(tmp)
        done = []
        for tmp in tmps:
            done.append(tmp.replace(tmp.with_suffix("")))
        return done
    except OSError:
        for p in tmps + [t.with_suffix("") for t in tmps]:
            p.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None, *, opener=None, env=None, out_dir: Path | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m scripts.capture_spotify",
                                 description="Capture one Spotify search and one album as fixtures.")
    ap.add_argument("query", nargs="+", help="search words, e.g. an artist and an album title")
    ap.add_argument("--verbose", action="store_true", help="print each request's method and URL")
    a = ap.parse_args(argv)
    env = os.environ if env is None else env
    client_id, secret = env.get("SPOTIFY_CLIENT_ID", ""), env.get("SPOTIFY_CLIENT_SECRET", "")
    if not client_id or not secret:
        print(ENV_HINT, file=sys.stderr)
        return 2
    try:
        search, album = capture(" ".join(a.query), client_id, secret, opener or OPENER.open, a.verbose)
        written = write_both(REPO if out_dir is None else Path(out_dir), [(SEARCH_FILE, search), (ALBUM_FILE, album)])
    except Stop as e:
        print(f"capture_spotify: {e}", file=sys.stderr)
        return e.code
    except OSError as e:                                # the files only: no request is made after this point
        print(f"capture_spotify: cannot write the fixtures ({e}); nothing written", file=sys.stderr)
        return 1
    for path in written:
        print(f"wrote {path}")
    print("catalog data only: read both files, then commit them yourself")
    return 0


if __name__ == "__main__":
    sys.exit(main())
