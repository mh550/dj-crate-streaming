"""AcoustID lookup: which MusicBrainz recording does this file's audio fingerprint belong to?

Used by `verify` (only when ACOUSTID_KEY is set) to catch a download that is the wrong song when Navidrome
already knows the recording id. The fingerprint is `fpcalc`'s compressed form (the web service rejects `-raw`).
The application key goes in the POST body, never in a URL, so it cannot reach a log or an exception message.
"""
from __future__ import annotations

import json
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

URL = "https://api.acoustid.org/v2/lookup"


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
    """Every recording of every result as {"id", "title", "score"}: best score first, each id once."""
    if resp.get("status") != "ok":
        raise ValueError(f"AcoustID status {resp.get('status')!r}: {(resp.get('error') or {}).get('message', 'no message')}")
    out: dict[str, dict] = {}
    for res in sorted(resp.get("results") or [], key=lambda r: r.get("score") or 0, reverse=True):
        for rec in res.get("recordings") or []:
            out.setdefault(rec["id"], {"id": rec["id"], "title": rec.get("title"), "score": res.get("score")})
    return list(out.values())


def lookup(path: Path, key: str, *, timeout: float = 10, opener=urllib.request.urlopen) -> list[dict]:
    duration, fp = compressed_fingerprint(path)
    body = urllib.parse.urlencode({"client": key, "meta": "recordings", "duration": duration,
                                   "fingerprint": fp, "format": "json"}).encode()
    req = urllib.request.Request(URL, data=body, method="POST")
    with opener(req, timeout=timeout) as r:
        return parse(json.loads(r.read().decode("utf-8", errors="replace")))


def make_lookup(key: str) -> Callable[[Path], list[dict]]:
    return lambda path: lookup(path, key)
