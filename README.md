# DJ crate streaming — the code

Spec and decisions live in `../ideas/dj-crate-streaming/`. This repo holds the parts we
have to write ourselves; everything else (Navidrome, slskd, Tailscale, gluetun) is
adopted. Python 3.10+, **stdlib only**, `pytest` for tests.

```
subsonic/   OpenSubsonic protocol layer
  client.py         the client we talk to Navidrome with (token auth, playlists, search, stream/download URLs)
  fake_server.py    an in-process fake Navidrome — enough protocol to develop and test offline
crates/     the orchestration layer: playlist → crate
  store.py          SQLite: which playlists are crates, per-track provisioning status, event log
  reconcile.py      sync crate state from Navidrome, judge each track against the crate policy
  service.py        HTTP API + serves web/ ; only this process holds Navidrome credentials
  cli.py            status | playlists | toggle | reconcile | wanted | serve | demo
web/        the client: stream + toggle crates from the same screen (vanilla JS, phone-first)
sourcing/   Phase 1: Soulseek sourcing — rank slskd results for a wanted track, verify downloads
  policy.py  scorer.py  verify.py  slskd_client.py  cli.py
fixtures/   slskd-shaped search responses covering the failure modes
tests/      35 tests, no network, ~10 s
```

## Try it now (no server needed)

```bash
cd ~/projects/dj-crate-streaming
python3 -m pytest -q
python3 -m crates.cli demo            # fake Navidrome + crate service → http://127.0.0.1:4580
```

Open the URL on this machine: pick a playlist, flip **crate**, watch each track get
judged (`ok` / `needs source`), check the **Wanted** tab (the sourcing queue), search,
hit **reconcile**. Audio in demo mode is fake bytes; the URLs are real.

Sourcing prototype, offline:

```bash
python3 -m sourcing.cli rank --fixture fixtures/search_responses.sample.json \
  --artist Chic --title "Good Times" --album "Risqué" --duration 501 --year 1979
```

## Against the real box (Phase 0 done)

```bash
export SUBSONIC_URL=http://127.0.0.1:4533 SUBSONIC_USER=you SUBSONIC_PASS=...
export SUBSONIC_PUBLIC_URL=https://<box>.<tailnet>.ts.net     # what the phone can reach; omit if same
python3 -m crates.cli status
python3 -m crates.cli playlists
python3 -m crates.cli toggle <playlist-id> on
python3 -m crates.cli wanted                     # → feed each line to sourcing.cli rank --slskd ...
python3 -m crates.cli serve                      # 127.0.0.1:4580 → front with `tailscale serve`
```

## How the pieces fit

```
phone browser ──/api/*──▶ crates.service ──Subsonic──▶ Navidrome (playlists, library facts)
      │                        │  SQLite: crate flags, track status, wanted queue
      └──302 signed URL────────┘──────────────────────▶ Navidrome /rest/stream (audio, transcoded per Player)
                               └──wanted──▶ sourcing.scorer ──▶ slskd (search, download) ──▶ sourcing.verify
```

- **A crate is a playlist plus a promise.** The toggle lives in our SQLite store; we
  also mirror it as `#crate` in the Navidrome playlist comment so every Subsonic
  client shows it. From any other client you can toggle a crate by renaming the
  playlist with a marker (`Disco Edits [crate]` or `🎛 Disco Edits`), or by editing
  the comment where the client allows it.
- **Judging** uses only what Subsonic reports (suffix, bitRate, samplingRate,
  bitDepth) against `sourcing/policy.py`. Deep checks (fake FLAC, duration) run in
  `sourcing/verify.py` once we hold the bytes.
- **Streaming never touches our process.** `/api/stream/<id>` answers 302 to a
  per-request signed Navidrome URL under its own client name (`dj-crates-web`), so
  Navidrome gives it its own Player and you set its transcoding profile in
  Navidrome → Settings → Players like any other device.

## On the phone

The web client is installable: open it over Tailscale in Safari → Share → **Add to
Home Screen**. It runs full-screen as its own app. Use it for crate work and casual
playback; for daily listening on iOS use Amperfy or play:Sub against the same
Navidrome — see `../ideas/dj-crate-streaming/phase0-options.md` §1.4 for why.

Container build for the Compose stack: `docker build -t crates .` (see the
`crates` service in the Phase 0 compose skeleton).

## Not done yet

- Sourcing jobs driven automatically from the wanted queue (today: CLI hand-off),
  status transitions `sourcing → verify → ok`, tag + move into `/srv/music`, rescan.
- Expected-duration lookup (MusicBrainz / SpotiFLAC) instead of trusting the library's.
- AcoustID fingerprint verification (`fpcalc`).
- Analysis (BPM/key → Serato GEOB), stems, device sync — Phases 2–4.
- SoundCloud in the client: stream-only via the official API (needs Artist Pro); not a crate source.
- A native phone client if the web client's background audio proves unreliable on iOS.
