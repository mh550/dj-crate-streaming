# 06 · Verification (what proves a download is the right file and a good file)

Pinned clone `~/research/soulsync-src/SoulSync` at `34bf7cf9c741`, read only (nothing in it was executed).
Citations: `SoulSync:<path>:<line>` in that clone, `ours:<path>:<line>` in this worktree; *unverified* marks a claim
without one. Music only: two audiobook routing calls sit on the import path
(`SoulSync:core/downloads/post_processing.py:277-278`, `SoulSync:core/imports/pipeline.py:1798-1804`); they are named
here once and skipped. The AcoustID scoring rules themselves are in 03-matching.md; this file covers where they sit in
the chain and what a failure does.

## What SoulSync does

**Not where the feature list looks.** `core/downloads/validation.py` checks *candidates* before a transfer (below,
"Before the transfer"); the file checks run in the import pipeline, `core/imports/pipeline.py` and
`core/imports/file_integrity.py`. The monitor sets a finished transfer to `post_processing` and submits
`run_post_processing_worker` (`SoulSync:core/downloads/post_processing.py:158`), which hands the found file to
`post_process_matched_download_with_verification` (`SoulSync:web_server.py:15385-15391`). That wrapper runs the inner
`post_process_matched_download`, which records each check's outcome as a flag on the context; the wrapper then reads
the flags and decides retry, fail or complete (`SoulSync:core/imports/pipeline.py:1921-1935`,
`SoulSync:core/imports/pipeline.py:1959-2115`).

```
transfer Completed ─► post_processing worker: find the file (5 × 5 s), audio extension, expected path
   ─► import pipeline (per-context lock)
        race guard ─► size settles ─► integrity tier 1 ─► [flac -t, opt-in] ─► [audio guard, opt-in]
        ─► quality gate (never rejects under the default profile) ─► [AcoustID, opt-in] ─► replace guards
        │                                                                                     │
        any FAIL ──► ss_quarantine/<file>.quarantined + JSON sidecar; (peer, file) blocked     ▼
                     ─► requeue next candidate (≤ 5) ─► give up: failed (+ 90-day blocklist, not for integrity)  move into library
                                                                                   (or atomic staging, opt-in)
                                                                     ─► [ReplayGain, opt-in] ─► batch end:
                                                                         publish staged album, album consistency
```

### Steps after a transfer completes (`core/downloads/post_processing.py`)

1. Bail if the task was cancelled, completed or taken over, or lacks a filename or peer
   (`SoulSync:core/downloads/post_processing.py:167-208`).
2. Find the task's context: task-scoped key, then the legacy `peer::filename` key, then a fuzzy match on the same
   uploader and basename that **refuses to guess** when more than one context fits
   (`SoulSync:core/downloads/post_processing.py:138-155`, `SoulSync:core/downloads/post_processing.py:239-274`).
3. Torrent/Usenet: pick the requested track out of the release and copy it into the transfer folder
   (`SoulSync:core/downloads/post_processing.py:294-347`, `SoulSync:core/downloads/post_processing.py:95-113`).
4. Look for the file up to **5 times, 5 s apart** (`SoulSync:core/downloads/post_processing.py:386-451`). A hit must
   have one of 14 audio extensions (`SoulSync:core/downloads/post_processing.py:50-67`), and a hit in the library
   folder counts only if its real path equals the context's `_final_processed_path`
   (`SoulSync:core/downloads/post_processing.py:70-77`, `SoulSync:core/downloads/post_processing.py:434-442`).
   Not found: `failed`, naming the folder (`SoulSync:core/downloads/post_processing.py:453-477`).
5. With a context, run the import pipeline with verification; **without one, the task is marked completed with no
   import and no check** (`SoulSync:core/downloads/post_processing.py:621-666`).

### The check chain, in the order it runs (`core/imports/pipeline.py`, `core/imports/file_integrity.py`)

"Off" means the default is off. Profile columns override config keys when a quality profile resolves
(`SoulSync:core/imports/pipeline.py:254-277`).

| # | Check | Threshold, default | On failure | Cite |
|---|---|---|---|---|
| 0 | per-context lock | one lock per context key | serialises a duplicate dispatch | `SoulSync:core/imports/pipeline.py:773-778` |
| 1 | race guard: source file still there | `os.path.exists` | destination exists → success; already quarantined → return; else `failed` | `SoulSync:core/imports/pipeline.py:780-807` |
| 2 | size settles | ≤ 5 polls × 1.5 s; **never rejects** | — | `SoulSync:core/imports/pipeline.py:809-823` |
| 3a | **extension and size** | < 10 KiB fails | quarantine `integrity` | `SoulSync:core/imports/file_integrity.py:94`, `SoulSync:core/imports/file_integrity.py:376-390` |
| 3b | **header parse** (mutagen) | parse error / unknown format fails | quarantine `integrity` | `SoulSync:core/imports/file_integrity.py:392-426` |
| 3c | lossless **density** = (size × 8 / length) / (rate × bits × channels) | < 0.30 only *triggers* a decode; fails only if the decode shows truncation or silence | quarantine `integrity` | `SoulSync:core/imports/file_integrity.py:208`, `SoulSync:core/imports/file_integrity.py:445-470` |
| 3d | zero-length header | decoded < 0.8 × expected fails | quarantine `integrity` | `SoulSync:core/imports/file_integrity.py:472-549` |
| 3e | **duration vs expected** | ±3.0 s (±5.0 s over 600 s); a longer file gets max(tol, 15 s); user override `post_processing.duration_tolerance_seconds` (0 = auto, ≤ 60, both ways); skipped with no expected length and for local imports | quarantine `integrity` | `SoulSync:core/imports/file_integrity.py:100-141`, `SoulSync:core/imports/file_integrity.py:144-161`, `SoulSync:core/imports/file_integrity.py:551-598` |
| 3f | **`flac -t`** (frames + MD5) | `post_processing.verify_flac_decode` **off**; fails open without `flac` or on timeout (600 s) | quarantine `integrity` | `SoulSync:core/settings.py:611-615`, `SoulSync:core/imports/file_integrity.py:296-345` |
| 4 | audio guard: decoded < 0.85 × container length, or more than 50 % silence at −50 dB (2 s) | profile `deep_audio_verify` / `post_processing.audio_completeness_check` **off** | quarantine `silence`; give-up blocklists | `SoulSync:core/imports/pipeline.py:927-980`, `SoulSync:core/imports/silence.py:34-43`, `SoulSync:core/imports/silence.py:229-289` |
| 5 | **quality gate**: format, bit depth, rate, bitrate vs the profile's ranked targets (mutagen's claim, not a measurement) | passes on any target, and also whenever `fallback_enabled` or `downsample_enabled`; the seeded "Balanced" profile has fallback on, so **by default it never rejects**; WAV/AIFF/APE/WMA/DSD skip it | quarantine `quality`; give-up blocklists | `SoulSync:core/imports/guards.py:159-225`, `SoulSync:core/quality/schema.py:136-143`, `SoulSync:core/quality/schema.py:171-172`, `SoulSync:core/imports/pipeline.py:987-1043` |
| 6 | **AcoustID** (03-matching.md has the rules) | `acoustid.enabled` **off**; lookup error → continue; best score < 0.80 → SKIP; version gate; title ≥ 0.70 + artist ≥ 0.60 → PASS; a confident other title → FAIL | FAIL → quarantine `acoustid`; SKIP quarantines only with `acoustid_required` / `acoustid.require_verified` (both off) | `SoulSync:core/settings.py:745-748`, `SoulSync:core/imports/pipeline.py:1045-1159`, `SoulSync:core/matching/audio_verification.py:26-29` |
| 7 | artist context present | — | `failed`, no quarantine | `SoulSync:core/imports/pipeline.py:1248-1254` |
| 8 | replace: a real upgrade under the profile | only for upgrade jobs or `replace_lower_quality` (off) | keep the library file; task fails | `SoulSync:core/imports/pipeline.py:1543-1564`, `SoulSync:core/imports/quality_replace.py:12-49` |
| 9-10 | replace: incoming ≥ 0.8 × the existing file's length | header length first, decode only when it reads 0 (the comment says "REAL decoded lengths") | quarantine `integrity` | `SoulSync:core/imports/pipeline.py:108-134`, `SoulSync:core/imports/pipeline.py:1565-1617` |
| 11 | replace: the destination exists with > 2 tags | — | the **incoming download is deleted** as redundant | `SoulSync:core/imports/pipeline.py:1618-1647` |
| 12 | move; retire a superseded original only after re-checking 8 and 9 | — | the old file stays | `SoulSync:core/imports/pipeline.py:1686-1702` |

