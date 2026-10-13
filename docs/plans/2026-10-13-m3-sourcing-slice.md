# M3 — Phase 1 sourcing slice: wanted → search → score → (approved) download → verify → file → rescan → ok

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** done 2026-10-13 — tasks 1–6, fresh-context review (3 critical / 5 important fixed, 4 minors deferred) and a /simplify pass applied; 80 tests. Follow-up recorded in README "Not done yet": a `sourcing_jobs` table before any background runner.

**Goal:** One CLI command takes one wanted track all the way from `needs_source` to `ok` in the crate store, fully tested against an in-process fake slskd and the existing fake Navidrome; without `--approve` it stops after scoring and prints the pick.

**Architecture:** A new `sourcing/fetch.py` orchestrates existing pieces (`scorer.rank`, `verify.verify`, `SlskdClient`, `SubsonicClient`, `CrateStore`) plus two small new ones: `sourcing/organize.py` (file a verified download into `Artist/Album (Year)/NN - Title.ext`, collision-safe) and `sourcing/fake_slskd.py` (an HTTP fake mirroring `subsonic/fake_server.py`). The crate store gains an `external_wanted` table so a Spotify playlist can seed the queue for tracks that aren't in Navidrome at all. Status flow uses the store's existing names: `needs_source → sourcing → verify → ok | failed`.

**Tech Stack:** Python 3.10+ stdlib only (`http.server`, `urllib`, `sqlite3`, `shutil`), pytest via `~/.local/bin/pytest`. ffmpeg/ffprobe only at runtime, never in tests (FLAC headers are parsed in pure Python by `sourcing.verify.flac_streaminfo`).

**Spec:** `~/projects/OVERNIGHT.md` §M3 and `~/projects/ideas/dj-crate-streaming/spec.md` (search → score → download → verify). Out of scope: background jobs, MusicBrainz lookups, AcoustID, analysis, live Soulseek transfers (rule 5: downloads only with `--approve`, and the live stack isn't up until M4).

## Global Constraints

- stdlib only in `sourcing/`, `crates/`, `subsonic/` (README: "Python 3.10+, stdlib only").
- Never move or modify anything under `/srv/incoming/library-import/`; downloads live under `/srv/incoming/<slskd-user>/…` and are *moved* into `/srv/music` (same filesystem, our own files).
- Never overwrite an existing file in `/srv/music`; collisions get ` (2)`, ` (3)` … suffixes.
- Layout written by organize must equal beets' `deploy/beets.yaml` path format: `$albumartist/$album ($year)/$track - $title.ext`, `Singles/` when no album, no `(0000)` when no year.
- `python3 -m pytest` is not available; run `~/.local/bin/pytest -q`. Suite must stay green (54 today).
- Store statuses are the existing `STATUSES = ("ok", "needs_source", "sourcing", "verify", "failed", "removed")` — do not add names.

## Review Focus

1. A download that never completes (peer goes away): `fetch` must time out, set `failed` with reason "download timed out", and leave nothing half-filed in `/srv/music`. → Task 4 `test_fetch_download_timeout_fails_cleanly`.
2. The top-scored candidate is `rejected` (e.g. locked or wrong length) and no other passes: `fetch` reports "no acceptable candidate", status stays `needs_source` (not `failed`, so it is retried when peers change). → Task 4 `test_fetch_no_acceptable_candidate_leaves_needs_source`.
3. Verified file whose tags don't match (Navidrome can't find it after rescan): status `verify` with reason naming the filed path, never `ok` on a guess. → Task 4 `test_fetch_filed_but_not_found_after_rescan`.
4. The same wanted song sits in two crates: the playlist swap must happen in both and both rows end `ok`. → Task 4 `test_fetch_swaps_song_in_every_crate`.
5. Titles with `/`, `:` or leading/trailing dots must produce a safe single path component. → Task 2 `test_target_path_sanitises_components`.

---

### Task 1: Fake slskd server (search + enqueue + download completion)

**Files:**
- Create: `sourcing/fake_slskd.py`
- Create: `tests/helpers.py` (move `make_flac` here from `tests/test_verify.py:7-13`)
- Modify: `tests/test_verify.py:7-13` (import `make_flac` from helpers instead of defining it)
- Test: `tests/test_fake_slskd.py`

**Interfaces:**
- Consumes: `sourcing.slskd_client.SlskdClient` (unchanged), fixture shape of `fixtures/search_responses.sample.json`.
- Produces: `class FakeSlskdServer(responses: list[dict], downloads_dir: Path, files: dict[str, bytes], api_key="k", complete=True)` context manager with `.url`; `.enqueued: list[tuple[str, str]]` (username, filename). On enqueue, if `complete`, it writes `files[filename]` to `downloads_dir/<username>/<basename>` and reports the transfer as `{"state": "Completed, Succeeded", "filename": ..., "username": ...}` from `GET /api/v0/transfers/downloads`; if `complete=False` the transfer stays `"InProgress"` forever.

- [ ] **Step 1: Move `make_flac` into `tests/helpers.py`**

