"""CLI for the crate layer.

  python -m crates.cli status
  python -m crates.cli playlists                 # every Navidrome playlist, crate flag + provisioning summary
  python -m crates.cli toggle <playlist-id> on|off
  python -m crates.cli reconcile                 # sync crate state from Navidrome, re-judge every track
  python -m crates.cli wanted                    # the sourcing queue (feeds `sourcing.cli rank`)
  python -m crates.cli serve [--bind 127.0.0.1 --port 4580]
  python -m crates.cli demo                      # fake Navidrome + service on one port, for poking at the UI

Connection comes from env: SUBSONIC_URL, SUBSONIC_USER, SUBSONIC_PASS (+ optional SUBSONIC_PUBLIC_URL, CRATES_DB).
"""
from __future__ import annotations

import argparse
import json
import sys
import threading

from .service import Config, CrateApp, CrateServer


def fmt_dur(s: int | None) -> str:
    return f"{(s or 0) // 60}:{(s or 0) % 60:02d}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="crates")
    ap.add_argument("--url"); ap.add_argument("--user"); ap.add_argument("--password"); ap.add_argument("--db")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("playlists")
    t = sub.add_parser("toggle"); t.add_argument("playlist_id"); t.add_argument("state", choices=["on", "off"])
    sub.add_parser("reconcile")
    w = sub.add_parser("wanted"); w.add_argument("--json", action="store_true")
    s = sub.add_parser("serve"); s.add_argument("--bind"); s.add_argument("--port", type=int)
    d = sub.add_parser("demo"); d.add_argument("--port", type=int, default=4580)
    a = ap.parse_args(argv)

    if a.cmd == "demo":
        from subsonic.fake_server import FakeSubsonicServer
        fake = FakeSubsonicServer().__enter__()
        cfg = Config(subsonic_url=fake.url, username="demo", password="demo", db_path=":memory:", port=a.port)
        app = CrateApp(cfg)
        app.reconcile()
        srv = CrateServer(app)
        print(f"fake Navidrome: {fake.url}   crate UI: {srv.url}   (Ctrl-C to stop)")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0

    cfg = Config.from_env(subsonic_url=a.url, username=a.user, password=a.password, db_path=a.db)
    if not cfg.username:
        print("set SUBSONIC_USER / SUBSONIC_PASS (and SUBSONIC_URL)", file=sys.stderr)
        return 1
    app = CrateApp(cfg)

    if a.cmd == "status":
        print(json.dumps(app.status(), indent=2))
    elif a.cmd == "playlists":
        for p in app.playlists():
            flag = "▣ crate" if p["crate"] else "▢      "
            summ = p["summary"]
            extra = f"  ok {summ['ok']}/{summ['total']}  need {summ['needs_source']}" if summ else ""
            print(f"{flag}  {p['id']:<12} {p['name']:<32} {p['songCount']:>3} tracks {fmt_dur(p['duration']):>7}{extra}")
    elif a.cmd == "toggle":
        v = app.set_crate(a.playlist_id, a.state == "on")
        print(json.dumps(v, indent=2))
    elif a.cmd == "reconcile":
        print(json.dumps(app.reconcile(), indent=2))
    elif a.cmd == "wanted":
        items = app.store.wanted()
        if a.json:
            print(json.dumps(items, indent=2))
        else:
            for t in items:
                print(f"{t['artist']} — {t['title']}  [{t['album'] or '?'} {t['year'] or ''}]  {fmt_dur(t['duration'])}  ←{t['reason']}  in {', '.join(t['crates'])}")
            if not items:
                print("nothing to source")
    elif a.cmd == "serve":
        srv = CrateServer(app, a.bind, a.port)
        print(f"crate service on {srv.url} → Navidrome {cfg.subsonic_url} as {cfg.username}")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
