# 07 · Filing and the library (tags, file placement, Navidrome scans and playlists, deletes)

Pinned clone `~/research/soulsync-src/SoulSync` at `34bf7cf9c741`, read only (nothing in it was executed).
Citations: `SoulSync:<path>:<line>` in that clone, `ours:<path>:<line>` in this worktree; *unverified* marks a claim
without one, and "read from code" marks a consequence derived from cited lines but not run. Music only: an audiobook
sidecar hook sits on the import path (`SoulSync:core/imports/pipeline.py:1801-1804`) and the audiobook post-processor
mentions beets (`SoulSync:core/audiobook_post_processor.py:415`); both are named here once and skipped. The import
checks themselves (integrity, quality, AcoustID, quarantine) are in 06-verification.md; this file starts where a
file has passed them.

## What SoulSync does

```
 transfer Completed ─► run_post_processing_worker ─► post_process_matched_download_with_verification
 (monitor, 04/06)  downloads/post_processing.py:158       pipeline.py:1900 (wrapper: retry/fail/complete)
                                                              │
 auto_import_worker  ── separate watcher of import.staging_path (auto_import.enabled = False) ──┐
 (no verification wrapper; calls the inner pipeline directly, emits batch_complete itself)       │
                                                              ▼                                  ▼
                       core/imports/pipeline.py: post_process_matched_download (pipeline.py:762)
                         checks (06) ─► build_final_path_for_track (paths.py:1079)
                            root = soulseek.transfer_path ("./Transfer", settings.py:539)
                            template = file_organization.templates.album_path / single_path / compilation_path
                                       (settings.py:915-919; "$albumartist/$albumartist - $album/$track - $title")
                         ─► TAGS: enhance_file_metadata on the downloaded file, clear-all then rewrite (pipeline.py:1514)
                         ─► collision: existing tagged file → delete the incoming; else (or upgrade) overwrite (1620-1647)
                         ─► safe_move_file: os.replace (file_ops.py:208), copy+fsync+replace across devices
                         ─► old copy of a replaced/upgraded track: os.remove (pipeline.py:1691-1735)
                         ─► [ReplayGain, opt-in] ─► DB rows
                                                              │
 batch end ─► batch_complete (lifecycle.py:817-830) ─► automation "Auto-Scan After Downloads" (automation_engine.py:140-145)
   ─► WebScanManager.request_scan: 60 s debounce (web_server.py:1284) ─► Subsonic startScan (navidrome_client.py:1905-1916)
   ─► poll getScanStatus every 30 s, "done" only after ≥ 300 s and scanning=false, cap 1800 s (web_scan_manager.py:268-324)
   ─► library_scan_completed ─► database update ─► sync_downloaded_playlists (automation_engine.py:146-157)
```

Two corrections to the feature's expected order: **tags are written before the move**, on the downloaded file
(`SoulSync:core/imports/pipeline.py:1514` runs before `SoulSync:core/imports/pipeline.py:1686`), and
`core/auto_import_worker.py` is **not on the download path**. It is a separate watcher of an import folder, off by
default (`SoulSync:core/auto_import_worker.py:1-9`, `SoulSync:api/import_routes.py:352-364`), that hands each identified
file to the inner pipeline and skips the verification wrapper (`SoulSync:web_server.py:15509-15519`,
`SoulSync:core/auto_import_worker.py:2370`). "Simple downloads" are the exception to the template: they move first, to
`<transfer>/<remote album folder>/<original filename>`, and only fill missing tags afterwards
(`SoulSync:core/imports/pipeline.py:1164-1190`, `SoulSync:core/imports/paths.py:339-369`).

### Does it use beets?

No. beets is not a dependency, is never imported and is never run: the only tag library in `requirements.txt` is
`mutagen==1.47.0` (`SoulSync:requirements.txt:21`), and `grep -i beet` over `requirements.txt`, `Dockerfile` and
`pyproject.toml` finds nothing. SoulSync is its own tagger and organiser. Every `beets` hit in `core/` is one of:
- **a convention it copies**: the `$atypes` path variable imitates the beets `albumtypes` plugin so that a user "can
  copy the types/bracket/ignore_va block straight out of their beets config"
  (`SoulSync:core/imports/album_types.py:1-21`, `SoulSync:core/settings.py:933-939`), it emits nothing for a plain
  album so a beets-organised library keeps one layout (`SoulSync:core/imports/paths.py:1222-1223`), and an opt-in
  "original date as DATE" option copies beets' `original_date` (`SoulSync:core/settings.py:825-830`, default off);
- **reading tags beets or Picard wrote**: ISRC (`SoulSync:core/auto_import_worker.py:178-180`), per-recording ids
  (`SoulSync:core/imports/album_matching.py:331`), a multi-valued RELEASETYPE
  (`SoulSync:core/library/reorganize_tag_source.py:134-139`), the MusicBrainz album comment
  (`SoulSync:core/library/release_identity.py:3-6`, `SoulSync:core/library_reorganize.py:1336-1338`);
- **a comment**: the duration tolerance borrows "Picard ~7s, Beets ~10-15s" (`SoulSync:core/imports/album_matching.py:454`),
  `ignore_va` (`SoulSync:core/imports/compilation.py:107-108`), "Matches Picard / Beets convention"
  (`SoulSync:core/metadata/source.py:2070`), the original-date option (`SoulSync:core/metadata/source.py:1201-1206`).

So adopting SoulSync's filing would mean replacing beets, not putting it next to beets (D18's "one beets writer" has
no counterpart).

### What it writes into tags, and when

