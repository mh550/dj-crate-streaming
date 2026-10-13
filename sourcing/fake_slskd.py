"""In-process fake slskd — just enough of the REST surface SlskdClient uses, for tests and demos.

    with FakeSlskdServer(responses, downloads_dir, files={filename: bytes}) as srv:
        SlskdClient(srv.url, "k")

Searches always complete immediately with `responses` (slskd response shape, see
fixtures/search_responses.sample.json). Enqueueing a file "downloads" it by writing
`files[filename]` under downloads_dir/<username>/<basename>, unless complete=False, in
which case the transfer stays InProgress forever (for timeout tests).
"""
from __future__ import annotations

import json
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class FakeSlskdServer:
    def __init__(self, responses: list[dict], downloads_dir: Path, files: dict[str, bytes],
                 api_key: str = "k", complete: bool = True, port: int = 0):
        self.responses, self.downloads_dir, self.files = responses, Path(downloads_dir), files
        self.api_key, self.complete = api_key, complete
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

    def _download(self, username: str, filename: str, size: int) -> dict:
        self.enqueued.append((username, filename))
        t = {"username": username, "filename": filename, "size": size, "state": "InProgress"}
        if self.complete:
            dest = self.downloads_dir / username / re.split(r"[\\/]", filename)[-1]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(self.files.get(filename, b""))
            t["state"] = "Completed, Succeeded"
        self.transfers.append(t)
        return t

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
                    self._send(fake.transfers)
                elif path.startswith("/api/v0/transfers/downloads/"):
                    user = path.rsplit("/", 1)[1]
                    self._send([t for t in fake.transfers if t["username"] == user])
                else:
                    self._send({"error": "not found"}, 404)

            def do_DELETE(self):
                if not self._auth():
                    return
                fake.searches.pop(urllib.parse.unquote(self.path).rsplit("/", 1)[1], None)
                self._send({})

        return H
