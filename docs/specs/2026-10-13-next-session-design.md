# Next session: quality tiers, naming convention, library hygiene, sharing, network posture

**Status:** revision 4, 2026-10-13 evening: D10 recommendation, download validation (§3a), Spotify URLs, branch policy. Implemented by `~/projects/OVERNIGHT-2.md`. Decisions in §0
are his unless marked *default*. Nothing here is implemented. A future `/loop` session
turns §7 into `docs/plans/` plans (writing-plans → executing-plans), bounded tasks first.

**Where things stand (facts the spec builds on):**

- Navidrome 0.64 + crate service + web client are up, loopback-only, fronted by
  `tailscale serve` at `https://pop-os.taildf8564.ts.net` (Navidrome) and `:4580`
  (crate UI). Admin user `michael`; password only in `/srv/docker/.env` (`ND_PASS`).
  The crates container reads the same `ND_USER`/`ND_PASS`, so a password change means
  editing `.env` and `docker compose up -d crates`.
- `/srv/music` = 859 files laid out by beets (`deploy/beets.yaml`) in copy mode as
  `$albumartist/$album ($year)/$track - $title`, or `$artist/Singles/$title` for
  singletons. Originals untouched in `/srv/incoming/library-import/` and on the laptop.
  28 of the 859 are redundant copies of the same audio (`docs/library-map.csv`
  `other_copies`).
- Michael's 35 genre/playlist folders exist as Navidrome playlists (908 entries), DB
  only — no playlist files on disk.
- slskd 0.26.1 logged in through gluetun/ProtonVPN; shares `/srv/music` read-only
  (859 files / 670 folders, scan complete). **Upload cap applied 2026-10-13:** 5 slots,
  586 KiB/s (0.6 MB/s) in `/srv/docker/slskd/slskd.yml` (backup `slskd.yml.bak-2026-10-13`),
  verified live after a container restart. Zero downloads so far.
- **What Amperfy shows is tags, not paths.** The path convention holds for all 859
  files, but 440 import groups went in "as is" with whatever tags the downloaders
  wrote: 92 titles carry a ` - ` suffix or a `Artist - 'Title' (Album)` pattern
  (sockseek style), 366 files sit under `Compilations` because their album artist is
  "Various", 16 have no album, 4 no artist. That is the inconsistency Michael saw.
- **Spotify playlist definitions survive partially.** The `playlists/<name>/` folders
  each hold a SpotiFLAC download report (`<name>.txt`, Spotify order, every track
  attempted, 265 successes): perfect songs 114, skate three unofficial soundtrack 52,
  the world is beautiful… 50, shakori 47, nothin to it 7, funk todos 5, and three
  with one entry (dance, jazz bar, whats sacking mac pack). The `sockseek/<name>/`
  folders (secondset 58, Tea tent 71, shakori 87, shakori2 14, freedom 14, …) have no
  tracklist: only the files that downloaded, in no order.
