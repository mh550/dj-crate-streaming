r"""CLI: rank candidates for a wanted track, from a fixture file or a live slskd.

  python -m sourcing.cli rank --fixture fixtures/search_responses.sample.json --artist Chic --title "Good Times" --duration 501
  python -m sourcing.cli rank --slskd http://server:5030 --api-key $SLSKD_KEY --artist Chic --title "Good Times" [--download]
  python -m sourcing.cli verify /srv/incoming/03\ -\ Good\ Times.flac --duration 501
  python -m sourcing.cli fetch --wanted s4 [--approve]        # one wanted track, end to end (see fetch.py)
  python -m sourcing.cli seed-spotify https://open.spotify.com/playlist/...   # queue tracks not in Navidrome
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .scorer import Wanted, rank, explain
from .policy import DEFAULT_POLICY
from .spotify_csv import fetch_entity
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

    f = sub.add_parser("fetch", help="take one wanted track through search → score → (approve) download → verify → file → ok")
    f.add_argument("--wanted", required=True, help="song id from `crates.cli wanted` (or ext-N from seed-spotify)")
    f.add_argument("--approve", action="store_true", help="actually download; without it, stop after scoring")
    f.add_argument("--slskd", default=os.environ.get("SLSKD_URL", "http://127.0.0.1:5030"))
    f.add_argument("--api-key", default=os.environ.get("SLSKD_API_KEY"))

    s = sub.add_parser("seed-spotify", help="add every track of a public Spotify playlist/album to the wanted queue")
    s.add_argument("url")

    a = ap.parse_args(argv)

    if a.cmd == "seed-spotify":
        from crates.service import Config
        from crates.store import CrateStore
        from .spotify_csv import rows
        db = Config.from_env().db_path
        Path(db).parent.mkdir(parents=True, exist_ok=True)
        store = CrateStore(db)
        added = dup = 0
        for r in rows(fetch_entity(a.url)):          # dicts: {"Artist", "Title", "Length"} (seconds)
            if store.find_external(r["Artist"], r["Title"]):
                dup += 1
            else:
                store.add_external_wanted(r["Artist"], r["Title"], duration_s=r["Length"], source=a.url); added += 1
        store.commit()
        print(f"{added} added, {dup} already queued ({a.url})")
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
        Path(cfg.db_path).parent.mkdir(parents=True, exist_ok=True)
        store = CrateStore(cfg.db_path)
        nav = SubsonicClient(cfg.subsonic_url, cfg.username, cfg.password)
        r = fetch(a.wanted, store=store, slskd=SlskdClient(a.slskd, a.api_key), navidrome=nav,
                  reconciler=Reconciler(nav, store), music_root=Path(os.environ.get("MUSIC_ROOT", "/srv/music")),
                  downloads_root=Path(os.environ.get("DOWNLOADS_ROOT", "/srv/incoming")), approve=a.approve)
        print(r.explain)
        if r.pick:
            print(f"pick: {r.pick.username}: {r.pick.basename}  (score {r.pick.score:.2f})")
        print(f"{r.status}: {r.reason}" + (f"  → {r.filed}" if r.filed else ""))
        return 0 if r.status in ("ok", "needs_source", "sourcing") else 2

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