```python
# tests/helpers.py
"""Shared test helpers (no pytest fixtures here; plain functions)."""
import struct
from pathlib import Path


def make_flac(path: Path, sr=44100, bps=16, ch=2, total=44100 * 300, pad_bytes=0) -> Path:
    """Write a file with a valid FLAC STREAMINFO header and `pad_bytes` of zeros as the 'audio'."""
    hdr = b"fLaC"
    # STREAMINFO: last-block flag + type 0, length 34
    hdr += bytes([0x80]) + (34).to_bytes(3, "big")
    minblk, maxblk, minfrm, maxfrm = 4096, 4096, 0, 0
    body = struct.pack(">HH", minblk, maxblk) + minfrm.to_bytes(3, "big") + maxfrm.to_bytes(3, "big")
    packed = (sr << 44) | ((ch - 1) << 41) | ((bps - 1) << 36) | total
    body += packed.to_bytes(8, "big") + bytes(16)
    path.write_bytes(hdr + body + bytes(pad_bytes))
    return path
```

Replace the `make_flac` definition in `tests/test_verify.py` with `from tests.helpers import make_flac` (keep the three tests unchanged). If the existing body differs from the above, keep the existing body — only its location changes.

- [ ] **Step 2: Run the verify tests to confirm nothing broke**

Run: `~/.local/bin/pytest -q tests/test_verify.py`
Expected: 3 passed

- [ ] **Step 3: Write the failing fake-slskd tests**

```python
# tests/test_fake_slskd.py
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
```

- [ ] **Step 4: Run to verify it fails**

Run: `~/.local/bin/pytest -q tests/test_fake_slskd.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'sourcing.fake_slskd'`

- [ ] **Step 5: Implement the fake**

```python
# sourcing/fake_slskd.py
"""In-process fake slskd — just enough of the REST surface SlskdClient uses, for tests and demos.

    with FakeSlskdServer(responses, downloads_dir, files={filename: bytes}) as srv:
        SlskdClient(srv.url, "k")

Searches always complete immediately with `responses` (slskd response shape, see
fixtures/search_responses.sample.json). Enqueueing a file "downloads" it by writing
`files[filename]` under downloads_dir/<username>/<basename>, unless complete=False.
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
        self.thread.start(); return self

    def __exit__(self, *exc):
        self.httpd.shutdown(); self.httpd.server_close()

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
            def log_message(self, *a):  # silence
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
                self._send({"error": "unauthorized"}, 401); return False

            def do_POST(self):
                if not self._auth(): return
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
                if not self._auth(): return
                path = urllib.parse.unquote(self.path)
                m = re.fullmatch(r"/api/v0/searches/([^/]+)(/responses)?", path)
                if m and m.group(1) in fake.searches:
                    if m.group(2):
                        self._send(fake.responses)
                    else:
                        self._send({"id": m.group(1), "state": "Completed, Succeeded",
                                    "responseCount": len(fake.responses)})
                elif path == "/api/v0/transfers/downloads":
                    self._send(fake.transfers)
                elif path.startswith("/api/v0/transfers/downloads/"):
                    user = path.rsplit("/", 1)[1]
                    self._send([t for t in fake.transfers if t["username"] == user])
                else:
                    self._send({"error": "not found"}, 404)

            def do_DELETE(self):
                if not self._auth(): return
                sid = urllib.parse.unquote(self.path).rsplit("/", 1)[1]
                fake.searches.pop(sid, None)
                self._send(None, 204) if False else self._send({})

        return H
```

Note: `SlskdClient._req` treats an empty body as `None`; sending `{}` on DELETE is fine.

- [ ] **Step 6: Run to verify it passes**

Run: `~/.local/bin/pytest -q tests/test_fake_slskd.py tests/test_verify.py`
Expected: 7 passed

- [ ] **Step 7: Commit**

```bash
git add sourcing/fake_slskd.py tests/helpers.py tests/test_verify.py tests/test_fake_slskd.py
git commit -m "sourcing: in-process fake slskd (search, enqueue, completion); share make_flac helper"
```

---

### Task 2: organize.py — file a verified download into the library layout

**Files:**
- Create: `sourcing/organize.py`
- Test: `tests/test_organize.py`

**Interfaces:**
- Produces: `target_path(music_root: Path, artist: str, title: str, ext: str, album: str | None = None, year: int | None = None, track: int | None = None) -> Path` (not yet existing, collision-free); `file_into(src: Path, music_root: Path, *, artist, title, album=None, year=None, track=None) -> Path` (moves `src`, returns the final path, never overwrites).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_organize.py
from pathlib import Path

from sourcing.organize import file_into, target_path


def test_target_path_matches_beets_layout(tmp_path):
    p = target_path(tmp_path, "Chic", "Good Times", "flac", album="Risqué", year=1979, track=3)
    assert p == tmp_path / "Chic" / "Risqué (1979)" / "03 - Good Times.flac"


def test_target_path_without_album_or_year(tmp_path):
    assert target_path(tmp_path, "Chic", "Good Times", "flac") == tmp_path / "Chic" / "Singles" / "00 - Good Times.flac"
    assert target_path(tmp_path, "Chic", "Good Times", "flac", album="Risqué") == tmp_path / "Chic" / "Risqué" / "00 - Good Times.flac"


