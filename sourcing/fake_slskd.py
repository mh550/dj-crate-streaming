"""In-process fake slskd — just enough of the REST surface SlskdClient uses, for tests and demos.

    with FakeSlskdServer(responses, downloads_dir, files={filename: bytes}) as srv:
        SlskdClient(srv.url, "k")

Searches always complete immediately with `responses` (slskd response shape, see
fixtures/search_responses.sample.json). Enqueueing a file "downloads" it the way slskd does:
the bytes land at downloads_dir/<remote parent folder>/<basename>, and transfers are reported
per user as {username, directories:[{directory, files:[{id, filename, state, size}]}]}.
complete=False keeps transfers InProgress forever (timeout tests). fail_enqueue=True makes
POST /transfers/downloads answer 500 (peer gone); a set of peers makes it do so for those peers only. An enqueue
to one of `errored_peers` records a transfer in `error_state` (default `Completed, Errored`) with no file (a VPN
drop). An enqueue to one of `stalled_peers` stays `Queued, Remotely` forever (a peer that never starts, S2-05b).
`posts` lists every enqueue POST as (peer, file count), a refused one included; `deleted` every DELETE of a known
transfer as (peer, filename, remove). DELETE of a transfer acts as slskd 0.26.1 does: without ?remove=true it only cancels (the record stays),
with it the record goes; an unknown id is 404.
"""
from __future__ import annotations

import json
import re
import threading
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .scorer import split_remote


class FakeSlskdServer:
    def __init__(self, responses: list[dict], downloads_dir: Path, files: dict[str, bytes],
                 api_key: str = "k", complete: bool = True, fail_enqueue: bool | set[str] = False, port: int = 0,
                 errored_peers: set[str] = frozenset(), stalled_peers: set[str] = frozenset()):
        self.responses, self.downloads_dir, self.files = responses, Path(downloads_dir), files
        self.api_key, self.complete, self.fail_enqueue = api_key, complete, fail_enqueue
        self.errored_peers, self.error_state = set(errored_peers), "Completed, Errored"
        self.stalled_peers = set(stalled_peers)
        self.searches: dict[str, str] = {}            # id → searchText, until the search is deleted
        self.searched: list[str] = []                 # every searchText, in order
        self.enqueued: list[tuple[str, str]] = []     # (username, filename)
        self.posts: list[tuple[str, int]] = []        # (username, file count): one per POST /transfers/downloads/<peer>
        self.transfers: list[dict] = []
        self.deleted: list[tuple[str, str, bool]] = []  # (username, filename, remove): every DELETE of a transfer
        self.empty_reads = 0                          # this many responses reads answer [] (live slskd, 2026-10-21)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    def seed_transfer(self, username: str, filename: str, state: str, transfer_id: str | None = None) -> dict:
        """Pretend an earlier attempt left this record behind (slskd keeps completed transfers)."""
        t = {"id": transfer_id or str(uuid.uuid4()), "username": username, "filename": filename, "size": 0,
             "state": state}
        self.transfers.append(t)
        return t

    def _download(self, username: str, filename: str, size: int) -> dict:
        self.enqueued.append((username, filename))
        t = {"id": str(uuid.uuid4()), "username": username, "filename": filename, "size": size, "state": "InProgress"}
        if username in self.errored_peers:
            t["state"] = self.error_state
        elif username in self.stalled_peers:
            t["state"] = "Queued, Remotely"
        elif self.complete:
            folder, base = split_remote(filename)
            dest = self.downloads_dir / folder / base
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(self.files.get(filename, b""))
            t["state"] = "Completed, Succeeded"
        self.transfers.append(t)
        return t

    def _user_view(self, username: str) -> dict:
        # sorted by id: slskd's real order isn't captured, so no code may rely on it (e.g. "the last is the newest")
        dirs: dict[str, list[dict]] = {}
        for t in sorted(self.transfers, key=lambda t: t["id"]):
            if t["username"] == username:
                dirs.setdefault(split_remote(t["filename"])[0], []).append(t)
        return {"username": username, "directories": [{"directory": d, "files": fs} for d, fs in dirs.items()]}

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, payload, code=200):
                raw = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n)) if n else None

            def _auth(self) -> bool:
                if self.headers.get("X-API-Key") == fake.api_key:
                    return True
                self._send({"error": "unauthorized"}, 401)
                return False

            def do_POST(self):
                if not self._auth():
                    return
                path = urllib.parse.unquote(self.path)
                body = self._body()
                if path == "/api/v0/searches":
                    fake.searches[body["id"]] = body["searchText"]
                    fake.searched.append(body["searchText"])
                    self._send({"id": body["id"], "state": "Completed, Succeeded"})
                elif path.startswith("/api/v0/transfers/downloads/"):
                    user = path.rsplit("/", 1)[1]
                    fake.posts.append((user, len(body)))
                    if fake.fail_enqueue is True or user in (fake.fail_enqueue or ()):
                        return self._send({"error": "peer unreachable"}, 500)
                    self._send([fake._download(user, f["filename"], f.get("size", 0)) for f in body])
                else:
                    self._send({"error": "not found"}, 404)

            def do_GET(self):
                if not self._auth():
                    return
                path = urllib.parse.unquote(self.path)
                m = re.fullmatch(r"/api/v0/searches/([^/]+)(/responses)?", path)
                if m and m.group(1) in fake.searches:
                    if m.group(2):
                        if fake.empty_reads > 0:
                            fake.empty_reads -= 1
                            return self._send([])
                        self._send(fake.responses)
                    else:
                        self._send({"id": m.group(1), "state": "Completed, Succeeded", "responseCount": len(fake.responses)})
                elif path == "/api/v0/transfers/downloads":
                    users = sorted({t["username"] for t in fake.transfers})
                    self._send([fake._user_view(u) for u in users])
                elif path.startswith("/api/v0/transfers/downloads/"):
                    view = fake._user_view(path.rsplit("/", 1)[1])
                    if view["directories"]:
                        self._send(view)
                    else:                       # real slskd (0.26) answers 404 for a peer with no transfers
                        self._send({"error": "not found"}, 404)
                else:
                    self._send({"error": "not found"}, 404)

            def do_DELETE(self):
                if not self._auth():
                    return
                parts = urllib.parse.urlsplit(self.path)
                path = urllib.parse.unquote(parts.path)
                m = re.fullmatch(r"/api/v0/transfers/downloads/([^/]+)/([^/]+)", path)
                if not m:
                    fake.searches.pop(path.rsplit("/", 1)[1], None)
                    return self._send({})
                t = next((t for t in fake.transfers if t["username"] == m.group(1) and t["id"] == m.group(2)), None)
                if t is None:
                    return self._send({"error": "not found"}, 404)
                remove = "true" in urllib.parse.parse_qs(parts.query).get("remove", [])
                fake.deleted.append((t["username"], t["filename"], remove))
                if remove:
                    fake.transfers.remove(t)
                elif not t["state"].startswith("Completed"):      # a plain DELETE cancels; the record stays
                    t["state"] = "Completed, Cancelled"
                self.send_response(204)
                self.end_headers()

        return H
