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
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

URL = "https://musicbrainz.org/ws/2/recording/{id}?fmt=json"
USER_AGENT = "dj-crate-streaming/0.1 (https://github.com/mh550/dj-crate-streaming)"


class _Limiter:
    """The process-wide spacing: one request in flight, each at least `min_interval_s` after the last finished.

    Module-level on purpose: the backfill client and the worker's confirm step (`recording_length`) are different
    callers of one MusicBrainz IP allowance, so no instance owns the limit. The lock is held across the request,
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


_SHARED = _Limiter()


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


def parse_recording(d: dict) -> Recording:
    """A `Recording` from MusicBrainz JSON: length ms -> s; works from `performance` relations, each once."""
    length = d.get("length")
    works = tuple(dict.fromkeys(r["work"]["id"] for r in d.get("relations") or []
                                if r.get("type") == "performance" and (r.get("work") or {}).get("id")))
    artist = "".join((c.get("name") or "") + (c.get("joinphrase") or "") for c in d.get("artist-credit") or [])
    return Recording(id=d["id"], title=d.get("title") or "", length_s=None if length is None else length / 1000,
                     artist=artist, work_ids=works, isrcs=tuple(d.get("isrcs") or ()),
                     releases=tuple(r["title"] for r in d.get("releases") or [] if r.get("title")))


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
        if self._cache_path and self._cache_path.exists():
            for line in self._cache_path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    row = json.loads(line)
                    self._cache[row["url"]] = (row["status"], row.get("body"))
                except (ValueError, KeyError, TypeError):
                    continue                                 # a torn last line from a killed run: ask again

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
                if e.code != 503:
                    raise MusicBrainzError(f"MusicBrainz HTTP {e.code}: {path}") from None
                if attempt == self.retries:
                    raise MusicBrainzError(f"MusicBrainz 503 after {self.retries} tries: {path}") from None
                try:
                    delay = min(int(e.headers.get("Retry-After")), MAX_RETRY_AFTER_S)
                except (TypeError, ValueError, AttributeError):
                    delay = 2 * attempt
                self._sleep(delay)
                continue
            except (urllib.error.URLError, OSError, ValueError) as e:
                raise MusicBrainzError(f"MusicBrainz request failed ({type(e).__name__}): {path}") from None
            self._remember(url, 200, body)
            return body
        raise MusicBrainzError(f"MusicBrainz 503 after {self.retries} tries: {path}")   # retries == 0

    def recording(self, mbid: str) -> Recording | None:
        d = self.get(f"recording/{mbid}", inc="work-rels isrcs")
        return None if d is None else parse_recording(d)

    def isrc(self, isrc: str) -> list[Recording]:
        d = self.get(f"isrc/{isrc}", inc="work-rels")
        return [] if d is None else [parse_recording(r) for r in d.get("recordings") or []]

    def search(self, artist: str, title: str, limit: int = 100) -> list[Recording]:
        d = self.get("recording", query=f'artist:"{_escape(artist)}" AND recording:"{_escape(title)}"', limit=limit)
        return [] if d is None else [parse_recording(r) for r in d.get("recordings") or []]