So with defaults a Soulseek file is proved by: at least 10 KiB, a parsable header, the right length (within 3 s, or 15 s when the file is longer; skipped without an expected length), and
(if it claims lossless) not implausibly thin unless it decodes whole. The quality gate can reject on bitrate after the
download only under a profile with fallback and downsample off, such as the audiophile preset
(`SoulSync:core/imports/guards.py:199-225`); under the seeded "Balanced" profile the lossy floor acts only in the
candidate filter before the transfer (quality profiles, below).

**Fake/transcode detection.** None in the import path. A FLAC made from an MP3, at the right length, passes 3a-3e;
`flac -t` (if on) passes because the MD5 is of the PCM it was encoded from
(`SoulSync:core/imports/file_integrity.py:299-318`); the quality gate reads "flac, 16-bit, 44.1 kHz" from the header
(`SoulSync:core/imports/file_ops.py:631-639`), which meets the default "FLAC 16-bit" target and outranks "MP3 320"
(`SoulSync:core/quality/schema.py:141-142`), so with replace-lower on it would replace a real 320
(`SoulSync:core/imports/quality_replace.py:31-36`). The density rule is a preview/padding detector, its own comment
putting dense material at 40-75 % of raw PCM (`SoulSync:core/imports/file_integrity.py:201-208`); whether a real
transcode ever falls under 0.30 is *unverified* (no file measured). A search for `spectr|upconver|transcod|lowpass|
fake.?lossless` over non-test Python hits nothing else on the import path (*unverified*: grep result, not a line).
The only lossy-source detector is a **library repair job**, "Fake Lossless Detector", off by default, weekly,
report-only, with `spectral_cutoff_khz: 16.0` (`SoulSync:core/repair_jobs/fake_lossless_detector.py:1-38`). It
high-passes the first 30 s at 0.35 × the sample rate and calls the file lossy if the rest is under −70 dB
(`SoulSync:core/repair_jobs/fake_lossless_detector.py:254-288`); at 48 kHz that edge is 16.8 kHz, above the 16.0
threshold, so it can never flag a 48 kHz file (`SoulSync:core/repair_jobs/fake_lossless_detector.py:108`). Two likely
defects, read not run: the extension test sits outside the file loop, so only each directory's last file is looked at
(`SoulSync:core/repair_jobs/fake_lossless_detector.py:67-70`), and ffmpeg runs with `-v quiet`, which probably hides
the `volumedetect` line it parses (`SoulSync:core/repair_jobs/fake_lossless_detector.py:255`; *unverified*, inferred
from ffmpeg's log levels).

**ReplayGain** (`core/replaygain.py`). Opt-in, `post_processing.replaygain_enabled` (default False), run after the
move and cover art (`SoulSync:core/imports/pipeline.py:1737-1753`). ffmpeg `ebur128=peak=true` measures integrated
LUFS and true peak; gain = −18 LUFS − measured, clamped to −30…−5 dB (`SoulSync:core/replaygain.py:18-46`,
`SoulSync:core/replaygain.py:79-100`). At import it writes **track** gain and peak tags only, through the atomic save
(`SoulSync:core/replaygain.py:277-328`, `SoulSync:core/imports/pipeline.py:1746`); an error is logged and the import
goes on (`SoulSync:core/imports/pipeline.py:1748-1749`). It is loudness tagging, not verification.


### Before the transfer (`core/downloads/validation.py`: candidates, not files)

- Soulseek: the 0.45/0.40/0.15 match score with a 0.58 floor (03, 04), quarantined `(peer, file)` pairs dropped, the
  size cap and the profile's quality ladder, and every word of an expected artist in one path segment
  (`SoulSync:core/soulseek_client.py:2781-2825`, `SoulSync:core/downloads/validation.py:981-1015`).
- A strict duration pre-check (the same 3 s / 15 s rule) applies only to Tidal, Qobuz, HiFi, Deezer and Amazon, **not
  Soulseek** (`SoulSync:core/downloads/validation.py:212-241`, `SoulSync:core/downloads/validation.py:534-550`).
- SoundCloud previews: dropped under 35 s or half the expected length (`SoulSync:core/downloads/validation.py:175-209`).

### Atomic album publish (`atomic_album_publish.py`, `atomic_manifest.py`, `atomic_recovery.py`)

**What "atomic" protects:** a media server scanning half an album while it downloads. An album batch's tracks are
imported into a hidden staging mirror and moved into the library "only once the WHOLE batch completes"
(`SoulSync:core/downloads/atomic_album_publish.py:3-9`). **Off by default** (`album_downloads.atomic_publish: False`,
`SoulSync:core/settings.py:871-874`).

- **Where:** `<library>/.soulsync_atomic_staging/<batch_id>/<library-relative path>`, inside the library so the move
  is a same-filesystem rename, dot-prefixed so scanners skip it (`SoulSync:core/downloads/atomic_album_publish.py:36-58`).
- **Gate,** decided once per batch at its first imported track: flag on, `is_album_download`, and an album folder
  with no audio yet ("fresh"); a fill into an existing album, a failed write probe or any error falls back to
  per-track publish (`SoulSync:core/imports/pipeline.py:482-584`). Upgrades are never staged
  (`SoulSync:core/imports/pipeline.py:1494-1499`). Only the first track's folder is checked
  (`SoulSync:core/imports/pipeline.py:512-527`); whether a later disc folder can collide is *unverified*.
- **When it publishes:** when every task is terminal, and terminal includes `failed`, `cancelled` and `not_found`
  (`SoulSync:core/downloads/lifecycle.py:1183-1201`). There is no completeness threshold: whatever is staged is moved
  (`SoulSync:core/downloads/atomic_album_publish.py:335`). So "atomic" means "not while still downloading", **not**
  "only when complete"; the missing tracks stay on the wishlist (`SoulSync:core/downloads/atomic_album_publish.py:7-9`) and later
  arrive per track (`SoulSync:core/downloads/atomic_recovery.py:27-32`).
- **How:** staged files in natural sort order, each `os.replace` (copy + fsync + rename across filesystems) followed
  by a DB repoint; the first failure rolls every published file and pointer back
  (`SoulSync:core/downloads/atomic_album_publish.py:256-379`, `SoulSync:core/imports/file_ops.py:183-239`). Each file
  is atomic; the album goes live one rename at a time. A failed publish is retried by the 30 s healer up to 3 times,
  then the batch is `error` with files kept (`SoulSync:core/downloads/lifecycle.py:59-62`,
  `SoulSync:core/downloads/lifecycle.py:1217-1241`). Staging is deleted only on a user cancel
  (`SoulSync:core/downloads/atomic_album_publish.py:382-430`).
- **Manifest:** `<staging_root>/.soulsync_batch.json`, JSON, written by temp file + `os.replace` under one lock,
  best-effort (`SoulSync:core/downloads/atomic_manifest.py:38-92`). Header `batch_id, transfer_dir, profile_id,
  album_name, created_at, updated_at`; per finished track `final_path, source, source_ids, track_name, artist_name,
  profile_id, staged_at` (`SoulSync:core/downloads/atomic_manifest.py:95-143`). No sizes, hashes, lengths or list of
  expected tracks, so it cannot tell a complete album from a partial one. Removed on a successful publish
  (`SoulSync:core/downloads/atomic_album_publish.py:366-376`).
- **Recovery** (`album_downloads.atomic_recover_orphans`, default True, `SoulSync:core/settings.py:875-881`) runs
  once at start-up, before the monitor (`SoulSync:web_server.py:24724-24760`). Each orphan tree is **published, not
  rolled back**, partial or not ("an album that fills in" beats "an album that never appears",
  `SoulSync:core/downloads/atomic_recovery.py:18-25`); a staged file whose destination exists goes to the recycle bin
  so the library copy wins (`SoulSync:core/downloads/atomic_recovery.py:126-193`); a tree without a manifest still
  recovers (`SoulSync:core/downloads/atomic_recovery.py:196-212`). It re-verifies nothing (*unverified*: no verify call found in `atomic_recovery.py` by grep).

### Album consistency (`core/album_consistency.py`)

Not a check: a **tag rewrite** that stops media-server album splits ("Picard-style",
`SoulSync:core/album_consistency.py:1-3`). After an album batch it picks one MusicBrainz release (the user's pinned
edition, else a cached pin, else a search scored on barcode +50, track count 0-40, status, country, format, date,
`SoulSync:core/album_consistency.py:100-162`, `SoulSync:core/album_consistency.py:303-361`). It matches files to its
tracklist by (disc, track) slot plus title, then title similarity ≥ 0.70, **never by length**
(`SoulSync:core/album_consistency.py:364-410`). Under 50 % matched it writes nothing
(`SoulSync:core/album_consistency.py:813-816`); otherwise matched files get 15 album-level MB tags, `album` and
`albumartist`, and per-track release-track and recording ids; unmatched files keep theirs
(`SoulSync:core/album_consistency.py:24-40`, `SoulSync:core/album_consistency.py:823-877`). Track numbers, titles,
art and format are not in its tag list (`SoulSync:core/album_consistency.py:24-40`). It runs after `_mark_batch_complete`, i.e. after the publish and after the
`batch_complete` event that drives the default auto-scan, on files already live
(`SoulSync:core/downloads/lifecycle.py:1243-1254`, `SoulSync:core/automation_engine.py:140-145`); gated by
`musicbrainz.embed_tags` (default True, `SoulSync:core/settings.py:824`, `SoulSync:core/downloads/lifecycle.py:952-960`).

**Same release?** Nothing checks that an album's files come from one release. The import matcher uses durations only
as a ±10 s per-track gate and an edition tie-break (`SoulSync:core/imports/album_matching.py:446-485`,
`SoulSync:core/imports/album_matching.py:835-879`); release bundles pair files by tag, disc/track and title ≥ 0.95
(`SoulSync:core/downloads/release_import.py:178-202`). Sameness is asserted by tagging one pinned release id, not
verified.

### AcoustID verification (`core/acoustid_verification.py`, `core/matching/audio_verification.py`)

Five outcomes, PASS / FAIL / SKIP / DISABLED / ERROR, with the stated rule "FAIL OPEN, only returns FAIL when we are
CONFIDENT the file is wrong" (`SoulSync:core/acoustid_verification.py:52-58`,
`SoulSync:core/acoustid_verification.py:472-475`). In order: client unavailable (no pyacoustid, no key, disabled, no
fpcalc) → SKIP (`SoulSync:core/acoustid_verification.py:539-544`, `SoulSync:core/acoustid_client.py:253-266`); a broken
lookup → ERROR, "never quarantine" (`SoulSync:core/acoustid_verification.py:564-571`); no match → SKIP
(`SoulSync:core/acoustid_verification.py:573-582`); then the string rules of 03-matching.md. A FAIL turns into SKIP
when every top match runs a very different length, max(60 s, 35 %)
(`SoulSync:core/matching/audio_verification.py:565-572`, `SoulSync:core/matching/acoustid_candidates.py:171-186`,
`SoulSync:core/matching/acoustid_candidates.py:118-124`).