def test_target_path_sanitises_components(tmp_path):
    p = target_path(tmp_path, "AC/DC", "Back: In .Black.", "mp3", album="../Evil", year=1980, track=1)
    assert p.parent.parent.name == "AC_DC"
    assert p.parent.name == "_Evil (1980)"            # "../Evil" → "/" becomes "_", leading dots stripped
    assert p.name == "01 - Back_ In .Black.mp3"
    assert tmp_path in p.parents and ".." not in p.parts


def test_target_path_avoids_collisions(tmp_path):
    first = tmp_path / "Chic" / "Risqué (1979)" / "03 - Good Times.flac"
    first.parent.mkdir(parents=True); first.write_bytes(b"old")
    p = target_path(tmp_path, "Chic", "Good Times", "flac", album="Risqué", year=1979, track=3)
    assert p == first.parent / "03 - Good Times (2).flac"


def test_file_into_moves_and_never_overwrites(tmp_path):
    src = tmp_path / "dl" / "x.flac"; src.parent.mkdir(); src.write_bytes(b"new")
    music = tmp_path / "music"
    out = file_into(src, music, artist="Chic", title="Good Times", album="Risqué", year=1979, track=3)
    assert out.read_bytes() == b"new" and not src.exists()
    src.write_bytes(b"again")
    out2 = file_into(src, music, artist="Chic", title="Good Times", album="Risqué", year=1979, track=3)
    assert out2 != out and out.read_bytes() == b"new" and out2.read_bytes() == b"again"
