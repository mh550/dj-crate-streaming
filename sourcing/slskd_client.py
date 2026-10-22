"""Minimal slskd REST client (stdlib only) — enough for search → poll → enqueue → watch.

API shape (slskd v0.2x, verified against the official python wrapper + soularr):
  POST /api/v0/searches                       {"searchText": ..., "searchTimeout": ms, "filterResponses": true, ...}
  GET  /api/v0/searches/{id}                  state: "InProgress" | "Completed, ..."
  GET  /api/v0/searches/{id}/responses        [ {username, hasFreeUploadSlot, queueLength, uploadSpeed, files:[...]} ]
  DELETE /api/v0/searches/{id}
  POST /api/v0/transfers/downloads/{username} [ {"filename": ..., "size": ...} ]
  GET  /api/v0/transfers/downloads/{username} → {username, directories:[{directory, files:[{id, filename, state, ...}]}]}
  GET  /api/v0/transfers/downloads            (all users, list of the same objects)
  DELETE /api/v0/transfers/downloads/{username}/{id}?remove=true   (forget a transfer; 0.26.1 keeps the record
                                              without remove=true, and answers 404 for an id it doesn't have)
Downloads land at <downloads>/<remote parent folder>/<basename>.
Auth: X-API-Key header (configure an API key in slskd.yml under web.authentication.api_keys).
Errors: every failed call raises SlskdError, "slskd <method> <endpoint template>: HTTP <code>" or ": <why>" for a
connection error. The template stands in for the peer's name, ids and the URL, so a reason never holds them or the key.
"""
from __future__ import annotations

import http.client
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


class SlskdError(OSError):
    """A failed slskd call; `status` is the HTTP code, None when slskd could not be reached."""

    def __init__(self, method: str, endpoint: str, status: int | None, why: str):
        super().__init__(f"slskd {method} {endpoint}: {why}")
        self.method, self.endpoint, self.status = method, endpoint, status


def _why(e: Exception) -> str:
    """A connection error's cause without its address: URLError wraps the socket error in `reason`, and a
    certificate error's text names the host, so it gives only its kind."""
    r = e.reason if isinstance(e, urllib.error.URLError) else e
    if isinstance(r, ssl.SSLError):
        return getattr(r, "reason", None) or type(r).__name__
    if isinstance(r, http.client.InvalidURL):
        return "invalid URL"
    if isinstance(r, http.client.HTTPException) and not isinstance(r, OSError):
        return type(r).__name__                  # IncompleteRead, BadStatusLine: the name says enough
    if isinstance(r, OSError):
        return r.strerror or str(r) or type(r).__name__
    return "invalid URL"                         # urllib's own text ("unknown url type: <host>") is about the URL


class SlskdClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30):
        self.base = base_url.rstrip("/") + "/api/v0"
        self.key = api_key
        self.timeout = timeout

    def _req(self, method: str, path: str, body: dict | list | None = None, *, endpoint: str) -> object:
        data = json.dumps(body).encode() if body is not None else None
        try:
            req = urllib.request.Request(self.base + path, data=data, method=method, headers={
                "X-API-Key": self.key, "Content-Type": "application/json", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            e.close()
            raise SlskdError(method, endpoint, e.code, f"HTTP {e.code}") from None
        except ValueError:                      # no scheme, a bad port: the text holds the URL
            raise SlskdError(method, endpoint, None, "invalid URL") from None
        except (OSError, http.client.HTTPException) as e:     # URLError, TimeoutError, a reset or cut-off connection
            raise SlskdError(method, endpoint, None, _why(e)) from None
        return json.loads(raw) if raw else None

    # --- searches
    def search(self, text: str, timeout_ms: int = 8000, max_queue: int = 50, min_speed: int = 0) -> str:
        sid = str(uuid.uuid4())
        self._req("POST", "/searches", {"id": sid, "searchText": text, "searchTimeout": timeout_ms, "filterResponses": True,
                                         "maximumPeerQueueLength": max_queue, "minimumPeerUploadSpeed": min_speed},
                  endpoint="/searches")
        return sid

    def search_state(self, sid: str) -> dict:
        return self._req("GET", f"/searches/{sid}", endpoint="/searches/<id>")  # type: ignore[return-value]

    def wait_search(self, sid: str, poll_s: float = 1.0, max_s: float = 30) -> dict:
        t0 = time.time()
        while time.time() - t0 < max_s:
            st = self.search_state(sid)
            if st.get("state") != "InProgress":
                return st
            time.sleep(poll_s)
        return self.search_state(sid)

    def search_responses(self, sid: str, expect: int = 0, poll_s: float = 1.0, tries: int = 5) -> list[dict]:
        """`expect`: the state's responseCount. Live slskd once answered a finished search with 250 counted
        responses as [] (2026-10-21), so an empty read of a search that counted some is read again."""
        got = self._req("GET", f"/searches/{sid}/responses", endpoint="/searches/<id>/responses") or []
        while not got and expect > 0 and tries > 0:
            time.sleep(poll_s)
            tries -= 1
            got = self._req("GET", f"/searches/{sid}/responses", endpoint="/searches/<id>/responses") or []
        return got  # type: ignore[return-value]

    def delete_search(self, sid: str) -> None:
        self._req("DELETE", f"/searches/{sid}", endpoint="/searches/<id>")

    # --- transfers
    def enqueue(self, username: str, files: list[dict]) -> object:
        return self._req("POST", f"/transfers/downloads/{urllib.parse.quote(username)}",
                         [{"filename": f["filename"], "size": f["size"]} for f in files],
                         endpoint="/transfers/downloads/<peer>")

    def downloads(self, username: str | None = None) -> object:
        if not username:
            return self._req("GET", "/transfers/downloads", endpoint="/transfers/downloads")
        try:
            return self._req("GET", f"/transfers/downloads/{urllib.parse.quote(username)}",
                             endpoint="/transfers/downloads/<peer>")
        except SlskdError as e:                 # slskd answers 404 for a peer with no transfers (yet, or any more)
            if e.status == 404:
                return {"username": username, "directories": []}
            raise

    def remove_download(self, username: str, transfer_id: str) -> None:
        try:
            self._req("DELETE", f"/transfers/downloads/{urllib.parse.quote(username)}/{urllib.parse.quote(transfer_id)}"
                                "?remove=true", endpoint="/transfers/downloads/<peer>/<id>")
        except SlskdError as e:                 # 404: already gone
            if e.status != 404:
                raise


def transfer_files(downloads_response: object) -> list[dict]:
    """Flatten slskd's per-user {directories:[{files:[...]}]} shape (or a list of them) into transfer records."""
    users = downloads_response if isinstance(downloads_response, list) else [downloads_response or {}]
    return [f for u in users if isinstance(u, dict) for d in u.get("directories", []) for f in d.get("files", [])]