- **Strings only.** `verify_audio_file` takes title, artist and length, no recording id
  (`SoulSync:core/acoustid_verification.py:495-503`, `SoulSync:core/imports/pipeline.py:1059-1086`). AcoustID's
  MusicBrainz ids are used only to fill a missing title/artist (`SoulSync:core/acoustid_verification.py:185-219`)
  and to fetch alternate titles (cached in memory 24 h / 1 h, 512 entries)
  (`SoulSync:core/acoustid_verification.py:296-340`, `SoulSync:core/acoustid_verification.py:435-437`). The verdict
  rests on title/artist similarity (`SoulSync:core/matching/audio_verification.py:480-493`).
- **What a result does** (`SoulSync:core/imports/pipeline.py:1095-1150`): FAIL quarantines (`acoustid`); SKIP imports
  unless the profile's `acoustid_required` / `acoustid.require_verified` is on (both off), then it quarantines as
  `acoustid_unverified`; ERROR imports ("would stall the whole pipeline during an outage"). Unavailable is recorded as
  `disabled` and imports even with `require_verified` on, because the block sits inside `if available`
  (`SoulSync:core/imports/pipeline.py:1053`, `SoulSync:core/imports/pipeline.py:1154-1156`).
- **Operational:** no fingerprint or lookup cache and no throttle of its own (it trusts pyacoustid's, per a docstring,
  `SoulSync:core/acoustid_client.py:4-7`); a rate-limit reply is an ERROR, so the file imports
  (`SoulSync:core/acoustid_client.py:436-439`). Without fpcalc on PATH the client **downloads chromaprint's fpcalc
  v1.5.1 from GitHub** at import time (`SoulSync:core/acoustid_client.py:85-176`).