```

- [ ] **Step 2: Run to verify it fails**

Run: `~/.local/bin/pytest -q tests/test_organize.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'sourcing.organize'`

- [ ] **Step 3: Implement**

```python
# sourcing/organize.py
"""File a verified download into the library the way beets lays it out.

    Artist/Album (Year)/NN - Title.ext      (deploy/beets.yaml `paths.default`)
    Artist/Singles/NN - Title.ext           when there is no album tag

Names come from the *wanted* record (what the crate asked for), not from the file's own
tags, so the result is deterministic and never depends on a stranger's tagging. Never
overwrites: an existing target gets " (2)", " (3)" … before the extension.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _safe(s: str) -> str:
    s = _BAD.sub("_", (s or "").strip())
    s = s.lstrip(".") or "_"                   # no hidden or ".." components
    return s


def target_path(music_root: Path, artist: str, title: str, ext: str, album: str | None = None,
                year: int | None = None, track: int | None = None) -> Path:
    album_dir = _safe(album) if album else "Singles"
    if album and year:
        album_dir = f"{album_dir} ({year})"
    stem = f"{track or 0:02d} - {_safe(title)}"
    ext = ext.lower().lstrip(".")
    folder = Path(music_root) / _safe(artist) / album_dir
    candidate = folder / f"{stem}.{ext}"
    n = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({n}).{ext}"
        n += 1
    return candidate


def file_into(src: Path, music_root: Path, *, artist: str, title: str, album: str | None = None,
              year: int | None = None, track: int | None = None) -> Path:
    dest = target_path(music_root, artist, title, src.suffix, album, year, track)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return dest
```

- [ ] **Step 4: Run to verify it passes**

Run: `~/.local/bin/pytest -q tests/test_organize.py`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add sourcing/organize.py tests/test_organize.py
git commit -m "sourcing/organize: file a download as Artist/Album (Year)/NN - Title, collision-safe"
```

---

### Task 3: Crate store — external wanted rows and the sourcing status walk

**Files:**
- Modify: `crates/store.py` (schema at `SCHEMA` string, `wanted()` at ~138, add two methods)
- Test: `tests/test_crates.py` (append)

**Interfaces:**
- Produces: `CrateStore.add_external_wanted(artist, title, album=None, duration_s=None, year=None, source=None) -> str` returning an id `ext-<rowid>`; `CrateStore.external(ext_id) -> dict | None`; `CrateStore.set_external_status(ext_id, status, reason=None)`; `CrateStore.wanted()` now also yields external rows shaped like crate rows: `{"song_id": "ext-7", "title", "artist", "album", "year", "duration", "status", "reason", "crates": [], "external": True}`.
- `set_track_status` is unchanged and already logs an event; `fetch` uses it for crate rows.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_crates.py
def test_external_wanted_rows_join_the_queue():
    store = CrateStore()
    ext = store.add_external_wanted("Chic", "Good Times", album="Risqué", duration_s=501, year=1979, source="spotify:abc")
    assert ext.startswith("ext-")
    w = store.wanted()
    assert [x["song_id"] for x in w] == [ext]
    assert w[0]["external"] is True and w[0]["crates"] == [] and w[0]["duration"] == 501
    store.set_external_status(ext, "sourcing")
    assert store.external(ext)["status"] == "sourcing"
    assert store.wanted() == []                      # in flight → not offered again
    store.set_external_status(ext, "failed", "download timed out")
    assert store.wanted()[0]["reason"] == "download timed out"


def test_external_status_names_are_validated():
    store = CrateStore()
    ext = store.add_external_wanted("A", "B")
    import pytest
    with pytest.raises(AssertionError):
        store.set_external_status(ext, "verifying")
```

- [ ] **Step 2: Run to verify it fails**

Run: `~/.local/bin/pytest -q tests/test_crates.py -k external`
Expected: FAIL with `AttributeError: 'CrateStore' object has no attribute 'add_external_wanted'`

- [ ] **Step 3: Implement**

Add to the `SCHEMA` string in `crates/store.py` (after the `events` table):

```sql
CREATE TABLE IF NOT EXISTS external_wanted (
  id          INTEGER PRIMARY KEY,
  artist      TEXT NOT NULL, title TEXT NOT NULL, album TEXT, year INTEGER, duration INTEGER,
  source      TEXT,                               -- e.g. spotify playlist URL
  status      TEXT NOT NULL DEFAULT 'needs_source',
  reason      TEXT,
  created_at  REAL NOT NULL, updated_at REAL NOT NULL
);
```

Add methods to `CrateStore` (next to `wanted`):

```python
    # --- external wanted (not in Navidrome at all; seeded from Spotify etc.)
    def add_external_wanted(self, artist: str, title: str, album: str | None = None, duration_s: float | None = None,
                            year: int | None = None, source: str | None = None) -> str:
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO external_wanted(artist,title,album,year,duration,source,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (artist, title, album, year, int(duration_s) if duration_s else None, source, now, now))
        self.log(None, f"ext-{cur.lastrowid}", "wanted", f"{artist} — {title}")
        return f"ext-{cur.lastrowid}"

    def external(self, ext_id: str) -> dict | None:
        r = self.db.execute("SELECT * FROM external_wanted WHERE id=?", (int(ext_id.split('-', 1)[1]),)).fetchone()
        return self._ext_row(r) if r else None

    def set_external_status(self, ext_id: str, status: str, reason: str | None = None) -> None:
        assert status in STATUSES, status
        self.db.execute("UPDATE external_wanted SET status=?, reason=?, updated_at=? WHERE id=?",
                        (status, reason, time.time(), int(ext_id.split('-', 1)[1])))
        self.log(None, ext_id, "status", status)

    @staticmethod
    def _ext_row(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["song_id"] = f"ext-{d.pop('id')}"
        d["crates"], d["external"] = [], True
        return d
```

and extend `wanted()` so its return is `list(out.values()) + [self._ext_row(r) for r in self.db.execute("SELECT * FROM external_wanted WHERE status IN ('needs_source','failed') ORDER BY id")]`.

- [ ] **Step 4: Run to verify it passes**

Run: `~/.local/bin/pytest -q tests/test_crates.py`
Expected: all passed (existing `test_wanted_is_deduped_across_crates` still green — external rows are appended after crate rows)

- [ ] **Step 5: Commit**

```bash
git add crates/store.py tests/test_crates.py
git commit -m "crates/store: external wanted rows (seeded outside Navidrome) join the sourcing queue"
```

---

### Task 4: fetch.py — the orchestration, end to end against both fakes

**Files:**
- Create: `sourcing/fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Consumes: `FakeSlskdServer` (Task 1), `organize.file_into` (Task 2), `CrateStore.wanted/set_track_status/set_external_status/external` (Task 3), `scorer.Wanted/rank/explain`, `verify.verify`, `SlskdClient`, `SubsonicClient.start_scan/scan_status/search_songs/playlist/update_playlist`, `crates.reconcile.Reconciler.reconcile_playlist(pl: Playlist) -> tuple[int,int,int]`.
- Produces: `@dataclass FetchResult(status: str, reason: str, pick: Candidate | None, filed: Path | None, new_song_id: str | None, explain: str)`; `fetch(wanted_id: str, *, store, slskd, navidrome, reconciler, music_root: Path, downloads_root: Path, approve: bool, policy=DEFAULT_POLICY, download_timeout_s=600, poll_s=1.0, scan_timeout_s=120) -> FetchResult`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fetch.py
import json
from pathlib import Path

import pytest

from crates.reconcile import Reconciler
from crates.store import CrateStore
from sourcing.fake_slskd import FakeSlskdServer
from sourcing.fetch import fetch
from sourcing.slskd_client import SlskdClient
from subsonic.client import SubsonicClient
from subsonic.fake_server import FakeSubsonicServer
from tests.helpers import make_flac

RESPONSES = json.loads(Path("fixtures/search_responses.sample.json").read_text())
GOOD = RESPONSES[0]["files"][0]["filename"]      # Chic — Good Times FLAC, 501 s


def good_flac_bytes(tmp_path) -> bytes:
    return make_flac(tmp_path / "src.flac", total=44100 * 501, pad_bytes=501 * 900_000 // 8).read_bytes()


@pytest.fixture
def world(tmp_path):
    """Fake Navidrome whose crate 'Chicago 86' (pl-2) contains s4, a 128 kbps MP3 → needs_source;
    we make the wanted track *Chic — Good Times* by relabelling s4 so the fixture search matches."""
    with FakeSubsonicServer() as nd:
        s4 = nd.state.songs["s4"]
        s4.update(title="Good Times", artist="Chic", album="Risqué", year=1979, track=3, duration=501)
        store = CrateStore()
        client = SubsonicClient(nd.url, "demo", "demo")
        rec = Reconciler(client, store)
        rec.set_crate("pl-2", True)
        wanted = [w for w in store.wanted() if w["song_id"] == "s4"]
        assert wanted and wanted[0]["status"] == "needs_source"
        yield dict(nd=nd, store=store, client=client, rec=rec, music=tmp_path / "music", dl=tmp_path / "dl")


def run(world, srv, approve, **kw):
    return fetch("s4", store=world["store"], slskd=SlskdClient(srv.url, "k"), navidrome=world["client"],
                 reconciler=world["rec"], music_root=world["music"], downloads_root=world["dl"],
                 approve=approve, poll_s=0.01, download_timeout_s=kw.pop("download_timeout_s", 1),
                 scan_timeout_s=1, **kw)


def test_without_approve_only_scores_and_prints_pick(world, tmp_path):
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        r = run(world, srv, approve=False)
    assert r.status == "needs_source" and r.pick.username == "vinylhead77" and "Good Times" in r.explain
    assert srv.enqueued == [] and world["store"].track_status_map("pl-2")["s4"]["status"] == "needs_source"


def test_approved_fetch_runs_to_ok(world, tmp_path):
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        # what Navidrome will "find" after the rescan: the filed FLAC
        world["nd"].state.songs["s9"] = dict(world["nd"].state.songs["s1"], id="s9", title="Good Times", artist="Chic",
                                             album="Risqué", suffix="flac", bitRate=880, samplingRate=44100, bitDepth=16,
                                             path="Chic/Risqué (1979)/03 - Good Times.flac")
        r = run(world, srv, approve=True)
    assert r.status == "ok", r.reason
    assert r.filed == world["music"] / "Chic" / "Risqué (1979)" / "03 - Good Times.flac" and r.filed.read_bytes() == flac
    assert r.new_song_id == "s9"
    pl = world["client"].playlist("pl-2")
    assert [e.id for e in pl.entries] == ["s3", "s9", "s5"]           # swapped in place
    st = world["store"].track_status_map("pl-2")
    assert st["s9"]["status"] == "ok" and st["s4"]["status"] == "removed"
    assert not (world["dl"] / "vinylhead77" / "03 - Good Times.flac").exists()


def test_bad_download_is_failed_and_not_filed(world, tmp_path):
    fake_lossless = make_flac(tmp_path / "bad.flac", total=44100 * 501, pad_bytes=10_000).read_bytes()
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: fake_lossless}) as srv:
        r = run(world, srv, approve=True)
    assert r.status == "failed" and "transcode" in r.reason
    assert world["store"].track_status_map("pl-2")["s4"]["status"] == "failed"
    assert not world["music"].exists()


def test_fetch_download_timeout_fails_cleanly(world, tmp_path):
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: b"x"}, complete=False) as srv:
        r = run(world, srv, approve=True, download_timeout_s=0.05)
    assert r.status == "failed" and "timed out" in r.reason
    assert not world["music"].exists()


def test_fetch_no_acceptable_candidate_leaves_needs_source(world):
    locked = [dict(r, files=[dict(f, isLocked=True) for f in r["files"]]) for r in RESPONSES]
    with FakeSlskdServer(locked, world["dl"], files={}) as srv:
        r = run(world, srv, approve=True)
    assert r.status == "needs_source" and "no acceptable candidate" in r.reason and srv.enqueued == []


def test_fetch_filed_but_not_found_after_rescan(world, tmp_path):
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        r = run(world, srv, approve=True)                  # no s9 registered → Navidrome never sees it
    assert r.status == "verify" and "03 - Good Times.flac" in r.reason
    assert r.filed.exists()
    assert world["store"].track_status_map("pl-2")["s4"]["status"] == "verify"


def test_fetch_swaps_song_in_every_crate(world, tmp_path):
    world["client"].update_playlist("pl-1", add_song_ids=["s4"])   # second crate holding the same song
    world["rec"].set_crate("pl-1", True); world["rec"].reconcile()
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        world["nd"].state.songs["s9"] = dict(world["nd"].state.songs["s1"], id="s9", title="Good Times", artist="Chic",
                                             album="Risqué", suffix="flac", path="Chic/Risqué (1979)/03 - Good Times.flac")
        r = run(world, srv, approve=True)
    assert r.status == "ok"
    for pl_id in ("pl-1", "pl-2"):
        ids = [e.id for e in world["client"].playlist(pl_id).entries]
        assert "s9" in ids and "s4" not in ids
        assert world["store"].track_status_map(pl_id)["s9"]["status"] == "ok"


def test_external_wanted_row_files_without_playlist_swap(world, tmp_path):
    ext = world["store"].add_external_wanted("Chic", "Good Times", album="Risqué", duration_s=501, year=1979)
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        world["nd"].state.songs["s9"] = dict(world["nd"].state.songs["s1"], id="s9", title="Good Times", artist="Chic", suffix="flac")
        r = fetch(ext, store=world["store"], slskd=SlskdClient(srv.url, "k"), navidrome=world["client"],
                  reconciler=world["rec"], music_root=world["music"], downloads_root=world["dl"], approve=True,
                  poll_s=0.01, download_timeout_s=1, scan_timeout_s=1)
    assert r.status == "ok" and world["store"].external(ext)["status"] == "ok"
```

- [ ] **Step 2: Run to verify it fails**

Run: `~/.local/bin/pytest -q tests/test_fetch.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'sourcing.fetch'`

- [ ] **Step 3: Implement**

```python
# sourcing/fetch.py
"""One wanted track, end to end: search → score → (approved) download → verify → file → rescan → ok.

    needs_source ──search/score──▶ (print pick, stop)            without approve
    needs_source ─▶ sourcing ─▶ verify ─▶ ok                      approve, all good
                                 │          └─▶ verify + reason    filed, but Navidrome didn't find it
                                 └─▶ failed                        bad file / download timed out
    needs_source (unchanged) when no acceptable candidate — retried next time