**How it saves.** Every writer uses mutagen (`SoulSync:core/tag_writer.py:12-17`, `SoulSync:core/metadata/common.py:56`).
ID3 is saved as v2.4 with v1 removed, and FLAC with `deleteid3=True` (`SoulSync:core/metadata/common.py:149-158`). The
shared `save_audio_file` writes into a `<path>.<pid>.<tid>.<uuid8>.sstmp` copy in the same folder, re-parses it, checks
that the audio is unchanged (FLAC: byte-compares the audio frames; other formats: rate, channels, depth, samples,
duration within max(0.25 s, 2 %)), then calls `os.replace` (`SoulSync:core/metadata/common.py:278-377`,
`SoulSync:core/metadata/common.py:188-252`, `SoulSync:core/metadata/common.py:337`). A failed audio check aborts and
leaves the original alone (`SoulSync:core/metadata/common.py:339-349`), and so does a tag-encoding error
(`SoulSync:core/metadata/common.py:366-370`); a copy, permission or replace failure falls back to a plain in-place
save (`SoulSync:core/metadata/common.py:372-377`). Several
writers bypass it and save in place: the verification-status tag (`SoulSync:core/tag_writer.py:199`), lyrics
(`SoulSync:core/lyrics_client.py:180-208`), the cover-art filler (`SoulSync:core/metadata/art_apply.py:185`), the
"full" library re-tag (`SoulSync:core/repair_jobs/library_retag.py:150`) and MBID-mismatch removal
(`SoulSync:core/repair_jobs/mbid_mismatch_detector.py:172`).

**1. On import, before the move: clear everything, then rewrite** (`enhance_file_metadata`,
`SoulSync:core/metadata/enrichment.py`). Master switch `metadata_enhancement.enabled`, default True
(`SoulSync:core/settings.py:794-795`, `SoulSync:core/metadata/enrichment.py:72-74`). The sequence: strip APEv2 (MP3),
snapshot the embedded art in memory, `clear_pictures()`, **`tags.clear()` and save the file with no tags**
(`SoulSync:core/metadata/enrichment.py:90-114`), then write from the matched source metadata:
- core frames (`SoulSync:core/metadata/enrichment.py:157-235`): ID3 `TIT2 TPE1 TXXX:Artists TPE2 TXXX:Album Artists
  TALB TDRC TCON TRCK TPOS`; Vorbis `title artist artists albumartist albumartists album date genre tracknumber
  tracktotal totaltracks discnumber`; MP4 `©nam ©ART aART ©alb ©day ©gen trkn disk`. Multi-valued artists follow
  `metadata_enhancement.tags.write_multi_artist` (True in the fresh-install template, False when the key is missing:
  `SoulSync:core/settings.py:812-819`, `SoulSync:core/metadata/enrichment.py:147`);
- MusicBrainz ids with Picard's frame names (`SoulSync:core/metadata/source.py:173-215`,
  `SoulSync:core/metadata/musicbrainz_tags.py:175-204`): recording id as ID3 `UFID:http://musicbrainz.org` / Vorbis
  `MUSICBRAINZ_TRACKID`, plus artist, release (album), release-group, album-artist and release-track ids, album/track
  comment, release type/status/country, `ORIGINALDATE` (`TDOR`), `MEDIA`, `LABEL` (`TPUB`), `ISRC` (`TSRC`), and the
  release-level set BARCODE, ASIN, CATALOGNUMBER, TOTALDISCS, SCRIPT (`SoulSync:core/metadata/musicbrainz_tags.py:139-172`).
  The recording lookup uses title, artist, artist MBID, file duration and the file's ISRC
  (`SoulSync:core/metadata/source.py:396-450`);