- `core/audio_length.py` fixes lying CBR MP3 Xing headers (`SoulSync:core/audio_length.py:1-14`) and is used only by
  audiobook code (*unverified*: grep hits `core/audiobook_completeness.py` and `core/audiobook_library_metadata.py`
  only). The verifier reads length with mutagen (`SoulSync:core/acoustid_verification.py:99-109`).
- A library repair job runs the same decision core over the whole library and files retag / redownload / delete
  findings (`SoulSync:core/repair_jobs/acoustid_scanner.py:1-8`).

### Quality profiles (`core/quality/`)

A profile is a `quality_profiles` row: a ranked target ladder (format, minimum bit depth, minimum sample rate,
minimum bitrate), `fallback_enabled`, search mode, upgrade policy and cutoff, and the per-profile switches
`acoustid_required`, `downsample_enabled`, `deep_audio_verify`, `replace_lower_quality`, `lossy_copy_*`
(`SoulSync:core/quality/schema.py:61-87`, `SoulSync:core/quality/model.py:178-186`). Seeded: **"Balanced"** (FLAC
24/192 … FLAC 16, then MP3 320, fallback **on**) and "Upgrade until top quality" (FLAC only, fallback still on)
(`SoulSync:core/quality/schema.py:136-175`). Presets: audiophile (FLAC 24-bit only, fallback off), balanced,
space_saver (MP3 320/256/192) (`SoulSync:api/quality_profiles.py:90-101`,
`SoulSync:database/music_database.py:15273-15320`). "Lossy never" is not a switch but an all-FLAC ladder with fallback
off (`SoulSync:core/quality/release_format.py:15-17`). A profile can be set per watchlist artist, mirrored playlist,
wishlist track and library track (`SoulSync:database/music_database.py:1058`, `SoulSync:database/music_database.py:1385`,
`SoulSync:database/music_database.py:2503`, `SoulSync:database/music_database.py:2538`).

- **Before download** on the candidate's *claimed* attributes: `filter_and_rank` keeps only the best target bucket
  present, or everything when nothing matches and fallback is on, or nothing when it is off
  (`SoulSync:core/quality/model.py:286-343`). A FLAC with no stated rate/depth is guessed from kbps (≥ 1450 kbps =
  24-bit) (`SoulSync:core/quality/model.py:72-104`). Torrent/Usenet releases also get a size sanity check (lossless
  < 400 kbit/s implied rejected), used only by the album bundle (`SoulSync:core/quality/release_format.py:288-303`,
  `SoulSync:core/download_plugins/album_bundle.py:606`).
- **After download** on mutagen's header values (check 5 above; "Each value is a *claim* … the post-download quality
  guard later verifies the real file", `SoulSync:core/quality/source_map.py:10-14`). The header of a transcode tells
  the same lie as the filename.
- **Upgrades** replace: a real upgrade under the profile and ≥ 0.8 × the old length, then the new file overwrites the
  destination and an original at another path is removed with `os.remove`, no recycle bin
  (`SoulSync:core/imports/pipeline.py:1686-1702`). `retention.py` records the quality acquired so an intended downsample
  does not re-trigger an upgrade (`SoulSync:core/quality/retention.py:1-11`).

### Quarantine (`core/imports/quarantine.py`, `api/quarantine.py`, `core/downloads/review_reject.py`)

- **What lands there:** five triggers in use (the docstring also names `bit_depth` and `unknown`,
  `SoulSync:core/imports/guards.py:31-37`): `integrity` (size, parse, length, `flac -t`, and the replace-length guard),
  `silence`, `quality`, `acoustid`, `acoustid_unverified` (`SoulSync:core/imports/pipeline.py:844-880`,
  `SoulSync:core/imports/pipeline.py:927-950`, `SoulSync:core/imports/pipeline.py:995-1010`,
  `SoulSync:core/imports/pipeline.py:1101-1120`).
