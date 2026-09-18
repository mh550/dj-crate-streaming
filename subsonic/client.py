"""Minimal OpenSubsonic client, stdlib only. Written to be *read* as much as used —
each method notes the protocol fact it relies on.

Protocol in one paragraph (Subsonic 1.16.1 + OpenSubsonic extensions):
  Every call is `GET {server}/rest/{method}.view` with query params (Navidrome also
  accepts the bare `/rest/{method}`; other servers may not, so we keep `.view`). Always sent:
    u   username
    t   md5(password + salt) as lowercase hex         } "token auth" — the password
    s   the random salt used for t (fresh per call)   }  itself never crosses the wire
    v   protocol version we speak (1.16.1)
    c   client name — Navidrome creates a "Player" per (user, c) and hangs the
        transcoding profile / max bitrate on it. So the value of `c` decides what
        format your phone gets. Pick a stable, descriptive name.
    f   json  (default is XML)
  Response: {"subsonic-response": {"status": "ok"|"failed", "version": ..., "type": "navidrome",
             "serverVersion": ..., "openSubsonic": true, <payload>}}; on failure an
  "error": {"code", "message"} object. Binary endpoints (stream/download/getCoverArt) return bytes.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterable

API_VERSION = "1.16.1"
DEFAULT_CLIENT_NAME = "dj-crates"

# Subsonic error codes (http://www.subsonic.org/pages/api.jsp, "Error handling")
ERRORS = {
    0: "generic error", 10: "required parameter missing", 20: "client must upgrade",
    30: "server must upgrade", 40: "wrong username or password", 41: "token auth not supported for LDAP user",
    50: "user not authorized", 60: "trial expired", 70: "requested data not found",
}


class SubsonicError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(f"subsonic error {code}: {message}")
        self.code = code
        self.message = message


@dataclass
class Song:
    """The fields of a Subsonic `Child` (song) entry we care about. Everything else is in `raw`."""
    id: str
    title: str
    artist: str | None
    album: str | None
    duration: int | None          # seconds
    bit_rate: int | None          # kbps as the server reports it
    suffix: str | None            # file extension without the dot: flac, mp3 ...
    content_type: str | None
    size: int | None
    path: str | None
    year: int | None = None
    track: int | None = None
    sample_rate: int | None = None   # OpenSubsonic: samplingRate
    bit_depth: int | None = None     # OpenSubsonic: bitDepth
    music_brainz_id: str | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, d: dict) -> "Song":
        return cls(
            id=str(d["id"]), title=d.get("title", ""), artist=d.get("artist"), album=d.get("album"),
            duration=d.get("duration"), bit_rate=d.get("bitRate"), suffix=(d.get("suffix") or "").lower() or None,
            content_type=d.get("contentType"), size=d.get("size"), path=d.get("path"), year=d.get("year"),
            track=d.get("track"), sample_rate=d.get("samplingRate"), bit_depth=d.get("bitDepth"),
            music_brainz_id=d.get("musicBrainzId"), raw=d,
        )


@dataclass
class Playlist:
    id: str
    name: str
    song_count: int
    duration: int
    comment: str | None = None
    owner: str | None = None
    public: bool = False
    changed: str | None = None
    entries: list[Song] = field(default_factory=list)   # only filled by get_playlist

    @classmethod
    def from_json(cls, d: dict) -> "Playlist":
        return cls(
            id=str(d["id"]), name=d.get("name", ""), song_count=int(d.get("songCount") or 0),
            duration=int(d.get("duration") or 0), comment=d.get("comment"), owner=d.get("owner"),
            public=bool(d.get("public", False)), changed=d.get("changed"),
            entries=[Song.from_json(e) for e in d.get("entry", [])],
        )


class SubsonicClient:
    def __init__(self, base_url: str, username: str, password: str,
                 client_name: str = DEFAULT_CLIENT_NAME, timeout: float = 30):
        self.base = base_url.rstrip("/")
        self.user = username
        self._password = password
        self.client_name = client_name
        self.timeout = timeout
        self.server_info: dict = {}   # filled by ping(): type, serverVersion, openSubsonic

    # ---------- auth + transport ----------

    def auth_params(self) -> dict[str, str]:
        """Token auth: a fresh salt per request; t = md5(password + salt).
        Weakness worth knowing: anyone who captures (t, s) can brute-force the password
        offline, which is why this must only travel over HTTPS or a private network
        (Tailscale). OpenSubsonic's `apiKeyAuthentication` extension avoids that, but
        Navidrome (v0.64, Sept 2026) does not implement it yet — see supports()."""
        salt = secrets.token_hex(8)
        token = hashlib.md5((self._password + salt).encode()).hexdigest()
        return {"u": self.user, "t": token, "s": salt, "v": API_VERSION, "c": self.client_name, "f": "json"}

    def url(self, method: str, **params: Any) -> str:
        """Build a fully authenticated URL. Repeated params (songId=a&songId=b) are lists."""
        q: list[tuple[str, str]] = list(self.auth_params().items())
        for k, v in params.items():
            if v is None:
                continue
            if isinstance(v, (list, tuple)):
                q.extend((k, str(x)) for x in v)
            else:
                q.append((k, str(v).lower() if isinstance(v, bool) else str(v)))
        return f"{self.base}/rest/{method}.view?{urllib.parse.urlencode(q)}"

    def _get_bytes(self, method: str, **params: Any) -> tuple[bytes, str]:
        req = urllib.request.Request(self.url(method, **params), headers={"Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:   # Navidrome returns 200 even for API errors; HTTP errors are transport-level
            raise SubsonicError(0, f"HTTP {e.code} from {method}") from e

    def call(self, method: str, **params: Any) -> dict:
        """JSON call; unwraps `subsonic-response`, raises SubsonicError on status=failed."""
        raw, ctype = self._get_bytes(method, **params)
        if "json" not in ctype and not raw.lstrip().startswith(b"{"):
            raise SubsonicError(0, f"{method}: expected JSON, got {ctype or 'unknown'}")
        env = json.loads(raw)["subsonic-response"]
        if env.get("status") != "ok":
            err = env.get("error", {})
            raise SubsonicError(int(err.get("code", 0)), err.get("message") or ERRORS.get(int(err.get("code", 0)), "?"))
        self.server_info = {k: env.get(k) for k in ("type", "version", "serverVersion", "openSubsonic")}
        return env

    # ---------- system ----------

    def ping(self) -> dict:
        self.call("ping")
        return self.server_info

    def extensions(self) -> dict[str, list[int]]:
        """OpenSubsonic: which optional extensions the server implements (e.g. formPost,
        transcodeOffset, songLyrics, apiKeyAuthentication). Plain Subsonic servers 404/error here."""
        try:
            env = self.call("getOpenSubsonicExtensions")
        except SubsonicError:
            return {}
        return {e["name"]: e.get("versions", []) for e in env.get("openSubsonicExtensions", [])}

    def supports(self, extension: str) -> bool:
        return extension in self.extensions()

    def scan_status(self) -> dict:
        return self.call("getScanStatus")["scanStatus"]

    def start_scan(self) -> dict:
        return self.call("startScan")["scanStatus"]

    # ---------- playlists (the orchestrator's source of truth for "what is a crate") ----------

    def playlists(self) -> list[Playlist]:
        env = self.call("getPlaylists")
        return [Playlist.from_json(p) for p in env.get("playlists", {}).get("playlist", [])]

    def playlist(self, playlist_id: str) -> Playlist:
        return Playlist.from_json(self.call("getPlaylist", id=playlist_id)["playlist"])

    def create_playlist(self, name: str, song_ids: Iterable[str] = ()) -> Playlist:
        env = self.call("createPlaylist", name=name, songId=list(song_ids))
        return Playlist.from_json(env["playlist"])

    def update_playlist(self, playlist_id: str, *, name: str | None = None, comment: str | None = None,
                        public: bool | None = None, add_song_ids: Iterable[str] = (),
                        remove_indexes: Iterable[int] = ()) -> None:
        """Protocol quirk: songs are *added by id* but *removed by position* (songIndexToRemove)."""
        self.call("updatePlaylist", playlistId=playlist_id, name=name, comment=comment, public=public,
                  songIdToAdd=list(add_song_ids), songIndexToRemove=list(remove_indexes))

    def delete_playlist(self, playlist_id: str) -> None:
        self.call("deletePlaylist", id=playlist_id)

    # ---------- library ----------

    def song(self, song_id: str) -> Song:
        return Song.from_json(self.call("getSong", id=song_id)["song"])

    def search_songs(self, query: str, count: int = 20, offset: int = 0) -> list[Song]:
        env = self.call("search3", query=query, songCount=count, songOffset=offset, artistCount=0, albumCount=0)
        return [Song.from_json(s) for s in env.get("searchResult3", {}).get("song", [])]

    # ---------- media ----------

    def stream_url(self, song_id: str, max_bit_rate: int | None = None, fmt: str | None = None,
                   time_offset: int | None = None) -> str:
        """`stream` — Navidrome's decision (core/stream, v0.64):
             format=raw                        → original bytes, always
             format=X (≠ source suffix)        → transcode to X
             maxBitRate < source bitrate       → transcode to DefaultDownsamplingFormat (opus)
             player has a forced profile       → that profile at the player's max bitrate
             otherwise                         → original bytes ("direct play")
           timeOffset starts N seconds in (needs the transcodeOffset extension).
        Returns a URL because <audio src=...> and mobile players want a URL, not bytes."""
        return self.url("stream", id=song_id, maxBitRate=max_bit_rate, format=fmt,
                        timeOffset=time_offset, estimateContentLength=True)

    def download_url(self, song_id: str) -> str:
        """`download` = the original file. Navidrome *can* transcode downloads when
        AutoTranscodeDownload is on and the player has a profile, so we pin format=raw."""
        return self.url("download", id=song_id, format="raw")

    def cover_art_url(self, cover_id: str, size: int | None = None) -> str:
        return self.url("getCoverArt", id=cover_id, size=size)

    def download(self, song_id: str) -> bytes:
        return self._get_bytes("download", id=song_id, format="raw")[0]
