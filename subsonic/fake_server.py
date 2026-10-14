"""An in-process fake OpenSubsonic server — enough of the protocol for tests and for
developing the client UI before the real Navidrome box exists.

Faithful where it matters (auth check, response envelope, error codes, playlist
add-by-id/remove-by-index, per-player transcoding decision), toy everywhere else.

    python -m subsonic.fake_server --port 4533          # then point anything Subsonic at it
    user: demo / password: demo
"""
from __future__ import annotations

import argparse
import hashlib
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

API_VERSION = "1.16.1"


def _fold(s: str) -> str:
    """Navidrome's full-text search is case-, accent- and punctuation-insensitive; so is the fake."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in s if not unicodedata.combining(ch)).casefold()

# A small library that exercises the crate policy: lossless, hi-res, 320 mp3, 128 mp3.
SAMPLE_SONGS = [
    {"id": "s1", "title": "Good Times", "artist": "Chic", "album": "Risqué", "year": 1979, "track": 3,
     "duration": 501, "bitRate": 880, "suffix": "flac", "contentType": "audio/flac", "size": 55219000,
     "samplingRate": 44100, "bitDepth": 16, "path": "Chic/Risqué (1979)/03 - Good Times.flac", "coverArt": "al-1", "albumId": "al-1"},
    {"id": "s2", "title": "I Feel Love", "artist": "Donna Summer", "album": "I Remember Yesterday", "year": 1977, "track": 8,
     "duration": 356, "bitRate": 2550, "suffix": "flac", "contentType": "audio/flac", "size": 113000000,
     "samplingRate": 96000, "bitDepth": 24, "path": "Donna Summer/I Remember Yesterday (1977)/08 - I Feel Love.flac", "coverArt": "al-2", "albumId": "al-2"},
    {"id": "s3", "title": "Move Your Body", "artist": "Marshall Jefferson", "album": "The House Music Anthem", "year": 1986, "track": 1,
     "duration": 383, "bitRate": 320, "suffix": "mp3", "contentType": "audio/mpeg", "size": 15320000,
     "samplingRate": 44100, "path": "Marshall Jefferson/The House Music Anthem/01 - Move Your Body.mp3", "coverArt": "al-3", "albumId": "al-3"},
    {"id": "s4", "title": "Can You Feel It", "artist": "Mr. Fingers", "album": "Washing Machine", "year": 1986, "track": 2,
     "duration": 340, "bitRate": 128, "suffix": "mp3", "contentType": "audio/mpeg", "size": 5440000,
     "samplingRate": 44100, "path": "Mr. Fingers/Washing Machine/02 - Can You Feel It.mp3", "coverArt": "al-4", "albumId": "al-4"},
    {"id": "s5", "title": "Strings of Life", "artist": "Rhythim Is Rhythim", "album": "Strings of Life", "year": 1987, "track": 1,
     "duration": 480, "bitRate": 950, "suffix": "flac", "contentType": "audio/flac", "size": 57000000,
     "samplingRate": 44100, "bitDepth": 16, "path": "Rhythim Is Rhythim/Strings of Life/01 - Strings of Life.flac", "coverArt": "al-5", "albumId": "al-5"},
]

SAMPLE_PLAYLISTS = [
    {"id": "pl-1", "name": "Disco Edits", "comment": "", "owner": "demo", "public": False, "songs": ["s1", "s2", "s3"]},
    {"id": "pl-2", "name": "Chicago 86", "comment": "warmup #crate", "owner": "demo", "public": False, "songs": ["s3", "s4", "s5"]},
    {"id": "pl-3", "name": "Sunday Listening", "comment": "", "owner": "demo", "public": False, "songs": ["s2"]},
]

# 1x1 transparent PNG for getCoverArt
_PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8ffff3f0300050001c3da3a9a0000000049454e44ae426082")


class FakeState:
    def __init__(self, username: str = "demo", password: str = "demo"):
        self.username, self.password = username, password
        self.songs = {s["id"]: dict(s) for s in SAMPLE_SONGS}
        self.playlists = {p["id"]: dict(p, songs=list(p["songs"])) for p in SAMPLE_PLAYLISTS}
        self.players: dict[tuple[str, str], dict] = {}   # (user, client) → {"format": ..., "maxBitRate": ...}
        self.scanning = False
        self.requests: list[tuple[str, dict]] = []       # (method, params) log for tests
        self.lock = threading.Lock()

    def auth_ok(self, q: dict) -> bool:
        if q.get("u") != self.username:
            return False
        if "t" in q and "s" in q:
            return hashlib.md5((self.password + q["s"]).encode()).hexdigest() == q["t"]
        if "p" in q:   # legacy: plain or enc:<hex>
            p = q["p"]
            if p.startswith("enc:"):
                p = bytes.fromhex(p[4:]).decode()
            return p == self.password
        return False

    def playlist_json(self, p: dict, with_entries: bool) -> dict:
        songs = [self.songs[s] for s in p["songs"] if s in self.songs]
        d = {"id": p["id"], "name": p["name"], "comment": p.get("comment", ""), "owner": p["owner"],
             "songCount": len(songs), "duration": sum(s["duration"] for s in songs),
             "created": "2026-09-17T00:00:00Z", "changed": "2026-09-17T00:00:00Z"}
        if p.get("public"):            # Navidrome omits the key when false (fixture: getPlaylists_sample)
            d["public"] = True
        if with_entries:
            d["entry"] = [dict(s, isDir=False, type="music") for s in songs]
        return d


def _resp(payload: dict | None = None, error: tuple[int, str] | None = None) -> bytes:
    env = {"status": "ok" if not error else "failed", "version": API_VERSION, "type": "fake-navidrome",
           "serverVersion": "0.0.0-fake", "openSubsonic": True}
    if error:
        env["error"] = {"code": error[0], "message": error[1]}
    if payload:
        env.update(payload)
    return json.dumps({"subsonic-response": env}).encode()


def make_handler(state: FakeState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):   # quiet
            pass

        def _send(self, body: bytes, ctype: str = "application/json", status: int = 200, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):   # OpenSubsonic formPost: same params, in the body
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode() if length else ""
            self._handle(self.path.split("?")[0], parse_qs(body, keep_blank_values=True))

        def do_GET(self):
            u = urlparse(self.path)
            self._handle(u.path, parse_qs(u.query, keep_blank_values=True))

        def _handle(self, path: str, qs: dict[str, list[str]]):
            if not path.startswith("/rest/"):
                return self._send(b"not found", "text/plain", 404)
            method = path[len("/rest/"):].removesuffix(".view")
            q = {k: v[0] for k, v in qs.items()}
            multi = qs
            with state.lock:
                state.requests.append((method, q))
                # getOpenSubsonicExtensions is the one method the spec says must be reachable unauthenticated.
                if method != "getOpenSubsonicExtensions" and not state.auth_ok(q):
                    return self._send(_resp(error=(40, "Wrong username or password")))
                # Navidrome creates a Player per (user, client name) on first contact.
                state.players.setdefault((q.get("u", ""), q.get("c", "")), {"format": None, "maxBitRate": 0})
                fn = getattr(self, "m_" + method, None)
                if not fn:
                    return self._send(_resp(error=(0, f"unknown method {method}")))
                return fn(q, multi)

        # --- methods
        def m_ping(self, q, m):
            self._send(_resp())

        def m_getOpenSubsonicExtensions(self, q, m):
            self._send(_resp({"openSubsonicExtensions": [{"name": "formPost", "versions": [1]},
                                                          {"name": "transcodeOffset", "versions": [1]},
                                                          {"name": "songLyrics", "versions": [1]}]}))

        def m_getScanStatus(self, q, m):
            self._send(_resp({"scanStatus": {"scanning": state.scanning, "count": len(state.songs)}}))

        def m_startScan(self, q, m):
            self._send(_resp({"scanStatus": {"scanning": True, "count": len(state.songs)}}))

        def m_getPlaylists(self, q, m):
            self._send(_resp({"playlists": {"playlist": [state.playlist_json(p, False) for p in state.playlists.values()]}}))

        def m_getPlaylist(self, q, m):
            p = state.playlists.get(q.get("id", ""))
            if not p:
                return self._send(_resp(error=(70, "Playlist not found")))
            self._send(_resp({"playlist": state.playlist_json(p, True)}))

        def m_createPlaylist(self, q, m):
            if "name" not in q:
                return self._send(_resp(error=(10, "Required parameter is missing: name")))
            pid = "pl-" + uuid.uuid4().hex[:6]
            state.playlists[pid] = {"id": pid, "name": q["name"], "comment": "", "owner": q["u"], "public": False,
                                    "songs": [s for s in m.get("songId", []) if s in state.songs]}
            self._send(_resp({"playlist": state.playlist_json(state.playlists[pid], True)}))

        def m_updatePlaylist(self, q, m):
            p = state.playlists.get(q.get("playlistId", ""))
            if not p:
                return self._send(_resp(error=(70, "Playlist not found")))
            if "name" in q: p["name"] = q["name"]
            if "comment" in q: p["comment"] = q["comment"]
            if "public" in q: p["public"] = q["public"] == "true"
            for idx in sorted((int(i) for i in m.get("songIndexToRemove", [])), reverse=True):
                if 0 <= idx < len(p["songs"]):
                    p["songs"].pop(idx)
            p["songs"].extend(s for s in m.get("songIdToAdd", []) if s in state.songs)
            self._send(_resp())

        def m_deletePlaylist(self, q, m):
            state.playlists.pop(q.get("id", ""), None)
            self._send(_resp())

        def m_getSong(self, q, m):
            s = state.songs.get(q.get("id", ""))
            if not s:
                return self._send(_resp(error=(70, "Song not found")))
            self._send(_resp({"song": dict(s, isDir=False, type="music")}))

        def m_search3(self, q, m):
            words = _fold(q.get("query", "")).split()      # Navidrome: every word must match somewhere
            hits = [dict(s, isDir=False, type="music") for s in state.songs.values()
                    if all(w in _fold(f"{s['title']} {s['artist']} {s['album']}") for w in words)]
            n, off = int(q.get("songCount", 20)), int(q.get("songOffset", 0))
            self._send(_resp({"searchResult3": {"song": hits[off:off + n]}}))

        def m_stream(self, q, m):
            """Mirror Navidrome's decision: the player's profile applies unless the request
            overrides with format/maxBitRate; format=raw always means the original bytes."""
            s = state.songs.get(q.get("id", ""))
            if not s:
                return self._send(_resp(error=(70, "Song not found")))
            player = state.players.get((q.get("u", ""), q.get("c", "")), {"format": None, "maxBitRate": 0})
            fmt = q.get("format")
            cap = int(q.get("maxBitRate") or 0)
            if fmt == "raw":
                target = None
            elif fmt and fmt != s["suffix"]:
                target = fmt                                   # explicit different format → transcode
            elif fmt == s["suffix"]:
                target = None                                  # same format → direct play
            elif cap and cap < s["bitRate"]:
                target = "opus"                                # DefaultDownsamplingFormat
            elif player["format"] and player["format"] != s["suffix"]:
                target = player["format"]; cap = cap or player["maxBitRate"]   # forced player profile
            elif player["maxBitRate"] and player["maxBitRate"] < s["bitRate"]:
                target = "opus"; cap = player["maxBitRate"]
            else:
                target = None
            if target is None:
                ctype, note = s["contentType"], "raw"
            else:
                ctype, note = {"mp3": "audio/mpeg", "opus": "audio/ogg", "aac": "audio/aac", "flac": "audio/flac"}.get(target, "application/octet-stream"), f"transcoded:{target}@{cap or 'default'}"
            self._send(f"FAKEAUDIO {s['id']} {note}".encode(), ctype, extra={"X-Fake-Transcode": note, "Accept-Ranges": "bytes"})

        def m_download(self, q, m):
            s = state.songs.get(q.get("id", ""))
            if not s:
                return self._send(_resp(error=(70, "Song not found")))
            self._send(f"FAKEAUDIO {s['id']} original".encode(), s["contentType"])

        def m_getCoverArt(self, q, m):
            self._send(_PNG, "image/png")

    return Handler


class FakeSubsonicServer:
    """Context-manager wrapper: `with FakeSubsonicServer() as srv: SubsonicClient(srv.url, 'demo', 'demo')`."""

    def __init__(self, port: int = 0, username: str = "demo", password: str = "demo"):
        self.state = FakeState(username, password)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(self.state))
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="fake OpenSubsonic server for offline development")
    ap.add_argument("--port", type=int, default=4533)
    a = ap.parse_args(argv)
    srv = FakeSubsonicServer(a.port)
    print(f"fake subsonic on {srv.url}  (user demo / pass demo)  Ctrl-C to stop")
    with srv:
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