- **Where:** `<download_path>/ss_quarantine/<YYYYmmdd_HHMMSS>_<stem><ext>.quarantined` plus a JSON sidecar
  (`original_filename`, `quarantine_reason`, `timestamp`, `expected_track`, `expected_artist`, `context_key`,
  `trigger`, the whole pipeline context) (`SoulSync:core/imports/guards.py:54-105`,
  `SoulSync:core/imports/quarantine.py:34-76`). Never deleted at quarantine time; if the move fails the file stays put
  (`SoulSync:core/imports/guards.py:31-105`).
- **Feedback into search:** every quarantine writes `quarantine_source_blocks(username, filename, …)`, no TTL, capped
  at 25,000 rows (`SoulSync:core/imports/guards.py:107-124`, `SoulSync:database/music_database.py:24099-24136`); the
  Soulseek filter drops those pairs, plus any found in sidecars, before ranking
  (`SoulSync:core/soulseek_client.py:2710-2749`, `SoulSync:core/imports/quarantine.py:97-170`).
- **Retry:** the task goes back to `searching` on the next cached candidate (default on, ≤ 5; ≤ 100 in the opt-in
  exhaustive mode) (`SoulSync:core/settings.py:623`, `SoulSync:core/downloads/monitor.py:60-66`,
  `SoulSync:core/downloads/monitor.py:397-416`). An opt-in fallback accepts the oldest quarantined candidate when ≥ 2
  failed the same version mismatch, bypassing only AcoustID (`SoulSync:core/imports/version_mismatch_fallback.py:140-148`).
- **How long:** no TTL, but the default-on "Full Cleanup" automation runs every 12 h (first 15 min after start) and
  empties `ss_quarantine` (`SoulSync:core/automation_engine.py:244-250`), so an unreviewed file lives about 12 h
  (inferred from the default schedule, not observed).