Crate rows (song already in Navidrome, just not good enough) also get the playlist entry
swapped to the new song in every crate that holds it, then reconciled so the new row is `ok`
and the old one `removed`. External rows (seeded from Spotify) just need the file in the library.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from crates.reconcile import Reconciler
from crates.store import CrateStore
from subsonic.client import SubsonicClient
from .policy import DEFAULT_POLICY, QualityPolicy
from .scorer import Candidate, Wanted, explain, rank
from .slskd_client import SlskdClient
from .verify import verify


@dataclass
class FetchResult:
    status: str
    reason: str
    pick: Candidate | None = None
    filed: Path | None = None
    new_song_id: str | None = None
    explain: str = ""


def _norm(s: str | None) -> str:
    return re.sub(r"[^\w]+", "", (s or "").casefold())


def fetch(wanted_id: str, *, store: CrateStore, slskd: SlskdClient, navidrome: SubsonicClient,
          reconciler: Reconciler, music_root: Path, downloads_root: Path, approve: bool,
          policy: QualityPolicy = DEFAULT_POLICY, download_timeout_s: float = 600, poll_s: float = 1.0,
          scan_timeout_s: float = 120) -> FetchResult:
    row = next((w for w in store.wanted() if w["song_id"] == wanted_id), None)
    if row is None:
        return FetchResult("missing", f"{wanted_id} is not in the wanted queue")
    external = bool(row.get("external"))

    def set_status(status: str, reason: str | None = None) -> None:
        if external:
            store.set_external_status(wanted_id, status, reason)
        else:
            for pl in store.all(enabled_only=True):
                if wanted_id in store.track_status_map(pl.playlist_id):
                    store.set_track_status(pl.playlist_id, wanted_id, status, reason)
        store.commit()

    wanted = Wanted(row["artist"], row["title"], row.get("album"), row.get("duration"), row.get("year"))
    sid = slskd.search(f"{wanted.artist} {wanted.title}")
    slskd.wait_search(sid, poll_s=poll_s, max_s=30)
    cands = rank(slskd.search_responses(sid), wanted, policy)
    slskd.delete_search(sid)
    text = explain(cands)
    best = next((c for c in cands if not c.rejected), None)
    if best is None:
        return FetchResult("needs_source", "no acceptable candidate", None, explain=text)
    if not approve:
        return FetchResult("needs_source", "pick printed; re-run with --approve to download", best, explain=text)

    set_status("sourcing", f"downloading from {best.username}")
    slskd.enqueue(best.username, [{"filename": best.filename, "size": best.size}])
    landed = Path(downloads_root) / best.username / best.basename
    t0 = time.time()
    while True:
        states = [t.get("state", "") for t in (slskd.downloads(best.username) or []) if t.get("filename") == best.filename]
        if any(s.startswith("Completed, Succeeded") for s in states) and landed.exists():
            break
        if any(s.startswith("Completed") for s in states) or time.time() - t0 > download_timeout_s:
            why = "download timed out" if time.time() - t0 > download_timeout_s else f"download ended: {states}"
            set_status("failed", why)
            return FetchResult("failed", why, best, explain=text)
        time.sleep(poll_s)

    set_status("verify", "checking the file")
    vd = verify(landed, wanted.duration_s)
    if not vd.ok:
        why = "; ".join(vd.problems)
        set_status("failed", why)
        return FetchResult("failed", why, best, explain=text)

    from .organize import file_into
    filed = file_into(landed, Path(music_root), artist=wanted.artist, title=wanted.title,
                      album=wanted.album, year=wanted.year, track=row.get("track"))

    navidrome.start_scan()
    t0 = time.time()
    while navidrome.scan_status().get("scanning") and time.time() - t0 < scan_timeout_s:
        time.sleep(poll_s)
    new = next((s for s in navidrome.search_songs(wanted.title, count=50)
                if (s.suffix or "") == filed.suffix.lstrip(".").lower()
                and _norm(s.title) == _norm(wanted.title) and _norm(s.artist) == _norm(wanted.artist)), None)
    if new is None:
        why = f"filed as {filed.relative_to(music_root)} but Navidrome has not picked it up yet"
        set_status("verify", why)
        return FetchResult("verify", why, best, filed, explain=text)

    if external:
        set_status("ok", f"filed as {filed.relative_to(music_root)}")
        return FetchResult("ok", "filed and visible in Navidrome", best, filed, new.id, text)

    for crate in store.all(enabled_only=True):
        pl = navidrome.playlist(crate.playlist_id)
        ids = [e.id for e in pl.entries]
        if wanted_id not in ids:
            continue
        idx = ids.index(wanted_id)
        navidrome.update_playlist(pl.id, add_song_ids=[new.id], remove_indexes=[idx])
        # the add appends; move the new id into the old slot by rebuilding the tail
        pl2 = navidrome.playlist(pl.id)
        ids2 = [e.id for e in pl2.entries]
        if ids2.index(new.id) != idx:
            tail = ids2[idx:]
            tail.remove(new.id)
            navidrome.update_playlist(pl.id, remove_indexes=list(range(idx, len(ids2))))
            navidrome.update_playlist(pl.id, add_song_ids=[new.id] + tail)
        reconciler.reconcile_playlist(navidrome.playlist(pl.id))
    store.commit()
    return FetchResult("ok", "filed, swapped into every crate, reconciled", best, filed, new.id, text)