- streaming-source ids as `TXXX`/plain keys (Spotify, iTunes, Deezer, Tidal, Qobuz, HiFi, JioSaavn, AudioDB, Genius,
  Beatport), each with its own toggle, default on (`SoulSync:core/metadata/source.py:124-168`,
  `SoulSync:core/metadata/source.py:218-219`; Beatport's id at `SoulSync:core/metadata/source.py:1433-1434`);
- BPM (`TBPM`), key (`TKEY`, Beatport), AudioDB mood/style, a merged genre list of at most 5, copyright, label, and
  Last.fm/Genius/Bandcamp URLs; the first source with a value wins (`SoulSync:core/metadata/source.py:1248-1440`). The
  lookup order is `metadata_enhancement.post_process_order` (`SoulSync:core/settings.py:797`);
- cover art `APIC`/FLAC `Picture`/`covr` when `metadata_enhancement.embed_album_art` is on (default True), no picture
  branch for OGG/Opus (`SoulSync:core/metadata/artwork.py:656-670`, `SoulSync:core/settings.py:796`); a `QUALITY` tag
  (`SoulSync:core/metadata/enrichment.py:254-261`); on success `SOULSYNC_VERIFICATION`
  (`SoulSync:core/imports/pipeline.py:587-603`, `SoulSync:core/tag_writer.py:173-203`).
- Not written: no AcoustID id or fingerprint tag (*absence inferred*: grep for `ACOUSTID_ID`/`Acoustid Id` writers
  outside tests finds none), and no version/edition field of its own (*absence inferred*: `grep -rnE "TIT3|SUBTITLE"
  --include=*.py` outside `tests/` finds no tag writer); the nearest is MusicBrainz's disambiguation, written as the
  album/track comment above (`SoulSync:core/metadata/musicbrainz_tags.py:144-147`, `SoulSync:core/metadata/source.py:617-621`).

If no source metadata is found, the file is saved **with its tags cleared** (art restored) and the import carries on
(`SoulSync:core/metadata/enrichment.py:116-123`). On an exception, `core_tag_guard.ensure_core_tags` refills only
missing title/artist/album/track/disc from the import context; it is a fallback filler, not a write guard
(`SoulSync:core/metadata/enrichment.py:309-311`, `SoulSync:core/metadata/core_tag_guard.py:1-8`). If enhancement
raises, the pipeline wipes all tags when the import had no matched metadata, else keeps them and strips only the
MusicBrainz album ids (`SoulSync:core/imports/tag_policy.py:11-23`, `SoulSync:core/imports/pipeline.py:1522-1535`).

**2. After an album batch: album consistency** picks one MusicBrainz release and overwrites the album-level ids
(release, release group, album artist, type, status, country, original date, barcode, media, catalogue number …) on
every file of the batch (`SoulSync:core/album_consistency.py:1-3`, `SoulSync:core/album_consistency.py:25-41`,
`SoulSync:core/album_consistency.py:703-733`), triggered for batches of ≥ 2 files with `musicbrainz.embed_tags` on
(`SoulSync:core/downloads/lifecycle.py:945-965`). Files already in the library are never opened for writing: new files
adopt their siblings' tags instead (`SoulSync:core/album_consistency.py:43-45`, `SoulSync:core/album_consistency.py:580-585`). (06 judges this as a check.)

**3. Later, from the library UI or repair jobs: field by field, no clear** (`write_tags_to_file`,
`SoulSync:core/tag_writer.py:400-555`). It replaces each frame from database values and adds known source ids without
re-fetching (`SoulSync:core/tag_writer.py:511-525`), with three guards: never overwrite a real value with "Various
Artists"/"Unknown"/empty (#800, `SoulSync:core/tag_writer.py:157-170`), never narrow a richer genre list
(`SoulSync:core/tag_writer.py:206-221`), keep date precision (#824, `SoulSync:core/tag_writer.py:591-608`). A preview
diff exists (`build_tag_diff`, `SoulSync:core/tag_writer.py:262-361`). Callers: `POST /api/library/track/<id>/write-tags`
and the batch route (`SoulSync:web_server.py:9809`, `SoulSync:web_server.py:9896`), the Library Re-tag job (off by
default, `dry_run: True`, `SoulSync:core/repair_jobs/library_retag.py:366-384`), and repair fixes, one of which
rewrites title and artist from an AcoustID result (`SoulSync:core/repair_worker.py:4845-4864`).

**Enrichment** (`core/enrichment/`, `core/*_worker.py`) writes the database only; ids reach files later, through
"Write Tags" or re-tag (`SoulSync:core/enrichment/services.py:1-14`, `SoulSync:core/musicbrainz_worker.py:352`).
**ReplayGain** after the move is opt-in, `post_processing.replaygain_enabled` default False
(`SoulSync:core/imports/pipeline.py:1740-1749`).

**Undo.** None. The atomic save protects the audio, not the old tags: the `.sstmp` is the *new* file
(`SoulSync:core/metadata/common.py:314-349`); only the cover art is held, in memory, for one call
(`SoulSync:core/metadata/art_preservation.py:57-83`); old text tags are cleared and saved with no copy
(`SoulSync:core/metadata/enrichment.py:110-114`). The re-tag findings record old→new for review but cannot reverse
(`SoulSync:core/repair_jobs/library_retag.py:1-11`); the repair "undo" endpoint only reopens a dismissed finding
(`SoulSync:api/repair.py:294`).

### How it triggers and awaits Navidrome scans

- **Trigger:** Subsonic `startScan` with no parameters (no `fullScan`), sent as POST
  (`SoulSync:core/navidrome_client.py:1905-1916`, `SoulSync:core/navidrome_client.py:476-483`). It does not ask
  `getScanStatus` first. Auth is Subsonic token + salt (md5, a fresh random salt per request) from `navidrome.base_url`,
  `navidrome.username`, `navidrome.password` (encrypted at rest) (`SoulSync:core/navidrome_client.py:380-413`,
  `SoulSync:core/settings.py:529-534`, `SoulSync:core/settings.py:91-107`). A native JWT from `/auth/login` is used only
  for the playlist cover upload (`SoulSync:core/navidrome_client.py:1328-1352`). It never opens Navidrome's database
  (*absence inferred*: no `navidrome.db` or `media_file` reference outside SoulSync's own video tables).
- **Who and when:** once per download run. `batch_complete` fires at batch end and is held back while other batches
  are pending, so the last batch scans for all (#1615, `SoulSync:core/downloads/lifecycle.py:812-832`,
  `SoulSync:core/automation/handlers/scan_library.py:53-56`); the seeded "Auto-Scan After Downloads" automation turns
  it into `request_scan` (`SoulSync:core/automation_engine.py:140-145`). A single simple download outside a batch
  requests one directly, but only while that same automation is on (`SoulSync:core/imports/pipeline.py:1209-1222`);
  the UI has `POST /api/scan/request` (`SoulSync:web_server.py:8341-8365`).
- **Debounce and wait** (`WebScanManager`, one per process, `SoulSync:web_server.py:1284`): every request restarts a
  60 s timer (`SoulSync:core/web_scan_manager.py:71-124`); a request during SoulSync's own scan becomes **one**
  follow-up scan (`SoulSync:core/web_scan_manager.py:97-105`, `SoulSync:core/web_scan_manager.py:353-355`). It then polls
  every 30 s and declares the scan done only when ≥ 300 s have passed **and** `getScanStatus` says not scanning; after
  1800 s it gives up "assuming complete" (`SoulSync:core/web_scan_manager.py:43`, `SoulSync:core/web_scan_manager.py:268-324`).
  Read from code: Navidrome's `is_library_scanning` returns False on any error (`SoulSync:core/navidrome_client.py:1918-1928`),
  so an unreachable Navidrome at the 5-minute mark reads as "done"; and a scan is never "done" in under 5 minutes, however small.
- **Scan, wait, then act:** completion emits `library_scan_completed` → database update → `sync_downloaded_playlists`
  (`SoulSync:core/automation_engine.py:146-157`, `SoulSync:core/automation/handlers/progress_callbacks.py:64-89`), and a
  playlist write that adds new or stale ids waits up to 180 s for `scanning=false`, else refuses
  (`SoulSync:core/library/navidrome_identity.py:22-40`, `SoulSync:core/library/navidrome_identity.py:317-320`).
- **Media-server layer** (`core/media_server/`): a capability lookup, not a dispatcher. `SCAN_TRIGGER` maps to
  `trigger_library_scan`/`is_library_scanning` (`SoulSync:core/media_server/contract.py:92-130`); servers are plex,
  jellyfin, navidrome and SoulSync's own standalone library (`SoulSync:core/media_server/registry.py:142-160`); callers
  reach the active client directly (`SoulSync:core/media_server/engine.py:1-32`). Navidrome's `post_scan` hook merges
  re-keyed same-path rows in SoulSync's own DB (`SoulSync:core/navidrome_client.py:127-142`,
  `SoulSync:core/library/navidrome_identity.py:193-267`).

### How it edits Navidrome playlists, and with what guards

**Where.** The server writes are in `core/navidrome_client.py` and their planners in `core/sync/playlist_edit.py`.
`core/playlists/` makes no Navidrome calls of its own (*absence inferred*: no `_make_request` there): it holds the mirrored-playlist lifecycle (refresh → discover →
sync to server → wishlist, `SoulSync:core/playlists/pipeline.py:1-7`), the server-side naming rule for colliding mirrors
(`SoulSync:core/playlists/sync_names.py:1-18`), playlist-as-folder materialising (`SoulSync:core/playlists/materialize.py:1-8`)
and the per-service source adapters (`SoulSync:core/playlists/sources/base.py:1-20`).

**Calls** (`core/navidrome_client.py`): `createPlaylist` with `name` + repeated `songId`, and with `playlistId` to
**overwrite the whole list in place** (`SoulSync:core/navidrome_client.py:1365-1431`); `updatePlaylist` with
`songIdToAdd` + `songIndexToRemove` (`SoulSync:core/navidrome_client.py:1761-1826`); `deletePlaylist`
(`SoulSync:core/navidrome_client.py:1293-1300`); cover via native `POST /api/playlist/{id}/image`
(`SoulSync:core/navidrome_client.py:1302-1363`). Mode is `playlist_sync.mode`, default `reconcile` on Docker (its seeded config.json has no `mode` key, so the callers' `reconcile` fallback applies, `SoulSync:config/config.example.json:85-87`, `SoulSync:entrypoint.sh:58-60`; a non-Docker install saves the defaults dict and runs `replace`, `SoulSync:core/settings.py:849`, `SoulSync:core/settings.py:1193-1199`), per mirror
overridable (`SoulSync:core/sync/playlist_edit.py:234-260`):
- **reconcile (default):** read the playlist (`getPlaylist`), plan, then one `updatePlaylist` that adds the wanted ids
  that are absent and removes, by index into the list just read, every entry whose id is no longer wanted
  (`SoulSync:core/navidrome_client.py:1786-1815`, `SoulSync:core/sync/playlist_edit.py:74-109`). So **a track the user
  added by hand is removed**, and every copy of an unwanted id goes (`SoulSync:core/navidrome_client.py:1810-1814`).
- **append:** adds only, except it drops a "superseded wrong match" (same title, no shared artist, right id present)
  (`SoulSync:core/navidrome_client.py:1644-1759`, `SoulSync:core/sync/playlist_edit.py:155-201`).
- **replace:** optional "<name> Backup" copy (`playlist_sync.create_backup`, off), then **deletes every other playlist
  of the same name** owned by the account and overwrites the first (`SoulSync:core/navidrome_client.py:1828-1903`,
  `SoulSync:core/navidrome_client.py:1879-1890`).
- UI single-track add/remove reads the ids, edits one occurrence and rewrites the **whole list** through
  `createPlaylist`+`playlistId` (`SoulSync:web_server.py:18873-18884`, `SoulSync:web_server.py:18967-18978`,
  `SoulSync:core/sync/playlist_edit.py:28-71`).

**Which playlists:** found by case-insensitive **name**, limited to `owner` = the configured user (an owner of None
passes) (`SoulSync:core/navidrome_client.py:1537`, `SoulSync:core/navidrome_client.py:1216-1233`). No prefix or "made by SoulSync" marker, so a hand-made playlist
with a mirror's name is adopted and rewritten (read from code). A mirror remembers its `server_playlist_id` and
follows it after an existence check, falling back to the name (`SoulSync:core/sync/mirrored_server_link.py:57-176`).
Per-profile users write as themselves (`SoulSync:core/navidrome_client.py:2062-2112`). The admin profile may edit or
delete any playlist the account sees, "SoulSync-made or not" (`SoulSync:web_server.py:18068-18085`,
`SoulSync:web_server.py:18986-18993`).

**Guards** (`@validated_playlist_write`, `SoulSync:core/library/navidrome_identity.py:270-375`), stronger than most
tools:
- refuses an empty write, except creating an empty playlist (`SoulSync:core/library/navidrome_identity.py:295-303`);
- **reads before writing** and refuses an unreadable playlist (`SoulSync:core/library/navidrome_identity.py:304-314`);
- proves each wanted id exists, by the current list or a full `search3` inventory read that refuses if the scan count
  moved during the read (`SoulSync:core/library/navidrome_identity.py:43-72`, `SoulSync:core/library/navidrome_identity.py:315-320`);
  a dead id is remapped to a re-keyed live song (same path or same artist/album/file tail and title, duration ±5 s), else
  marked skipped or ambiguous (`SoulSync:core/library/navidrome_identity.py:144-190`);
- refuses a non-append write that would drop an existing entry while any id is unresolved
  (`SoulSync:core/library/navidrome_identity.py:330-336`);
- **re-reads after writing** and fails unless the *set* of ids equals the expected set
  (`SoulSync:core/library/navidrome_identity.py:357-367`). Read from code: a set compares neither order nor duplicate
  count, and a failed check is reported, not rolled back.
- No compare-and-swap: the inner methods re-read just before `updatePlaylist` (`SoulSync:core/navidrome_client.py:1786`),
  and the lock is in-process only (`SoulSync:services/sync_service.py:22-39`). Zero matches never empties an existing
  playlist (`SoulSync:services/sync_service.py:844-889`), and a failed Navidrome reconcile does not fall back to replace
  (`SoulSync:services/sync_service.py:560-566`). No dry run for sync writes: `get_sync_preview` has no non-test caller
  (`SoulSync:services/sync_service.py:1668-1710`; caller *absence inferred* by grep).
- Hidden (missing) entries: the guard sees only what `getPlaylist` returns, and SoulSync never reads Navidrome's
  `playlist_tracks`, so a hidden row that shifts `songIndexToRemove` is not accounted for: the indexes are positions
  in the `getPlaylist` list (`SoulSync:core/navidrome_client.py:1514`, `SoulSync:core/navidrome_client.py:1786-1791`,
  `SoulSync:core/navidrome_client.py:1807-1814`) (*unverified* end to end: depends on Navidrome hiding missing rows,
  which ours measured on 0.64.2, `ours:crates/playlist_edit.py:3-6`; would be verified by a SoulSync reconcile against a
  Navidrome playlist that holds a missing file).

**Mapping tracks to Navidrome songs:** a fuzzy title/artist(/album) match against SoulSync's **own** library DB at 0.7,
after a confirmed-match cache (`SoulSync:services/sync_service.py:1346-1370`, `SoulSync:services/sync_service.py:1489-1529`);
the DB row id is the Navidrome song id (`SoulSync:services/sync_service.py:1529-1545`). No match goes to the wishlist
(`SoulSync:services/sync_service.py:1187-1190`).

### What it deletes or moves, and whether there is a reverse log

**On import** (all hard deletes, no bin): the incoming download when a tagged file already holds the target path
(`SoulSync:core/imports/pipeline.py:1620-1636`); the target itself is **overwritten** by `os.replace` when the existing
file has ≤ 2 tags, when its tags cannot be read ("proceeding with overwrite"), on a verified quality upgrade, on an
enhance and on a forced re-download (`SoulSync:core/imports/pipeline.py:1621-1647`, `SoulSync:core/imports/file_ops.py:208`);
there is no `.1` suffixing. The superseded original after a quality upgrade or enhance (`SoulSync:core/imports/pipeline.py:1691-1735`)
and after a redownload, `delete_old_file` default True (`SoulSync:core/library/redownload.py:101`,
`SoulSync:core/imports/pipeline.py:2224-2237`). A replacement shorter than 0.8× the existing length is quarantined
instead (`SoulSync:core/imports/pipeline.py:123-135`, `SoulSync:core/imports/pipeline.py:1593-1599`). After the move it unlinks slskd's `<stem>_<18+ digits>` dedup
siblings (`SoulSync:core/imports/file_ops.py:30-93`).

**Reorganize** (`core/library_reorganize.py`, `reorganize_queue.py`, `reorganize_runner.py`): re-runs an album's files
through the import pipeline to match the template. It has a real preview (`SoulSync:core/library_reorganize.py:1576-1595`)
and the repair job defaults to off, `dry_run=True` (`SoulSync:core/repair_jobs/library_reorganize.py:84-90`). A live run
copies each file into `ssync_staging/`, re-tags and moves it, updates `tracks.file_path`, then **`os.remove`s the
original and its sidecars** (`SoulSync:core/library_reorganize.py:1971-2044`, `SoulSync:core/reorganize_runner.py:137-156`,
`SoulSync:core/library_reorganize.py:2119-2124`), and prunes empty folders (`SoulSync:core/library_reorganize.py:2491`).
No old→new log (*absence inferred*: grep for undo/revert/rollback/history/jsonl over the four files finds only the
rename-only mode's in-run move-back, `SoulSync:core/library_reorganize.py:2673-2689`, and an in-memory list of 30,
`SoulSync:core/reorganize_queue.py:46-47`), and no scan request. Read from code, not run: reorganize never checks the
pipeline's "kept existing library file" flag, so when another file already holds a track's target path the original
may be deleted and the row pointed at the other file: the pipeline sets `_final_processed_path` to the target before
its existing-file check (`SoulSync:core/imports/pipeline.py:1501`), that check drops the incoming copy, sets the flag and
returns, leaving that path on the target, when the target has tags and the run is not enhance/force
(`SoulSync:core/imports/pipeline.py:1618-1638`),
and reorganize accepts any existing `_final_processed_path` (`SoulSync:core/library_reorganize.py:2036-2043`), repoints
the row and removes the original (`SoulSync:core/library_reorganize.py:2088-2090`,
`SoulSync:core/library_reorganize.py:2119-2120`).

**Repair jobs** (`core/repair_worker.py`, `core/repair_jobs/`), master switch `repair.master_enabled` default True
(`SoulSync:core/repair_worker.py:492`). Two helpers: `_delete_file_if_present` (hard `os.remove`,
`SoulSync:core/repair_worker.py:315-332`) and `_quarantine_file_if_present` (move into the recycle bin,
`SoulSync:core/repair_worker.py:349-390`). Only duplicate removal (`SoulSync:core/repair_worker.py:4064-4250`) and
corrupt audio (`SoulSync:core/repair_worker.py:3133`) use the bin. Hard deletes: quality-upgrade "delete"
(`SoulSync:core/repair_worker.py:2830-2842`), short previews (`SoulSync:core/repair_worker.py:3037`), fake lossless
(`SoulSync:core/repair_worker.py:3180`), AcoustID mismatch delete and redownload (`SoulSync:core/repair_worker.py:4639`,
`SoulSync:core/repair_worker.py:4706`), single/album dedup (`SoulSync:core/repair_worker.py:4303-4361`), live-commentary
cleanup (`SoulSync:core/repair_worker.py:4377-4413`), the original after a missing-lossy-copy conversion
(`SoulSync:core/repair_worker.py:6132`), orphan files (`SoulSync:core/repair_worker.py:3367`) and the
expired-download cleaner (off, dry run by default, `SoulSync:core/repair_jobs/expired_download_cleaner.py:137-169`).
Moves and renames: AcoustID relocate (`SoulSync:core/repair_worker.py:4726-4765`), unknown-artist fixer
(`SoulSync:core/repair_jobs/unknown_artist_fixer.py:569-588`), track-number repair (default on, `dry_run` True,
`SoulSync:core/repair_jobs/track_number_repair.py:68-75`), release-year folder rename
(`SoulSync:core/repair_jobs/album_release_year_repair.py:337`). Fixes act on the stored finding
(`SoulSync:core/repair_worker.py:2099-2109`).

**The recycle bin** (`api/deleted_files.py`, `core/library/deleted_quarantine.py`): `<transfer>/.deleted/<relpath>`
with a `.soulsync_deleted.json` manifest of `{original, deleted_at, source}`, written best-effort **after** the move
(`SoulSync:core/repair_jobs/base.py:19-40`, `SoulSync:core/library/deleted_quarantine.py:8-20`,
`SoulSync:core/library/deleted_quarantine.py:105-121`). Restore moves a file back and never overwrites
(`SoulSync:core/library/deleted_quarantine.py:190-223`), but the `tracks` row the duplicate fix deleted
(`SoulSync:core/repair_worker.py:4231`) is not restored (read from code). API: list, restore, purge (ids or all),
retention (`SoulSync:api/deleted_files.py:44-100`). Retention `library.deleted_keep_days` defaults to 0 = keep forever
(`SoulSync:core/library/deleted_quarantine.py:15-20`), yet the off-by-default "Weekly Cleanup" automation **empties the
whole bin when it is 0** and removes all of `ss_quarantine` (`SoulSync:core/library/cleanup.py:34-78`,
`SoulSync:core/automation_engine.py:230-235`). The filesystem duplicate cleaner also bins, with no dry run and no DB
update (`SoulSync:core/library/duplicate_cleaner.py:196-211`). `core/maintenance/dedupe_source_ids.py` changes the DB
only, `dry_run=True` by default (`SoulSync:core/maintenance/dedupe_source_ids.py:24-32`).

**Scale:** `grep -rEn 'os\.remove\(|os\.unlink\(|shutil\.rmtree\(|shutil\.move\(|send2trash|\.unlink\(' --include=*.py core api`,
excluding video/audiobook/podcast paths, gives 164 lines: `os.remove` 73, `.unlink(` 51, `shutil.move` 28,
`os.unlink` 9, `shutil.rmtree` 9, send2trash 0 (counted by the fact agent, 2026-10-22; not re-counted).

**Playlists before a delete.** Server playlist membership (`core/library/playlist_membership.py`, cached 300 s,
empty on failure, `SoulSync:core/library/playlist_membership.py:25-98`) is a **preference, not a block**: duplicate
"keep best" ranks a playlisted copy first (`SoulSync:core/library/duplicate_keep.py:36-62`), so when two copies are
both in playlists one is still binned, with no playlist repoint, and a user-picked keeper skips the check
(`SoulSync:core/repair_worker.py:4071-4091`). The expired-download cleaner keeps tracks still in an active SoulSync mirror or by a watched artist
(`SoulSync:core/library/expired_cleanup.py:9-18`), and "curated" ones, including a synced server "in playlist" signal
(`SoulSync:core/library/expired_cleanup.py:150`). Nothing else checks: *absence inferred* from `grep -n -i playlist`
over the reorganize files, duplicate cleaner, recycle bin, cleanup and quality replace (no hits) and
`core/repair_worker.py` (only 274-277, 1047, 4082-4088).

## How ours does it

**Filing (D18, one beets writer).** D18 puts approved downloads in a worker container with beets 1.6
(`ours:docs/specs/2026-10-13-next-session-design.md:72`); a filer exists only with `DJ_WORKER=1`
(`ours:sourcing/cli.py:35-39`), and `deploy/beets.yaml` says the worker is the only process that runs beets and forbids
`beet write`/`modify`/`import -L` on the library (`ours:deploy/beets.yaml:1-13`). D36 extends "one writer" to the
cleanup's trash step (`ours:docs/specs/2026-10-17-amperfy-pivot.md:31`). Fetch moves the verified file into a fresh
`.staging/<id>-<ts>/` (`ours:sourcing/fetch.py:466-469`), fills only *empty* artist/title from the wanted row
(`ours:sourcing/filer.py:62-77`), and runs `beet import -q -s -m -W -l <log>` (`ours:sourcing/filer.py:135`): singleton,
move, no write. It refuses a folder outside `.staging` (`ours:sourcing/filer.py:127-128`), takes exactly one audio file
(`ours:sourcing/filer.py:129-131`), and calls it "matched" when the per-call log has no `asis` line
(`ours:sourcing/filer.py:145-146`). The row moves to `verify` with its path the moment beets has filed it, so a kill never
files a second copy (`ours:sourcing/fetch.py:470-476`).

**Tags (D22, D29).** D29: full tags only on a fresh download with a confident MusicBrainz match
(`ours:docs/specs/2026-10-17-amperfy-pivot.md:24`). "Confident" is the MB recording length within ±4 s of the file's
(`ours:sourcing/musicbrainz.py:84-95`); then `beet write path:<that file>` writes beets' full field set to that one file
(`ours:sourcing/filer.py:150-166`), and an as-is import stays byte-identical (`ours:sourcing/filer.py:7-13`). D22 puts the
version label in the display title and `VERSION`/`TIT3` (`ours:docs/specs/2026-10-13-next-session-design.md:76`); in
code the label lives in the title and `VERSION`/`TIT3` is only read (`ours:sourcing/identity.py:11-14`,
`ours:scripts/identity_backfill.py:165-179`). Every other tag write is `write_minimal`, field by field
(`ours:scripts/tag_cleanup.py:73-88`, `ours:docs/hard-won-facts.md:35`), and the identity backfill logs a line before
each write and has a `revert` (`ours:scripts/identity_backfill.py:651-652`).

**Placement.** `singleton: $artist/Singles/$title`; albums use `$albumartist/$album ($year)/$track - $title`
(`ours:deploy/beets.yaml:31-35`). With `-s`, every download today files as `$artist/Singles/$title`
(`ours:tests/test_filer.py:86-92`). A name collision keeps both, as `Title.1.ext` (`duplicate_action: keep`,
`ours:deploy/beets.yaml:27`, `ours:tests/test_filer.py:102-115`). The **album-path decision (S2-06)**: album-request
tracks will file to `$albumartist/$album ($year)/$track - $title`, still as singletons, marked by a beets `--set` flag
and a query-keyed path, with the request's album identity written by `write_minimal` on the `.staging` file before
beets sees it (`ours:docs/specs/2026-10-22-downloads-and-requests.md:166-182`). Not built yet: no `dj_album`/`--set` in
`deploy/` or `sourcing/` (grep, 2026-10-22).

**Scans.** Subsonic `startScan`/`getScanStatus` (`ours:subsonic/client.py:174-178`). `scan_and_wait` waits until
`scanning` is false **and** `lastScan` changed (`ours:subsonic/client.py:252-267`); fetch polls `scanning` every 1 s for
up to 120 s and then finds the song by `search3` plus file size (`ours:sourcing/fetch.py:205-215`); the cleanup waits out
a running scan first (`ours:scripts/duplicate_cleanup.py:345-353`). Facts: the Subsonic `path` is virtual, real paths
are only in navidrome.db (`ours:docs/hard-won-facts.md:22`); a retag *and* move between two scans gives a new song id
(`ours:docs/hard-won-facts.md:23-24`); Navidrome lists a trashed song until the next scan
(`ours:docs/hard-won-facts.md:65-66`).

**Playlists (the guarded index edit, D44).** `crates/playlist_edit.py` is the only code that edits membership by index
(`ours:crates/playlist_edit.py:1`), because Navidrome 0.64.2 hides missing entries in `getPlaylist` while
`songIndexToRemove` still counts them (`ours:crates/playlist_edit.py:3-6`, `ours:docs/hard-won-facts.md:27-28`). Before a
write it reads the API *and* navidrome.db and refuses another owner's playlist, a smart playlist, gapped positions, any
hidden or missing row, or API ≠ db (`ours:crates/playlist_edit.py:54-82`). `rewrite(before, after)` refuses unless the
current list equals the caller's `before`, sends one `updatePlaylist`, and re-reads to confirm `after` exactly, in
order (`ours:crates/playlist_edit.py:116-141`). D44 places a filed track at its Spotify position, insert-only, never
moving an existing entry, in imported playlists only (`ours:docs/specs/2026-10-17-amperfy-pivot.md:39`,
`ours:crates/placement.py:83-115`). Navidrome's own playlist import is off on purpose (`ours:docs/hard-won-facts.md:24-26`).

**Deletes (trash, MOVES.txt).** `/srv/_trash/<day>/<relpath>`, never emptied by code
(`ours:crates/trash.py:1-6`); `move_to_trash` appends the reverse `mv` to `MOVES.txt` **before** the move and records a
failed move (`ours:crates/trash.py:116-152`); `restore` never overwrites (`ours:crates/trash.py:155-168`). The duplicate
cleanup is plan → repoint → scan → trash (`ours:scripts/duplicate_cleanup.py:1-59`). The four safety invariants are
`ours:CLAUDE.md:11-12`:
1. never trash while a playlist holds the file: `references()` counts hidden rows
   (`ours:crates/playlist_edit.py:97-102`), checked per file right before the move and again after
   (`ours:scripts/duplicate_cleanup.py:586-588`, `ours:scripts/duplicate_cleanup.py:614-629`), test
   `ours:tests/test_duplicate_cleanup.py:65`;
2. scan between repoint and trash: `_scanned_since_repoint` (`ours:scripts/duplicate_cleanup.py:423-437`), test
   `ours:tests/test_duplicate_cleanup.py:1192`;
3. recompute groups right before acting: `_recheck` against live navidrome.db (`ours:scripts/duplicate_cleanup.py:230-239`),
   test `ours:tests/test_duplicate_cleanup.py:386`;
4. a logged reverse for every destructive step: the repoint line before each write
   (`ours:scripts/duplicate_cleanup.py:272-293`), MOVES.txt before each move, the trash jsonl
   (`ours:scripts/duplicate_cleanup.py:606-609`), test `ours:tests/test_duplicate_cleanup.py:471`.
Fetch's only hard delete is its own unverified download (`ours:sourcing/fetch.py:462-464`).

## The difference that matters

| CLAUDE.md invariant (`ours:CLAUDE.md:11-12`) | SoulSync: honours / conflicts / not addressed | Citation |
|---|---|---|
| Never trash while any playlist (hidden entries included) still holds the file | **Conflicts.** Playlist membership only ranks which duplicate to keep; the others are binned even if a playlist holds them, with no repoint, and a user-picked keeper skips the check. Import, reorganize, upgrade and most repair deletes never look. Membership comes from `getPlaylist`, which hides missing rows. Only the expired-download cleaner keeps a track for its playlists: SoulSync's own active mirrors, or a synced server "in playlist" signal. | `SoulSync:core/library/duplicate_keep.py:36-62`, `SoulSync:core/repair_worker.py:4071-4091`, `SoulSync:core/library/playlist_membership.py:36-37`, `SoulSync:core/library/expired_cleanup.py:9-18`, `SoulSync:core/library/expired_cleanup.py:150` |
| Scan between repoint and trash | **Not addressed.** SoulSync never repoints a playlist before a delete; reorganize and the duplicate fix rewrite or delete `tracks` rows directly and request no scan. Its scan waits exist only before playlist *sync*. | `SoulSync:core/reorganize_runner.py:137-156`, `SoulSync:core/repair_worker.py:4231`, `SoulSync:core/automation_engine.py:146-157` |
| Recompute groups right before acting | **Partly honours.** Duplicate fixes act on the stored finding, not a recomputed group, but re-read membership and refuse an unresolvable or same-file keeper; orphan, dead-file and empty-folder fixes re-check; a quality upgrade re-checks before retiring the original. | `SoulSync:core/repair_worker.py:2099-2109`, `SoulSync:core/repair_worker.py:4133-4157`, `SoulSync:core/repair_worker.py:3292-3317`, `SoulSync:core/imports/pipeline.py:1694-1697` |
| Every destructive step has a logged reverse | **Conflicts.** Hard `os.remove` on import collisions, upgrades, redownloads, reorganize and most repair fixes; the bin's manifest is written after the move, does not restore the deleted DB row, and the Weekly Cleanup empties it; tag rewrites clear all tags with no copy; playlist reconcile/replace keep no before-list (the optional backup playlist is off). | `SoulSync:core/imports/pipeline.py:1691-1735`, `SoulSync:core/library_reorganize.py:2119-2124`, `SoulSync:core/library/deleted_quarantine.py:8-10`, `SoulSync:core/library/cleanup.py:58-78`, `SoulSync:core/metadata/enrichment.py:110-114` |

Beyond the table, three differences decide whether its filing could sit beside ours:

- **Tags.** SoulSync clears every tag on import and rewrites from its matched source, with no confidence gate of its own on that write (*absence inferred*: `grep -nE 'confiden|threshold|min_score|score'` over all of `core/metadata/enrichment.py` finds nothing; its only entry gate is the master switch, `SoulSync:core/metadata/enrichment.py:72-74`);
  with no metadata it saves the file *untagged* (`SoulSync:core/metadata/enrichment.py:110-123`). That is the opposite
  of D29 (full tags only on a confident match, else as-is) and of the 2026-10-15 lesson that a full rewrite collapses
  multi-valued fields (`ours:deploy/beets.yaml:1-13`). Its library-side writer is field-by-field with sensible guards,
  close to our `write_minimal`.
- **Playlists.** SoulSync's default **reconcile** removes anything the source playlist does not have, user-added
  tracks included, and adopts any same-named playlist of the account (`SoulSync:core/sync/playlist_edit.py:103-108`,
  `SoulSync:core/navidrome_client.py:1216-1233`). For Michael's crates, which he edits in Amperfy and Mixxx, that is
  data loss; D44 is insert-only into playlists we imported (`ours:docs/specs/2026-10-17-amperfy-pivot.md:39`). Its
  guard checks the id *set* after the write; ours checks the exact list before (compare-and-swap) and after, and
  cross-checks navidrome.db for hidden rows.
- **Placement and collisions.** SoulSync files every album track into an album folder from a template, which is what
  S2-06 still has to build; but on a collision it deletes the incoming file or overwrites the existing one, where
  beets keeps both (`Title.1.ext`) and our cleanup later chooses with `keep_rank` (`ours:scripts/dedupe_copies.py:61-64`).

## Worth taking?

- **Take (adapt): the playlist write guard's "prove the ids exist" step.** Before a write, check that every wanted id
  is a live song (from the list just read or a `search3` inventory read that refuses if the scan count changed
  meanwhile), and refuse a write that would drop entries while an id is unresolved
  (`SoulSync:core/library/navidrome_identity.py:43-72`, `SoulSync:core/library/navidrome_identity.py:330-336`). Ours
  checks presence in navidrome.db (`ours:crates/playlist_edit.py:116-141`), so this is only a cross-check, worth a line
  in S2/S3's review, not a build item.
- **Take (adapt): "wait for an idle scan before a playlist write that adds songs"** (180 s, then refuse;
  `SoulSync:core/library/navidrome_identity.py:22-40`).
  Ours refuses during a scan in the cleanup (`ours:scripts/duplicate_cleanup.py:405-410`) but placement does not wait
  (`grep -n -i scan crates/placement.py` finds only a docstring, `ours:crates/placement.py:38`). Cheap, and it fits D44.
- **Take (adapt) for S2-06: the album template and the "files already in the album win" rule.** SoulSync's
  `album_path` and album consistency's sibling adoption (new files take the tags of the album's files already on disk,
  which are never rewritten, `SoulSync:core/album_consistency.py:580-585`) match S2-06's "one folder, one Navidrome
  album" and D22's no-full-write rule.
- **Take (learn): its debounce and follow-up scan**, one scan per batch and one follow-up for requests during a scan
  (`SoulSync:core/web_scan_manager.py:97-117`), for S2's album jobs. Not its fixed 300 s minimum or its "error = not
  scanning" probe; our `lastScan` check is better (`ours:subsonic/client.py:252-267`).
- **Don't take:** clear-and-rewrite tagging (D29, D22); reconcile/replace playlist sync, name-matched adoption and
  whole-list rewrites (D44, the amperfy rule); hard deletes, a quarantine folder the default-on Full Cleanup purges every 12 h (`SoulSync:core/automation/handlers/download_cleanup.py:115-126`, `SoulSync:core/automation_engine.py:244-250`) and a recycle bin the opt-in Weekly Cleanup empties (`SoulSync:core/automation_engine.py:225-235`) (invariant 4, `crates/trash.py`);
  repair jobs that delete without a playlist check (invariant 1); SoulSync as the tagger/organiser in place of beets
  (D18).

**Verdict:** no. SoulSync's filing replaces beets with its own clear-and-rewrite tagger, its playlist sync removes
tracks it did not add, and it breaks two of our four safety invariants (playlist-held files and logged reverses); the
ideas worth carrying over are small: the write guard's id check, a scan wait before playlist writes, and the album
template plus sibling-tag adoption for S2-06.
