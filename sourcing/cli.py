r"""CLI: rank candidates for a wanted track, from a fixture file or a live slskd.

  python -m sourcing.cli rank --fixture fixtures/search_responses.sample.json --artist Chic --title "Good Times" --duration 501 [--tier low]
  python -m sourcing.cli rank --slskd http://server:5030 --api-key $SLSKD_KEY --artist Chic --title "Good Times" [--download]
  python -m sourcing.cli verify /srv/incoming/03\ -\ Good\ Times.flac --duration 501 [--tier crate] [--reference old.flac] [--json]
  python -m sourcing.cli fetch --wanted s4 [--approve] [--tier T]   # one wanted track, end to end (see fetch.py); tier: the row's
  python -m sourcing.cli seed-spotify https://open.spotify.com/playlist/...   # queue tracks not in Navidrome
  python -m sourcing.cli import-playlist <spotify-url|report.txt|exportify.csv>... [--name N] [--dry-run]   # D11: Spotify playlists → public Navidrome playlist + wanted rows
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .scorer import Wanted, rank, explain
from .policy import DEFAULT_TIER, TIERS
from .spotify_csv import fetch_entity
from .verify import full_band, verify


def describe_measurements(m: dict) -> list[str]:
    """The decoded measurements as short lines (header facts are printed separately)."""
    out = []
    if m.get("cutoff_khz") is not None:
        cut = m["cutoff_khz"]
        out.append(f"cutoff {'≥' if full_band(m) else '≈'}{cut} kHz" if cut else "cutoff below 11 kHz")
        out.append("band dB vs full: " + "  ".join(f">{e}k {v}" for e, v in m["bands_db"].items()))
    if m.get("decoded_s") is not None:
        out.append(f"decoded {m['decoded_s']} s · bits used {m.get('bits_used')} · peak {m['peak_db']:.2f} dBFS · "
                   f"flat factor {m['flat_factor']:.1f}")
    if "fingerprint_ber" in m:
        out.append(f"fingerprint bit-error rate vs reference {m['fingerprint_ber']} (same recording < 0.20)")
    return out


def add_slskd_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--slskd", default=os.environ.get("SLSKD_URL"), help="slskd base URL (or $SLSKD_URL), e.g. http://127.0.0.1:5030")
    p.add_argument("--api-key", default=os.environ.get("SLSKD_API_KEY"))


def add_tier_arg(p: argparse.ArgumentParser, default: str | None, what: str) -> None:
    p.add_argument("--tier", choices=list(TIERS), default=default, help=f"quality tier (spec §1): {what}")


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
    add_slskd_args(r)
    r.add_argument("--download", action="store_true", help="enqueue the top candidate (live mode only)")
    r.add_argument("--save", help="live mode: write the raw search responses here (rank them again with --fixture)")
    r.add_argument("--json", action="store_true")
    r.add_argument("--limit", type=int, default=10)
    add_tier_arg(r, DEFAULT_TIER, "what to score for (default crate)")

    v = sub.add_parser("verify", help="check a downloaded file")
    v.add_argument("path")
    v.add_argument("--duration", type=float)
    v.add_argument("--tier", choices=list(TIERS), help="also decode and judge at this tier (spec §3a); without it, header checks only")
    v.add_argument("--reference", help="a copy of the same recording (e.g. the library file being upgraded) to fingerprint against")
    v.add_argument("--json", action="store_true")

    f = sub.add_parser("fetch", help="take one wanted track through search → score → (approve) download → verify → file → ok")
    f.add_argument("--wanted", required=True, help="song id from `crates.cli wanted` (or ext-N from seed-spotify)")
    f.add_argument("--approve", action="store_true", help="actually download; without it, stop after scoring")
    add_slskd_args(f)
    add_tier_arg(f, None, "change the wanted row's tier, then fetch (external rows only; crate rows are crate)")

    s = sub.add_parser("seed-spotify", help="add every track of a public Spotify playlist/album to the wanted queue")
    s.add_argument("url")
    add_tier_arg(s, None, "tier for the queued rows (default crate; re-seeding with a tier changes it)")

    ip = sub.add_parser("import-playlist", help="Spotify URL / Exportify CSV / SpotiFLAC report → public Navidrome playlist; the rest become wanted rows")
    ip.add_argument("sources", nargs="+", help="several sources concatenate in order into one playlist (needs --name)")
    ip.add_argument("--name", help="playlist name (default: the source's own name; required with several sources)")
    ip.add_argument("--dry-run", action="store_true", help="match and report, write nothing")
    ip.add_argument("--merge", action="store_true", help="add to a same-named playlist this tool did not create (adopts it)")
    add_tier_arg(ip, None, "tier for the wanted rows it creates (default crate)")

    a = ap.parse_args(argv)

    if a.cmd == "import-playlist":
        from crates.service import Config
        from crates.store import CrateStore
        from subsonic.client import SubsonicClient
        from .import_playlist import NameCollision, import_playlist
        from .playlist_sources import concat, load
        if len(a.sources) > 1 and not a.name:
            print("several sources make one playlist: say which with --name", file=sys.stderr); return 1
        cfg = Config.from_env()
        if not (cfg.username and cfg.password):
            print("set SUBSONIC_USER / SUBSONIC_PASS (and SUBSONIC_URL)", file=sys.stderr); return 2
        groups, name = [], a.name
        for src in a.sources:
            try:
                src_name, rows = load(src, fetch=fetch_entity)
            except (SystemExit, OSError, KeyError, ValueError) as e:   # private playlist, no network, missing file, odd CSV: nothing written
                print(f"{src}: {e}", file=sys.stderr); return 1
            groups.append(rows); name = name or src_name
        rows = concat(groups)
        Path(cfg.db_path).parent.mkdir(parents=True, exist_ok=True)
        store = CrateStore(cfg.db_path)                 # opened only after every source loaded
        try:
            rep = import_playlist(name, rows, SubsonicClient(cfg.subsonic_url, cfg.username, cfg.password), store,
                                  source=" ".join(a.sources), dry_run=a.dry_run, merge=a.merge, tier=a.tier)
        except NameCollision as e:
            print(f"{e}; re-run with --merge to add to it, or pick another --name", file=sys.stderr); return 1
        print(rep.table())
        if a.dry_run:
            print("(dry run: nothing written)")
        return 0

    if a.cmd == "seed-spotify":
        from crates.service import Config
        from crates.store import CrateStore
        from .spotify_csv import rows
        db = Config.from_env().db_path
        Path(db).parent.mkdir(parents=True, exist_ok=True)
        store = CrateStore(db)
        before, total = store.external_count(), 0
        for r in rows(fetch_entity(a.url)):          # dicts: {"Artist", "Title", "Length"} (seconds)
            store.add_external_wanted(r["Artist"], r["Title"], duration_s=r["Length"], source=a.url, tier=a.tier)   # idempotent
            total += 1
        store.commit()
        added = store.external_count() - before
        print(f"{added} added, {total - added} already queued ({a.url})")
        return 0

    if a.cmd == "fetch":
        if not (a.slskd and a.api_key):
            print("need --slskd/$SLSKD_URL and --api-key/$SLSKD_API_KEY", file=sys.stderr); return 1
        from crates.service import Config, CrateApp
        from .fetch import fetch
        from .slskd_client import SlskdClient
        cfg = Config.from_env()
        if not cfg.username:
            print("set SUBSONIC_USER / SUBSONIC_PASS (and SUBSONIC_URL)", file=sys.stderr); return 1
        app = CrateApp(cfg)                          # same store/client/reconciler wiring as the crate service
        r = fetch(a.wanted, store=app.store, slskd=SlskdClient(a.slskd, a.api_key), navidrome=app.api,
                  reconciler=app.reconciler, tier=a.tier, music_root=Path(os.environ.get("MUSIC_ROOT", "/srv/music")),
                  downloads_root=Path(os.environ.get("DOWNLOADS_ROOT", "/srv/incoming")), approve=a.approve)
        print(r.explain)
        if r.pick:
            print(f"pick: {r.pick.username}: {r.pick.basename}  (score {r.pick.score:.2f})")
        print(f"{r.status}: {r.reason}" + (f"  → {r.filed}" if r.filed else ""))
        return 0 if r.status in ("ok", "needs_source", "sourcing") else 2

    if a.cmd == "verify":
        if a.reference and not a.tier:
            v.error("verify --reference needs --tier (the recording check runs with the decoded checks)")
        vd = verify(Path(a.path), a.duration, tier=a.tier, reference=a.reference)
        if a.json:
            print(json.dumps(vd.as_dict(a.tier), ensure_ascii=False))
        else:
            print(("OK  " if vd.ok else "BAD ") + a.path + (f"  (tier {a.tier})" if a.tier else ""))
            if vd.info:
                print(f"     {vd.info.codec} {vd.info.sample_rate} Hz / {vd.info.bit_depth} bit / {vd.info.channels} ch / {vd.info.duration_s and round(vd.info.duration_s, 1)} s  [{vd.info.source}]")
            for line in describe_measurements(vd.measurements):
                print("     ·", line)
            for p in vd.problems:
                print("     ✗", p)
            for w in vd.warnings:
                print("     !", w)
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
        if a.save:
            Path(a.save).write_text(json.dumps(responses))
    else:
        print("need --fixture or --slskd", file=sys.stderr); return 1

    cands = rank(responses, wanted, TIERS[a.tier])
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