```

Check against the fake Navidrome's `updatePlaylist` (fake_server.py:170-176): it pops `songIndexToRemove` indexes then extends with `songIdToAdd`, so the two-call reorder above yields `[s3, s9, s5]` for the test. Real Navidrome behaves the same (remove by index, add appends).

- [ ] **Step 4: Run to verify it passes**

Run: `~/.local/bin/pytest -q tests/test_fetch.py`
Expected: 8 passed. (`Reconciler.reconcile_playlist` at reconcile.py:171-172 already marks entries no longer in the playlist as `removed`, which is what makes the old row `removed` after the swap.)

- [ ] **Step 5: Commit**

```bash
git add sourcing/fetch.py tests/test_fetch.py
git commit -m "sourcing/fetch: wanted → search → score → approved download → verify → file → rescan → ok"
```

---

### Task 5: CLI — `fetch --wanted <id> [--approve]` and `seed-spotify <url>`

**Files:**
- Modify: `sourcing/cli.py` (add two subparsers; keep `rank`/`verify`)
- Test: `tests/test_sourcing_cli.py`

**Interfaces:**
- Consumes: `fetch.fetch`, `spotify_csv.fetch_entity(url) -> entity`, `spotify_csv.rows(entity)` which yields dicts `{"Artist": str, "Title": str, "Length": int seconds}` (`sourcing/spotify_csv.py:62-67`; `lead_artist` only hits the network when the subtitle contains a comma), `CrateStore.add_external_wanted`, `crates.service.Config.from_env`.
- Env contract: `SUBSONIC_URL/USER/PASS`, `CRATES_DB`, `SLSKD_URL` (default `http://127.0.0.1:5030`), `SLSKD_API_KEY`, `MUSIC_ROOT` (default `/srv/music`), `DOWNLOADS_ROOT` (default `/srv/incoming`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sourcing_cli.py
import json
from pathlib import Path

