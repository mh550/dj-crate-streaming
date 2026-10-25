"""MusicBrainz recording length: the check that makes a beets match 'confident' (D22).

beets 1.6 in quiet mode applies a MusicBrainz match on artist + title alone when the MB recording has no
length (distance 0.0, "strong"). For a DJ library, where a radio edit and a 12" are different versions, that
is a guess, and `beet write` would stamp the wrong recording id and titles on a fresh download. So the filer
asks `confirm_recording_length` before it writes: the match stands only when the recording's length agrees
with the file's.

MusicBrainz requires a descriptive User-Agent and allows about one request per second; the worker makes at
most one call per download. The identity backfill (M7) makes thousands, through the `MusicBrainz` client below.

Measured live (2026-10-16): a request takes about 0.6 s, and even at 1.05 s spacing about 11% (8 of ~70) answer
503 "server is currently busy". So the client spaces every request, retries a 503 with backoff (bounded), and
keeps a resumable on-disk cache: breaking the policy gets the IP blocked, which would also break the worker's
confirm step above, and an interrupted ~35 minute run must never ask the same question twice.
"""
from __future__ import annotations

import contextlib
import http.client
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from . import identity

URL = "https://musicbrainz.org/ws/2/recording/{id}?fmt=json"
USER_AGENT = "dj-crate-streaming/0.1 (https://github.com/mh550/dj-crate-streaming)"


class Limiter:
    """The process-wide spacing: one request in flight, each at least `min_interval_s` after the last finished.

    Module-level on purpose: the backfill client and the worker's confirm step (`recording_length`) are different
    callers of one MusicBrainz IP allowance, so no instance owns the limit (sourcing/acoustid.py keeps its own
    shared instance for AcoustID's allowance). The lock is held across the request,
    so threads queue. `clock`/`sleep` are injectable per call for tests.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._last: float | None = None

    def reset(self) -> None:
        self._last = None

    @contextlib.contextmanager
    def slot(self, clock: Callable[[], float], sleep: Callable[[float], None], min_interval_s: float):
        with self._lock:
            if self._last is not None:
                wait = min_interval_s - (clock() - self._last)
                if wait > 0:
                    sleep(wait)
            try:
                yield
            finally:
                self._last = clock()


_SHARED = Limiter()


def reset_shared_limiter() -> None:
    """Forget the last request time (tests: so order does not matter, and a fake clock never meets a real one)."""
    _SHARED.reset()


def recording_length(mb_trackid: str, *, timeout: float = 10, opener=urllib.request.urlopen,
                     sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                     min_interval_s: float = 1.05) -> float | None:
    """The recording's length in seconds, or None when MusicBrainz has none. Raises on HTTP/URL/JSON errors.

    Goes through the shared limiter, so it waits its turn behind a running backfill instead of bursting."""
    req = urllib.request.Request(URL.format(id=mb_trackid), headers={"User-Agent": USER_AGENT})
    with _SHARED.slot(clock, sleep, min_interval_s), opener(req, timeout=timeout) as r:
        length = json.loads(r.read().decode("utf-8", errors="replace")).get("length")
    return None if length is None else length / 1000


def confirm_recording_length(item, *, tol_s: float = 4.0,
                             lookup: Callable[[str], float | None] = recording_length) -> tuple[bool, str]:
    """(confident?, why) for a `FiledItem` beets matched. Never raises: a lookup failure is 'not confirmed'."""
    try:
        mb = lookup(item.mb_trackid)
    except Exception as e:                                   # network down, 404, rate limit, bad JSON: all "unconfirmed"
        return False, f"MusicBrainz lookup failed: {type(e).__name__}: {e}"
    if mb is None:
        return False, f"MusicBrainz has no length for recording {item.mb_trackid}"
    d = abs(mb - item.length)
    said = f"MusicBrainz length {mb:.0f} s vs file {item.length:.0f} s"
    return (True, said) if d <= tol_s else (False, f"{said} (Δ{d:.0f} s)")


# ---- the rate-limited client (M7 identity backfill) -------------------------------------------------------------

BASE = "https://musicbrainz.org/ws/2/"
RETRY_STATUS = (502, 503, 504)                               # MusicBrainz's proxy answers all three when busy
MAX_RETRY_AFTER_S = 60                                       # a hostile or confused header must not stall a run for an hour


class MusicBrainzError(Exception):
    """A request that cannot be answered: retries exhausted, an HTTP error other than 404, or no network."""


@dataclass(frozen=True)
class Recording:
    id: str
    title: str
    length_s: float | None
    artist: str                                              # artist-credit names joined with their joinphrases
    work_ids: tuple[str, ...] = ()
    isrcs: tuple[str, ...] = ()
    releases: tuple[str, ...] = ()                           # release titles
    disambiguation: str = ""                                 # often the only place MusicBrainz names the version
    video: bool = False


def parse_recording(d: dict) -> Recording:
    """A `Recording` from MusicBrainz JSON: length ms -> s; works from `performance` relations, each once."""
    length = d.get("length")
    works = tuple(dict.fromkeys(r["work"]["id"] for r in d.get("relations") or []
                                if r.get("type") == "performance" and (r.get("work") or {}).get("id")))
    artist = "".join((c.get("name") or "") + (c.get("joinphrase") or "") for c in d.get("artist-credit") or [])
    return Recording(id=d["id"], title=d.get("title") or "", length_s=None if length is None else length / 1000,
                     artist=artist, work_ids=works, isrcs=tuple(d.get("isrcs") or ()),
                     releases=tuple(r["title"] for r in d.get("releases") or [] if r.get("title")),
                     disambiguation=(d.get("disambiguation") or "").strip(), video=bool(d.get("video")))


def read_cache_lines(path: Path) -> list:
    """Every JSON line of an append-only cache file, in order; unparsable lines are skipped (the cache is derived).

    A killed run's torn last line is cut from the file first, or the next append would merge into it and lose
    both entries."""
    path = Path(path)
    if not path.exists():
        return []
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        data = data[:data.rfind(b"\n") + 1]
        with path.open("r+b") as f:
            f.truncate(len(data))
    rows = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _escape(s: str) -> str:
    """Lucene phrase escaping: a backslash or a quote inside "..." gets one more backslash."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


