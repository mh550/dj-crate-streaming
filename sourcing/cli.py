"""CLI: rank candidates for a wanted track, from a fixture file or a live slskd.

  python -m sourcing.cli rank --fixture fixtures/search_responses.sample.json --artist Chic --title "Good Times" --duration 501
  python -m sourcing.cli rank --slskd http://server:5030 --api-key $SLSKD_KEY --artist Chic --title "Good Times" [--download]
  python -m sourcing.cli verify /srv/incoming/03\ -\ Good\ Times.flac --duration 501
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .scorer import Wanted, rank, explain
from .policy import DEFAULT_POLICY
from .verify import verify


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sourcing")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("rank", help="score search results for a wanted track")
    r.add_argument("--artist", required=True)
    r.add_argument("--title", required=True)
    r.add_argument("--album")
    r.add_argument("--duration", type=float, help="expected length in seconds (from Spotify/MusicBrainz)")
    r.add_argument("--year", type=int)
    r.add_argument("--fixture", help="JSON file shaped like slskd search responses (offline mode)")
    r.add_argument("--slskd", help="slskd base URL, e.g. http://localhost:5030")
    r.add_argument("--api-key", default=os.environ.get("SLSKD_API_KEY"))
    r.add_argument("--download", action="store_true", help="enqueue the top candidate (live mode only)")
    r.add_argument("--json", action="store_true")
    r.add_argument("--limit", type=int, default=10)

    v = sub.add_parser("verify", help="check a downloaded file")
    v.add_argument("path")
    v.add_argument("--duration", type=float)

    a = ap.parse_args(argv)

    if a.cmd == "verify":
        vd = verify(Path(a.path), a.duration)
        print(("OK  " if vd.ok else "BAD ") + a.path)
        if vd.info:
            print(f"     {vd.info.codec} {vd.info.sample_rate} Hz / {vd.info.bit_depth} bit / {vd.info.channels} ch / {vd.info.duration_s and round(vd.info.duration_s, 1)} s  [{vd.info.source}]")
        for p in vd.problems:
            print("     ✗", p)
        return 0 if vd.ok else 2

    wanted = Wanted(a.artist, a.title, a.album, a.duration, a.year)
    if a.fixture:
        responses = json.loads(Path(a.fixture).read_text())
        client = None
    elif a.slskd:
        if not a.api_key:
            print("need --api-key or $SLSKD_API_KEY", file=sys.stderr); return 1
        from .slskd_client import SlskdClient
        client = SlskdClient(a.slskd, a.api_key)
        sid = client.search(f"{a.artist} {a.title}")
        st = client.wait_search(sid)
        responses = client.search_responses(sid)
        print(f"search {st.get('state')}: {len(responses)} peers responded", file=sys.stderr)
    else:
        print("need --fixture or --slskd", file=sys.stderr); return 1

    cands = rank(responses, wanted, DEFAULT_POLICY)
    if a.json:
        print(json.dumps([c.__dict__ for c in cands[: a.limit]], indent=2))
    else:
        print(f"wanted: {wanted.artist} — {wanted.title}" + (f" ({wanted.duration_s:.0f}s)" if wanted.duration_s else ""))
        print(explain(cands, a.limit))
    best = next((c for c in cands if not c.rejected), None)
    if a.download and client and best:
        client.enqueue(best.username, [{"filename": best.filename, "size": best.size}])
        print(f"enqueued from {best.username}: {best.basename}")
    return 0 if best else 3


if __name__ == "__main__":
    raise SystemExit(main())
