"""The crate service: a small HTTP API + static web client over Navidrome.

Why a service and not just a phone app: Navidrome only knows playlists. The crate
flag, the per-track provisioning status, the sourcing queue, and the device list live
*here*, next to the library. Any client (this web UI, a future native app, the CLI)
talks to this API; only this process holds the Navidrome credentials.

Security model: bind to 127.0.0.1 and front it with `tailscale serve` (HTTPS on the
tailnet). Audio is not proxied — /api/stream/<id> answers with a 302 to a per-request
signed Navidrome URL, so the phone pulls bytes straight from Navidrome over the same
private network. Set SUBSONIC_PUBLIC_URL when the URL the phone can reach differs from
the one this service uses (e.g. docker-internal vs. tailnet hostname).

    SUBSONIC_URL=http://127.0.0.1:4533 SUBSONIC_USER=me SUBSONIC_PASS=... python -m crates.cli serve
"""
from __future__ import annotations

import json
import mimetypes
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from sourcing.fetch import fetch
from sourcing.policy import DEFAULT_POLICY, STREAM, QualityPolicy, check_stream
from sourcing.slskd_client import SlskdClient
from subsonic.client import SubsonicClient, SubsonicError
from .reconcile import CommentNotKept, NameMarked, ReconcileBusy, Reconciler
from . import proposals, trash
from .store import CrateStore, PlayNowRefused, filed_path, held_by, pick_token, public, retryable_review

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("image/svg+xml", ".svg")
STREAM_CLIENT_NAME = "dj-crates-web"   # its own Navidrome Player → its own transcoding profile


