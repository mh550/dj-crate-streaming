# Next session: phone client, library reorganisation, sharing etiquette, network posture

**Status:** draft for Michael's review (written 2026-10-13 from his questions after the
overnight run). Not approved. Nothing here is implemented. A future `/loop` session
turns the approved parts into `docs/plans/` plans (writing-plans → executing-plans).

**Where things stand (facts the spec builds on):**

- Navidrome 0.64 + crate service + web client are up, loopback-only, fronted by
  `tailscale serve` at `https://pop-os.taildf8564.ts.net` (Navidrome) and `:4580`
  (crate UI). Admin user `michael`; password only in `/srv/docker/.env` (`ND_PASS`).
- `/srv/music` = 859 files, `Artist/Album (Year)/NN - Title.ext`, built by beets in
  copy mode. The original tree is untouched in `/srv/incoming/library-import/` and on
  the laptop. 28 of the 859 are redundant copies of the same audio (listed in
  `docs/library-map.csv` `other_copies`).
- Michael's 35 genre/playlist folders already exist as Navidrome playlists (908
  entries), created by `scripts/folders_to_playlists.py` from `library-map.csv`.
  They exist only inside Navidrome's database — no playlist files on disk yet.
- slskd 0.26.1 is logged in through gluetun/ProtonVPN (exit IP in Amsterdam, forwarded
  port negotiated automatically). It shares `/srv/music` read-only: 859 files / 670
  folders, scan complete. Upload settings are slskd defaults (10 slots, no speed cap,
  default leecher group). Zero downloads so far.
- The web client already has a per-stream quality selector (player default / opus 96 /
  opus 160 / mp3 320 / original) and a search box over the library.
- `ufw` is **active** on the host (verified via `systemctl is-active`); rules unread
  (needs sudo).

---

## 0. Decisions Michael owns (answer these first; everything below keys off them)