- **Human resolution** (`api/quarantine.py`): list and badge (`SoulSync:api/quarantine.py:87-160`); **approve** moves
  the file to `Transfer` and re-runs the pipeline with every check skipped, optionally deleting sibling entries and
  cancelling an in-flight retry (`SoulSync:api/quarantine.py:203-312`, `SoulSync:core/imports/quarantine.py:535-603`);
  approve counts as replace intent (`SoulSync:core/imports/pipeline.py:150-155`) and does not unblock the source ("the
  block is one specific (uploader, file), not the uploader", `SoulSync:core/imports/quarantine.py:590-602`);
  **delete** (`os.remove`, optional siblings) and **clear** (`SoulSync:api/quarantine.py:163-200`,
  `SoulSync:api/quarantine.py:61-77`); stream / A-B compare / tags for review (`SoulSync:api/quarantine.py:327-477`).
  No retry or unblock route (*unverified*: none among the routes read; `remove_quarantine_source_block` has no
  caller, `SoulSync:database/music_database.py:24155-24159`). `review_reject.py` serves the *other* list, imported-but-unverified files: rejecting one
  deletes it and its library row and adds `(peer, file)` to `download_blacklist`
  (`SoulSync:core/downloads/review_reject.py:1-47`, `SoulSync:api/verification.py:279-339`).

### Blocklists (`core/blocklist/`, `core/downloads/failed_blocklist.py`)

| Kind | Key | Lifetime | Written by | Read by |
|---|---|---|---|---|
| entity: artist / album / track never wanted | metadata-source id, cascade track → album → artist, artist-name fallback | none | `POST /api/blocklist` (`SoulSync:api/discover_routes.py:2199-2231`) | `add_to_wishlist`, the download-queue guard (`SoulSync:core/blocklist/matching.py:6-18`, `SoulSync:core/downloads/master.py:915-939`) |
| `download_blacklist` | exact (peer, filename) | none | review reject, manual blacklist (`SoulSync:database/music_database.py:3747-3760`) | download worker skip (`SoulSync:core/downloads/candidates.py:527-534`) |
| quarantine source blocks | exact (peer, filename) | none, 25,000 cap | every quarantine | Soulseek search filter |
| failed-download | SHA1 of service, artist, title, size; all Soulseek peers are one service | 90 days, 5,000 rows | give-up after retries for silence / quality / AcoustID, **not** integrity (`SoulSync:core/downloads/failed_blocklist.py:27-28`, `SoulSync:core/downloads/failed_blocklist.py:62-70`, `SoulSync:core/imports/pipeline.py:2090-2115`) | worker `is_candidate_blocked` (`SoulSync:core/downloads/candidates.py:536-544`) |

Nothing blocks a whole peer on the music side (`SoulSync:core/imports/quarantine.py:601-602`). Whether the
failed-download writer (wanted identity + picked size) and reader (the candidate's own attributes) ever produce the same
hash is *unverified* (`SoulSync:core/downloads/failed_blocklist.py:145-176`).

### Summary

| Question | SoulSync, default settings | Opt-in | Cite |
|---|---|---|---|
| Fake / transcode detection | **No.** Density < 0.30 of raw PCM triggers a decode for truncation/silence only; the quality gate reads the header's claim | `flac -t` (catches corruption, not transcodes); a weekly report-only spectral repair job that likely flags nothing | `SoulSync:core/imports/file_integrity.py:445-470`, `SoulSync:core/repair_jobs/fake_lossless_detector.py:34-38` |
| Wrong-song protection | Pre-download match score + base-title veto (03); after download only the length (±3 s, +15 s when longer, skipped without an expected length) | AcoustID: a confident fingerprint naming another title FAILs | `SoulSync:core/imports/file_integrity.py:551-598`, `SoulSync:core/matching/audio_verification.py:829-831` |
| Album consistency checks | **No check.** A post-publish tag rewrite to one pinned MB release (on by default); no length or same-release test | atomic staging (off) hides a partial album until the batch ends, then publishes it anyway | `SoulSync:core/album_consistency.py:364-410`, `SoulSync:core/downloads/lifecycle.py:1183-1201` |
| Quarantine | **Yes:** moved with a sidecar, `(peer, file)` blocked, next candidate tried (≤ 5), approve / delete in the UI, emptied every 12 h | require-verified, version-mismatch fallback | `SoulSync:core/imports/guards.py:31-124`, `SoulSync:api/quarantine.py:203-312` |

### Would ext-74 have been caught?

The case (`ours:docs/specs/2026-10-22-downloads-and-requests.md:27`): asked "I'm Still In Love With You", the peer
offered track 09 "One of These Good Old Days" from a folder named after the album; AcoustID said the latter at 0.958.
Spotify's 196 s and the file's 195 s agree, because MusicBrainz has track 1 at 195.7 s and track 9 at 195.6 s
(`ours:docs/specs/2026-10-22-downloads-and-requests.md:36-38`).

- **After download, default settings: no.** SoulSync's only identity check that is on by default is the length
  (±3 s, `SoulSync:core/imports/file_integrity.py:100-116`), and 195 vs 196 s passes. Size, header and quality gate
  pass a good FLAC.
- **With AcoustID enabled: yes, by `SoulSync:core/matching/audio_verification.py:829-831`.** The score 0.958 clears
  the 0.80 floor, the title similarity of the two names is far under 0.70, and no other returned recording carries the
  asked title, so `evaluate` ends in FAIL "Audio mismatch" → quarantine `acoustid`, `(peer, file)` blocked, the next
  candidate tried (`SoulSync:core/imports/pipeline.py:1112-1150`, `SoulSync:core/imports/guards.py:107-124`,
  `SoulSync:core/imports/pipeline.py:1998-2030`, `SoulSync:core/downloads/monitor.py:397-416`). The language-script skip does not apply to two
  ASCII titles (`SoulSync:core/matching/audio_verification.py:794-827`). This is read from code and the 10-21 numbers,
  not run; 03-matching.md has the hand estimate.
- **Before download** the base-title veto would have rejected the candidate on its filename (0.275 < 0.30), but not
  under a flat `Artist - Album - 09 - Title` name (03-matching.md, "ext-74 answer"). That is matching, not verification.

So the protection that would have caught ext-74 is the **title-based** AcoustID FAIL, exactly what S1-02 plans; it is
off in a default SoulSync install.

## How ours does it

One function proves a download, `verify` (`ours:sourcing/verify.py:236-333`), and `fetch` calls it on every approved
download at the row's tier, while the row still says `sourcing` (`ours:sourcing/fetch.py:458-459`). The scorer has
already refused, before any transfer, a denied format, a lossy file under the floor and a FLAC whose listed size and
length imply under 500 kbps (`ours:sourcing/scorer.py:143-151`, `ours:sourcing/scorer.py:183-187`).

**The quality rule (D24).** One rule, in four identically set tiers: lossless (flac preferred, then wav / aiff /
alac) or lossy at 256 kbps or more (mp3 / m4a); ogg, opus, wma refused; verification strict for every download
(`ours:docs/specs/2026-10-17-amperfy-pivot.md:19`, `ours:deploy/policy.toml:5-9`, `ours:deploy/policy.toml:24-58`).
`strict_verify = true` in every tier makes a file that is not the quality it claims a hard failure
(`ours:deploy/policy.toml:17-18`, `ours:sourcing/verify.py:232-233`, `ours:sourcing/verify.py:253`). The file has no
`min_lossless_kbps` or `duration_tolerance_s` key (`ours:sourcing/policy.py:68-69`), so the code defaults hold:
500 kbps and 4.0 s (`ours:sourcing/policy.py:27-33`).

**The checks, in order** (`ours:sourcing/verify.py:279-333`):

| # | Check | Threshold | Hard? | Cite |
|---|---|---|---|---|
| 1 | file exists | — | every tier | `ours:sourcing/verify.py:279-281` |
| 2 | header readable: FLAC STREAMINFO parsed by hand, else ffprobe | — | every tier | `ours:sourcing/verify.py:43-89`, `ours:sourcing/verify.py:282-285` |
| 3 | length vs the row's expected length (Spotify/MusicBrainz) | ±4.0 s | every tier | `ours:sourcing/verify.py:291-294`, `ours:sourcing/verify.py:303-305` |
| 3b | a new version (no expected length): arrived length vs the peer's listing | max(10 s, 5 %) | every tier | `ours:sourcing/verify.py:296-301` |
| 4 | FLAC implied bitrate (size × 8 / length) | < 500 kbps; overruled to a warning when the measured spectrum is full band | strict | `ours:sourcing/verify.py:306-310`, `ours:sourcing/verify.py:257-262` |
| 5 | sample rate | < 44.1 kHz | strict | `ours:sourcing/verify.py:311-312` |
| 6 | one ffmpeg decode + `flac -t` (FLAC MD5) | `flac -t` failure; no samples; ≥ 10 decode errors; digital silence | every tier | `ours:sourcing/verify.py:188-214`, `ours:sourcing/verify.py:407-422`, `ours:sourcing/verify.py:185` |
| 7 | truncation: header length − decoded length | > 1.0 s | every tier | `ours:sourcing/verify.py:424-426` |
| 8 | spectral cutoff: RMS above 11…20 kHz (22, 24 above 48 kHz); a ≥ 15 dB step between edges or a band 90 dB under full is the cutoff | ≤ 16 kHz on a lossless or ≥ 315 kbps file = `transcode`; 17–18 kHz = warning | strict | `ours:sourcing/verify.py:108-131`, `ours:sourcing/verify.py:433-442` |
| 9 | fake hi-res | > 48 kHz with cutoff ≤ 22 kHz | strict | `ours:sourcing/verify.py:443-444` |
| 10 | fake 24-bit: bits used per astats | > 16 claimed, ≤ 16 used | strict | `ours:sourcing/verify.py:445-447` |
| 11 | clipping (peak ≥ −0.1 dBFS, flat factor ≥ 1) | — | warning | `ours:sourcing/verify.py:448-450` |
| 12 | silence at the ends (−60 dB, 3 s) | — | warning | `ours:sourcing/verify.py:111`, `ours:sourcing/verify.py:451-457` |
| 13 | same recording as a reference copy: chromaprint raw fingerprints, best bit-error rate over ±80 items (≈ ±10 s); a copy upgrade fingerprints the whole file (≤ 900 s) | BER > 0.20 | every tier | `ours:sourcing/verify.py:139-148`, `ours:sourcing/verify.py:217-218`, `ours:sourcing/verify.py:350-384` |
| 14 | AcoustID lookup vs the known recording id | the known id is not among the returned ids | every tier | `ours:sourcing/verify.py:387-404` |

Without ffmpeg or `fpcalc` a check is skipped with a `skipped` warning
(`ours:sourcing/verify.py:316-323`, `ours:sourcing/verify.py:356-358`). Two skips are silent: without the `flac`
binary `flac -t` does not run (`ours:sourcing/verify.py:210`), and without `ACOUSTID_KEY` there is no lookup and
nothing is recorded (`ours:sourcing/cli.py:45`, `ours:sourcing/verify.py:331-332`).

**`_acoustid_check` and `acoustid.py`.** The lookup runs only when `ACOUSTID_KEY` is set (`ours:sourcing/cli.py:45`).
It POSTs fpcalc's compressed fingerprint of the first 120 s with the key in the body, spaced at 3 requests a second on
one process-wide limiter (`ours:sourcing/acoustid.py:90-98`, `ours:sourcing/acoustid.py:115-122`,
`ours:sourcing/acoustid.py:27-29`), and returns every recording of every result, best score first
(`ours:sourcing/acoustid.py:101-112`). A lookup error and "not in AcoustID" are warnings; only a returned id list that
lacks the known `recording_id` is the hard `recording` finding; with no recording id nothing can fail
(`ours:sourcing/verify.py:389-404`). `fetch` has a recording id only for a copy upgrade (the owned song's
`music_brainz_id` in Navidrome); an external row passes `None` (`ours:sourcing/fetch.py:448-455`). The answer cache
(`ours:sourcing/acoustid.py:37-87`) serves the identity backfill, not `fetch`.

**On failure.** A hard problem deletes our own download and fails the row; the verdict (problems, warnings,
measurements) is stored on the row first and shown under it in the web client (`ours:sourcing/fetch.py:460-464`,
`ours:docs/download-validation.md:68-70`). There is no quarantine folder, no per-file or per-peer block, and no
automatic retry: a later approval searches again (`ours:sourcing/fetch.py:1-7`). *unverified* (absence: `grep -rni
'quarantin\|blocklist'` over `sourcing/`, `crates/` and `scripts/` finds only the policy docstring's
"whitelist/blacklist", `ours:sourcing/policy.py:3`).

**Publish.** A verified file moves to its own `.staging/<id>-<ts>/` folder and beets imports it from there as a
singleton (`beet import -q -s -m -W`), so beets never sees slskd's folders and the library never sees an unverified
file (`ours:sourcing/fetch.py:466-468`, `ours:sourcing/filer.py:1-4`). Tags are written only after a MusicBrainz match
whose recording length agrees within 4 s (`ours:sourcing/filer.py:6-13`, `ours:sourcing/musicbrainz.py:84-95`). The
row is `verify` with the filed path from the moment beets files it, so a crash never files a second copy
(`ours:sourcing/fetch.py:469-476`). There is no album unit: one row, one file, one import. ReplayGain is not computed
(*unverified*: `grep -rni replaygain` over `sourcing/`, `crates/`, `deploy/` finds nothing).

**`docs/download-validation.md`** maps each hand check (Spek, `flac -t`, length vs MusicBrainz, first/last seconds,
bit depth) to the code and its hard/soft rule (`ours:docs/download-validation.md:36-47`), and names the limits: a
lossy encoder without a sharp cutoff can pass; the recording check needs a reference or an AcoustID key
(`ours:docs/download-validation.md:83-91`). On the 2026-10-15 library run, 22 of 831 files failed `crate`, 17 of
them lossy-sourced (`ours:docs/download-validation.md:79-81`).

**Planned.**
- **S1-02** makes AcoustID a hard finding without a recording id: a confident result (top score ≥ 0.8) none of whose
  recordings has the asked title's key is "AcoustID says this is <title>, not <asked>"
  (`ours:docs/specs/2026-10-22-downloads-and-requests.md:68-72`).
- **S2-03** matches an album request to one MusicBrainz release (track count + titles one to one; ties digital, CD,
  earliest), stores each row's `mb_recording_id`, and fetch passes it to verify, so the existing id check applies
  (`ours:docs/specs/2026-10-22-downloads-and-requests.md:112-119`).
- **S2-04/S2-05** add the album-level rules: a secondary folder must be the same release (lengths within 2 s, same
  format family), and one "not what it claims" verify finding distrusts the whole folder
  (`ours:docs/specs/2026-10-22-downloads-and-requests.md:127-129`, `ours:docs/specs/2026-10-22-downloads-and-requests.md:146-150`).
- S1-01 rejects the ext-74 candidate before download and S1-03 stops a wrong song renaming the row
  (`ours:docs/specs/2026-10-22-downloads-and-requests.md:61-67`, `ours:docs/specs/2026-10-22-downloads-and-requests.md:73-75`).

## The difference that matters

**D24, one DJ quality** (`ours:docs/specs/2026-10-17-amperfy-pivot.md:19`: lossless or lossy ≥ 256 kbps, "a re-encoded
fake is rejected"). SoulSync cannot hold D24 after the download. Its post-download quality gate reads the header,
which in a transcode says "FLAC 16/44.1" and meets the fifth of six default targets, "FLAC 16-bit", which outranks MP3 320
(`SoulSync:core/imports/file_ops.py:631-639`, `SoulSync:core/quality/schema.py:141`), and under the default
profile it never rejects at all (fallback on, `SoulSync:core/quality/schema.py:171-172`). Its only spectral test is a
report-only repair job, off by default and probably broken (above). Ours decodes every download (where ffmpeg is installed, `ours:sourcing/verify.py:316-318`) and fails a lossless
or ≥ 315 kbps claim whose spectrum stops at ≤ 16 kHz, a padded 24-bit file and fake hi-res, at every tier
(`ours:sourcing/verify.py:433-447`, `ours:deploy/policy.toml:17-18`, `ours:deploy/policy.toml:31`, `ours:deploy/policy.toml:58`); on the library run that rule caught 17 lossy-sourced
files out of 831 (`ours:docs/download-validation.md:79-81`). On D24 ours is well ahead, though not complete: the transcode rule fires only for a lossless or ≥ 315 kbps file
(`ours:sourcing/verify.py:435`), so a 256-314 kbps mp3 re-encoded from 128 kbps, which D24's floor admits, is not
flagged, and an encoder without a sharp cutoff passes (`ours:docs/download-validation.md:85-87`). SoulSync's ladder is
richer (per-playlist profiles, an upgrade policy), but D24 deliberately has one rule, so that is not a gap.

**D26, the exact track** (`ours:docs/specs/2026-10-17-amperfy-pivot.md:21`). Both stacks have the same hole today, from
opposite sides:
- SoulSync checks identity by **title string** (AcoustID titles vs the expected title) and never by recording id
  (`SoulSync:core/acoustid_verification.py:495-503`). That catches ext-74 when enabled, but it is off by default, and a
  string rule cannot tell two recordings that share a title (a live take and the studio cut) except through its
  version-label gate (03-matching.md).
- Ours checks identity by **recording id** (`ours:sourcing/verify.py:402-404`), which is exact when an id is known, but
  an external row never has one (`ours:sourcing/fetch.py:448-455`), so ext-74 passed. And because fetch read the
  wrong-titled file as "another version", it also dropped the expected length (`ours:sourcing/fetch.py:411-417`): our
  length check did not run on ext-74 at all, which the 10-21 notes do not say (read from code, not reproduced). Here it
  would not have mattered (195 vs 196 s), but for a same-folder wrong track of a different length ours checks only the
  peer's own listing (`ours:sourcing/verify.py:296-301`), which SoulSync's length check catches when the file is shorter by more than 3 s or longer by more than 15 s
  (`SoulSync:core/imports/file_integrity.py:100-116`).
- The planned pair covers both: S1-02 adds the title rule for rows without an id, S2-03 supplies ids for album rows
  (`ours:docs/specs/2026-10-22-downloads-and-requests.md:68-72`, `ours:docs/specs/2026-10-22-downloads-and-requests.md:112-119`).
  SoulSync's details worth copying into S1-02: FAIL only on a confident score (0.80, the same as ours), ERROR never
  fails, and a FAIL whose every top match has a very different length becomes SKIP
  (`SoulSync:core/matching/audio_verification.py:565-572`, `SoulSync:core/matching/acoustid_candidates.py:171-186`).

**What happens to a bad file.** SoulSync quarantines it with a sidecar, blocks that `(peer, file)` for good, and tries
the next candidate automatically, up to 5 times (`SoulSync:core/imports/guards.py:31-124`,
`SoulSync:core/downloads/monitor.py:60`). Ours deletes it and fails the row; the next approval searches again and can
pick the same peer's same file (`ours:sourcing/fetch.py:462-464`; *unverified* that nothing remembers it: no
blocklist found by grep). Under D7 the automatic retry is not ours to copy (each attempt is Michael's approval;
S1-06 allows one bounded retry on a transfer error, not a verify failure,
`ours:docs/specs/2026-10-22-downloads-and-requests.md:85-89`). Remembering the `(peer, file)` that failed verify is
cheap and fits D7: it changes what the next approval is offered, not whether it runs.

**Albums.** SoulSync's "atomic publish" is opt-in and publishes partial albums at batch end; its "album consistency"
rewrites tags after the files are live. Neither proves an album is one release
(`SoulSync:core/downloads/lifecycle.py:1183-1201`, `SoulSync:core/album_consistency.py:364-410`). Our plan is
stricter: a same-release secondary (lengths within 2 s), one "not what it claims" finding distrusts the whole folder,
and an album's identity written once, in `.staging`, before beets sees the file
(`ours:docs/specs/2026-10-22-downloads-and-requests.md:127-129`, `ours:docs/specs/2026-10-22-downloads-and-requests.md:146-150`,
`ours:docs/specs/2026-10-22-downloads-and-requests.md:171-180`). One thing SoulSync does that we don't plan: holding an
album's files out of the library until the batch ends, so Navidrome never indexes half an album
(`SoulSync:core/downloads/atomic_album_publish.py:3-9`). Ours files each verified row as it lands
(`ours:sourcing/fetch.py:466-476`).

**Safety invariants.** SoulSync hard-deletes in at least four places on this path, three of them: a redundant incoming download
(`SoulSync:core/imports/pipeline.py:1618-1647`), a replaced original (`SoulSync:core/imports/pipeline.py:1691-1702`) and
a rejected quarantine entry (`SoulSync:api/quarantine.py:163-200`), plus review-reject's delete of an imported file (`SoulSync:core/downloads/review_reject.py:1-47`), and its
cleanup empties quarantine every 12 h.
Ours deletes only its own unverified download (`ours:sourcing/fetch.py:463`), and a replaced library copy goes through
proof, repoint and trash (`ours:sourcing/fetch.py:29-35`).

## Worth taking?

- **Take (adapt): the title-based AcoustID rule** for rows without a recording id, i.e. build S1-02 as planned, plus
  SoulSync's length-contradiction escape (a FAIL whose top matches all run far from the file's length is not a FAIL)
  and its "lookup error never fails" rule, which ours already has (`ours:sourcing/verify.py:391-396`).
- **Take (adapt): remember a `(peer, file)` that failed verify** and reject it in the scorer for that row, as
  SoulSync's quarantine source block does (`SoulSync:core/soulseek_client.py:2710-2749`). Not its automatic retry (D7).
- **Take (adapt): keep the expected length when the title slot differs.** SoulSync checks the length against the
  row's whenever one is known (−3 s / +15 s by default) (`SoulSync:core/imports/file_integrity.py:551-598`); ours drops it when fetch calls the file "another
  version" (`ours:sourcing/fetch.py:411-417`). After S1-01 that path should only see real versions, but it is a
  one-line check for S1's review.
- **Consider for S2: hold an album's verified files in `.staging` until the album job ends**, then file them
  together. SoulSync's version shows the edge cases: decide once per batch, publish partials rather than strand them,
  and never overwrite on recovery (`SoulSync:core/downloads/atomic_recovery.py:18-25`,
  `SoulSync:core/downloads/atomic_recovery.py:126-193`). That needs Michael's call (would he rather see 7 of 9 tracks
  now or the album at once?), so it goes to 09's questions with the default "file as each row lands" (today's).
- **Don't take:** its quality gate and fake detection (ours is stronger); album consistency as a post-publish tag
  rewrite (S2-06 writes identity before filing, and D22 forbids full writes); quarantine as a folder emptied every
  12 h with hard deletes (our trash + `MOVES.txt` invariant); ReplayGain (loudness tagging is not verification; Mixxx
  analyses gain itself, *unverified* for Michael's setup).

**Verdict:** adapt. SoulSync's verification is weaker than ours on quality (no transcode detection after download) and
off by default on identity; the pieces worth taking are its title-based AcoustID FAIL (= S1-02), a remembered failed
`(peer, file)`, and, if Michael wants it, album-level staging before filing.