from crates.store import CrateStore
from sourcing import cli
from sourcing.fake_slskd import FakeSlskdServer
from subsonic.fake_server import FakeSubsonicServer

RESPONSES = json.loads(Path("fixtures/search_responses.sample.json").read_text())


def test_fetch_without_approve_prints_pick(tmp_path, monkeypatch, capsys):
    db = tmp_path / "crates.db"
    with FakeSubsonicServer() as nd, FakeSlskdServer(RESPONSES, tmp_path / "dl", files={}) as sl:
        nd.state.songs["s4"].update(title="Good Times", artist="Chic")
        monkeypatch.setenv("SUBSONIC_URL", nd.url); monkeypatch.setenv("SUBSONIC_USER", "demo"); monkeypatch.setenv("SUBSONIC_PASS", "demo")
        monkeypatch.setenv("CRATES_DB", str(db)); monkeypatch.setenv("SLSKD_URL", sl.url); monkeypatch.setenv("SLSKD_API_KEY", "k")
        monkeypatch.setenv("MUSIC_ROOT", str(tmp_path / "music")); monkeypatch.setenv("DOWNLOADS_ROOT", str(tmp_path / "dl"))
        from crates.cli import main as crates_main
        assert crates_main(["toggle", "pl-2", "on"]) == 0
        rc = cli.main(["fetch", "--wanted", "s4"])
    out = capsys.readouterr().out
    assert rc == 0 and "vinylhead77" in out and "--approve" in out and sl.enqueued == []


def test_seed_spotify_adds_external_rows(tmp_path, monkeypatch, capsys):
    db = tmp_path / "crates.db"; monkeypatch.setenv("CRATES_DB", str(db))
    entity = {"name": "Test", "trackList": [{"title": "Good Times", "subtitle": "Chic", "duration": 501_000}]}
    monkeypatch.setattr(cli, "fetch_entity", lambda url: entity)
    rc = cli.main(["seed-spotify", "https://open.spotify.com/playlist/abc"])
    assert rc == 0
    w = CrateStore(db).wanted()
    assert len(w) == 1 and w[0]["artist"] == "Chic" and w[0]["title"] == "Good Times" and w[0]["duration"] == 501
    assert "1 added" in capsys.readouterr().out
