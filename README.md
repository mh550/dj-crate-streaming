# DJ crate streaming — the code

Spec and decisions live in `../ideas/dj-crate-streaming/`. This repo holds the parts we
have to write ourselves; everything else (Navidrome, slskd, Tailscale, gluetun) is
adopted. Python 3.10+, **stdlib only**, `pytest` for tests.

```
subsonic/   OpenSubsonic protocol layer
  client.py         the client we talk to Navidrome with (token auth, playlists, search, stream/download URLs)
  fake_server.py    an in-process fake Navidrome — enough protocol to develop and test offline
crates/     the orchestration layer: playlist → crate
  store.py          SQLite: cache of crate/tier flags, per-track status, approvals, replacements, proposals, event log
  attrs.py          retired design (D21): `#crate` / `#tier:<t>` in a playlist comment; only used with CRATES_OWNER=comment
  reconcile.py      judge each crate track against the DJ-quality rule; the crate flag lives in crates.db (CRATES_OWNER=app)
  migrate_attrs.py  M8: one-time move of crates.db's flags and import tiers into comments (dry run by default)
  playlist_edit.py  M8: the only code that edits a playlist by index (cross-checks navidrome.db, refuses on doubt)
  trash.py          M8: move a library file to the trash (MOVES.txt first, never overwrites), restore it, size report
  proposals.py      M8: questions about one playlist slot (new version, unproven copy); Swap edits that slot only
  service.py        HTTP API + serves web/ ; only this process holds Navidrome credentials
  cli.py            status | playlists | toggle | tier | attrs migrate | reconcile | wanted | proposals | serve | demo
web/        the client: stream + toggle crates from the same screen (vanilla JS, phone-first)
sourcing/   Phase 1: Soulseek sourcing — one wanted track from search to a file Navidrome serves
  scorer.py  verify.py  slskd_client.py   rank + check
  identity.py       M7: what counts as the same song, version and copy (title labels, same-version test) — docs/identity.md
  policy.py         tiers + version preferences, read from deploy/policy.toml
  fetch.py          the slice: search → score → (approved) download → verify → file → rescan → ok; copy upgrades and play-now
  replace.py        M8: copy replacement: repoint every playlist → old copy to the trash → scan → done (resumable)
  filer.py          beet import of each verified download (the only beets writer)
  worker.py         the worker (D18): claims approvals, fetches, re-checks `verify` rows — see docs/worker.md
  acoustid.py       AcoustID lookup (only with ACOUSTID_KEY): is this file the recording Navidrome knows?
  musicbrainz.py    recording length from MusicBrainz: confirms a beets match before `beet write` (D22); also the rate-limited client the identity backfill uses
  fake_slskd.py     in-process slskd for tests/demos
  spotify_csv.py    public Spotify playlist → rows, no API credentials (embed page)
  cli.py            rank | verify | worker [--once] | fetch --wanted <id> [--approve [--wait]] | seed-spotify <url> | import-playlist <src>... [--name N]
scripts/    one-off library tooling: library_map.py (folder + audio-hash map), folders_to_playlists.py,
            identity_backfill.py (M7: propose / apply / revert MusicBrainz ids, reviewed — docs/worker.md)
deploy/     compose.yml (+ .env.example), beets.yaml, policy.toml (tiers + version preferences) — /srv/docker/compose.yml symlinks here
fixtures/   slskd-shaped search responses covering the failure modes
tests/      1,750 tests, no network, about 11 minutes
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
walks the row `needs_source → sourcing → verify → ok | failed | review`. A better copy of a song the library
already has replaces the old one only with proof (`docs/worker.md` "Copy replacement and the trash"); a file
Navidrome can't match stays `verify` with the filed path in the reason. `MUSIC_ROOT` (default `/srv/music`) and `DOWNLOADS_ROOT` (default
`/srv/incoming/soulseek`, where the slskd container writes) are overridable; the worker refuses an approved
fetch before any transfer when neither they nor their parent folders exist.

**Quality** (2026-10-17, D24): one rule, lossless (flac preferred) or lossy at 256 kbps or more; the four tier names below
are identical in `deploy/policy.toml` and `--tier` no longer changes what is accepted. The older description follows.