- Navidrome users: `michael` (admin, owns all 35 playlists, none public) and `amperfy`
  (test user, created by Michael's other session). A non-owner sees only public
  playlists, so `amperfy` currently sees none.
- `sourcing/policy.py` has one `QualityPolicy` (crate grade: lossless preferred, lossy
  floor 320 kbps, fake-FLAC check). `sourcing/scorer.py` already reads each peer's
  `uploadSpeed`, `queueLength`, `hasFreeUploadSlot` and the file size, so a speed-first
  tier is a weighting change, not new data.
- The web client's quality selector maps to Navidrome stream parameters only
  (opus 96/160, mp3 320, raw). It does not influence what gets downloaded.
- Host: `ufw` active (rules unread, needs sudo); `sshd` inactive; Tailscale SSH is
  permitted by the tailnet policy but not enabled on this node.

---

## 0. Decisions

| # | Decision | Status |
|---|---|---|
| D1 | Amperfy for listening *for now*; not locked in. Our own client is the home for cross-platform search and the quality tier picker, so the long-run phone app is ours. | Michael |
| D2 | Redundant copies are removed once proven redundant, and this becomes part of ingest ("garbage collection happens naturally but safely"). Original import tree stays until Michael says otherwise. | Michael |
| D3 | The 28 current duplicates: second copy → `/srv/_trash/<date>/`, playlists repointed. | Michael |
| D4 | Genre is a **hierarchy of tags** (House → Jungle…), grown with the library, applied to incoming music with little or no friction, no redundant or obsolete tags. Representation decided now (§5), implementation deferred. | Michael, deferred |
| D5 | One **naming convention**, defined once, applied to new downloads and backfilled over the existing library; the crate's name for a track and Navidrome's name must agree (§3). | Michael |
| D6 | Soulseek upload cap **0.6 MB/s (586 KiB/s), 5 slots** — applied. | Michael, done |
| D7 | Automatic downloads only after Michael has approved at least one manual download and said go. | *default* |
| D8 | External search sources: Spotify public embed data + MusicBrainz first; SoundCloud deferred (official API needs Artist Pro). | *default* |
| D9 | Quality tiers are **sourcing tiers** (what the Soulseek getter chooses), with the stream transcode following the same name. Definitions in §1. | Michael |
| D11 | **Playlists come from Spotify, not from folders.** The 35 folder playlists are a stopgap "quick genre reclassification"; the real playlists are Michael's Spotify playlists. Selected ones are ported into Navidrome (and so into the crate UI) and can be toggled to crates. Folder playlists stay until the Spotify ones replace them. | Michael |
| D10 | A low-tier file is **provisional**: when a crate claims the track or Michael raises the tier, the better file replaces it and the old one goes to `/srv/_trash/` (never auto-emptied). Michael asked whether to *keep* the low copy as a streaming option; recommendation is no: Navidrome transcodes every stream tier from the best file on hand and caches the result (3 GB cache), so a 64 kbps source can only make streams worse, while a second copy confuses playlists, dedupe and the Soulseek share (sharing upscales is bad etiquette). The trash folder is the "keep it just in case". | *recommended default*, Michael undecided |
| D13 | **A track Michael removes from an imported playlist stays removed** when the import is re-run (`imported_entries` remembers what the importer added). Question for Michael: keep that, or re-add removed tracks? | *default* (2026-10-14) |
| D14 | **" - Live" stays in titles** during the tag cleanup (spec §3 said strip it with the remaster suffixes; for a DJ a live take is a different recording, and the title is where Amperfy shows it). Remaster suffixes are stripped into comments as `version: …`. Question for Michael: strip " - Live" too? | *default* (2026-10-15) |
| D12 | **Branch policy:** `overnight/2026-10-13` was merged into `main` in both repos on 2026-10-13 evening. Every overnight run branches from `main`, and the review conversation after a run ends by merging that run's branch into `main` before any new branch is cut. | Michael |

---

## 1. Quality tiers (D9) — the setting that drives sourcing and streaming

One setting, four values, chosen in the app and stored on the wanted row / crate:

| Tier | Intent (Michael) | Sourcing policy | Stream |
|---|---|---|---|
| **Low** | fastest file we can get, even 32 kbps mp3 | any allowed lossy ≥ 32 kbps; score = speed first (free slot, short queue, high `uploadSpeed`, **small size**), format and bitrate only as tie-breaks | opus 64k |
| **Medium** | ≥ 64 kbps mp3, still speed-aggressive; better is fine if it arrives in reasonable time | lossy ≥ 64 kbps; speed weight high; a candidate whose estimated arrival (`size / min(uploadSpeed, our cap)` plus queue penalty) is under a budget (default 60 s) may win on quality | opus 96k |
| **High** | ≥ 128 kbps, "I'm on aux" | lossy ≥ 128 kbps or lossless; quality and speed balanced; arrival budget 5 min | opus 160k |
| **Crate** | live performance on real systems | today's `DEFAULT_POLICY`: lossless preferred, lossy floor 320 kbps (256 kbps mp3 allowed as the small option if Michael confirms), fake-FLAC check, sample-rate/bit-depth whitelist | original file |

Design:

- `QualityPolicy` gains `name`, `min_lossy_bitrate`, `speed_weight` (0..1) and
  `arrival_budget_s`; four instances `TIERS = {"low", "medium", "high", "crate"}`.
  The scorer adds an estimated-arrival term that uses the peer's `uploadSpeed`, our own
  download cap, `queueLength` and the file size, weighted by `speed_weight`. Existing
  tests keep passing with the `crate` tier (today's numbers unchanged).
- The crate policy stays the crate policy: toggling a playlist to a crate implies
  tier `crate` for every track in it. Low/Medium/High apply to listening-only wanted
  tracks (from search, §2) and to playlists that are not crates.
- Streaming: the web client's selector becomes the same four names, mapped as in the
  table, and the client name `dj-crates-web` gets the matching Navidrome player
  profile so the choice survives a cache clear. Navidrome transcodes from whatever
  file exists, so a Low-tier source can still be played at any stream setting.
- Upgrade path (D10): raising the tier on a track, or a crate claiming it, re-queues it
  as `needs_source` with the higher tier; after the new file is verified and filed, the
  old file goes to `/srv/_trash/<date>/`, playlists are repointed, Navidrome rescans.

Acceptance: a fixture with a 2 MB 64 kbps mp3 on a fast peer and a 30 MB FLAC on a slow
queued peer ranks the mp3 first under `low` and `medium`, the FLAC first under `crate`;
a test pins each tier's floor.

## 2. Search inside and outside the library (D1, D8)

One box, two result groups, in the web client:

- "In your library" = Navidrome `search3` (exists).
- "Not in your library" = D8 sources, queried in parallel with a 3 s budget, cached
  per query for a day in the crate DB. Pressing a result calls `add_external_wanted`
  with the current tier and shows it in Wanted; pressing again runs `fetch` for it
  (no `--approve` until D7). The user never sees a download they didn't press.
- SoundCloud: reserved slot in the source list, not built.

Acceptance: a track absent from Navidrome appears from Spotify's public data, lands in
`external_wanted` idempotently with its tier, and `fetch --wanted ext-N` reports a
scored pick under that tier.

## 2a. Porting Spotify playlists (D11)

Goal: `python3 -m sourcing.cli import-playlist <spotify-url | report.txt> [--name N]`
creates or updates a Navidrome playlist with the tracks the library already has, in
Spotify order, and queues the rest as wanted rows that remember their playlist and
position, so a later `fetch` inserts each one in place. Toggling that playlist to a
crate then works through the existing mechanism (every entry gets the crate tier).

- **Inputs, in order of preference:** (1) a Spotify playlist URL — public playlists via
  the existing `spotify_csv.fetch_entity` (embed page, no account, 100-track cap);
  (2) an Exportify CSV for private or long playlists (Michael exports from the phone
  and drops it in `/srv/incoming/playlists/`); (3) the SpotiFLAC report files already on
  disk, parsed as `Title - Artist` lines in order (covers the nine `playlists/*` folders
  today). SpotiFLAC itself is a downloader (Tidal/Qobuz/Deezer backends), not a
  playlist exporter; its reports are the useful by-product. Not adopted for sourcing.
- **Matching a Spotify row to a library track:** Navidrome `search3` on `artist
  title`, word-wise, then pick by duration within ±4 s when the playlist row has a
  length (URL and Exportify do; reports do not), else by exact normalised title +
  lead artist. Ambiguous or missing → wanted row (`external_wanted` gains
  `playlist_id`, `position`). Report file inputs have no duration, so expect more
  "needs review" rows there; the client shows them for a one-tap pick.
- **Idempotent:** re-running the same playlist updates in place (same rules as
  `folders_to_playlists.py`): never duplicates entries, never deletes a track Michael
  added by hand in Navidrome.
- **The `sockseek/*` folders:** no tracklist exists on disk. Michael supplied the URLs
  (2026-10-13 evening, public, verified readable): **Tea tent** = playlist
  `0wPBj1mjvAJcmr6zdaz228` (99 tracks) **plus** `1NzQAjrmZjW01Vibt4b1tR` (27, named
  "Tea tent2222" on Spotify, split only because of the old downloader's 100-song cap) →
  one Navidrome playlist "Tea tent" in that order, so `import-playlist` takes several
  URLs for one `--name`. **secondset** = `77cVGze44N3VVE3SPnJOGk` (68 tracks).
- **Visibility:** playlists are created as `michael` and set `public`, so the
  `amperfy` test user and any future user sees them. The 35 folder playlists should be
  made public the same way now (one `updatePlaylist` call each; blocked for Claude
  by the permission classifier on 2026-10-13, so Michael or his other session does it).

Acceptance: `import-playlist` on the perfect-songs report yields a Navidrome playlist
with ≥ 100 matched entries in report order and the unmatched ones as wanted rows with
positions; running it twice changes nothing; a fake-server test covers URL, CSV and
report inputs. **Implemented 2026-10-13** (`sourcing/playlist_sources.py`,
`sourcing/import_playlist.py`, `sourcing.cli import-playlist`, `crates.cli publish`).

## 3. Naming convention and name reconciliation (D5)

**Convention (decide once, in `deploy/beets.yaml`, already in force for the 859):**

```
<Album Artist>/<Album> (<Year>)/<NN> - <Title>.<ext>      albums
<Artist>/Singles/<Title>.<ext>                            no album
```

Sanitised the way beets does it (`replace:` rules; no trailing dots; ASCII not
forced). `sourcing/organize.py` reimplements this today in Python. **Replace it with
beets:** after verification, `fetch` runs `beet import -q` (singleton mode, same
config, `incremental`, `duplicate_action: skip`) on the downloaded file. One
definition of the convention, MusicBrainz-corrected tags when there is a match, and
the file's embedded tags and its path come from the same source.

**Reconciliation (the Open question #5 problem):** today the file is named from the
wanted record (crate tags) but Navidrome then shows the file's own embedded tags,
which can disagree. Rule: **the file's tags are the truth after import; the crate
entry is repointed to whatever Navidrome shows.** Concretely, after rescan `fetch`
matches by size (exists), then updates the wanted/crate row's artist/title to
Navidrome's values and logs the rename (`reason: "renamed: X → Y"`). A track stays
`verify` only when Navidrome cannot find the file at all. Soulseek/slskd does not
rename or retag, so this is ours.

**Backfill (what Amperfy made visible):** the paths follow the convention; the tags
do not. A bounded `scripts/tag_cleanup.py` (or `beet modify` rules) handles the known
patterns: strip ` - Remastered`, ` - Live`, ` - <year> Remaster` style suffixes from
titles into a `version`/comment field; split sockseek's `Artist - 'Title' (Album)`
titles back into artist/title/album; set `albumartist` from `artist` for the 366
"Compilations" files that are not real compilations (Michael's folders are not
Various-Artists albums), then `beet move` re-files them under the artist. Every change
is logged to `docs/tag-cleanup-report.md` and reversible from the original files in
`/srv/incoming/library-import`. Run MusicBrainz matching (`beet import -L` re-import
of the library) only after that, so titles are clean enough to match.

## 3a. Download validation — what careful Soulseek users check, done by code

Today `sourcing/verify.py` checks the FLAC header, implied bitrate and duration. That
misses the classic Soulseek failure: a lossy file re-encoded as FLAC or as "320", a
16-bit file padded to 24-bit, a truncated or clipped rip, or the wrong recording under
the right name. Common practice (spectrogram in Spek, `flac -t`, length against
Discogs/MusicBrainz, a listen to the first and last seconds, bit-depth sanity, tag and
art check) becomes a checklist in code. Tools already on the box: `ffmpeg`/`ffprobe`,
`flac`/`metaflac`, `fpcalc`. No `sox`.

| Check | How | Verdict |
|---|---|---|
| Integrity | `ffmpeg -v error -i f -f null -` has no output; FLAC also `flac -t` (verifies the decoded-audio MD5 in STREAMINFO) | hard fail, every tier |
| Transcode / upscale | band energy from ffmpeg: RMS above 16, 18, 19, 20 kHz vs full-band RMS (`highpass` + `astats`); estimate the cutoff. Lossless or ≥320 kbps content normally has energy to 19–20 kHz; a cutoff ≤16 kHz means it came from ≤128 kbps | hard fail for `crate` when the file claims lossless/≥320; flag otherwise. Old mono or lo-fi recordings can legitimately lack highs, so the message says what was measured |
| Fake 24-bit / fake 96 kHz | 24-bit: decode to s32 and check the low 8 bits are not all zero; >48 kHz: energy above 22 kHz exists | hard fail for `crate`, flag otherwise |
| Right recording | `fpcalc` fingerprint; when upgrading an existing library copy, compare the two fingerprints (bit-error rate over the overlap) — no network; AcoustID lookup only if Michael registers a free key | hard fail when a reference exists and they differ |
| Length | duration vs the wanted record ±4 s (exists); vs MusicBrainz editions once that plan lands | hard fail, every tier |
| Truncation / silence | container duration vs decoded duration; `silencedetect` > 3 s at start or end | hard fail if truncated; flag silence |
| Clipping | `astats` peak at 0 dBFS with a high flat factor | flag |
| Tags and art | artist/title present and match the wanted row loosely; embedded art or folder image | flag; beets fixes tags at filing |

Design: `verify(path, expected_duration, tier, reference=None) -> Verdict` with
`problems` (hard) and `warnings` (soft) and a `measurements` dict (cutoff kHz, peak,
bit depth seen, fingerprint match) that is stored on the wanted row and shown in the
web client. Test fixtures are generated with ffmpeg from seeded white noise: a true
FLAC, a 128 kbps mp3 decoded back to FLAC (cutoff ≈16 kHz), a 16-bit file padded to
24-bit, a truncated file. Noise has energy at every frequency, so the cutoff test is
deterministic. Shared uploads are only ever `/srv/music`, so what passes here is also
what Michael shares.

## 4. Library hygiene: playlists on disk, dedupe, garbage collection (D2, D3)

1. **Playlist files on disk** (bounded): `scripts/export_playlists.py` writes every
   Navidrome playlist as `/srv/music/_playlists/<name>.m3u8`, paths relative to
   `/srv/music`, idempotent. Navidrome can import these back, so the files are the
   portable truth. Acceptance: 35 files, every entry resolves, round-trip test on the
   fake server.
2. **Dedupe the 28** (bounded): `scripts/dedupe_copies.py` reads `other_copies` from
   `library-map.csv`, moves the non-preferred copy to `/srv/_trash/<date>/<relative
   path>`, repoints playlists via `update_playlist`, rescans, asserts 831 songs.
   Never touches `/srv/incoming/library-import`.
3. **GC at ingest** (part of `fetch`, same session as §1's upgrade path): after a new
   file is verified and matched in Navidrome, any other library file with the same
   audio hash, or the same track at a lower tier that this download replaces, goes to
   trash and its playlist entries are repointed. Trash is never auto-emptied;
   `crates.cli status` reports trash size and age so Michael empties it by hand.
4. **Share hygiene:** exclude `/srv/music/_playlists` from the Soulseek share.

## 5. Tag taxonomy (D4) — representation now, tooling later

Representation, so the first backfill never has to be redone:

- Tags live **in the files** as a multi-valued `GENRE` tag (Navidrome splits on `;`
  and shows multiple genres; beets writes them). No sidecar DB for the truth.
- The **hierarchy and aliases live in the repo**: `deploy/genres.yaml`, a tree
  (`House: [Jungle, Garage, …]`, `Soul: [Motown, …]`) plus `aliases:` mapping obsolete
  or variant names to canonical ones (`DnB: Drum and Bass`). Files carry leaf tags
  only; parents are derived by walking the tree, so "House" in the app means the
  union of its children. Renaming a tag = one alias line + one `beet modify` run.
- **Applying tags to incoming music, in order of trust:** the playlist/crate it was
  requested from (if that playlist maps to a tag), MusicBrainz/Discogs genres via
  beets, and beets' `lastgenre` plugin run against our own tree and whitelist
  (`canonical: deploy/genres.yaml`, `whitelist:` = the tree's leaves), so only known
  tags are ever written. Unknown suggestions go to a "proposed tags" list in the web
  client for a one-tap accept, which also adds them to the tree.
- **First backfill** = Michael's top-level folders (Tea tent, Soul-Motown,
  Haus-Jungle-GhettoTech-Dance/DnB, Latin-Bossa-Baile, disco-fonk-daft-punk/french-touch…)
  seeded into `genres.yaml` as the initial tree, then `library-map.csv` `folder` →
  leaf tags on each file. `playlists/*` and `sockseek/*` folders stay playlists, not
  tags.

Deferred: the tooling (lastgenre config, proposed-tags UI). The yaml and the backfill
are a bounded task once Michael has edited the seed tree.

## 6. Soulseek sharing etiquette (D6) and network posture

Already true: whole library shared read-only, scan complete, logged in, reachable
through the VPN's forwarded port. One bounded task in `slskd.yml`:

- `transfers.upload.slots: 5`, `speed_limit: 1172` (KiB/s ≈ 1.2 MB/s, D6 — revisit
  after a speed test), keep the default `leechers` group (one slow slot, not a block).
- `soulseek.description`: a human line instead of the stock string.
- `shares.filters`: exclude `_playlists`; never share `/srv/incoming`.
- Verify from a second account or a room that browsing works; write
  `docs/soulseek-etiquette.md`.

**Network posture (unchanged, confirmed):** Soulseek only inside gluetun (kill switch,
Proton's IP and port, home IP never seen); Navidrome and crates loopback + Tailscale
HTTPS; `ufw` active; everything stays in Docker on this box. Nothing moves to a cloud
host. UPnP: lets any LAN device open an inbound router port without a password;
nothing we run needs it; turn it off.

**Needs Michael (root, one line each):**

- Router: UPnP off, no port forwards.
- `sudo tailscale set --ssh` — enables Tailscale SSH on the box (tailnet policy already
  allows it). Then from the phone (Termius/Blink): `ssh mh550@pop-os`, authenticated
  by the tailnet, no password. After that the password is one command away:
  `grep ND_PASS /srv/docker/.env`.
- `sudo ufw status verbose` once, pasted into `docs/network-posture.md`.

## 7. Suggested session order (all on an `overnight/<date>` branch, test-first)

1. ~~§6 slskd settings~~ done 2026-10-13; the description and share filter remain.
2. §2a `import-playlist` from the nine report files + the Spotify URLs Michael names, playlists public.
3. §3 tag cleanup backfill (fixes what Amperfy shows).
4. §4.1 playlist export, §4.2 dedupe.
5. §1 tiers in `policy.py` + scorer + CLI `--tier`, web selector renamed.
5a. §3a download validation in `verify.py` (ffmpeg fixtures).
6. §3 beets-based filing in `fetch` + name reconciliation (retires `organize.py`).
7. §4.3 GC at ingest + §1 upgrade path.
8. §5 `genres.yaml` seed + folder backfill (after Michael edits the seed tree).
9. §2 external search (own spec section first).
10. Runner (`sourcing_jobs` table) — after D7.

## Not in scope

Serato crate/history import (Phase 2), device sync (Phase 3), stems, SoundCloud API,
native iOS app, emptying trash automatically.
