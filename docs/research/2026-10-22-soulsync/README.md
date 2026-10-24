# SoulSync review: how it works, how it compares, what to take

Research run `dj-soulsync-review-2026-10-22` (spec: `docs/specs/2026-10-22-soulsync-review.md`). Subject:
[SoulSync](https://github.com/Nezreka/SoulSync), read from the pinned read-only clone at commit `34bf7cf9c741`
(2026-10-21, "Merge pull request #1821"). Music only; video/TV, audiobooks and podcasts are named once and skipped.

Citations: `SoulSync:<path>:<line>` is a path in that clone at `34bf7cf9c741`; `ours:<path>:<line>` is a path in this
repository at the run's base. A claim with no citation carries the mark *unverified*.

## Summary

**Verdict: option (c), port specific pieces into the queued S-runs, re-written in our own words, with no SoulSync
process, fork or copied code** ([09-recommendations.md](09-recommendations.md#recommendation)). (a) and (b) conflict
with D7, D18, D24, D26 and D44 in ways config cannot fix, and (d) leaves cheap fixes unused.

### Top 5 findings

1. SoulSync conflicts with D7: every request path an admin uses downloads at once (`SoulSync:api/request.py:287-306`)
   or on the 30-minute "Auto-Process Wishlist" timer (`SoulSync:core/automation_engine.py:76-83`), and only restricted
   member profiles wait for approval ([08-ui-api.md](08-ui-api.md#the-difference-that-matters)).
2. Its filing would be a second library writer beside beets (D18): it uses its own clear-and-rewrite tagger, its
   playlist sync removes entries it did not add (`SoulSync:core/sync/playlist_edit.py:96-108`), and it breaks two of
   our four safety invariants ([07-filing-library.md](07-filing-library.md#the-difference-that-matters)).
3. Running or forking it means tracking a release about every 2 days (median 2.16 days over the latest 20), from one
   author with 88.8 % of contributions, whose CI never tests the commit `:latest` is built from
   (`SoulSync:.github/workflows/docker-publish.yml:4-12`; [01-map.md](01-map.md#maintenance-health)).
4. Its Soulseek album path is the closest working example of goal E: it pins one folder covering ≥ 80 % of the tracks
   (`SoulSync:core/downloads/master.py:1372-1382`), but it has no same-release rule, so a mix of releases can still come
   from the per-track tail, and S2-04/S2-05 should take its structure and keep ours stricter
   ([04-soulseek.md](04-soulseek.md#album-requests-and-folder-choice)).
5. It would barely have stopped ext-74: its base-title veto rejects the wrong song by only 0.025
   (`SoulSync:core/matching_engine.py:1307-1335`), the folder-reuse path has no veto (`SoulSync:web_server.py:16757-16762`),
   and its title-based AcoustID FAIL, which S1-02 adopts, is off by default (`SoulSync:core/settings.py:745-748`;
   [03-matching.md](03-matching.md#the-difference-that-matters)).

### Next steps

As in [09-recommendations.md](09-recommendations.md#recommendation) `## Recommendation`, in order; nothing is
applied yet.
1. **Apply** the S1 spec deltas (S1-01, S1-02, S1-04) to `docs/specs/2026-10-22-downloads-and-requests.md` before the
   `dj-crate-streaming-2026-10-22-fixes` run, after Michael's yes (< 0.1 harness night).
2. **Run** S1 (`dj-crate-streaming-2026-10-22-fixes`), 8 features with the deltas (1 harness night).
3. **Apply** the S2-S4 deltas (S2-03, S2-04, S2-05, S2-06, S3-01, S3-03, S3-06, S4-01) before the
   `dj-crate-streaming-2026-10-22-build` run (< 0.1 harness night).
4. **Run** S2-S4 (`dj-crate-streaming-2026-10-22-build`), 15 features (about 2.25 harness nights).
5. **Capture** the slskd shapes in Michael's morning (S4-01 checklist): the multi-file enqueue response, transfer
   records per state, `DELETE … ?remove=true`, the search timeout key, `GET /server` during a drop (about 30 min live,
   Michael's, D7).
6. **Write** a follow-up spec, `docs/specs/<date>-soulsync-followups.md`, for the pieces that wait for step 5 or for
   goal B (rows 4, 6, 10, 12 of the (c) table and the `bytesTransferred` checks); one docs session, then about
   0.75 harness night to build.
7. **Re-read** `core/spotify_client.py` at SoulSync's then-current release when a run builds the Spotify provider
   behind `sourcing/catalog.py`, after S3-06's capture (a quarter of a harness night).

Questions for Michael: see 09-recommendations.md

## Sections

1. [01-map.md](01-map.md): what SoulSync is (process model, data stores, settings and credentials, deployment,
   tests and CI, module map, license, maintenance health).
2. [02-intake.md](02-intake.md): where wanted music comes from (Spotify, other playlist sources, wishlist and
   watchlist, requests, Lidarr compatibility).
3. [03-matching.md](03-matching.md): "have it / missing", identity, versions and editions.
4. [04-soulseek.md](04-soulseek.md): Soulseek sourcing in full (queries, scoring, album folders, fallback, peer
   memory, transfers, errors, throttling, the slskd endpoint table).
5. [05-other-sources.md](05-other-sources.md): the non-Soulseek music sources, with legality / terms-of-service
   flags, and how the orchestrator picks between sources.
6. [06-verification.md](06-verification.md): what proves a download is right and good (validation, album
   consistency, AcoustID, quarantine).
7. [07-filing-library.md](07-filing-library.md): tags, file placement, the library, and Navidrome.
8. [08-ui-api.md](08-ui-api.md): UI, API and the phone.
9. [09-recommendations.md](09-recommendations.md): the four options, the recommendation, next steps, and questions
   for Michael.
10. [README.md](README.md): this file: the summary above, then the stage-by-stage comparison and the fit to goals.

## Stage-by-stage comparison

"Ours (built)" is this run's base (`main` plus PR #16's hotfix). The S1 branch
`origin/harness/dj-crate-streaming-2026-10-22-fixes` did not exist when this was written (`git ls-remote`,
2026-10-22), so "ours (planned)" is the downloads spec, not code. Each cell is a summary; the linked section has the
mechanism in full.

| Stage | SoulSync | Ours (built) | Ours (planned S1-S4) | Stronger and why |
|---|---|---|---|---|
| **Intake** | Twelve source keys (Spotify, Tidal, Deezer, YouTube Music, Beatport, ListenBrainz…) mirrored into its DB and synced by user-built automations, the Run button or after downloads (no built-in schedule, [02-intake.md](02-intake.md#what-soulsync-does)), into a track-keyed wishlist that is processed every 30 min; Spotify by authorization code with the user's own app (`SoulSync:core/spotify_client.py:800-819`), plus a SpotipyFree fallback that imitates the web player (`SoulSync:core/spotify_public_api.py:4-9`); album identity lives only in a JSON blob on the row (`SoulSync:database/music_database.py:807-817`). [02-intake.md](02-intake.md#what-soulsync-does) | Spotify only: embed page, Exportify CSV or SpotiFLAC report into one `Row` (`ours:sourcing/playlist_sources.py:1-14`); `import-playlist` matches against Navidrome and keeps playlist and position on each wanted row (`ours:sourcing/import_playlist.py:355-357`); no login, no schedule. [02-intake.md](02-intake.md#how-ours-does-it) | S2-01 `requests` table with `mb_release_id`, `track_no`; S2-02 album URL fills album/track/year; S3-01 one link endpoint; S3-02 MusicBrainz catalog search behind a provider interface; S3-06 a capture for Michael's own Spotify app (`ours:docs/specs/2026-10-22-downloads-and-requests.md:103-111`, `ours:docs/specs/2026-10-22-downloads-and-requests.md:188-221`) | **SoulSync today** on breadth and on Spotify login (private playlists need its authorization-code flow, which S3-06's Client Credentials cannot reach). **Ours planned** on the record: an album is first-class and nothing is fetched on a timer (D7). |
| **Matching** | Weighted fuzzy scores with many hand-tuned thresholds; "have it" is title + artist at 0.7 with no duration and no id; extended and radio edit pass with a small penalty; a base-title veto at 0.30 (`SoulSync:core/matching_engine.py:1307-1335`); an exact-id pre-check only after a download (`SoulSync:core/imports/library_check.py:12-17`). [03-matching.md](03-matching.md#the-difference-that-matters) | Key equality, versions as identity, lengths within 4 s, else `ambiguous` for Michael (`ours:sourcing/import_playlist.py:188-197`); the scorer's title-slot rule only ranks (`ours:sourcing/scorer.py:99-105`). [03-matching.md](03-matching.md#how-ours-does-it) | S1-01 rejects a title slot naming another song; S1-07 asks the library before downloading (`ours:docs/specs/2026-10-22-downloads-and-requests.md:62-67`, `ours:docs/specs/2026-10-22-downloads-and-requests.md:89-92`) | **Ours**, for D26 and the crates: exact rules, no thresholds to tune. SoulSync's exact-id "already owned" pattern is the piece worth taking. |
| **Search/score** | 1-3 query variants per track, candidates scored by the matching engine, a quality-rung ladder, measured peer throughput (1 h memory) as a tie-break (`SoulSync:core/downloads/peer_observation.py:28-50`). [04-soulseek.md](04-soulseek.md#search-and-candidates), [scoring](04-soulseek.md#scoring) | One query `"<artist> <title>"`, 8 s search, a 0-100 score with hard rejections for format, D24's floor and another version (`ours:sourcing/fetch.py:386-405`, `ours:sourcing/scorer.py:138-254`); advertised slot/queue/speed only. [04-soulseek.md](04-soulseek.md#how-ours-does-it) | S1-01 (above); S2-04 one album search `"<artist> <album>"` (`ours:docs/specs/2026-10-22-downloads-and-requests.md:120-122`) | **Even.** SoulSync has more recall and real speed data; ours rejects more of the wrong files and spares Soulseek searches. A measured-speed tie-break is cheap to add. |
| **Album sourcing and fallback** | Built: folders grouped by (peer, directory), one pinned when it covers ≥ 80 % and scores ≥ 0.62 (`SoulSync:core/downloads/master.py:1372-1382`, `SoulSync:core/downloads/master.py:43`), only matched files enqueued, up to 4 alternative folders each covering *all* still owed (`SoulSync:core/soulseek_client.py:2197-2259`), per-track for the rest; no same-release test, a verify failure never distrusts the folder. [04-soulseek.md](04-soulseek.md#album-requests-and-folder-choice), [when a track fails](04-soulseek.md#when-a-track-fails) | None: every row is its own search and its own peer, one approval at a time (`ours:sourcing/worker.py:267-279`); the only album signal is +4 for a folder named like the album (`ours:sourcing/scorer.py:224-225`). | S2-04 primary + one same-release secondary (lengths within 2 s or the MB release), at most two folders, then per-track; S2-05 one enqueue, switch the rest of the folder, distrust a folder on one "not what it claims" finding (`ours:docs/specs/2026-10-22-downloads-and-requests.md:120-156`) | **SoulSync today** (it exists). **Ours planned** on design: the same shape plus the two rules SoulSync lacks (same release, distrust fakes) and a tighter bound. |
| **Transfer handling** | One POST per file with a 7-POST fallback cascade; the global `GET transfers/downloads` once per tick (`SoulSync:core/downloads/monitor.py:759`); `remove=True` on cancels in the download path (`SoulSync:core/downloads/monitor.py:690`); 3 error and 3 stall retries, each a fresh search (`SoulSync:core/downloads/monitor.py:921-989`, `SoulSync:core/downloads/monitor.py:853-896`); every non-2xx becomes None (`SoulSync:core/soulseek_client.py:235-306`). [04-soulseek.md](04-soulseek.md#transfers), [errors](04-soulseek.md#errors-and-outages), [endpoints](04-soulseek.md#every-slskd-endpoint-soulsync-calls) | Per-peer listing with the hotfix's "404 = no transfers" (`ours:sourcing/slskd_client.py:79-84`); DELETE without `remove=true` and `mine[-1]` by filename (`ours:docs/specs/2026-10-22-downloads-and-requests.md:39-43`); a failed transfer fails the row, no second candidate (`ours:sourcing/fetch.py:430-446`). | S1-04 `?remove=true`, own transfer = an id not there before the enqueue; S1-05 reasons name step and endpoint; S1-06 one more peer per approval (`ours:docs/specs/2026-10-22-downloads-and-requests.md:76-88`) | **SoulSync today** on hygiene (remove on cancel, one global listing). **Ours after S1** on correctness: a stricter own-transfer rule, error reasons kept, retries bounded by D7. |
| **Verification** | After download, by default: length (−3/+15 s, `SoulSync:core/imports/file_integrity.py:100-116`), size and header; no transcode detection; AcoustID title FAIL only when enabled (`SoulSync:core/matching/audio_verification.py:829-831`, off at `SoulSync:core/settings.py:745-748`); quarantine blocks the `(peer, file)` and tries up to 5 more. [06-verification.md](06-verification.md#summary) | Decodes every download: spectral cutoff, fake hi-res, implied rate (`ours:sourcing/verify.py:433-447`); AcoustID fails only when a recording id is known (`ours:sourcing/verify.py:402-404`); a bad file is deleted and nothing remembers it (`ours:sourcing/fetch.py:462-464`). [06-verification.md](06-verification.md#how-ours-does-it) | S1-02 title-based AcoustID finding without an id; S2-03 recording ids from the MB release (`ours:docs/specs/2026-10-22-downloads-and-requests.md:68-72`, `ours:docs/specs/2026-10-22-downloads-and-requests.md:112-119`) | **Ours** on quality (D24: SoulSync cannot see a transcode). **SoulSync** on identity when its AcoustID is on and on remembering a failed `(peer, file)`; S1-02 closes the first gap, the second is not planned. |
| **Tagging/filing** | No beets: an in-house mutagen tagger clears every tag and rewrites from the matched source, or saves the file untagged (`SoulSync:core/metadata/enrichment.py:110-123`); an album-folder template (`SoulSync:core/settings.py:915-919`); a collision deletes the incoming file or overwrites. [07-filing-library.md](07-filing-library.md#does-it-use-beets), [tags](07-filing-library.md#what-it-writes-into-tags-and-when) | beets 1.6 singleton import, move, no write (`ours:sourcing/filer.py:135`); full tags only on a confident MB match; `write_minimal` field by field otherwise; collisions keep both as `Title.1.ext` (`ours:deploy/beets.yaml:27`); everything files to `$artist/Singles/`. [07-filing-library.md](07-filing-library.md#how-ours-does-it) | S2-06 album path `$albumartist/$album ($year)/$track - $title`, identity written by `write_minimal` in `.staging` before beets, reverse in the event (`ours:docs/specs/2026-10-22-downloads-and-requests.md:166-182`) | **Ours** (D18, D22, D29: no destructive rewrite, nothing lost on a collision). SoulSync has the album folder today; S2-06 plans it. |
| **Navidrome/playlists** | Debounced `startScan` with one follow-up scan (`SoulSync:core/web_scan_manager.py:97-117`) and a 300 s minimum before a scan counts as done (`SoulSync:core/web_scan_manager.py:268-324`); default reconcile sync adds every source id missing and removes every id the source lacks (`SoulSync:core/sync/playlist_edit.py:96-108`), appended by `songIdToAdd` (`SoulSync:core/navidrome_client.py:1800-1806`); a name lookup on its own account then overwrite (`SoulSync:core/navidrome_client.py:1216-1226`); an id-set check after the write. [07-filing-library.md](07-filing-library.md#how-it-edits-navidrome-playlists-and-with-what-guards) | `scan_and_wait` on `lastScan` (`ours:subsonic/client.py:252-267`); `playlist_edit` checks API and navidrome.db before (`ours:crates/playlist_edit.py:54-82`), compare-and-swap and exact re-read (`ours:crates/playlist_edit.py:116-141`); D44 insert-only at the Spotify position (`ours:crates/placement.py:83-115`). | No playlist change; S2-07 adds one approval per playlist (`ours:docs/specs/2026-10-22-downloads-and-requests.md:183-186`) | **Ours.** SoulSync's reconcile removes what Michael added and re-adds what he removed; ours never removes or moves an entry. |
| **UI/API** | 1,212 route decorators ([routes](08-ui-api.md#routes-and-how-they-are-registered)); a 24-page admin console, responsive, installable with a service worker (`SoulSync:webui/static/sw.js:93-111`); login off by default ([auth](08-ui-api.md#auth-sessions-and-profiles)); key-scoped `/api/v1` (`SoulSync:api/auth.py:40-101`) whose `POST /api/v1/request` downloads at once (`SoulSync:api/request.py:287-306`); no Subsonic server. [08-ui-api.md](08-ui-api.md#the-difference-that-matters) | Stdlib `crates` service: wanted list, preview, approve, play-now (`ours:crates/service.py:439-441`, `ours:crates/service.py:253-279`); a manifest with an SVG icon and no service worker (`ours:web/manifest.webmanifest:1-9`); no auth beyond the tailnet (`ours:docs/architecture.md:545-546`). [08-ui-api.md](08-ui-api.md#how-ours-does-it) | S3-01..S3-05 request API (link, catalog search, preview/approve, CLI, docs), no UI, same exposure as `/api/*` (`ours:docs/specs/2026-10-22-downloads-and-requests.md:188-214`) | **SoulSync** on surface and phone installability. **Ours planned** on request shape: one link endpoint, preview, explicit approve. Neither has a `share_target`; SoulSync's login is off by default and ours has none beyond the tailnet. |
| **Operations** (deploy, backups, locks, observability) | One container from a floating `:latest` image (`SoulSync:docker-compose.yml:8-9`), published on every push to `main` with no tests on that commit (`SoulSync:.github/workflows/docker-publish.yml:4-12`); schema migrated in-app at boot; the entrypoint remaps uid/gid, chowns, copies a default config and runs no migrations (`SoulSync:entrypoint.sh:19-37`, `SoulSync:entrypoint.sh:58-64`). Backups: an "Auto-Backup Database" automation every 3 days (`SoulSync:core/automation_engine.py:238-243`), integrity-checked SQLite online backup (`SoulSync:core/db_integrity.py:83-124`) of the database only, written beside it (`SoulSync:core/automation/handlers/maintenance.py:109`), 5 kept, never pruning the newest healthy one (`SoulSync:core/automation/handlers/maintenance.py:98`, `SoulSync:core/db_integrity.py:127-140`). Locks: one gunicorn process (`SoulSync:gunicorn.conf.py:4-6`) with in-process thread locks (`SoulSync:core/imports/jobs.py:20`), no file lock (*absence inferred*: `grep -rlE 'import fcntl\|fcntl\.flock\|filelock'` over its `.py` files finds none). Observability: a `curl` healthcheck (`SoulSync:Dockerfile:144-148`), a `/status` route (`SoulSync:web_server.py:3435`). [01-map.md](01-map.md#deployment) | `ours:CLAUDE.md` Live system: `deploy.sh` refuses a dirty tree and tags `dj-crates:<sha>`, rollback by tag (`ours:CLAUDE.md:60-68`); nightly restic of `/srv/music`, `/srv/docker`, `/srv/crates` plus consistent `.snap` copies (`ours:CLAUDE.md:43-56`); a live-writer lock placed where the backup job can hold it too (`ours:CLAUDE.md:57-58`) and the worker's lock (`ours:sourcing/worker.py:84-86`); the export Check (`ours:CLAUDE.md:35-42`); Gatus with ntfy alerts, backup heartbeat included (`ours:docs/monitoring.md:7-8`, `ours:docs/monitoring.md:19`). | S4-01 downloads checklist with check and undo per step (`ours:docs/specs/2026-10-22-downloads-and-requests.md:224-227`) | **Ours**: pinned images tagged by commit, rollback, the music itself backed up, a lock the backup can share. SoulSync's "refuse to back up a corrupt DB, never prune the last healthy copy" is already ours: `snapshot-crates-db.sh` replaces a snapshot only once the copy passes the integrity check (`ours:scripts/snapshot-crates-db.sh:16-18`); SoulSync keeps 5 copies, ours one plus restic history. |
| **Safety** (approval gate, one beets writer, reverse logs, trash rules) | Approval only for member profiles, enforced in the scheduler ([08-ui-api.md](08-ui-api.md#the-difference-that-matters)); a 30-minute wishlist automation ships enabled (`SoulSync:core/automation_engine.py:77-83`); web, downloaders, tagger and repair jobs share one process and database ([01-map.md](01-map.md#the-difference-that-matters)); hard deletes, a bin manifest written after the move, quarantine purged every 12 h by the Full Cleanup (`SoulSync:core/automation_engine.py:244-250`, [06-verification.md](06-verification.md#summary)), playlist-held duplicates binned without repoint (`SoulSync:core/library/duplicate_keep.py:36-54`, `SoulSync:core/repair_worker.py:4071-4091`). [07-filing-library.md](07-filing-library.md#the-difference-that-matters) | `approvals` row per download (`ours:crates/store.py:105-108`); the worker is the only beets writer (`ours:deploy/beets.yaml:1-13`); trash + `MOVES.txt`, never auto-emptied (`ours:crates/trash.py:1-6`); the four invariants, each tested (`ours:CLAUDE.md:11-12`); the cleanup refuses during a scan (`ours:scripts/duplicate_cleanup.py:405-410`). | S1-08 `wanted reopen`, dry run first, reverse in the event; S2-05 Michael's click as the only trigger; S2-06 old tag values in the event (`ours:docs/specs/2026-10-22-downloads-and-requests.md:93-95`, `ours:docs/specs/2026-10-22-downloads-and-requests.md:140-141`, `ours:docs/specs/2026-10-22-downloads-and-requests.md:178`) | **Ours**, clearly: SoulSync breaks two of the four invariants and D7; its design assumes it owns the library alone. |

### The 2026-10-21 failure classes

What each class did to us is in the downloads spec's findings table
(`ours:docs/specs/2026-10-22-downloads-and-requests.md:23-50`).

1. **404 from `GET /transfers/downloads/{peer}`.**
   - *SoulSync:* never asks the per-peer listing on purpose (one call may reach it with a transfer id as the peer
     name, `SoulSync:core/soulseek_client.py:1042`; slskd's answer there is *unverified*, the S4-01 `GET /transfers/downloads/<id>` capture would settle it); it reads the global `GET transfers/downloads` once per tick
     (`SoulSync:core/downloads/monitor.py:759`, `SoulSync:core/soulseek_client.py:1079`), so the 10-21 404 before the
     first enqueue could not happen there. A 404 it does get elsewhere becomes a silent None
     (`SoulSync:core/soulseek_client.py:257-258`). [04-soulseek.md](04-soulseek.md#the-difference-that-matters)
   - *Ours did:* all 8 rows failed at 21:46 before any enqueue; the hotfix `6238ee5` (deployed; `19fedea` in this branch) reads the 404 as "no transfers"
     (`ours:docs/specs/2026-10-22-downloads-and-requests.md:25`, `ours:sourcing/slskd_client.py:79-84`); ext-78 still
     shows the stale reason (`ours:docs/specs/2026-10-22-downloads-and-requests.md:30`).
   - *Planned:* S1-04 reads a 404 on DELETE as gone; S1-05 makes the reason name the endpoint and status
     (`ours:docs/specs/2026-10-22-downloads-and-requests.md:76-84`). Worth adding from SoulSync: poll the global listing
     for album jobs.
2. **Wrong song from a same-named album folder (ext-74).**
   - *SoulSync:* on the per-track search path its base scorer accepts track 09, and the base-title veto rejects it by
     0.025 (0.275 < 0.30, `SoulSync:core/matching_engine.py:1307-1335`). On the folder-reuse path there is no veto and
     it is accepted at ≥ 0.70 (`SoulSync:web_server.py:16757-16762`); under a flat `Artist - Album - 09 - Title` name it
     is accepted too. After download, the title-based AcoustID FAIL would quarantine it
     (`SoulSync:core/matching/audio_verification.py:829-831`), but only when enabled, which it is not by default
     (`SoulSync:core/settings.py:745-748`). [03-matching.md](03-matching.md#the-difference-that-matters),
     [06-verification.md](06-verification.md#would-ext-74-have-been-caught)
   - *Ours did:* accepted it at 84.5, verify had no recording id so AcoustID's "One of These Good Old Days" (0.958) was no
     finding, and `finish` renamed the row onto the other song
     (`ours:docs/specs/2026-10-22-downloads-and-requests.md:27`, `ours:docs/specs/2026-10-22-downloads-and-requests.md:35-38`).
   - *Planned:* S1-01 rejects the title slot, S1-02 fails on AcoustID's title, S1-03 never renames onto another song,
     S1-08 reopens ext-74, S2-03 supplies recording ids for album rows
     (`ours:docs/specs/2026-10-22-downloads-and-requests.md:62-75`, `ours:docs/specs/2026-10-22-downloads-and-requests.md:93-95`,
     `ours:docs/specs/2026-10-22-downloads-and-requests.md:112-118`). S1-01's key equality is stricter than SoulSync's
     veto; S1-02 is SoulSync's AcoustID rule, on by default.
3. **Stale transfer records (DELETE without `remove=true`).**
   - *SoulSync:* passes `remove=True` on every cancel in the download path (`SoulSync:core/downloads/monitor.py:690`)
     and clears its own finished records every 5 min (`SoulSync:core/automation_engine.py:190-196`); its verify-failure
     retry marks the `(peer, file)` used and walks the other cached candidates before searching again
     (`SoulSync:core/downloads/monitor.py:396-416`), so an old
     record would not be taken for a new one. It still picks the last of two records with the same peer and path
     (`SoulSync:core/downloads/monitor.py:768`). [04-soulseek.md](04-soulseek.md#transfers)
   - *Ours did:* nothing went wrong on 10-21 (the 22:38 retry came back fine), but `remove_download` leaves the record and
     fetch takes `mine[-1]` by filename, and the fake hides it
     (`ours:docs/specs/2026-10-22-downloads-and-requests.md:39-43`).
   - *Planned:* S1-04: `?remove=true`, the fake keeps records like slskd does, and the own transfer is a record whose id
     was not there before the enqueue (`ours:docs/specs/2026-10-22-downloads-and-requests.md:76-81`), stricter than
     SoulSync's last-wins key. Worth adding from SoulSync: remove our own record once the file is filed.
4. **VPN drop mid-transfer.**
   - *SoulSync:* retries a `Completed, Errored` transfer at once, then at least 5 s apart, up to 3 times, each with a fresh search
     on any peer (`SoulSync:core/downloads/monitor.py:936-937`), then the wishlist retries later (`SoulSync:core/downloads/monitor.py:922-985`). It never checks that slskd is
     logged in again first, though it has the probe (`SoulSync:core/soulseek_client.py:2668-2690`); whether the first
     retry lands inside the ~10 s drop is *unverified* (04-soulseek.md names the log that would settle it).
     [04-soulseek.md](04-soulseek.md#errors-and-outages)
   - *Ours did:* 13 drops between 21:30 and 00:50; a transfer caught in one ends `Completed, Errored` and the row fails
     with no second source (`ours:docs/specs/2026-10-22-downloads-and-requests.md:44-47`,
     `ours:sourcing/fetch.py:430-446`).
   - *Planned:* S1-06 tries one more candidate from another peer, once per approval
     (`ours:docs/specs/2026-10-22-downloads-and-requests.md:85-88`); for albums, S2-05's switch on a transfer error
     (`ours:docs/specs/2026-10-22-downloads-and-requests.md:146-148`). SoulSync recovers further but beyond D7's bound;
     the piece to take is a `GET /server` login wait before the second attempt.
5. **One album across 5 peers and 4 releases.**
   - *SoulSync:* an album batch pins one folder when one covers ≥ 80 % of the tracks and scores ≥ 0.62
     (`SoulSync:core/downloads/master.py:1372-1382`, `SoulSync:core/downloads/master.py:43`), switches to alternatives only if each covers everything still owed
     (`SoulSync:core/soulseek_client.py:2197-2259`), and sends the rest per-track to any peer, with no same-release test.
     It files every track into the album template (`SoulSync:core/settings.py:915-919`) and rewrites their tags to one
     MusicBrainz release after publish (`SoulSync:core/album_consistency.py:364-410`,
     `SoulSync:core/album_consistency.py:823-877`). So it would most likely have
     taken one folder, and a mix of releases could still come from the per-track tail, tagged as one release.
     [04-soulseek.md](04-soulseek.md#when-a-track-fails), [06-verification.md](06-verification.md#the-difference-that-matters)
   - *Ours did:* the album rows carried `album: null`, every row was its own search, and the filer imported singletons,
     so 5 peers and 4 releases landed in `Al Green/Singles/` (`ours:docs/specs/2026-10-22-downloads-and-requests.md:48-50`).
   - *Planned:* S2-02 fills the album on every row, S2-03 matches the MB release, S2-04/S2-05 plan and run one folder
     plus one same-release secondary, S2-06 files into one album folder
     (`ours:docs/specs/2026-10-22-downloads-and-requests.md:109-182`). Stricter than SoulSync on "same release", and the
     tags are written once in `.staging` rather than rewritten after publish.

### Michael's decisions

| Decision | In five words | SoulSync | Citation |
|---|---|---|---|
| D7 (`ours:docs/specs/2026-10-13-next-session-design.md:61`) | Downloads only after Michael's approval | **Conflicts.** `POST /api/v1/request` downloads the best hit at once; the wishlist automation runs every 30 min from install; approval exists only for member profiles, and a wishlist item is retried on a schedule without a new approval. [08-ui-api.md](08-ui-api.md#the-difference-that-matters) | `SoulSync:api/request.py:287-306`, `SoulSync:core/automation_engine.py:77-83`, `SoulSync:core/wishlist/retry_backoff.py:7-17` |
| D18 (`ours:docs/specs/2026-10-13-next-session-design.md:72`) | Worker container: the only writer | **Conflicts.** One gunicorn process holds the web UI, downloaders, tagger, scheduler and repair jobs, and it has no beets. Beside ours it is a second library writer unless confined to an input folder. [01-map.md](01-map.md#the-difference-that-matters), [07-filing-library.md](07-filing-library.md#does-it-use-beets) | `SoulSync:gunicorn.conf.py:4-6`, `SoulSync:Dockerfile:53-61` |
| D22/D29 (`ours:docs/specs/2026-10-13-next-session-design.md:76`, `ours:docs/specs/2026-10-17-amperfy-pivot.md:24`) | Full tags only when confident | **Conflicts.** It clears every tag and rewrites from whatever source matched, with no confidence gate, and saves the file untagged when there is no metadata; its library cleaner strips explicit/clean, which D22 keeps as versions. [07-filing-library.md](07-filing-library.md#what-it-writes-into-tags-and-when) | `SoulSync:core/metadata/enrichment.py:110-123`, `SoulSync:database/music_database.py:14215-14216` |
| D24 (`ours:docs/specs/2026-10-17-amperfy-pivot.md:19`) | Lossless or ≥256, fakes rejected | **Conflicts.** The quality gate reads the header's claim, the default profile never rejects, and nothing detects a transcode after download; its YouTube source makes the re-encoded fake D24 forbids. [06-verification.md](06-verification.md#the-difference-that-matters) | `SoulSync:core/quality/schema.py:171-172`, `SoulSync:core/imports/file_integrity.py:445-470`, `SoulSync:core/settings.py:1106-1115` |
| D26 (`ours:docs/specs/2026-10-17-amperfy-pivot.md:21`) | The exact version, no stand-ins | **Conflicts.** On Soulseek an extended mix costs −0.025 and a radio edit −0.04, so both stand in for the plain cut; "have it" ignores duration. [03-matching.md](03-matching.md#remaster-live-extended-radio-edit) | `SoulSync:core/matching_engine.py:1246-1248`, `SoulSync:core/matching_engine.py:1204-1206`, `SoulSync:core/matching_engine.py:1421` (penalty halved) |
| D27 (`ours:docs/specs/2026-10-17-amperfy-pivot.md:22`) | Crates app owns crate flag | **Not addressed.** SoulSync has no crate concept; which playlists it syncs is its own mirror list in its own DB (`mirrored_playlists`, [02-intake.md](02-intake.md#other-playlist-sources)). If it shared the Navidrome account it would find a same-named playlist and overwrite it. [07-filing-library.md](07-filing-library.md#the-difference-that-matters) | `SoulSync:database/music_database.py:1385`, `SoulSync:core/navidrome_client.py:1216-1226` |
| D31/D35 (`ours:docs/specs/2026-10-17-amperfy-pivot.md:26`, `ours:docs/specs/2026-10-17-amperfy-pivot.md:30`) | Keep flac, repoint, trash rest | **Conflicts, partly honours.** Lossless outranks lossy for the keeper, but a playlist-held copy wins first, nothing is repointed, the other copies are binned even if a playlist holds them, and the bin can be emptied by a cleanup job. [07-filing-library.md](07-filing-library.md#the-difference-that-matters) | `SoulSync:core/library/duplicate_keep.py:22-25`, `SoulSync:core/library/duplicate_keep.py:36-54`, `SoulSync:core/repair_worker.py:4071-4091`, `SoulSync:core/automation_engine.py:225-235` |
| D44 (`ours:docs/specs/2026-10-17-amperfy-pivot.md:39`) | Insert at Spotify position, only | **Conflicts.** Reconcile appends missing ids with `songIdToAdd` (no position) and removes ids the source lacks, so a track Michael added is removed and one he removed returns. [02-intake.md](02-intake.md#the-difference-that-matters) | `SoulSync:core/sync/playlist_edit.py:96-108`, `SoulSync:core/navidrome_client.py:1800-1806` |

D7's recorded text is "automatic downloads only after Michael has approved at least one manual download and said go"
(`ours:docs/specs/2026-10-13-next-session-design.md:61`); this report reads it, as the review spec does, as "nothing
downloads without Michael's approval" (`ours:docs/specs/2026-10-22-soulsync-review.md:44`). SoulSync conflicts
with both readings.

## Fit to goals

The goals are quoted from the review spec (`ours:docs/specs/2026-10-22-soulsync-review.md:33-44`). Each part says
whether SoulSync has the goal today, how (with links to the section file), and what it costs two ways:

- **from SoulSync**: the cheapest route that uses SoulSync, either running it beside ours or porting a piece of it;
- **build ours**: our own code, mostly the planned S-features.

**Effort unit.** A *harness night* is one overnight run of this harness. The run's default is that one night does
about 6-10 features, or 1-2 human days (an assumption, *unverified*; the initializer's question 1 in `progress.md` asks
Michael to change it). For scale, the queued downloads run has 23 features: S1 8, S2 7, S3 6, S4 2
(`ours:docs/specs/2026-10-22-downloads-and-requests.md:61-96`,
`ours:docs/specs/2026-10-22-downloads-and-requests.md:97-187`,
`ours:docs/specs/2026-10-22-downloads-and-requests.md:188-222`,
`ours:docs/specs/2026-10-22-downloads-and-requests.md:223-230`). That is about 3 harness nights.
Every effort figure below is a judgment, not a measurement (*unverified* until a run does the work).

Several "from SoulSync" figures run SoulSync itself, and they share one **fixed setup cost of about 1 harness night**
(*unverified* estimate; the first SoulSync setup run's actual length would verify it): its own compose project from a pinned digest, not `:latest`
(`SoulSync:docker-compose.yml:8-9`); its own Navidrome user; its `transfer_path` (`SoulSync:core/settings.py:539`)
pointed at an input folder that our worker files from, never `/srv/music`; and the automations that act without
approval turned off. Those automations are the 30-minute wishlist run (`SoulSync:core/automation_engine.py:77-83`) and
the 12-hour Full Cleanup (`SoulSync:core/automation_engine.py:244-250`). Under the build-only policy, Michael would do
the live part of that setup himself.

### B, the client

**SoulSync: partly.** Only option 1 is relevant to it, and only in part: it has an installable, responsive web UI. It
has no Subsonic server, being only a Subsonic client of Navidrome (`SoulSync:core/navidrome_client.py:451-481`), so
option 2 has nothing to start from. It has no native app for option 3 (*absence inferred*: `find` over the clone for Xcode, Android, Gradle, Swift,
Kotlin, Capacitor or Flutter project files finds none, and 01-map.md's module map lists none). [08-ui-api.md](08-ui-api.md#the-difference-that-matters)
has each option in full.

**Option 1: Amperfy, plus our web client as a phone web app, plus an iOS share-sheet Shortcut**
(`ours:docs/specs/2026-10-22-soulsync-review.md:35`). SoulSync's UI has these:
- a phone stylesheet, "overrides for ≤768px" (`SoulSync:webui/static/mobile.css:1-4`);
- a manifest with `display: standalone` and 192/512 PNG icons (`SoulSync:webui/static/manifest.json:5-36`);
- a real service worker (`SoulSync:webui/static/sw.js:93-111`), skipped on non-HTTPS origins
  (`SoulSync:webui/static/init.js:3881-3886`).

Ours has a manifest with one SVG icon and no service worker (`ours:web/manifest.webmanifest:1-9`). It does have the
`apple-mobile-web-app-*` meta tags (`ours:web/index.html:7-9`), which SoulSync lacks
([08-ui-api.md](08-ui-api.md#phone-fit)). Neither project has a `share_target`
(`SoulSync:webui/static/manifest.json:1-37`). The only Shortcut-shaped endpoint SoulSync has is
`POST /api/v1/request`. It takes a free-text query, not a link (`SoulSync:api/request.py:345-363`), and downloads the
best hit at once without approval (`SoulSync:api/request.py:272-341`), so a Shortcut aimed at it breaks D7. SoulSync's
UI would sit beside Amperfy as a second app on a second server. It is a 24-page admin console
(`SoulSync:webui/src/platform/shell/route-manifest.ts:29-61`), not a companion to the Subsonic client. Its request
paths have no per-download preview: "Begin Analysis" analyses and downloads in one step
(`SoulSync:web_server.py:19512-19517`).

**Cost:** from SoulSync: 1.5 harness nights / build ours: 0.5 harness night.
- From SoulSync: the fixed setup, plus a patch that makes "Begin Analysis" and `/api/v1/request` wait for an approval, carried on every upstream release.
- Build ours: on top of S3-01/S3-03 (`ours:docs/specs/2026-10-22-downloads-and-requests.md:191-211`), four small items: a static-only service worker, PNG icons, a `share_target` that posts to S3-01, and a written Shortcut recipe.

Android would use the `share_target`; iOS needs the Shortcut (*unverified* until tried on Michael's phone).

**Option 2: a Subsonic proxy inside crates, in octo-fiesta's style**
(`ours:docs/specs/2026-10-22-soulsync-review.md:36`). There is no Subsonic server in SoulSync to adopt (above). Its
Navidrome proxy shows one pattern a proxy needs: it forwards `Range` and streams the body unbuffered
(`SoulSync:web_server.py:12693-12723`). Ours answers 302 and never carries audio (`ours:crates/service.py:454-459`).
SoulSync's "play a track you don't own" downloads the whole file first (`SoulSync:core/streaming/prepare.py:114-123`).
Its queue prefetch (`SoulSync:web_server.py:6842-6858`) files up to 250 unowned tracks into the library
(`SoulSync:core/playback/prefetch.py:15`) with no per-track approval. Both break D7. A proxy in crates would instead
turn a `stream` of a missing id into our play-now approval (`ours:crates/service.py:253-279`). Nobody has measured
which Subsonic endpoints Amperfy calls (*unverified*: Navidrome's request log while Amperfy browses, plays and syncs would verify it), so the size of that proxy is a guess.

**Cost:** from SoulSync: 2-3 harness nights (the same as ours) / build ours: 2-3 harness nights.
- From SoulSync: nothing in it is a Subsonic server, so it saves only the `Range` lesson.
- Build ours: a proxy for the subset of Subsonic that Amperfy calls, forwarding to Navidrome and turning missing tracks into approvals, tested against a fake.

**Option 3: a native fork, Cassette/Minidisc or Yuzic** (`ours:docs/specs/2026-10-22-soulsync-review.md:37`).
A native Subsonic client would still talk to Navidrome. It would reach SoulSync only through its key-scoped `/api/v1`
(`SoulSync:api/auth.py:40-101`), whose request status a client can poll (`SoulSync:api/request.py:432-462`). The
lesson is that API's shape, which S3-03/S3-05 already plan
(`ours:docs/specs/2026-10-22-downloads-and-requests.md:207-214`). One gap remains: ours plans no auth beyond the tailnet
(`ours:docs/specs/2026-10-22-downloads-and-requests.md:211`, `ours:docs/architecture.md:545-546`). The forks' sources
are not read in this run (*unverified*: reading their server-API code would verify it).

**Cost:** from SoulSync: ≥ 5 harness nights (the same as ours) / build ours: ≥ 5 harness nights.
- From SoulSync: it has no app code to fork, so its API is the only input, and S3 already plans that shape.
- Build ours: a fork of a Swift or Flutter client is mostly work this Linux box cannot build or test, so much of it falls to Michael or another machine.

### C, requests from the phone

**SoulSync: partly.** C asks for a search bar over the common catalogs, or a pasted or shared link, with Spotify only
through Michael's own developer app (`ours:docs/specs/2026-10-22-soulsync-review.md:38-39`).
- **Search bar: yes.** It searches about five catalogs on an unconfigured install, and Spotify, Discogs and Hydrabase
  once configured (`SoulSync:core/search/orchestrator.py:229-256`), plus the local library
  (`SoulSync:core/search/orchestrator.py:1-13`).
- **Paste a link: partly.** It has two parsers, and each misses one kind. The search bar's keyword table has no
  playlist kind (`SoulSync:core/search/by_id.py:83-91`), so a playlist link gets only a hint
  (`SoulSync:core/search/by_id.py:305-308`). The Sync page's Spotify parser takes only playlist and album links
  (`SoulSync:core/spotify_public_scraper.py:39-42`). Tidal links work nowhere (`SoulSync:core/search/by_id.py:45-48`).
- **Share a link: no.** There is no `share_target` and no Shortcut (`SoulSync:webui/static/manifest.json:1-37`).
- **Spotify through his own app: yes.** It uses the authorization-code flow with the user's own client id
  (`SoulSync:core/spotify_client.py:800-819`). It also has a credential-less SpotipyFree fallback that imitates the web
  player (`SoulSync:core/spotify_public_api.py:4-9`), which C rules out.
- **Approval: only for member profiles.** An admin approves a member's request
  (`SoulSync:api/music_requests.py:247-266`), and the item then waits for the 30-minute wishlist run
  (`SoulSync:core/wishlist/processing.py:1076-1091`). That queue misses D7 in four ways:
  - Michael would be the admin, and the admin's own paths download at once or on the timer: Begin Analysis
    (`SoulSync:web_server.py:19512-19517`), the wishlist (`SoulSync:core/automation_engine.py:76-83`) and
    `/api/v1/request` (`SoulSync:api/request.py:287-306`).
  - It approves a request, not a chosen file.
  - It retries on a schedule with no new approval (`SoulSync:core/wishlist/retry_backoff.py:7-17`).
  - A member may reach `start-missing-process` without the check (*unverified* at runtime;
    [08-ui-api.md](08-ui-api.md#a-request-from-the-phone)).

[08-ui-api.md](08-ui-api.md#a-request-from-the-phone) and [02-intake.md](02-intake.md#the-difference-that-matters)
have the flows. Ours today takes a Spotify link only through the CLI (`ours:docs/architecture.md:365`). S3 plans one
link endpoint, MusicBrainz catalog search, then preview and approve
(`ours:docs/specs/2026-10-22-downloads-and-requests.md:188-221`). S3-06's Client Credentials cannot read Michael's
private playlists ([02-intake.md](02-intake.md#the-difference-that-matters)). Two pieces of SoulSync shorten our
build: its link-keyword table (`SoulSync:core/search/by_id.py:83-91`) and its 2026 Spotify rules
(`SoulSync:core/spotify_client.py:1510-1530`).

**Cost:** from SoulSync: 2 harness nights, plus a fork to maintain / build ours: 1.5 harness nights.
- From SoulSync: the fixed setup, plus an approval patch on three request paths in a codebase that changes weekly ([01-map.md](01-map.md#maintenance-health)).
- Build ours: S3's 6 features (about 1 night), plus about 0.5 night for an authorization-code login with Michael's own app.

### D, more than one song at a time

**SoulSync: has.** A playlist sync puts every unmatched track on the wishlist
(`SoulSync:services/sync_service.py:1187-1245`). An album click queues each track
(`SoulSync:api/wishlist_routes.py:605-606`, `SoulSync:core/wishlist/routes.py:790`). The wishlist run then submits
album batches (`SoulSync:core/wishlist/processing.py:211`). The cost is in the record:
- A wishlist row is one track keyed by a provider track id. The album exists only inside a JSON blob
  (`SoulSync:database/music_database.py:807-817`), and requests are grouped back into albums only for display
  (`SoulSync:core/requests/music.py:50-99`).
- An approved item is retried on a schedule with no new approval (`SoulSync:core/wishlist/retry_backoff.py:7-17`).

[02-intake.md](02-intake.md#the-difference-that-matters) has the detail. Ours today is one wanted row per track. Its
`import-playlist` keeps playlist and position (`ours:sourcing/import_playlist.py:355-357`) but downloads one approval
at a time (`ours:sourcing/worker.py:267-279`). The plan makes the album a record:
- S2-01: a `requests` table with `mb_release_id` and `track_no`;
- S2-02: fills the album from an album URL;
- S2-07: a playlist in one go.

Those three are at `ours:docs/specs/2026-10-22-downloads-and-requests.md:103-111` and
`ours:docs/specs/2026-10-22-downloads-and-requests.md:183-186`. S2-05 (under E) runs the album job.

**Cost:** from SoulSync: 1.5 harness nights / build ours: 0.5 harness night.
- From SoulSync: the fixed setup plus turning off its scheduled retries, and its track-keyed row still drops the album identity that E needs.
- Build ours: S2-01, S2-02 and S2-07 are 3 features, at the unit's 6-10 features a night.

### E, album-first sourcing

**SoulSync: partly.** Goal E's three steps (`ours:docs/specs/2026-10-22-soulsync-review.md:41-42`), each marked
against SoulSync. The full read is in [04-soulseek.md, "When a track fails"](04-soulseek.md#when-a-track-fails),
including its goal E table, and folder choice is in [album requests](04-soulseek.md#album-requests-and-folder-choice).

1. "One peer's folder for the whole album." **Present.** A folder is pinned when it covers ≥ 80 % of the requested
   tracks (`SoulSync:core/downloads/master.py:1372-1382`) and scores ≥ 0.62 (`SoulSync:core/downloads/master.py:43`).
   Only the files that match wanted tracks are enqueued (`SoulSync:core/soulseek_client.py:2073-2097`).
2. "On trouble, switch to **one** other folder for the rest, preferring the same release." **Different.**
   - It walks up to 4 alternative folders, each only if it covers *all* that is still owed
     (`SoulSync:core/soulseek_client.py:2197-2259`).
   - Nothing prefers the same release: release identity returns None for every Soulseek peer
     (`SoulSync:core/download_plugins/release_identity.py:80-83`), and the bundle ignores the expected album duration
     (`SoulSync:core/soulseek_client.py:1948-1953`).
   - A verify failure never distrusts the folder: the retry clears the peer and download id the folder-drop check
     looks for (`SoulSync:core/downloads/monitor.py:410-413`, `SoulSync:web_server.py:16737-16751`).
3. "Per-track only as the last resort." **Present, with a difference.**
   - Tracks the folder did not supply go per-track to any peer (`SoulSync:core/downloads/task_worker.py:208-216`).
   - A bundle with no completed file falls back to per-track for the whole album
     (`SoulSync:core/soulseek_client.py:2148-2154`).
   - In that fallback, the batch's folder moves to whichever per-track download starts next
     (`SoulSync:web_server.py:16865-16872`), so one album can still spread across peers.
   - That source-reuse path takes a file at the base score ≥ 0.70 with no title veto, which is how ext-74's wrong song
     gets in (`SoulSync:web_server.py:16757-16762`).

Ours has none of this today. The only album signal is +4 for a folder named like the album
(`ours:sourcing/scorer.py:224-225`). S2-03..S2-06 plan the following
(`ours:docs/specs/2026-10-22-downloads-and-requests.md:112-182`):
- S2-03: a MusicBrainz release match;
- S2-04: a primary folder, plus one same-release secondary folder (lengths within 2 s, or the same MB release);
- S2-05: distrust a folder on one "not what it claims" finding;
- S2-06: one album path.

Running SoulSync would still leave it without the same-release rule and the one-switch bound. Its bundle and retry
code is woven through its task worker, monitor and staging ([04-soulseek.md](04-soulseek.md#when-a-track-fails)).
So the piece worth re-writing in S2-04 is small: the one-to-one track assignment `assign_album_tracks`
(`SoulSync:core/downloads/soulseek_identity.py:310-340`) and the folder score
(`SoulSync:core/downloads/master.py:438-516`). Re-writing them in our own words follows 04's "paraphrase, don't copy";
the MIT notice is needed only if code is copied.

**Cost:** from SoulSync: 1.5 harness nights / build ours: 1 harness night.
- From SoulSync: the fixed setup plus confining its output to an input folder, for a fallback that still breaks goal E's one-switch, same-release rule.
- Build ours: S2-03..S2-06 are 4 features after S1-01/S1-02 (`ours:docs/specs/2026-10-22-downloads-and-requests.md:97`), and S2-04/S2-05 are the largest features in S2, so they count at the slow end of the unit.

### Crates for DJing

**SoulSync: no.** The goal is playlists kept synced, Mixxx on a Rane One reading the same library, one DJ quality (D24),
the exact track (D26) and nothing downloaded without approval (D7) (`ours:docs/specs/2026-10-22-soulsync-review.md:43-44`).
SoulSync has no crate concept (*absence inferred*: `grep -rlIiw 'crate\|crates'` over its `.py/.js/.ts/.tsx/.html` finds
only a chat-badge test). The playlists it syncs are its own mirror list (`SoulSync:database/music_database.py:1385`).

- **Synced playlists: conflicts.** Its default reconcile adds every source id that is missing and removes every entry
  the source lacks, so a track Michael added by hand is removed and one he removed comes back
  (`SoulSync:core/sync/playlist_edit.py:96-108`). It appends with `songIdToAdd`, with no position
  (`SoulSync:core/navidrome_client.py:1800-1806`). Ours is insert-only at the Spotify position (D44,
  `ours:docs/specs/2026-10-17-amperfy-pivot.md:39`), and the crate flag lives in `crates.db` (D27,
  `ours:docs/specs/2026-10-17-amperfy-pivot.md:22`).
- **Mixxx reading the same library: not addressed, and the tags are at risk.** SoulSync has no DJ-software integration.
  Its code and docs never name Mixxx (*absence inferred*: `grep -rliI mixxx` over its `.py/.md/.js/.ts/.tsx/.json` finds
  nothing; a test names a playlist "Rekordbox Set", `SoulSync:tests/downloads/test_playlist_folder_exists.py:66`).
  Ours treats the file's tags as the record because they travel into Mixxx
  (`ours:docs/specs/2026-10-16-ownership-and-identity.md:24`). SoulSync clears every tag on import and rewrites from
  its matched source, or saves the file untagged (`SoulSync:core/metadata/enrichment.py:110-123`). On a collision it
  deletes or overwrites ([07-filing-library.md](07-filing-library.md#what-it-writes-into-tags-and-when)).
- **D24: conflicts.** Its quality gate reads the header's claim, and nothing detects a transcode
  (`SoulSync:core/quality/schema.py:171-172`, `SoulSync:core/imports/file_integrity.py:445-470`;
  [06-verification.md](06-verification.md#the-difference-that-matters)).
- **D26: conflicts.** On Soulseek an extended mix costs −0.025 and a radio edit −0.04, so either stands in for the plain
  cut. Those are the base penalties (`SoulSync:core/matching_engine.py:1246-1248`,
  `SoulSync:core/matching_engine.py:1204-1206`) halved on a match (`SoulSync:core/matching_engine.py:1421`;
  [03-matching.md](03-matching.md#remaster-live-extended-radio-edit)).
- **D7: conflicts** (goal C above).

**Would it write to the same Navidrome playlists and beets index as ours?**
- **Navidrome playlists: yes, if it shares Michael's account.**
  - It finds a playlist by case-insensitive name (`SoulSync:core/navidrome_client.py:1537`) among the configured
    account's own playlists, then overwrites it (`SoulSync:core/navidrome_client.py:1216-1233`).
  - It marks no playlist as its own, so a crate with a mirror's name would be adopted and reconciled
    ([07-filing-library.md](07-filing-library.md#how-it-edits-navidrome-playlists-and-with-what-guards)).
  - On its own Navidrome user its sync touches only that user's playlists. Its admin profile, though, may edit or delete
    any playlist the account sees (`SoulSync:web_server.py:18068-18085`), and Navidrome lets an admin edit another
    user's playlist (`ours:crates/playlist_edit.py:38`). So its Navidrome user must not be an admin, or the `amperfy`
    account's playlists are within reach.
- **beets index: not the database itself, but the library under it.**
  - SoulSync has no beets and never writes beets' `library.db`
    ([07-filing-library.md](07-filing-library.md#does-it-use-beets), `SoulSync:requirements.txt:21`).
  - It files under its own `transfer_path` with its own template (`SoulSync:core/settings.py:539`,
    `SoulSync:core/settings.py:915-919`). Pointed at `/srv/music`, it would be a second writer of the library that
    beets indexes.
  - That is the **two-writers conflict with D18**: the worker is the only process that downloads, runs beets or moves
    files into `/srv/music` (`ours:docs/specs/2026-10-13-next-session-design.md:72`,
    `ours:docs/architecture.md:76-77`).
  - beets' index would then list files that SoulSync's collisions and repair jobs deleted, and miss files nobody
    imported ([07-filing-library.md](07-filing-library.md#the-difference-that-matters)).
  - The only safe confinement is the fixed setup above: an input folder, its own non-admin Navidrome user, and its
    playlist sync off.

What crates need is built in ours:
- the crate switch;
- D44 placement (`ours:crates/placement.py:83-115`);
- D24 verify (`ours:sourcing/verify.py:433-447`);
- D26 sourcing, which rejects another version (`ours:sourcing/scorer.py:171-177`), and D26 matching, which leaves it
  ambiguous (`ours:sourcing/import_playlist.py:188-197`).

**Cost:** from SoulSync: not reachable without a fork (≥ 2 harness nights, then every upstream release) / build ours: 0 more harness nights.
- From SoulSync: its playlist sync, tagger, quality gate, version penalties and request paths would all have to change, which is a fork, not a configuration.
- Build ours: what is left (S2-07's playlist in one go, S1's fixes) is already counted under D and in the S1 run.