class MusicBrainz:
    """Spacing is process-wide (`_SHARED`), not per instance; use one cache file per run.

    `opener`, `sleep` and `clock` are injectable so tests never touch the network or wait.
    """

    def __init__(self, *, opener=urllib.request.urlopen, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic, min_interval_s: float = 1.05, retries: int = 4,
                 timeout: float = 15, cache: Path | None = None):
        self._opener, self._sleep, self._clock = opener, sleep, clock
        self.min_interval_s, self.retries, self.timeout = min_interval_s, retries, timeout
        self._cache_path = Path(cache) if cache else None
        self._cache: dict[str, tuple[int, dict | None]] = {}
        for row in read_cache_lines(self._cache_path) if self._cache_path else ():
            try:
                self._cache[row["url"]] = (row["status"], row.get("body"))
            except (KeyError, TypeError):
                continue

    def _remember(self, url: str, status: int, body: dict | None) -> None:
        self._cache[url] = (status, body)
        if self._cache_path:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self._cache_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"url": url, "status": status, "body": body}, ensure_ascii=False) + "\n")
                f.flush()

    def get(self, path: str, **query) -> dict | None:
        """The JSON at `path` (relative to /ws/2/), or None on 404. Cached answers cost no request and no wait."""
        url = BASE + path + "?" + urllib.parse.urlencode({"fmt": "json", **query})
        if url in self._cache:
            status, body = self._cache[url]
            return body if status == 200 else None
        for attempt in range(1, self.retries + 1):
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with _SHARED.slot(self._clock, self._sleep, self.min_interval_s), \
                        self._opener(req, timeout=self.timeout) as r:
                    body = json.loads(r.read().decode("utf-8", errors="replace"))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    self._remember(url, 404, None)
                    return None
                if e.code not in RETRY_STATUS:
                    raise MusicBrainzError(f"MusicBrainz HTTP {e.code}: {path}") from None
                if attempt == self.retries:
                    raise MusicBrainzError(f"MusicBrainz {e.code} after {self.retries} tries: {path}") from None
                try:
                    delay = int(e.headers.get("Retry-After"))
                except (TypeError, ValueError, AttributeError):
                    delay = -1
                delay = min(delay, MAX_RETRY_AFTER_S) if delay >= 0 else 2 * attempt
                self._sleep(delay)
                continue
            except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:
                raise MusicBrainzError(f"MusicBrainz request failed ({type(e).__name__}): {path}") from None
            self._remember(url, 200, body)
            return body
        raise MusicBrainzError(f"MusicBrainz 503 after {self.retries} tries: {path}")   # retries == 0

    def recording(self, mbid: str) -> Recording | None:
        d = self.get(f"recording/{mbid}", inc="artist-credits work-rels isrcs")
        return None if d is None else parse_recording(d)

    def isrc(self, isrc: str) -> list[Recording]:
        """The ISRC's recordings with their artist credits (without `artist-credits` the endpoint sends none,
        measured 2026-10-16) and works."""
        d = self.get(f"isrc/{isrc}", inc="artist-credits work-rels")
        return [] if d is None else [parse_recording(r) for r in d.get("recordings") or []]

    def search(self, artist: str, title: str, limit: int = 100) -> list[Recording]:
        d = self.get("recording", query=f'artist:"{_escape(artist)}" AND recording:"{_escape(title)}"', limit=limit)
        return [] if d is None else [parse_recording(r) for r in d.get("recordings") or []]

    def release_search(self, artist: str, album: str, limit: int = 25) -> list[dict]:
        """The releases MusicBrainz finds for artist + album (search JSON: id, title, track-count, date, media)."""
        d = self.get("release", query=f'artist:"{_escape(artist)}" AND release:"{_escape(album)}"', limit=limit)
        return [] if d is None else list(d.get("releases") or [])

    def release(self, mbid: str) -> dict | None:
        """The release with its media, tracks and their recordings; None when MusicBrainz has no such release."""
        return self.get(f"release/{mbid}", inc="recordings")