```

The `entity` dict is the shape `rows()`/`lead_artist()` read: `trackList[*].title`, `.subtitle` (artist string; no comma → no network call), `.duration` in ms.

- [ ] **Step 2: Run to verify it fails**

Run: `~/.local/bin/pytest -q tests/test_sourcing_cli.py`
Expected: FAIL (argparse `invalid choice: 'fetch'`)

- [ ] **Step 3: Implement**

Add to `sourcing/cli.py` after the `verify` subparser:

```python
    f = sub.add_parser("fetch", help="take one wanted track through search → score → (approve) download → verify → file → ok")
    f.add_argument("--wanted", required=True, help="song id from `crates.cli wanted` (or ext-N from seed-spotify)")
    f.add_argument("--approve", action="store_true", help="actually download; without it, stop after scoring")
    f.add_argument("--slskd", default=os.environ.get("SLSKD_URL", "http://127.0.0.1:5030"))
    f.add_argument("--api-key", default=os.environ.get("SLSKD_API_KEY"))

    s = sub.add_parser("seed-spotify", help="add every track of a public Spotify playlist/album to the wanted queue")
    s.add_argument("url")
```

and the handlers (before `wanted = Wanted(...)`):

```python
    if a.cmd == "seed-spotify":
        from crates.service import Config
        from crates.store import CrateStore
        from .spotify_csv import rows
        store = CrateStore(Config.from_env().db_path)
        n = 0
        for r in rows(fetch_entity(a.url)):          # dicts: {"Artist", "Title", "Length"} (seconds)
            store.add_external_wanted(r["Artist"], r["Title"], duration_s=r["Length"], source=a.url); n += 1
        store.commit()
        print(f"{n} added to the wanted queue from {a.url}")
        return 0

    if a.cmd == "fetch":
        if not a.api_key:
            print("need --api-key or $SLSKD_API_KEY", file=sys.stderr); return 1
        from crates.reconcile import Reconciler
        from crates.service import Config
        from crates.store import CrateStore
        from subsonic.client import SubsonicClient
        from .fetch import fetch
        from .slskd_client import SlskdClient
        cfg = Config.from_env()
        if not cfg.username:
            print("set SUBSONIC_USER / SUBSONIC_PASS (and SUBSONIC_URL)", file=sys.stderr); return 1
        store = CrateStore(cfg.db_path)
        nav = SubsonicClient(cfg.subsonic_url, cfg.username, cfg.password)
        r = fetch(a.wanted, store=store, slskd=SlskdClient(a.slskd, a.api_key), navidrome=nav,
                  reconciler=Reconciler(nav, store), music_root=Path(os.environ.get("MUSIC_ROOT", "/srv/music")),
                  downloads_root=Path(os.environ.get("DOWNLOADS_ROOT", "/srv/incoming")), approve=a.approve)
        print(r.explain)
        if r.pick:
            print(f"pick: {r.pick.username}: {r.pick.basename}  (score {r.pick.score:.2f})")
        print(f"{r.status}: {r.reason}" + (f"  → {r.filed}" if r.filed else ""))
        return 0 if r.status in ("ok", "needs_source") else 2
```

Add `from .spotify_csv import fetch_entity` at module top (the test monkeypatches `cli.fetch_entity`).

- [ ] **Step 4: Run to verify it passes**

Run: `~/.local/bin/pytest -q`
Expected: all passed (≈71)

- [ ] **Step 5: Commit**

```bash
git add sourcing/cli.py tests/test_sourcing_cli.py
git commit -m "sourcing/cli: fetch --wanted <id> [--approve]; seed-spotify <url> seeds the wanted queue"
```

---

### Task 6: Docs

**Files:**
- Modify: `README.md` ("Not done yet" list and the sourcing section)
- Modify: `~/projects/ideas/dj-crate-streaming/decisions.md` (Open questions: default chosen overnight)

- [ ] **Step 1: README**

Under "Sourcing prototype, offline:" add:

```bash
python3 -m sourcing.cli seed-spotify https://open.spotify.com/playlist/...   # → ext-N wanted rows
python3 -m sourcing.cli fetch --wanted s4             # search + score, prints the pick, no download
python3 -m sourcing.cli fetch --wanted s4 --approve   # download → verify → /srv/music → rescan → crate ok
```

In "Not done yet", replace the first bullet with: "Background jobs that run `fetch` automatically from the wanted queue (today: one track per command, downloads only with `--approve`)."

- [ ] **Step 2: decisions.md**

Append under "Open questions (need Michael)": "5. *Defaulted overnight:* `fetch` names files from the **wanted record** (crate tags), not the download's own tags, and keeps the store's existing `verify` status name instead of adding `verifying`. Also: a download whose tags Navidrome can't match stays `verify` with the filed path in the reason rather than being auto-retagged — change?"

- [ ] **Step 3: Commit**

```bash
git add README.md && git commit -m "docs: sourcing fetch/seed-spotify usage"
(cd ~/projects && git add ideas/dj-crate-streaming/decisions.md && git commit -m "decisions: overnight defaults for the sourcing slice")
```