| # | Question | Default if no answer |
|---|---|---|
| D1 | **Phone client:** keep Amperfy (App Store, Subsonic) for daily listening and grow our web client for crate work? Or make our web client the only phone app? | Amperfy + web client (decision of 2026-09-18 stands) |
| D2 | **Original tree:** once playlists are exported as files and the redundant copies are resolved, may `/srv/incoming/library-import/` be moved to `/srv/_trash/<date>/`? (The laptop keeps its copy either way.) | Keep until Michael says otherwise |
| D3 | **The 28 redundant copies** (decisions.md Open question #6): delete the second copy (to `/srv/_trash/`) and point every playlist at the surviving one? | Move duplicates to `/srv/_trash/<date>/`, repoint playlists, rescan — reversible |
| D4 | **Genre categorisation:** write Michael's top-level folder name (Tea tent, Haus-Jungle-GhettoTech-Dance, Soul-Motown…) into each file's `GENRE` tag so Navidrome/Amperfy can browse by it? Tag writes modify the copies in `/srv/music` only. | Yes, top-level folder → `GENRE`, sub-folder kept only as playlist |
| D5 | **Fetch naming** (Open question #5): keep naming downloaded files from the crate's own tags, status `verify` when Navidrome can't match, no auto-retag? | Keep |
| D6 | **Soulseek upload cap:** limit upload speed so a busy share never starves the house connection? Suggested 2 MB/s (uplink unknown — Michael knows the plan). | 2 MB/s, 10 slots |
| D7 | **Automatic sourcing:** when `fetch --approve` has worked by hand a few times, may a background runner download from the wanted queue without a per-track approve? Scope: only tracks already in a toggled crate, FLAC-or-better policy, cap N per day. | Not until Michael has approved at least one manual download and said go |
| D8 | **Cross-platform search sources:** which catalogues should search cover beyond the library? Spotify (public, no account), SoundCloud (official API needs Artist Pro; scraping is against terms), Discogs/MusicBrainz (free, metadata only)? | Spotify public embed + MusicBrainz; SoundCloud deferred |

---

## 1. Phone client (answers Michael's question 2)

**Today:** the fastest intuitive search on the phone is any Subsonic app pointed at
`https://pop-os.taildf8564.ts.net` with user `michael` and the `ND_PASS` value.
Amperfy (iOS, free, open source) was chosen 2026-09-18; its search covers artist,
album, song and is offline-capable. Nothing to build for that.

**What our web client adds, in order:**

1. **Install-to-Home-Screen polish** (bounded): confirm the manifest works on iOS 26,
   keep the Subsonic session alive, and make search the first screen.
2. **Quality preference Low / Medium / High** (bounded): replace the five raw options
   with three named presets stored per device (`localStorage`) and mapped to Navidrome
   stream parameters: Low = opus 96k, Medium = opus 160k, High = original file. The
   crate service already proxies `/api/stream/<id>` with `format`/`maxBitRate`, so this
   is UI plus one mapping table. Also set the same preset as the Navidrome *Player*
   transcoding profile for the client name `dj-crates-web`, so the choice survives a
   browser cache clear. **Acceptance:** switching preset mid-playback changes the
   next stream's `Content-Type`/bitrate as reported by Navidrome; a test pins the
   mapping.
3. **Search across the library and outside it** (architectural, future scope 2.1.1):
   one search box, two result groups. "In your library" = Navidrome `search3`.
   "Not in your library" = external catalogues (D8). Pressing an external result
   calls the existing `add_external_wanted` and shows the row in the Wanted list;
   pressing again runs `fetch` for it (without `--approve` until D7). The user never
   sees a download start that they didn't press. **Acceptance:** a track absent from
   Navidrome appears from Spotify's public data, lands in `external_wanted`
   idempotently, and `fetch --wanted ext-N` reports a scored pick.
4. **Crate toggles and device targets in the app** (future scope 2.1.3): the toggle
   already exists in the web client (playlist → crate switch). The new part is a
   `crate_targets` table (crate × device/USB label) and a per-crate "send to" picker.
   Device sync itself is Phase 3; this session only records the intent. **Acceptance:**
   toggling a crate and picking "USB-A" survives a reload and shows in `crates.cli status`.

Order: 2 → 1 → 3 → 4. Item 3 is the only one that needs a spec section of its own
before planning (source abstraction, rate limits, caching).

## 2. Crates service: what `wanted` and `fetch` do (answers crates question 1)

- `crates.cli wanted` is a **report**, not a step. It lists every track that a toggled
  crate needs but the library can't satisfy under the crate policy (status
  `needs_source`), plus anything queued by `seed-spotify`. You ran it overnight only
  because the sourcing CLI takes a wanted id as its argument.
- `sourcing.cli fetch --wanted <id>` takes one wanted track: slskd search → score
  candidates → print the pick. With `--approve` it also downloads, verifies the file
  (FLAC header, duration), files it under `/srv/music`, rescans Navidrome, swaps the
  track into every crate playlist, and marks the row `ok` (or `failed`/`verify`).
- **Yes, the plan is automation** once the manual path is trusted. Prerequisites in
  order, already recorded in `README.md` "Not done yet": (a) a `sourcing_jobs` table so
  job state stops riding on `crate_tracks.status`, (b) a runner (systemd timer or a
  loop in the crates container) that picks `needs_source` rows and calls `fetch`,
  gated by D7, (c) the web client shows job progress from that table. The fetch
  path is unchanged; the runner is a loop around it.

## 3. Music library: decouple genre folders from the file layout (library question 1)

Most of this is already done by the overnight import; what remains is making it
durable and finishing the dedupe.

1. **Playlist files on disk** (bounded): export every Navidrome playlist as
   `/srv/music/_playlists/<name>.m3u8` with paths relative to `/srv/music`, via a new
   `scripts/export_playlists.py` (Subsonic `getPlaylist` → m3u8; stdlib). Navidrome
   can also *import* m3u files from the music folder, so the files are the portable
   source of truth and the DB is a cache. Run after any playlist change (same
   idempotent style as `folders_to_playlists.py`). **Acceptance:** 35 files, every
   entry resolves to an existing file, round-trip test against the fake server.
2. **Dedupe the 28 copies** (bounded, gated on D3): `scripts/dedupe_copies.py` reads
   `other_copies` from `library-map.csv`, moves the non-preferred copy to
   `/srv/_trash/<date>/<same relative path>`, repoints playlists via the API (remove by
   index, add by id — `update_playlist` already does this), rescans, verifies song
   count = 831. Never touches `/srv/incoming/library-import`.
3. **Genre from folder** (bounded, gated on D4): `scripts/genre_from_folder.py` maps
   `library-map.csv` `folder` top level → `GENRE` tag on the copy in `/srv/music`
   using the beets library already in `/srv/docker/beets` (`beet modify -y
   path:<file> genre=<folder>`; beets rewrites the tag in place). Playlist-named folders
   (`playlists/*`, `sockseek/*`) get no genre; they stay playlists. Rescan afterwards.
4. **Laptop tree can be retired** (D2): nothing to build; a line in the runbook.

## 4. Soulseek sharing etiquette (library question 2)

Already true: the whole library is shared read-only (859 files), scan complete, the
account is logged in, and the port is reachable through the VPN so other users can
actually download. Etiquette items to set, all in `slskd.yml` or the compose
environment (bounded, one task):

- Upload speed cap per D6; keep 10 slots; leave the default `leechers` group (users
  sharing nothing get one slow slot rather than being blocked).
- Set `soulseek.description` to something human ("DJ library, FLAC where I have it,
  ask for anything") instead of the stock slskd string.
- Keep the share name `shared`; exclude `/srv/music/_playlists` and `.incomplete`
  from the share with `shares.filters`.
- Never share `/srv/incoming` (unverified downloads).
- Verify from a second Soulseek account or by asking in a room that browsing the share
  works. **Acceptance:** `GET /api/v0/shares` shows 859 files and the options show the
  cap; `docs/soulseek-etiquette.md` records the settings and why.

## 5. Router and network posture (network questions 1–2)

**UPnP** lets any device on the LAN ask the router to open an inbound port to it,
with no password. Disabling it means nothing on the home network, including a
compromised device, can expose itself to the internet without Michael logging in to the
router. Nothing we run needs it: Tailscale hole-punches outbound; slskd's inbound port
is on Proton's server, not the router.

**What is already secured and how:**

| Service | Exposure | Mechanism |
|---|---|---|
| Soulseek (slskd) | Internet, through VPN only | gluetun container owns the network; kill switch; ProtonVPN port forwarding gives peers a port on Proton's IP; home IP never seen by peers. UI on 127.0.0.1:5030 only. |
| Navidrome | Tailnet only | Port bound to 127.0.0.1; `tailscale serve` terminates HTTPS with a Let's Encrypt cert; only devices logged in to the tailnet can reach it. |
| Crate service | Tailnet only | Same; port 4580. It is the only process holding Navidrome credentials. |
| Host | LAN | ufw active (rules unread). No Docker port published on a LAN address. |

**Long term these stay in Docker on this box.** That is the right shape: the VPN is a
container property (slskd can't leak around it), Tailscale is a host property (the
phone reaches the box without the commercial VPN ever touching the host), and loopback
publishing plus `tailscale serve` means nothing changes if the LAN or router changes.
Moving services to a cloud host would break the "all media stays home" and "VPN only
for Soulseek" rules; not planned.

Remaining tasks (all need Michael, none need code):

1. Router: UPnP off; confirm no port forwards (also closes the §2.5 checklist).
2. `sudo ufw status verbose` once, paste into `docs/network-posture.md`; add
   `ufw allow in on tailscale0` only if something on the tailnet fails.
3. Optional: front slskd's UI with `tailscale serve --bg --https=5030 5030` so the
   phone can watch transfers. Low value until D7.
4. Optional hardening: `ND_ENABLESHARING=false` already; set Navidrome
   `ND_AUTHREQUESTLIMIT`/`ND_AUTHWINDOWLENGTH` to rate-limit logins; disable Navidrome
   "Last.fm/Spotify" integrations we don't use.

## Suggested session order

1. §0 answers from Michael (this message).
2. §3.1 playlist export, §3.2 dedupe, §4 etiquette, §1.2 quality presets — four
   bounded tasks, each its own plan, each a test-first commit on an `overnight/` branch.
3. §1.3 external search — spec section first, then plan.
4. §2 runner — only after D7.

## Not in scope here

Serato crate/history import (Phase 2), device sync (Phase 3), stems, SoundCloud API
(needs Artist Pro), native iOS app.