# ---- the release an album request is (S2-03) --------------------------------------------------------------------

_FORMAT_RANK = {"Digital Media": 0, "CD": 1}                 # ties: digital, then CD, then anything else


@dataclass(frozen=True)
class ReleaseTrack:
    position: int                                            # 1-based across all media, like a request row's track_no
    title: str
    recording_id: str


@dataclass(frozen=True)
class ReleaseMatch:
    id: str
    format: str
    date: str
    tracks: tuple[ReleaseTrack, ...]                         # tracks[i] is the row with track_no i + 1


def _format(release: dict) -> str:
    return ((release.get("media") or [{}])[0] or {}).get("format") or ""


def _tie_order(release: dict) -> tuple:
    date = release.get("date") or ""
    return _FORMAT_RANK.get(_format(release), len(_FORMAT_RANK)), not date, date


def _title_key(title: str | None, artist: str | None) -> tuple:
    """`Oh ,Pretty Woman` (Spotify) and `Oh, Pretty Woman` (MusicBrainz) are one key; so are ' and ’. The version
    counts too: a live or remixed track of the same name is another recording."""
    t = identity.parse_title(title, artist)
    return identity.loose(t.base), t.key


def match_release(rows: Sequence[dict], releases: Sequence[dict],
                  fetch_release: Callable[[str], dict | None]) -> ReleaseMatch | None:
    """The release whose tracks are the request's rows one to one, in track order across all media, or None.

    `rows` are a request's rows (dicts with `track_no`, `artist`, `title` or `asked_title`), numbered 1..n (the
    caller drops removed and superseded rows); `releases` are search
    results. Only releases listing n tracks are fetched, in tie order (digital, CD, then the earliest date; no
    date last), and the first whose every track title has its row's key wins. Order matters, not only the set:
    a file AcoustID'd as track 9 must not pass as track 1 (ext-74)."""
    by_no = {r.get("track_no"): r for r in rows}
    n = len(rows)
    if n == 0 or set(by_no) != set(range(1, n + 1)):
        return None
    for rel in sorted((r for r in releases if r.get("track-count") == n and r.get("id")), key=_tie_order):
        body = fetch_release(rel["id"])
        if not body:
            continue
        listed = [t for m in body.get("media") or [] for t in m.get("tracks") or []]
        if len(listed) != n:
            continue
        tracks = tuple(ReleaseTrack(i, t.get("title") or "", (t.get("recording") or {}).get("id") or "")
                       for i, t in enumerate(listed, 1))
        if all(t.recording_id and _title_key(t.title, row.get("artist"))
               == _title_key(row.get("asked_title") or row.get("title"), row.get("artist"))
               for t, row in ((t, by_no[t.position]) for t in tracks)):
            return ReleaseMatch(rel["id"], _format(rel), rel.get("date") or "", tracks)
    return None
