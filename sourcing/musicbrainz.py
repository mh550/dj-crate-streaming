"""MusicBrainz recording length: the check that makes a beets match 'confident' (D22).

beets 1.6 in quiet mode applies a MusicBrainz match on artist + title alone when the MB recording has no
length (distance 0.0, "strong"). For a DJ library, where a radio edit and a 12" are different versions, that
is a guess, and `beet write` would stamp the wrong recording id and titles on a fresh download. So the filer
asks `confirm_recording_length` before it writes: the match stands only when the recording's length agrees
with the file's.

MusicBrainz requires a descriptive User-Agent and allows about one request per second; the worker makes at
most one call per download.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Callable

URL = "https://musicbrainz.org/ws/2/recording/{id}?fmt=json"
USER_AGENT = "dj-crate-streaming/0.1 (https://github.com/mh550/dj-crate-streaming)"


def recording_length(mb_trackid: str, *, timeout: float = 10, opener=urllib.request.urlopen) -> float | None:
    """The recording's length in seconds, or None when MusicBrainz has none. Raises on HTTP/URL/JSON errors."""
    req = urllib.request.Request(URL.format(id=mb_trackid), headers={"User-Agent": USER_AGENT})
    with opener(req, timeout=timeout) as r:
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