**Quality tiers** (spec §1, retired as a choice): `low | medium | high | crate`. `rank`, `fetch`, `seed-spotify` and
`import-playlist` take `--tier`; wanted rows remember theirs (new rows from `import-playlist` and `seed-spotify` default to
`medium`; crate tracks are always `crate`), and `fetch` scores with the row's tier. Listening tiers trade quality for estimated arrival,
assuming our own download speed is 1 MB/s (`deploy/policy.toml`). `rank --slskd … --save r.json` keeps
the raw responses so `rank --fixture r.json --tier <other>` compares tiers on one search.

## M7: identity (songs, versions, copies)

M7 puts one definition of "the same" in `sourcing/identity.py`: **song** (artist + title without version words),
**version** (a recording: radio edit, 12", dub, live...) and **copy** (a file). Read `docs/identity.md` for the rules
with real titles from the library. What it changed:

- **One normaliser.** The five that disagreed (scorer, import, store, dedupe, tag rules) now call `identity`.
  Accents are ignored and `&` means "and" everywhere.
- **The import matcher** asks: same recording (ISRC)? same version? an *accepted* other version? A stand-in (for
  example a 12" for a radio-edit row) is logged, never silent, and needs every one of its version words accepted.
- **The scorer** has a version preference term, and a crate upgrade refuses another version.
- **verify** knows a copy upgrade from a new version. A copy upgrade reports `replaceable` (full-length fingerprint
  against the old file, bit-error rate 0.20 or less, durations agree, verdict `ok`). M8 trashes the old copy only
  when it is true.
- **Where to start:** `docs/decisions.md` (current decisions), `docs/specs/2026-10-17-amperfy-pivot.md` (the pivot), `docs/next-todos.md` (what to build
  next), `docs/hard-won-facts.md`, `docs/how-ids-work.md`, `docs/architecture.md`.
- **`deploy/policy.toml`** holds the one download-quality rule (lossless, or lossy at 256 kbps or more; D24) in four
  identical tier entries, and no version preferences (D26: the exact track is sourced), editable without code: `docs/worker.md` "Editing the policy".
- **The id backfill** (`scripts/identity_backfill.py`) proposes MusicBrainz recording, work and AcoustID ids for the
  files that lack them. It does not use beets (measured: beets matched a 412 s 12" to a 403 s 90's mix). Michael reviews
  the report, then `apply` writes only those id fields where the file's own field is empty, and `revert` can undo it.
  It runs in the worker:

```bash
cd /srv/docker
docker compose exec -T worker python -m scripts.identity_backfill propose [--limit N]    # read-only; ~1 h for the library
docker compose exec -T worker python -m scripts.identity_backfill apply /data/identity/identity-proposal.json --dry-run
docker compose exec -T worker python -m scripts.identity_backfill apply /data/identity/identity-proposal.json --yes [--classes a,b] [--limit N] [--only GLOB]
docker compose exec -T worker python -m scripts.identity_backfill revert /data/identity/apply-<time>.jsonl
```

The proposal and report land in `/srv/docker/crates/identity/`. Nothing is written to the library until `apply --yes`.

## M8: lifecycle (ownership, replacement, play-now)

M8 follows `docs/specs/2026-10-16-ownership-and-identity.md`. What it changed, in plain words:

- **(Retired 2026-10-17) The comment owns crate and tier.** The crates app owns the crate flag now
  (`docs/specs/2026-10-17-amperfy-pivot.md`); `attrs migrate` is refused. `reconcile` still runs in the worker every
  `WORKER_RECONCILE_S` (600 s), so a change of the crate switch or of the library takes effect without opening the web client.
- **Listening tiers upgrade only below their floor.** A low, medium or high playlist queues a track only when its
  format is not allowed or a lossy file is under the tier's bit rate floor. "Lossless preferred" is a crate wish.
- **Copy replacement.** A better copy of the same recording, proven by fingerprint, takes the old copy's place in
  every playlist, and the old file goes to `/srv/docker/_trash` (never deleted, never overwritten, undo lines in
  `MOVES.txt`). No proof: both copies stay and you are asked.
- **Questions, not swaps.** A new version (a 12" for a radio edit) never replaces anything by itself. The Wanted tab
  shows a question per playlist slot with Swap and Keep (`crates.cli proposals` does the same).
- **Play-now.** The play button on a track you do not have is your approval for one fast `low` copy. It plays when
  it lands and the proper-tier upgrade waits in Wanted for your approval.
- **Safer API.** Preview picks carry an opaque `token`; no wanted, approval or preview response shows a Soulseek peer
  name or an absolute path.

`docs/worker.md` has the details and the commands.

## Against the real box (Phase 0 done)

```bash
export SUBSONIC_URL=http://127.0.0.1:4533 SUBSONIC_USER=you SUBSONIC_PASS=...
export SUBSONIC_PUBLIC_URL=https://<box>.<tailnet>.ts.net     # what the phone can reach; omit if same
python3 -m crates.cli status
python3 -m crates.cli playlists
python3 -m crates.cli toggle <playlist-id> on           # keep this playlist synced as a crate (crates.db only)
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

- **A crate is a playlist plus a promise.** Since 2026-10-17 (D27) the crates app owns it: you switch a playlist on in the
  crates web client (or `crates.cli toggle`), `crates.db` holds the answer, and nothing is written to the playlist's
  name or comment (D33: "made by import-playlist" is a crates.db row too). Every track of a crate must have a
  DJ-quality file: lossless, or lossy at 256 kbps or more. The earlier comment-owned design (`#crate`, `#tier:`; set
  `CRATES_OWNER=comment`) is retired but still in the code.
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
  five options: `server` (default: no format sent, so Navidrome's player profile decides), `low`, `medium`, `high`
  (opus 64k / 96k / 160k) and `crate` (original), saved server-side
  (`GET/POST /api/stream-tier`) and sent as `/api/stream/<id>?tier=…`.

## On the phone

The web client is installable: open it over Tailscale in Safari → Share → **Add to
Home Screen**. It runs full-screen as its own app. Use it for crate work and casual
playback; for daily listening on iOS use Amperfy or play:Sub against the same
Navidrome — see `../ideas/dj-crate-streaming/phase0-options.md` §1.4 for why.

Container build for the Compose stack: `docker build -t crates .` (see the
`crates` service in the Phase 0 compose skeleton). The same image runs the `worker` service (`docs/worker.md`).

## Not done yet

- **A filed external track is not placed in its playlist.** A downloaded row (and a play-now track) is in the
  library but not in the playlist that wanted it; re-running `import-playlist` appends it at the end. M9 would
  insert it at its Spotify position (`docs/specs/2026-10-17-m9-remaining-ownership.md`).
- **`repoint: auto`.** A new version is always a question. A per-tier policy that answers for you is not built.
- **The ".1" names.** A same-format upgrade is filed by beets as `… .1.flac` and keeps that name after the old copy
  goes to the trash. Renaming it would change the Navidrome id unless the file has a recording id.
- **The 102 existing copy groups.** M7 found 102 groups of copies of one version (217 files) already in the library.
  Replacement is for new downloads only; a reviewed clean-up of the old ones is M9.
- The version *field* (`VERSION`/`TIT3`) is read but never written: labels live in titles, and writing the field is
  a later, separately reviewed proposal. The backfill's `apply` on the real library waits for Michael's review of
  the report.
- The worker (`docs/worker.md`) runs approved downloads automatically; automatic approval (`policy:` / `agent:`
  approvers) and a `sourcing_jobs` table (status, filed path, slskd transfer per wanted id, instead of riding on
  `crate_tracks.status` and the free-text reason) are not built. Also: check Navidrome for a good copy *before* searching.
- Expected-duration lookup (MusicBrainz / SpotiFLAC) instead of trusting the library's.
- Analysis (BPM/key → Serato GEOB), stems, device sync — Phases 2–4.
- SoundCloud in the client: stream-only via the official API (needs Artist Pro); not a crate source.
- A native phone client if the web client's background audio proves unreliable on iOS.
