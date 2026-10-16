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
sourcing/   Phase 1: Soulseek sourcing — one wanted track from search to a file Navidrome serves
  policy.py  scorer.py  verify.py  slskd_client.py   rank + check (unchanged)
  fetch.py          the slice: search → score → (approved) download → verify → file → rescan → crate ok
  filer.py          beet import of each verified download (the only beets writer)
  worker.py         the worker (D18): claims approvals, fetches, re-checks `verify` rows — see docs/worker.md
  acoustid.py       AcoustID lookup (only with ACOUSTID_KEY): is this file the recording Navidrome knows?
  musicbrainz.py    recording length from MusicBrainz: confirms a beets match before `beet write` (D22)
  fake_slskd.py     in-process slskd for tests/demos
  spotify_csv.py    public Spotify playlist → rows, no API credentials (embed page)
  cli.py            rank | verify | worker [--once] | fetch --wanted <id> [--approve [--wait]] | seed-spotify <url> | import-playlist <src>... [--name N]
scripts/    one-off library tooling: library_map.py (folder + audio-hash map), folders_to_playlists.py
deploy/     compose.yml (+ .env.example), beets.yaml — /srv/docker/compose.yml symlinks here
fixtures/   slskd-shaped search responses covering the failure modes
tests/      75 tests, no network, ~25 s
```

## Try it now (no server needed)

```bash
cd ~/projects/dj-crate-streaming
pytest -q                             # pytest comes from pipx on the box (~/.local/bin)
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

Against a live slskd (M4) with `SLSKD_URL`/`SLSKD_API_KEY` set, plus the `SUBSONIC_*` vars below:

```bash
python3 -m sourcing.cli seed-spotify https://open.spotify.com/playlist/...   # → ext-N wanted rows
python3 -m sourcing.cli import-playlist <spotify-url|report.txt|exportify.csv>... [--name N] [--dry-run]
    # D11: Spotify playlist → public Navidrome playlist (library matches, in order) + wanted rows with playlist/position
python3 -m sourcing.cli fetch --wanted s4             # search + score, prints the pick, no download
cd /srv/docker && docker compose exec -T worker python -m sourcing.cli fetch --wanted s4 --approve [--wait]
    # (container form only: needs the worker's CRATES_DB) records Michael's approval; the worker daemon (the one beets writer) then downloads → verifies → files with
    # beets → rescans → crate ok on its next tick; --wait prints its outcome (docs/worker.md)
# normally: Preview + Approve in the web client, and the worker container downloads (docs/worker.md)
```

Without `--approve` nothing is transferred (rule: Soulseek downloads are Michael's call). `fetch`
walks the crate row `needs_source → sourcing → verify → ok | failed`, swaps the new song into every
crate that held the old one, and reconciles; a file Navidrome can't match stays `verify` with the
filed path in the reason. `MUSIC_ROOT` (default `/srv/music`) and `DOWNLOADS_ROOT` (default
`/srv/incoming/soulseek`, where the slskd container writes) are overridable; the worker refuses an approved
fetch before any transfer when neither they nor their parent folders exist.

**Quality tiers** (spec §1): `low | medium | high | crate`. `rank`, `fetch`, `seed-spotify` and
`import-playlist` take `--tier`; wanted rows remember theirs (default `crate`; crate tracks are always
`crate`), and `fetch` scores with the row's tier. Listening tiers trade quality for estimated arrival,
assuming our own download speed is 1 MB/s (`sourcing/policy.py`). `rank --slskd … --save r.json` keeps
the raw responses so `rank --fixture r.json --tier <other>` compares tiers on one search.

## Against the real box (Phase 0 done)

```bash
export SUBSONIC_URL=http://127.0.0.1:4533 SUBSONIC_USER=you SUBSONIC_PASS=...
export SUBSONIC_PUBLIC_URL=https://<box>.<tailnet>.ts.net     # what the phone can reach; omit if same
python3 -m crates.cli status
python3 -m crates.cli playlists
python3 -m crates.cli toggle <playlist-id> on
python3 -m crates.cli wanted                     # → feed each line to sourcing.cli rank --slskd ...
python3 -m crates.cli publish [NAME ...]         # make playlists visible to every Navidrome user
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
  bitDepth) against `sourcing/policy.py`. Deep checks run in `sourcing/verify.py` once we
  hold the bytes (spec §3a, `docs/download-validation.md`): one ffmpeg decode measures the
  spectral cutoff, bits used, truncation, silence and clipping, `flac -t` checks the MD5, and
  `fpcalc` compares against a reference copy (CLI `--reference`; `fetch` passes the library copy of a crate upgrade). The tier decides what is a hard failure.
  `python3 -m sourcing.cli verify <file> --tier crate [--reference old.flac]` on the host
  (the worker image has ffmpeg, flac and fpcalc; the crates service only serves); `fetch` keeps the last result per wanted row (`verify`
  in `/api/wanted`, shown in the web client).
- **Streaming never touches our process.** `/api/stream/<id>` answers 302 to a
  per-request signed Navidrome URL under its own client name (`dj-crates-web`), so
  Navidrome gives it its own Player and you set its transcoding profile in
  Navidrome → Settings → Players like any other device. The web client's quality menu is
  the same four tiers (opus 64k / 96k / 160k / original), saved server-side
  (`GET/POST /api/stream-tier`) and sent as `/api/stream/<id>?tier=…`.

## On the phone

The web client is installable: open it over Tailscale in Safari → Share → **Add to
Home Screen**. It runs full-screen as its own app. Use it for crate work and casual
playback; for daily listening on iOS use Amperfy or play:Sub against the same
Navidrome — see `../ideas/dj-crate-streaming/phase0-options.md` §1.4 for why.

Container build for the Compose stack: `docker build -t crates .` (see the
`crates` service in the Phase 0 compose skeleton). The same image runs the `worker` service (`docs/worker.md`).

## Not done yet

- The worker (`docs/worker.md`) runs approved downloads automatically; automatic approval (`policy:` / `agent:`
  approvers) and a `sourcing_jobs` table (status, filed path, slskd transfer per wanted id, instead of riding on
  `crate_tracks.status` and the free-text reason) are not built. Also: check Navidrome for a good copy *before* searching.
- Expected-duration lookup (MusicBrainz / SpotiFLAC) instead of trusting the library's.
- Analysis (BPM/key → Serato GEOB), stems, device sync — Phases 2–4.
- SoundCloud in the client: stream-only via the official API (needs Artist Pro); not a crate source.
- A native phone client if the web client's background audio proves unreliable on iOS.