class ApiError(Exception):
    """An expected failure with the HTTP status it should answer with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class Config:
    subsonic_url: str
    username: str
    password: str
    public_url: str | None = None
    db_path: str = "data/crates.db"
    bind: str = "127.0.0.1"
    port: int = 4580
    trash_dir: str | None = None          # read-only view of /srv/_trash (status reports it)
    slskd_url: str | None = None          # slskd, for previews (and the worker)
    slskd_key: str | None = None
    navidrome_db: str | None = None       # read-only navidrome.db: playlist edits cross-check it (crates.playlist_edit)

    @classmethod
    def from_env(cls, **overrides) -> "Config":
        env = os.environ
        cfg = cls(
            subsonic_url=env.get("SUBSONIC_URL", "http://127.0.0.1:4533"),
            username=env.get("SUBSONIC_USER", ""),
            password=env.get("SUBSONIC_PASS", ""),
            public_url=env.get("SUBSONIC_PUBLIC_URL") or None,
            db_path=env.get("CRATES_DB", "data/crates.db"),
            bind=env.get("CRATES_BIND", "127.0.0.1"),
            port=int(env.get("CRATES_PORT", "4580")),
            trash_dir=env.get("CRATES_TRASH") or None,
            slskd_url=env.get("SLSKD_URL") or None,
            slskd_key=env.get("SLSKD_API_KEY") or None,
            navidrome_db=env.get("NAVIDROME_DB") or None,
        )
        for k, v in overrides.items():
            if v is not None:
                setattr(cfg, k, v)
        return cfg


class CrateApp:
    """Everything the HTTP layer needs, so it can also be driven directly from tests/CLI."""

    def __init__(self, cfg: Config, policy: QualityPolicy = DEFAULT_POLICY, store: CrateStore | None = None,
                 slskd: SlskdClient | None = None):
        self.cfg = cfg
        self.api = SubsonicClient(cfg.subsonic_url, cfg.username, cfg.password)
        self.media = SubsonicClient(cfg.public_url or cfg.subsonic_url, cfg.username, cfg.password, client_name=STREAM_CLIENT_NAME)
        if store is None:
            Path(cfg.db_path).parent.mkdir(parents=True, exist_ok=True)
            store = CrateStore(cfg.db_path)
        self.store = store
        self.reconciler = Reconciler(self.api, store, policy)
        self.policy = policy
        if slskd is None and cfg.slskd_url and cfg.slskd_key:
            slskd = SlskdClient(cfg.slskd_url, cfg.slskd_key)
        self.slskd = slskd
        self._lock = threading.Lock()

    # --- read
    def worker_heartbeat_age(self) -> float | None:
        """Seconds since the worker touched worker.heartbeat (beside the crates db); None if it never did."""
        if self.cfg.db_path == ":memory:":
            return None
        try:
            return max(0.0, time.time() - (Path(self.cfg.db_path).parent / "worker.heartbeat").stat().st_mtime)
        except OSError:
            return None

    def status(self) -> dict:
        info = self.api.ping()
        return {"server": self.cfg.subsonic_url, "publicServer": self.cfg.public_url or self.cfg.subsonic_url,
                "user": self.cfg.username, "serverType": info.get("type"), "serverVersion": info.get("serverVersion"),
                "openSubsonic": info.get("openSubsonic"), "crates": len(self.store.all(enabled_only=True)),
                "wanted": len(self.store.wanted()), "workerHeartbeatAge": self.worker_heartbeat_age(),
                "trash": trash.summary(self.cfg.trash_dir), "playlistHealth": self.store.playlist_health(),
                "policy": {"preferred": self.policy.preferred, "allow": self.policy.allow, "deny": self.policy.deny,
                           "minLossyBitrate": self.policy.min_lossy_bitrate}}

    def playlists(self) -> list[dict]:
        return [self.reconciler.crate_view(p) for p in self.api.playlists()]

    def crates(self) -> list[dict]:
        """The crates Navidrome still lists (one getPlaylists): a crate row whose playlist is gone waits for the
        next reconcile to drop it (N3), and is not shown."""
        on = {c.playlist_id for c in self.store.all(enabled_only=True)}
        return [self.reconciler.crate_view(p) for p in self.api.playlists() if p.id in on]

    def playlist(self, pid: str) -> dict:
        pl = self.api.playlist(pid)
        view = self.reconciler.crate_view(pl)
        status = self.store.track_status_map(pid) if view["tier"] else {}     # crate or tier-only
        view["entries"] = []
        for pos, s in enumerate(pl.entries):
            st = status.get(s.id)
            view["entries"].append({
                "id": s.id, "position": pos, "title": s.title, "artist": s.artist, "album": s.album, "year": s.year,
                "duration": s.duration, "suffix": s.suffix, "bitRate": s.bit_rate, "sampleRate": s.sample_rate,
                "bitDepth": s.bit_depth, "coverArt": s.raw.get("coverArt"),
                "crateStatus": st["status"] if st else None, "crateReason": st["reason"] if st else None,
            })
        # the playlist's queued rows the library does not have yet (import-playlist's): the web lists them with the
        # play-now ▶ the Wanted tab has; public() keeps peer names and absolute paths out of the reasons
        view["wanted"] = [public({
            "id": w["song_id"], "artist": w["artist"], "title": w["title"], "status": w["status"],
            "reason": w["reason"], "provisional": bool(w["provisional"]), "library_song_id": w["library_song_id"],
            "filed": filed_path(w["reason"]) is not None})
            for w in self.store.external_for_playlist(pid) if not w["library_song_id"] and w["status"] != "ok"]
        return view

    def search(self, q: str, count: int = 25) -> list[dict]:
        return [{"id": s.id, "title": s.title, "artist": s.artist, "album": s.album, "duration": s.duration,
                 "suffix": s.suffix, "bitRate": s.bit_rate, "coverArt": s.raw.get("coverArt")} for s in self.api.search_songs(q, count)]

    # --- write
    def set_crate(self, pid: str, enabled: bool) -> dict:
        with self._lock:
            return self.reconciler.set_crate(pid, enabled)

    def set_tier(self, pid: str, tier: str | None) -> dict:
        with self._lock:
            return self.reconciler.set_tier(pid, tier)

    def reconcile(self) -> dict:
        with self._lock:
            return self.reconciler.run().as_dict()

    def add_to_playlist(self, pid: str, song_ids: list[str]) -> dict:
        self.api.update_playlist(pid, add_song_ids=song_ids)
        if self.store.playlist_tier(pid) is not None:           # a tiered playlist: judge the new songs now
            with self._lock:
                self.reconciler.reconcile_playlist(self.api.playlist(pid))
        return self.playlist(pid)

    def create_playlist(self, name: str, song_ids: list[str] = (), crate: bool = False) -> dict:
        pl = self.api.create_playlist(name, song_ids)
        if crate:
            return self.set_crate(pl.id, True)
        return self.reconciler.crate_view(pl)

    # --- approvals (D23): a preview searches and ranks but never downloads; an approval is what lets the worker
    def _not_in_progress(self, wanted_id: str) -> dict:
        """The row, unless it is missing (404) or in progress (409): a `sourcing` row is being downloaded and a
        `verify` row is filed already; the worker finishes both, and neither may be searched or approved again."""
        row = self.store.find_wanted(wanted_id)
        if row is None:
            raise ApiError(404, f"{wanted_id} is not in any enabled crate or the external queue")
        if row["status"] in ("sourcing", "verify"):
            raise ApiError(409, f"{wanted_id} is {row['status']} (in progress): the worker finishes it")
        ext = held_by(row.get("reason")) if row["status"] == "review" else None
        if ext is not None:                         # one open request per song: the upgrade in flight is it
            raise ApiError(409, f"{wanted_id} waits for its upgrade in flight: approve {ext}")
        a = self.store.approval_in_progress(wanted_id)
        if a is not None and a["used_at"] is not None:  # claimed: the worker is searching or downloading already
            what = "a play-now download" if a["purpose"] == "play-now" else "a download"
            raise ApiError(409, f"{wanted_id}: {what} is in progress (approval #{a['id']}); the worker finishes it")
        return row

    def approvable(self, wanted_id: str) -> dict:
        """The row, unless approving it is refused (404, 409): see _not_in_progress, and a `review` row that is not
        retryable waits for a pick between library versions (or holds on an upgrade): a download would not answer
        it and fetch would refuse the approval, so nothing is recorded. The CLI asks this before changing a tier."""
        row = self._not_in_progress(wanted_id)
        if row["status"] == "review" and not retryable_review(row.get("reason")):
            raise ApiError(409, f"{wanted_id} needs a pick first ({public(row.get('reason') or 'review')})")
        return row

    def preview(self, wanted_id: str) -> dict:
        if self.slskd is None:
            raise ApiError(503, "slskd is not configured")
        with self._lock:
            self._not_in_progress(wanted_id)
            r = fetch(wanted_id, store=self.store, slskd=self.slskd, navidrome=self.api, reconciler=self.reconciler,
                      music_root=Path(os.environ.get("MUSIC_ROOT", "/srv/music")),
                      downloads_root=Path(os.environ.get("DOWNLOADS_ROOT", "/srv/incoming/soulseek")), approve=False)
            if r.status == "missing":
                raise ApiError(404, r.reason)
            pick = r.pick.as_dict() if r.pick else None
            if pick is not None:
                pick["token"] = pick_token(pick)    # what the web posts back to approve it (no peer name)
            out = {"status": r.status, "reason": r.reason, "pick": pick, "explain": r.explain, "ts": time.time()}
            self.store.set_preview(wanted_id, out)   # kept whole, server-side
            return public(out)

    def approve(self, wanted_id: str, candidate: dict | None) -> dict:
        """Michael's yes for one row: the candidate he saw, else the cached preview's pick (which may be None,
        leaving the worker to search and pick itself). The web posts the pick as previews show it, with its `token`
        and no peer name: the full candidate is the stored preview's pick with that token (409 when the preview
        changed since: preview again). A candidate naming its peer (`username` + `filename`) is taken as it is."""
        with self._lock:
            row = self.approvable(wanted_id)
            if candidate is None:
                candidate = (self.store.preview(wanted_id) or {}).get("pick")
            elif isinstance(candidate, dict) and "token" in candidate and "username" not in candidate:
                stored = (self.store.preview(wanted_id) or {}).get("pick")
                if not (isinstance(candidate["token"], str) and stored and pick_token(stored) == candidate["token"]):
                    raise ApiError(409, f"{wanted_id}: that pick is no longer the preview's; preview again")
                candidate = stored
            elif not (isinstance(candidate, dict) and isinstance(candidate.get("username"), str)
                      and isinstance(candidate.get("filename"), str)):
                raise ApiError(400, "candidate needs a string username and filename, or a preview's token")
            self.store.approve(wanted_id, "michael", candidate, row["tier"])
            return public(self.store.approval(wanted_id))

    def play_now(self, wanted_id: str) -> dict:
        """Michael pressed play on a queued track the library does not have (D20): that tap is his approval for ONE
        fast copy at tier `low`, filed as a provisional copy; the worker takes it first, and the row's tier (its
        upgrade's) is untouched. Refused (409, nothing recorded) for anything that has or is getting a file: a
        playlist row (its song is in Navidrome), a row with a library song (play that), an `ok` row, one in progress
        (sourcing, verify, filed but not indexed, or an approval waiting or being fetched: a double tap or a second
        device), or a `review` row (a version must be picked first). 404 for an unknown id."""
        with self._lock:
            row = self.store.find_wanted(wanted_id)
            if row is None:
                raise ApiError(404, f"{wanted_id} is not in any enabled crate or the external queue")
            if not row.get("external"):
                raise ApiError(409, f"{wanted_id} is in the library already: play the library file")
            if row.get("library_song_id"):
                raise ApiError(409, f"{wanted_id} is already in the library: play {row['library_song_id']}")
            status = row["status"]
            if status == "ok":
                raise ApiError(409, f"{wanted_id} is already in the library ({row.get('reason') or 'ok'})")
            if status in ("sourcing", "verify") or (status == "failed" and filed_path(row.get("reason"))):
                raise ApiError(409, f"{wanted_id} is in progress ({status}): the worker finishes it")
            if status == "review":
                raise ApiError(409, f"{wanted_id} needs a pick first ({row.get('reason')}): pick a version first")
            try:                                    # the INSERT itself refuses a second one (any process)
                self.store.approve(wanted_id, "michael", None, "low", purpose="play-now")
            except PlayNowRefused:                  # a double tap, a second device, or the worker fetching it
                raise ApiError(409, self._busy(wanted_id, self.store.approval_in_progress(wanted_id))) from None
            return public(self.store.approval(wanted_id))

    @staticmethod
    def _busy(wanted_id: str, a: dict | None) -> str:
        if a is not None and a["used_at"] is not None:
            return f"{wanted_id} is in progress: the worker is fetching it (approval #{a['id']})"
        what = "a play-now approval" if a is not None and a["purpose"] == "play-now" else "an approval"
        return f"{wanted_id} already has {what} waiting for the worker" + (f" (#{a['id']})" if a else "")

    def wanted_row(self, wanted_id: str) -> dict:
        row = self.store.wanted_row(wanted_id)
        if row is None:
            raise ApiError(404, f"{wanted_id} is not in any enabled crate or the external queue")
        return public(row)

    # --- proposals (D23): questions about one playlist slot; Michael's answer edits that slot, downloads nothing
    def proposals(self, include_decided: bool = False) -> list[dict]:
        """Open proposals (every one with include_decided), each with its playlist's name from the cache. Questions
        whose slot or playlist is gone are marked stale first (proposals.prune); when navidrome.db cannot be read the
        list is served as it is."""
        if self.cfg.navidrome_db:
            with self._lock:
                try:
                    proposals.prune(self.store, Path(self.cfg.navidrome_db))
                except (sqlite3.Error, OSError):
                    pass
        return [self._proposal_view(p) for p in self.store.proposals(open_only=not include_decided)]

    def _proposal_view(self, p: dict) -> dict:
        c = self.store.get(p["playlist_id"])
        return p | {"playlist_name": c.name if c else p["playlist_id"]}

    def _answer(self, proposal_id: int, answer) -> dict:
        try:
            answer()
        except KeyError:
            raise ApiError(404, f"no proposal #{proposal_id}") from None
        except proposals.Decided as e:
            raise ApiError(409, str(e)) from None
        return self._proposal_view(self.store.proposal(proposal_id))

    def accept_proposal(self, proposal_id: int, decided_by: str = "michael") -> dict:
        """Edit that one slot (guarded; any doubt answers `stale`, writing nothing). Needs navidrome.db (the guard)."""
        if not self.cfg.navidrome_db:
            raise ApiError(503, "navidrome.db is not configured (NAVIDROME_DB): a slot edit needs it to check the playlist")
        with self._lock:
            return self._answer(proposal_id, lambda: proposals.apply(
                self.store, self.api, Path(self.cfg.navidrome_db), proposal_id, decided_by, self.reconciler))

    def decline_proposal(self, proposal_id: int, decided_by: str = "michael") -> dict:
        with self._lock:
            return self._answer(proposal_id, lambda: proposals.decline(self.store, proposal_id, decided_by))

    # --- media URLs (signed per call)
    def stream_url(self, song_id: str, max_bit_rate: int | None, fmt: str | None) -> str:
        return self.media.stream_url(song_id, max_bit_rate, fmt)

    def download_url(self, song_id: str) -> str:
        return self.media.download_url(song_id)

    def cover_url(self, cover_id: str, size: int | None) -> str:
        return self.media.cover_art_url(cover_id, size)


def make_handler(app: CrateApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "dj-crates/0.1"

        def log_message(self, fmt, *args):
            if os.environ.get("CRATES_LOG"):
                super().log_message(fmt, *args)

        # --- helpers
        def _json(self, obj, status: int = 200):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _redirect(self, url: str):
            self.send_response(302)
            self.send_header("Location", url)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _static(self, rel: str):
            rel = rel or "index.html"
            f = (WEB_DIR / rel).resolve()
            if WEB_DIR not in f.parents or not f.is_file():
                return self._json({"error": "not found"}, 404)
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(f.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def _route(self, method: str):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            parts = [p for p in u.path.split("/") if p]
            try:
                if not parts or parts[0] != "api":
                    if method != "GET":
                        return self._json({"error": "method not allowed"}, 405)
                    return self._static("/".join(parts))
                return self._api(method, parts[1:], q)
            except ApiError as e:
                return self._json({"error": str(e)}, e.status)
            except NameMarked as e:                 # turn it off by renaming the playlist
                return self._json({"error": str(e)}, 409)
            except CommentNotKept as e:             # Navidrome did not keep what we wrote; nothing was cached
                return self._json({"error": str(e)}, 502)
            except ReconcileBusy as e:              # the worker is reconciling; nothing was written
                return self._json({"error": f"busy, try again ({e})"}, 503)
            except SubsonicError as e:
                return self._json({"error": str(e), "code": e.code}, 502 if e.code == 0 else 400)
            except sqlite3.Error:                   # navidrome.db (NAVIDROME_DB) missing, locked or unreadable
                return self._json({"error": "Navidrome's database can't be read right now"}, 503)
            except (ConnectionError, OSError) as e:
                return self._json({"error": f"cannot reach Navidrome: {e}"}, 502)
            except (KeyError, ValueError) as e:
                return self._json({"error": f"bad request: {e}"}, 400)

        def _api(self, method: str, p: list[str], q: dict):
            head = p[0] if p else ""
            if method == "GET":
                if head == "status":
                    return self._json(app.status())
                if head == "playlists" and len(p) == 1:
                    return self._json(app.playlists())
                if head == "playlists" and len(p) == 2:
                    return self._json(app.playlist(p[1]))
                if head == "crates":
                    return self._json(app.crates())
                if head == "wanted" and len(p) == 1:
                    return self._json(public(app.store.wanted()))
                if head == "wanted" and len(p) == 2:
                    return self._json(app.wanted_row(p[1]))
                if head == "proposals" and len(p) == 1:
                    return self._json(app.proposals(include_decided=q.get("all") in ("1", "true")))
                if head == "events":
                    return self._json(public(app.store.events(int(q.get("limit", 50)))))
                if head == "search":
                    return self._json(app.search(q.get("q", ""), int(q.get("count", 25))))
                if head == "stream-tier":
                    return self._json({"tier": app.store.stream_tier(),
                                       "tiers": {t: {"format": f, "maxBitRate": b} for t, (f, b) in STREAM.items()}})
                if head == "stream" and len(p) == 2:
                    if "tier" in q:                                  # spec §1: the stream follows the tier's name
                        fmt, mbr = STREAM[check_stream(q["tier"])]
                        return self._redirect(app.stream_url(p[1], mbr, fmt))
                    mbr = q.get("maxBitRate")
                    return self._redirect(app.stream_url(p[1], int(mbr) if mbr else None, q.get("format")))
                if head == "download" and len(p) == 2:
                    return self._redirect(app.download_url(p[1]))
                if head == "cover" and len(p) == 2:
                    sz = q.get("size")
                    return self._redirect(app.cover_url(p[1], int(sz) if sz else None))
            elif method == "POST":
                body = self._body()
                if head == "playlists" and len(p) == 3 and p[2] == "crate":
                    return self._json(app.set_crate(p[1], bool(body.get("enabled", True))))
                if head == "playlists" and len(p) == 3 and p[2] == "tier":
                    tier = body.get("tier")
                    if tier is not None and not isinstance(tier, str):
                        raise ApiError(400, "tier must be a tier name or null")
                    return self._json(app.set_tier(p[1], tier))
                if head == "playlists" and len(p) == 3 and p[2] == "songs":
                    return self._json(app.add_to_playlist(p[1], list(body.get("songIds", []))))
                if head == "playlists" and len(p) == 1:
                    return self._json(app.create_playlist(body["name"], list(body.get("songIds", [])), bool(body.get("crate", False))), 201)
                if head == "wanted" and len(p) == 3 and p[2] in ("preview", "approve", "play-now"):
                    if p[2] == "preview":
                        return self._json(app.preview(p[1]))
                    if p[2] == "play-now":
                        return self._json(app.play_now(p[1]))
                    return self._json(app.approve(p[1], body.get("candidate")))
                if head == "proposals" and len(p) == 3 and p[2] in ("accept", "decline"):
                    if not p[1].isdigit():
                        raise ApiError(400, f"proposal id must be a number, not {p[1]!r}")
                    if p[2] == "accept":
                        return self._json(app.accept_proposal(int(p[1])))
                    return self._json(app.decline_proposal(int(p[1])))
                if head == "reconcile":
                    return self._json(app.reconcile())
                if head == "stream-tier":
                    app.store.set_stream_tier(str(body.get("tier")))
                    return self._json({"tier": app.store.stream_tier()})
            return self._json({"error": "not found"}, 404)

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

    return Handler


class CrateServer:
    def __init__(self, app: CrateApp, bind: str | None = None, port: int | None = None):
        self.app = app
        self.httpd = ThreadingHTTPServer((bind or app.cfg.bind, app.cfg.port if port is None else port), make_handler(app))
        self.httpd.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        h, p = self.httpd.server_address[:2]
        return f"http://{h}:{p}"

    def start_background(self) -> "CrateServer":
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def serve_forever(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def __enter__(self):
        return self.start_background()

    def __exit__(self, *exc):
        self.stop()
