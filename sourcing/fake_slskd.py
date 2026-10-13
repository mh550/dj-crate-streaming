"""In-process fake slskd — just enough of the REST surface SlskdClient uses, for tests and demos.

    with FakeSlskdServer(responses, downloads_dir, files={filename: bytes}) as srv:
        SlskdClient(srv.url, "k")

Searches always complete immediately with `responses` (slskd response shape, see
fixtures/search_responses.sample.json). Enqueueing a file "downloads" it the way slskd does:
the bytes land at downloads_dir/<remote parent folder>/<basename>, and transfers are reported
per user as {username, directories:[{directory, files:[{id, filename, state, size}]}]}.
complete=False keeps transfers InProgress forever (timeout tests); fail_enqueue=True makes
POST /transfers/downloads answer 500 (peer gone).
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
                 api_key: str = "k", complete: bool = True, fail_enqueue: bool = False, port: int = 0):
        self.responses, self.downloads_dir, self.files = responses, Path(downloads_dir), files
        self.api_key, self.complete, self.fail_enqueue = api_key, complete, fail_enqueue
        self.searches: dict[str, str] = {}            # id → searchText
        self.enqueued: list[tuple[str, str]] = []     # (username, filename)
        self.transfers: list[dict] = []
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

    def seed_transfer(self, username: str, filename: str, state: str) -> dict:
        """Pretend an earlier attempt left this record behind (slskd keeps completed transfers)."""
        t = {"id": str(uuid.uuid4()), "username": username, "filename": filename, "size": 0, "state": state}
        self.transfers.append(t)
        return t

    def _download(self, username: str, filename: str, size: int) -> dict:
        self.enqueued.append((username, filename))
        t = {"id": str(uuid.uuid4()), "username": username, "filename": filename, "size": size, "state": "InProgress"}
        if self.complete:
            folder, base = split_remote(filename)
            dest = self.downloads_dir / folder / base
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(self.files.get(filename, b""))
            t["state"] = "Completed, Succeeded"
        self.transfers.append(t)
        return t

    def _user_view(self, username: str) -> dict:
        dirs: dict[str, list[dict]] = {}
        for t in self.transfers:
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
                    self._send({"id": body["id"], "state": "Completed, Succeeded"})
                elif path.startswith("/api/v0/transfers/downloads/"):
                    if fake.fail_enqueue:
                        return self._send({"error": "peer unreachable"}, 500)
                    user = path.rsplit("/", 1)[1]
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
                        self._send(fake.responses)
                    else:
                        self._send({"id": m.group(1), "state": "Completed, Succeeded", "responseCount": len(fake.responses)})
                elif path == "/api/v0/transfers/downloads":
                    users = sorted({t["username"] for t in fake.transfers})
                    self._send([fake._user_view(u) for u in users])
                elif path.startswith("/api/v0/transfers/downloads/"):
                    self._send(fake._user_view(path.rsplit("/", 1)[1]))
                else:
                    self._send({"error": "not found"}, 404)

            def do_DELETE(self):
                if not self._auth():
                    return
                path = urllib.parse.unquote(self.path)
                m = re.fullmatch(r"/api/v0/transfers/downloads/([^/]+)/([^/]+)", path)
                if m:
                    fake.transfers = [t for t in fake.transfers if not (t["username"] == m.group(1) and t["id"] == m.group(2))]
                else:
                    fake.searches.pop(path.rsplit("/", 1)[1], None)
                self._send({})

        return H
