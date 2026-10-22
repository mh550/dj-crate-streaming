"""AcoustID lookup: which MusicBrainz recording does this file's audio fingerprint belong to?

Used by `verify` (only when ACOUSTID_KEY is set) to catch a download that is the wrong song when Navidrome
already knows the recording id. The fingerprint is `fpcalc`'s compressed form (the web service rejects `-raw`).
The application key goes in the POST body, never in a URL, so it cannot reach a log or an exception message.

AcoustID allows 3 requests a second per client: every request waits its slot on one process-wide limiter
(`_SHARED`, a `musicbrainz.Limiter` of its own, since the two services are separate allowances). The backfill's
`propose` keeps the answers in `acoustid-cache.jsonl` beside the proposal (`Cache`), keyed on the file's path,
size and mtime_ns, so a re-propose fingerprints and asks only for files that changed (M9 §8a). The cache is
derived: delete it to ask again.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from .musicbrainz import Limiter, read_cache_lines

URL = "https://api.acoustid.org/v2/lookup"
MIN_INTERVAL_S = 1 / 3                       # AcoustID's documented limit: 3 requests per second

_SHARED = Limiter()


def reset_shared_limiter() -> None:
    """Forget the last request time (tests: so order does not matter, and a fake clock never meets a real one)."""
    _SHARED.reset()


class Cache:
    """Lookup answers by (path, size, mtime_ns), one JSON line each, appended per lookup; the last line for a key
    wins and an unreadable line is skipped. Only the file's stamp and AcoustID's recordings are stored: never the
    key."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._rows: dict[tuple, list] = {}
        for row in read_cache_lines(self.path):
            try:
                found = row["recordings"]
                if isinstance(found, list) and all(isinstance(a, dict) and isinstance(a.get("id"), str)
                                                   for a in found):
                    self._rows[(row["path"], row["size"], row["mtime_ns"])] = found
            except (KeyError, TypeError):                    # not an object, or a field missing: skipped
                continue

    @staticmethod
    def stamp(path: Path) -> tuple[str, int, int]:
        st = Path(path).stat()
        return str(path), st.st_size, st.st_mtime_ns

    def get(self, stamp: tuple[str, int, int]) -> list[dict] | None:
        return self._rows.get(stamp)

    def put(self, stamp: tuple[str, int, int], recordings: list[dict]) -> None:
        self._rows[stamp] = recordings
        line = json.dumps({"path": stamp[0], "size": stamp[1], "mtime_ns": stamp[2], "recordings": recordings},
                          ensure_ascii=False) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:  # one write of a whole line: a crash leaves at most a
            fh.write(line)                                    # torn tail, which the next load cuts
            fh.flush()
            os.fsync(fh.fileno())


def cached(lookup: Callable[[Path], list[dict]], cache: Cache) -> Callable[[Path], list[dict]]:
    """`lookup` answered from `cache` when the file is unchanged; a fresh answer is stored (an empty one too: "not
    in AcoustID" is an answer), a failure is not. A cache that cannot be written never hides the answer."""
    def run(path: Path) -> list[dict]:
        stamp = Cache.stamp(path)                # before fingerprinting: a file changed meanwhile is asked again
        hit = cache.get(stamp)
        if hit is not None:
            return hit
        found = lookup(path)
        try:
            cache.put(stamp, found)
        except OSError:
            pass
        return found
    return run


def compressed_fingerprint(path: Path) -> tuple[int, str]:
    """(duration in whole seconds, compressed fingerprint) from fpcalc's first 120 s."""
    run = subprocess.run(["fpcalc", "-json", "-length", "120", str(path)], stdin=subprocess.DEVNULL,
                         capture_output=True, timeout=300, text=True, encoding="utf-8", errors="replace")
    try:
        out = json.loads(run.stdout)
        return round(out["duration"]), out["fingerprint"]
    except (ValueError, KeyError, TypeError):
        raise ValueError(f"fpcalc gave no fingerprint (exit {run.returncode})") from None


def parse(resp: dict) -> list[dict]:
    """Every recording of every result as {"id", "title", "score", "acoustid"}: best score first, each id once.

    "acoustid" is the AcoustID track id of the result the recording came from (what `acoustid_id` stores)."""
    if resp.get("status") != "ok":
        raise ValueError(f"AcoustID status {resp.get('status')!r}: {(resp.get('error') or {}).get('message', 'no message')}")
    out: dict[str, dict] = {}
    for res in sorted(resp.get("results") or [], key=lambda r: r.get("score") or 0, reverse=True):
        for rec in res.get("recordings") or []:
            out.setdefault(rec["id"], {"id": rec["id"], "title": rec.get("title"), "score": res.get("score"),
                                                  "acoustid": res.get("id")})
    return list(out.values())


def lookup(path: Path, key: str, *, timeout: float = 10, opener=urllib.request.urlopen,
           clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> list[dict]:
    duration, fp = compressed_fingerprint(path)
    body = urllib.parse.urlencode({"client": key, "meta": "recordings", "duration": duration,
                                   "fingerprint": fp, "format": "json"}).encode()
    req = urllib.request.Request(URL, data=body, method="POST")
    with _SHARED.slot(clock, sleep, MIN_INTERVAL_S), opener(req, timeout=timeout) as r:
        return parse(json.loads(r.read().decode("utf-8", errors="replace")))


def make_lookup(key: str, cache: Cache | None = None, clock: Callable[[], float] = time.monotonic,
                sleep: Callable[[float], None] = time.sleep, *,
                opener=urllib.request.urlopen) -> Callable[[Path], list[dict]]:
    """`path -> recordings` for `key`, spaced by the shared limiter; with a cache, unchanged files cost nothing."""
    def run(path: Path) -> list[dict]:
        return lookup(path, key, opener=opener, clock=clock, sleep=sleep)
    return run if cache is None else cached(run, cache)
