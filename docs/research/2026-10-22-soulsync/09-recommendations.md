# 09 Recommendations: adopt, run beside, port pieces, or learn only

Feature V4-01 of run `dj-soulsync-review-2026-10-22` (spec `ours:docs/specs/2026-10-22-soulsync-review.md:158-171`).
Citations as in the README: `SoulSync:<path>:<line>` at `34bf7cf9c741`, `ours:<path>:<line>` at this run's base. A
claim with no citation carries the mark *unverified*. This file applies nothing: every spec change below is a
**draft, not applied**.

**Inputs.** The stage table, failure classes and decision table (README `## Stage-by-stage comparison`), the cost lines
of `## Fit to goals` (README), each section file's `## Worth taking?`, and 01-map.md's `## License` and
`## Maintenance health`. The S1 branch `origin/harness/dj-crate-streaming-2026-10-22-fixes` still does not exist
(`git ls-remote origin`, 2026-10-22, this session), so "ours (planned)" is the downloads spec, not code.

**Effort unit.** One *harness night* is one overnight run of this harness, about 6-10 features, or 1-2 human days
(the run's default, question 1 below; *unverified*). The queued downloads run is 23 features, about 3 harness nights
(README `## Fit to goals`). Every effort figure here is a judgment, not a measurement (*unverified* until a run does
the work). "Fixed setup" is the README's one-night cost of running SoulSync at all: its own compose project from a
pinned digest rather than `:latest` (`SoulSync:docker-compose.yml:8-9`), its own non-admin Navidrome user, its
`transfer_path` (`SoulSync:core/settings.py:539`) on an input folder, and its no-approval automations off
(`SoulSync:core/automation_engine.py:77-83`, `SoulSync:core/automation_engine.py:244-250`).

## Options

The four rows every option shares:
- **Maintenance pace** (01-map.md `## Maintenance health`): 101 releases, median 2.16 days between the latest 20
  (`ours:docs/research/2026-10-22-soulsync/01-map.md:351-352`). `core/downloads/` had 71 commits in 30 days
  (`ours:docs/research/2026-10-22-soulsync/01-map.md:435`), and one release merge was 275 files and +37,273 lines
  (`ours:docs/research/2026-10-22-soulsync/01-map.md:425`). One author holds 88.8 % of the contributions, so the bus
  factor is 1 (`ours:docs/research/2026-10-22-soulsync/01-map.md:378-384`). CI never tests the commit `:latest` is built from
  (`SoulSync:.github/workflows/docker-publish.yml:4-12`).
- **Licence** (01-map.md `## License`): MIT (`SoulSync:license.txt:1-18`). Any copy or substantial portion keeps the
  copyright line and the permission notice (`SoulSync:license.txt:10-11`), in the file header or a
  `THIRD_PARTY_NOTICES` that ships in the `dj-crates` image (`ours:docs/research/2026-10-22-soulsync/01-map.md:327-333`).
  Ideas re-implemented in our own words need no notice. The image's `spotipyFree` is GPL-3.0
  (`SoulSync:requirements.txt:88-95`).

### (a) Adopt wholesale

SoulSync replaces `sourcing/` (intake, scorer, fetch, verify, filer) and becomes the library's writer. Crates stays
for playlists and placement.

| Aspect | (a) Adopt wholesale |
|---|---|
| Effort | **≥ 4 harness nights** (≈ 4-8 human days, 1-2 weeks; *unverified*): the fixed setup (1), then a fork to restore D7, D24, D26 and D44, which config cannot reach (≥ 2, README `### Crates for DJing` cost line), then rewiring crates' approvals, placement and identity onto SoulSync's database and paths (≥ 1, *unverified*). |
| Risk | A **second library writer and no beets**: it files under its own template, deletes or overwrites on a collision (`SoulSync:core/settings.py:915-919`; 07-filing-library.md `### What it writes into tags, and when`), and its duplicate repair bins the other copies even when a playlist holds them, with no repoint (`SoulSync:core/library/duplicate_keep.py:36-54`, `SoulSync:core/repair_worker.py:4071-4091`), against D18 (`ours:docs/specs/2026-10-13-next-session-design.md:72`) and invariant 1 (`ours:CLAUDE.md:11-12`). **Tags lost**: it clears every tag and rewrites from whichever source matched (`SoulSync:core/metadata/enrichment.py:110-123`), and Mixxx reads those tags (`ours:docs/specs/2026-10-16-ownership-and-identity.md:24`). **D24**: its quality gate reads the header's claim (`SoulSync:core/quality/schema.py:171-172`) and nothing after download detects a transcode (06-verification.md `## The difference that matters`). **D26**: an extended mix or radio edit stands in for the plain cut (`SoulSync:core/matching_engine.py:1246-1248`). **D7**: the wishlist runs every 30 min from install (`SoulSync:core/automation_engine.py:77-83`). **Playlists**: its reconcile removes what Michael added (`SoulSync:core/sync/playlist_edit.py:96-108`). **Trash**: quarantine is purged every 12 h (`SoulSync:core/automation_engine.py:244-250`). **Upgrade risk**: a floating image built from untested commits (`SoulSync:docker-compose.yml:8-9`). |
| Ongoing maintenance | A fork rebased on a release about every 2 days (Maintenance pace, above), carrying patches into `core/downloads/` at its 71 commits a month. Each rebase is at least an hour of review and conflicts (*unverified*: timing the first two rebases onto upstream releases would verify it). If the one maintainer stops, the fork is ours alone. |
| Licensing | A fork is a copy: keep `license.txt` whole. Shipping its image brings `spotipyFree`'s GPL-3.0 (`SoulSync:requirements.txt:88-95`). |
| What changes or is lost in ours | Lost: `sourcing/scorer.py`, `sourcing/fetch.py`, `sourcing/verify.py` (D24's decode checks, `ours:sourcing/verify.py:433-447`), `sourcing/filer.py` and beets (`ours:sourcing/filer.py:1-5`), the approvals table (`ours:crates/store.py:105-108`), the four tested invariants, and the queued S1-S4 run. Kept but rewired: `crates/placement.py` and `crates/playlist_edit.py`. Gained: twelve intake source keys (`SoulSync:core/playlists/sources/bootstrap.py:46-116`), a 24-page UI (`SoulSync:webui/src/platform/shell/route-manifest.ts:29-61`), album batches today (`SoulSync:core/wishlist/processing.py:211`). |

### (b) Run it beside ours

SoulSync does some jobs (intake breadth, catalog search, or the downloads themselves) and ours keeps verify, beets,
placement and playlists. The fixed setup is the confinement.

| Aspect | (b) Run it beside ours |
|---|---|
| Effort | **≈ 2.5 harness nights** (≈ 2.5-5 human days, about a week; *unverified*): the fixed setup (1), an approval patch on its three admin request paths (≈ 1, README `### C, requests from the phone` cost line), and a watcher in our worker that hands SoulSync's output folder to verify and beets (≈ 0.5; ours files only from `.staging` today, `ours:sourcing/filer.py:3`). |
| Risk | The approval patch is lost or bypassed on an upgrade (it touches `SoulSync:web_server.py:19512-19517`, `SoulSync:api/request.py:287-306` and the wishlist run). Two clients of one slskd (below). A mis-set path writes straight into `/srv/music`. A second Navidrome scanner (`SoulSync:core/web_scan_manager.py:97-117`) makes our duplicate cleanup refuse more often, since it refuses during a scan (`ours:scripts/duplicate_cleanup.py:405-410`). Its retries run without a new approval (`SoulSync:core/wishlist/retry_backoff.py:7-17`). |
| Ongoing maintenance | The approval patch is carried on every release (Maintenance pace, above); the fixed setup is re-checked on each upgrade (new automations ship enabled, `SoulSync:core/automation_engine.py:77-83`). |
| Licensing | (b) needs the approval patch, so the image is a modified copy: keep `license.txt` and the notice in it. Its `spotipyFree` brings GPL-3.0 obligations if we ship that image (`SoulSync:requirements.txt:88-95`). |
| What changes or is lost in ours | New: an input-folder watcher in `sourcing/worker.py`, a second Navidrome user. Changed: `sourcing/fetch.py`'s transfer handling must tell its own records from SoulSync's (S1-04). Lost: nothing, but goal E's same-release rule and D26 do not apply to what SoulSync picks; ours can only reject the result afterwards. |

**Integration points** (what ours would call or watch):
1. **Its output folder.** SoulSync files under `soulseek.transfer_path` (`SoulSync:core/settings.py:539`) with its own
   template (`SoulSync:core/settings.py:915-919`). Pointed at an input folder outside `/srv/music`, our worker would
   watch it and run each file through verify and the beets singleton import (`ours:sourcing/filer.py:1-5`). Its tags
   would already be rewritten by then (`SoulSync:core/metadata/enrichment.py:110-123`).
2. **Its key-scoped API.** `/api/v1` is mounted at `SoulSync:web_server.py:1829` behind API keys
   (`SoulSync:api/auth.py:40-101`). Crates could, after Michael's approval, call `POST /api/v1/request` with a query
   (`SoulSync:api/request.py:345-363`) and poll `GET /api/v1/request/<id>` (`SoulSync:api/request.py:432-462`). The
   request takes free text and downloads the best hit itself (`SoulSync:api/request.py:272-341`), so the approval would
   cover a query, not a file.
3. **slskd, shared.** SoulSync talks to slskd itself (`SoulSync:core/soulseek_client.py:210`). Its cleanups default to
   scope `own`, so they remove only the transfers and searches it created
   (`SoulSync:core/soulseek_client.py:1370-1380`, `SoulSync:core/settings.py:561`); scope `all` deletes every client's
   finished transfers (`SoulSync:core/soulseek_client.py:1607-1612`). Ours today sends a DELETE for any finished
   record of the same filename at that peer before it enqueues, whoever made it (`ours:sourcing/fetch.py:425-428`);
   without `remove=true` slskd keeps the record (`ours:docs/specs/2026-10-22-downloads-and-requests.md:39-43`), but
   after S1-04 adds `remove=true` that loop would really delete SoulSync's record. It also reads `mine[-1]` by
   filename (`ours:sourcing/fetch.py:432-433`), so it could take SoulSync's record for its own until S1-04's "id not
   there before the enqueue" rule lands (`ours:docs/specs/2026-10-22-downloads-and-requests.md:80-81`). Beside
   SoulSync, that loop must touch only ids ours enqueued.
4. **Navidrome.** It is a Subsonic client of Navidrome (`SoulSync:core/navidrome_client.py:451-481`) and triggers
   scans (`SoulSync:core/web_scan_manager.py:97-117`).

**Conflicts:**
- **Two writers to the library and beets (D18).** The worker is the only process that downloads, runs beets or moves
  files into `/srv/music` (`ours:docs/specs/2026-10-13-next-session-design.md:72`, `ours:docs/architecture.md:76-77`).
  SoulSync has no beets (`SoulSync:requirements.txt:21`; 07-filing-library.md `### Does it use beets?`) and would be a
  second writer of the library beets indexes unless confined to the input folder (README `### Crates for DJing`).
- **Navidrome playlists (D27).** The crate flag lives in `crates.db`
  (`ours:docs/specs/2026-10-17-amperfy-pivot.md:22`). SoulSync finds a playlist by name among its account's playlists
  and overwrites it (`SoulSync:core/navidrome_client.py:1216-1233`), and its reconcile removes entries the source lacks
  (`SoulSync:core/sync/playlist_edit.py:96-108`). On Michael's account a crate with a mirror's name would be adopted and
  rewritten; it needs its own user with playlist sync off.
- **The approval gate (D7).** "Automatic downloads only after Michael has approved at least one manual download and said go"
  (`ours:docs/specs/2026-10-13-next-session-design.md:61`). SoulSync's admin paths download at once or on the
  30-minute timer (`SoulSync:api/request.py:287-306`, `SoulSync:core/automation_engine.py:77-83`) and retry without
  a new approval (`SoulSync:core/wishlist/retry_backoff.py:7-17`). Approval exists only for member profiles
  (`SoulSync:api/music_requests.py:247-266`).
- **The `amperfy` account.** Off-limits to us (`ours:CLAUDE.md:29`). SoulSync's admin profile may edit or delete any
  playlist its Navidrome account sees (`SoulSync:web_server.py:18068-18085`), and a Navidrome admin can edit another
  user's playlist (`ours:crates/playlist_edit.py:38`). Its Navidrome user must not be an admin.

### (c) Port specific pieces

Ours stays as it is and takes named pieces into the queued S-features, re-written in our own words (the brief forbids
copying in this run; `ours:docs/specs/2026-10-22-soulsync-review.md:21-24`).

| Aspect | (c) Port specific pieces |
|---|---|
| Effort | **≈ 1 harness night on top of the queued 3** (≈ 1-2 human days; *unverified*): the rows marked "inside S…" fold into S-features already planned and add about 0.25 night to the S2-S4 run (step 4); the rest (rows 4, 6, 10, 12, row 3's bytes check and the byte-based stall guard, which wait for a capture or for B) go to a follow-up spec of about 0.75 night (step 6). |
| Risk | A re-written piece carries SoulSync's assumptions into ours: its thresholds were tuned against its fuzzy scores (`SoulSync:core/matching_engine.py:1517-1529`), so a ported rule is re-derived on our key rules and our fixtures, never taken with its numbers. Ported slskd behaviour is untested against slskd 0.26.1 until the S4 captures (04-soulseek.md `### What our S1-04 and S2 should capture`). |
| Ongoing maintenance | None from upstream: no runtime dependency and no fork. Upstream's pace matters only if we re-read it later (the cited lines drift within days, `ours:docs/research/2026-10-22-soulsync/01-map.md:435`). |
| Licensing | Re-written in our words: no notice. If any line is copied, add `THIRD_PARTY_NOTICES` with SoulSync's copyright line and permission notice (`SoulSync:license.txt:1-18`); it would be the first licence text in our tree (`ours:docs/research/2026-10-22-soulsync/01-map.md:333`). |
| What changes or is lost in ours | Changes: `sourcing/scorer.py`, `sourcing/fetch.py`, `sourcing/slskd_client.py`, `sourcing/verify.py`, the planned `sourcing/album.py`, `crates/placement.py`, the S3 request endpoints, `web/`. Lost: nothing. |

Candidate modules:

| # | SoulSync file(s) | Replaces or extends in ours | Port effort | MIT notice |
|---|---|---|---|---|
| 1 | `core/downloads/soulseek_identity.py` one-to-one track assignment (`SoulSync:core/downloads/soulseek_identity.py:310-340`), folder score and coverage floor (`SoulSync:core/downloads/master.py:438-516`, `SoulSync:core/downloads/master.py:1372-1382`) | the planned `sourcing/album.py` (S2-04, `ours:docs/specs/2026-10-22-downloads-and-requests.md:120-132`) | inside S2-04 | re-write: none |
| 2 | `core/downloads/peer_observation.py` measured throughput, 1 h memory (`SoulSync:core/downloads/peer_observation.py:28-50`) | the advertised-speed estimate in `sourcing/scorer.py` (`ours:sourcing/scorer.py:122-135`), as an input to S2-04's planner | inside S2-04 | re-write: none |
| 3 | `core/downloads/monitor.py` `remove=True` on cancel, one global listing per tick, "Completed with fewer bytes than the size is not done" (`SoulSync:core/downloads/monitor.py:690`, `SoulSync:core/downloads/monitor.py:759`, `SoulSync:core/downloads/monitor.py:637-644`) | `remove_download` and the poll in `sourcing/slskd_client.py` and `sourcing/fetch.py` (`ours:sourcing/slskd_client.py:86-87`, `ours:sourcing/fetch.py:425-446`), S1-04 and S2-05 | `remove=true` and the global listing inside S1-04 / S2-05; the bytes check in the follow-up (needs `bytesTransferred` captured) | re-write: none |
| 4 | `core/soulseek_client.py` login probe (`SoulSync:core/soulseek_client.py:2668-2690`), which guesses the field's casing (`SoulSync:core/soulseek_client.py:2677-2679`) | a `server()` call in `sourcing/slskd_client.py`, waited on before S1-06's second attempt, once `GET /server` is captured (step 5) | follow-up, 0.1 night | re-write: none |
| 5 | `core/matching/audio_verification.py` title FAIL and its length escape (`SoulSync:core/matching/audio_verification.py:829-831`, `SoulSync:core/matching/audio_verification.py:565-572`, `SoulSync:core/matching/acoustid_candidates.py:171-186`) | `_acoustid_check` in `sourcing/verify.py` (`ours:sourcing/verify.py:402-404`), S1-02 | inside S1-02 | re-write: none |
| 6 | `core/soulseek_client.py` quarantine source block, a failed `(peer, file)` never offered again (`SoulSync:core/soulseek_client.py:2710-2749`) | a rejection in `sourcing/scorer.py` from the row's events in `crates/store.py`; not planned today (`ours:sourcing/fetch.py:462-464` deletes and forgets) | 0.2 night | re-write: none |
| 7 | `core/imports/library_check.py` "already owned only on an exact id pairing" (`SoulSync:core/imports/library_check.py:12-17`) | `choose` in `sourcing/import_playlist.py` (`ours:sourcing/import_playlist.py:155`) once rows carry `mb_recording_id` (S2-03) | inside S2-03 | re-write: none |
| 8 | `core/search/by_id.py` link keyword → kind table and `spotify:` URIs (`SoulSync:core/search/by_id.py:83-155`) | the link parser behind S3-01's `POST /api/requests` (`ours:docs/specs/2026-10-22-downloads-and-requests.md:191-196`) | inside S3-01 | re-write: none |
| 9 | `core/spotify_client.py` 2026 rules, throttle and bans (`SoulSync:core/spotify_client.py:1510-1530`, `SoulSync:core/spotify_client.py:90`, `SoulSync:core/spotify_client.py:137`, `SoulSync:core/spotify_client.py:375-461`) | S3-06's capture script now, the Spotify provider behind S3-02's interface in the next run (`ours:docs/specs/2026-10-22-downloads-and-requests.md:203-205`) | inside S3-06; provider later | re-write: none |
| 10 | `core/library/navidrome_identity.py` wait for an idle scan before a playlist write (`SoulSync:core/library/navidrome_identity.py:22-40`) | `crates/placement.py`, which does not wait (`ours:crates/placement.py:83-115`) | 0.1 night | re-write: none |
| 11 | `core/album_consistency.py` files already in the album win (`SoulSync:core/album_consistency.py:580-585`) | the album identity S2-06 writes in `.staging` (`ours:docs/specs/2026-10-22-downloads-and-requests.md:171-178`) | inside S2-06 | re-write: none |
| 12 | `webui/static/sw.js` and `webui/static/manifest.json` (`SoulSync:webui/static/sw.js:93-111`, `SoulSync:webui/static/manifest.json:5-36`) | `web/manifest.webmanifest` (`ours:web/manifest.webmanifest:1-9`) plus a new static-only `web/sw.js` and a `share_target` to S3-01 | 0.2 night, after B (question 6) | re-write: none |
| 13 | `core/requests/music.py` request states (`SoulSync:core/requests/music.py:20`, `SoulSync:core/requests/music.py:102-115`) | the derived status in S3-03's responses (`ours:docs/specs/2026-10-22-downloads-and-requests.md:207-211`) | inside S3-03 | re-write: none |
| 14 | the issue-numbered matching regressions as test shapes (`SoulSync:core/matching_engine.py:323-367`, `SoulSync:core/text/title_match.py:75-105`, `SoulSync:core/matching_engine.py:1288-1306`) | new cases in `tests/test_scorer.py` (S1-01) | inside S1-01 | filename shapes only: none |
| 15 | `core/imports/file_integrity.py` length check whenever an expected length is known (`SoulSync:core/imports/file_integrity.py:551-598`) | fetch drops the expected length when it calls the file "another version" (`ours:sourcing/fetch.py:411-417`); a one-line check in S1-01's review (06-verification.md `## Worth taking?`) | inside S1-01 | re-write: none |

Not candidates, each for a stated reason in its section: the matcher's weighted thresholds (03-matching.md), the
streaming-service getters and the orchestrator (05-other-sources.md, question 4), the tagger and playlist sync
(07-filing-library.md), the UI itself (08-ui-api.md). Two more stay as review notes, not ports: the playlist write
guard's "prove the ids exist" cross-check (`SoulSync:core/library/navidrome_identity.py:43-72`; ours already checks
navidrome.db, `ours:crates/playlist_edit.py:116-141`), and browse-before-trust, which needs the peer browse the
downloads spec leaves out on purpose (`ours:docs/specs/2026-10-22-downloads-and-requests.md:235`). The backup idea "replace a snapshot only once it passes an
integrity check" (`SoulSync:core/db_integrity.py:83-140`) is already ours (`ours:scripts/snapshot-crates-db.sh:17`).

### (d) Learn only

Ours takes nothing by module; the report stays a reference, and the S-run is built as written.

| Aspect | (d) Learn only |
|---|---|
| Effort | **0 harness nights** beyond the queued 3. |
| Risk | The gaps SoulSync shows stay open: the stale-record and same-filename hazard beyond S1-04's rule (row 3 above), a VPN-drop retry that lands inside the ~10 s logout (`ours:docs/specs/2026-10-22-downloads-and-requests.md:44-47`), a failed `(peer, file)` offered again, an album plan with ad hoc assignment instead of a maximum matching, and playlist writes during a scan. |
| Ongoing maintenance | None. |
| Licensing | None. |
| What changes or is lost in ours | Nothing changes; the S-run is built as specified. |

## Recommendation

**Option (c): port specific pieces, re-written in our own words, into the queued S-runs; no SoulSync process, fork or
copied code.** (a) and (b) fail Michael's decisions in ways config cannot fix: D7, D18, D24, D26 and D44 all conflict
(README `### Michael's decisions`), and crates is "not reachable without a fork" (README `### Crates for DJing`).
Their maintenance is a fork or a patch against a release every two days with a bus factor of 1. (d) leaves cheap,
specific fixes on the table, most of which fit inside features already queued. Because the recommendation is (c), no
SoulSync trial is proposed (question 3).

Next steps, in order:
1. **Apply** the S1 spec deltas below (S1-01, S1-02, S1-04) to `docs/specs/2026-10-22-downloads-and-requests.md`
   before the `dj-crate-streaming-2026-10-22-fixes` run starts. Size: one short docs session (< 0.1 harness night),
   Michael's yes first.
2. **Run** S1 (`dj-crate-streaming-2026-10-22-fixes`) on `docs/specs/2026-10-22-downloads-and-requests.md` S1, 8
   features with the deltas. Size: 1 harness night.
3. **Apply** the S2-S4 deltas (S2-03, S2-04, S2-05, S2-06, S3-01, S3-03, S3-06, S4-01) to the same spec before the
   `dj-crate-streaming-2026-10-22-build` run. Size: one short docs session (< 0.1 harness night).
4. **Run** S2-S4 (`dj-crate-streaming-2026-10-22-build`) on the same spec's S2-S4, 15 features. Size: about 2.25
   harness nights (2 as planned, plus about 0.25 for the folded rows of the (c) table), the album ones at the slow end.
5. **Capture** the slskd shapes in Michael's morning (the S4-01 checklist, `docs/plans/2026-10-22-downloads-checklist.md`,
   delta below): the multi-file enqueue response, transfer records per state, `DELETE … ?remove=true`, the search
   timeout key, `GET /server` during a drop. Size: about 30 min live, Michael's (D7).
6. **Write** a follow-up spec for the pieces that wait for step 5 or for B (rows 4, 6, 10, 12 of the (c) table: the
   `GET /server` login wait before S1-06's second attempt, a remembered failed `(peer, file)`, a scan wait before
   placement, the service worker and `share_target` once B is answered; plus the `bytesTransferred` checks: "Completed
   with fewer bytes than the size is not done" and a byte-based stall guard for album folders) at
   `docs/specs/<date>-soulsync-followups.md`. Size: one docs session, then about 0.75 harness night to build.
7. **Re-read** `core/spotify_client.py` at SoulSync's then-current release when the next run builds the Spotify
   provider behind `sourcing/catalog.py` (S3-02's interface), after S3-06's capture. Size: a quarter of a harness night of
   reading.

## What it means for the queued runs

Keep 12, change 11, drop 0 of the 23 S-features (`ours:docs/specs/2026-10-22-downloads-and-requests.md:61-230`).
Nothing in SoulSync argues for dropping one: where it differs, ours is the stricter design or SoulSync shows the same
need.

| Feature | Keep / change / drop | Why |
|---|---|---|
| S1-01 reject a title slot naming another song | change | SoulSync's base-title veto stops ext-74 by only 0.025 (0.275 against a 0.30 floor, 03-matching.md's worked figure, `ours:docs/research/2026-10-22-soulsync/03-matching.md:316-319`) and is missing on its folder-reuse path (`SoulSync:core/matching_engine.py:1307-1335`, `SoulSync:web_server.py:16757-16762`); its issue-numbered regressions are free test shapes for ours (03-matching.md `## Worth taking?`). |
| S1-02 AcoustID disagreement without a recording id | change | It is SoulSync's title FAIL (`SoulSync:core/matching/audio_verification.py:829-831`), which also turns a FAIL into a skip when every top match is far from the file's length (`SoulSync:core/matching/acoustid_candidates.py:171-186`; 06-verification.md `## The difference that matters`). |
| S1-03 never rename a row onto another song | keep | SoulSync has no such guard and rewrites tags from whatever matched (`SoulSync:core/metadata/enrichment.py:110-123`; 07-filing-library.md `### What it writes into tags, and when`). |
| S1-04 slskd transfer hygiene | change | SoulSync removes its own finished records every 5 min and leaves other clients' alone by default (`SoulSync:core/automation_engine.py:190-196`, `SoulSync:core/soulseek_client.py:1589-1600`; 04-soulseek.md `### Transfers`). Its "fewer bytes than the size" check (`SoulSync:core/downloads/monitor.py:637-644`) needs an uncaptured field, so it goes to the follow-up (step 6). |
| S1-05 a reason names the step and the endpoint | keep | SoulSync turns every non-2xx into None and loses the status this needs (`SoulSync:core/soulseek_client.py:235-306`; 04-soulseek.md `### Errors and outages`). |
| S1-06 one more source on a transfer error | keep | SoulSync retries at once into the ~10 s logout although it has a login probe (`SoulSync:core/downloads/monitor.py:936-937`, `SoulSync:core/soulseek_client.py:2668-2690`; 04-soulseek.md `### Errors and outages`). The probe guesses the field's casing (`SoulSync:core/soulseek_client.py:2677-2679`), so our login wait waits for the `GET /server` capture (step 5) and goes to the follow-up (step 6); S1-06 stays as written. |
| S1-07 ask the library before downloading | keep | SoulSync's "have it" is title and artist at 0.7 with no duration (`SoulSync:services/sync_service.py:705-714`), and its exact-id check runs only after a download (`SoulSync:core/imports/library_check.py:12-17`; 03-matching.md `## The difference that matters`); ours reuses the import's exact rules before searching, and the exact-id pairing lands with S2-03's ids. |
| S1-08 `wanted reopen` | keep | SoulSync has no logged reverse for a wrong file; it hard-deletes (`SoulSync:core/automation_engine.py:244-250`; 07-filing-library.md `## The difference that matters`). |
| S2-01 requests in crates.db | keep | SoulSync keeps the album only in a JSON blob on a track row (`SoulSync:database/music_database.py:807-817`; 02-intake.md `## The difference that matters`), the weakness S2-01 avoids. |
| S2-02 an album URL fills the album | keep | Same reason: SoulSync groups requests back into albums only for display (`SoulSync:core/requests/music.py:50-99`). |
| S2-03 MusicBrainz release match | change | SoulSync's "already owned only on an exact MBID/ISRC pairing" (`SoulSync:core/imports/library_check.py:12-17`; 03-matching.md `## Worth taking?`) is cheap once rows carry `mb_recording_id`. |
| S2-04 album-first plan | change | SoulSync's folder logic is the working example: one-to-one assignment by maximum matching and measured peer speed (`SoulSync:core/downloads/soulseek_identity.py:310-340`, `SoulSync:core/downloads/peer_observation.py:28-50`; 04-soulseek.md `### Album requests and folder choice`). |
| S2-05 album job in the worker | change | SoulSync polls one global listing per tick and cancels a peer frozen for 180 s with `remove=True` (`SoulSync:core/downloads/monitor.py:759`, `SoulSync:core/soulseek_client.py:2405-2626`; 04-soulseek.md `### When a track fails`). |
| S2-06 album path | change | SoulSync's album consistency lets files already in the album folder win, never rewriting them (`SoulSync:core/album_consistency.py:580-585`; 07-filing-library.md `## Worth taking?`). |
| S2-07 a playlist in one go | keep | SoulSync's playlist sync removes and re-adds entries (`SoulSync:core/sync/playlist_edit.py:96-108`); ours stays insert-only (D44) and only adds one approval. |
| S3-01 `POST /api/requests` | change | SoulSync's link table maps path keywords and `spotify:` URIs to kinds but has no playlist kind (`SoulSync:core/search/by_id.py:83-91`; 08-ui-api.md `## Worth taking?`). |
| S3-02 catalog search | keep | SoulSync's adapter shape, one normalized track per source (`SoulSync:core/playlists/sources/base.py:64-115`; 02-intake.md `## Worth taking?`), matches the planned provider interface; MusicBrainz alone is right until a Spotify capture exists. |
| S3-03 list, preview, approve | change | SoulSync's request states (`SoulSync:core/requests/music.py:20`) are what a client shows; ours derives them from rows (S2-01) and should name them in the response. |
| S3-04 CLI | keep | Every SoulSync request path an admin uses downloads at once or on a timer (`SoulSync:api/request.py:287-306`; 08-ui-api.md `## The difference that matters`); ours keeps approve as Michael's explicit step, and the CLI is that step without a client. |
| S3-05 `docs/api.md` | keep | SoulSync's request API is a POST plus a status poll by id (`SoulSync:api/request.py:432-462`; 08-ui-api.md `### A request from the phone`), the shape S3-03 already plans; nothing to change. |
| S3-06 `scripts/capture_spotify.py` | change | SoulSync never sleeps through a Retry-After: over 60 s it stops all calls (`SoulSync:core/spotify_client.py:137`, `SoulSync:core/spotify_client.py:375-461`; 02-intake.md `### Spotify`). |
| S4-01 downloads checklist | change | 04-soulseek.md `### What our S1-04 and S2 should capture` lists six slskd shapes we have never captured and SoulSync guesses at, e.g. the `/server` field casing (`SoulSync:core/soulseek_client.py:2677-2679`); five fit the spec (the peer browse is out on purpose, `ours:docs/specs/2026-10-22-downloads-and-requests.md:235`). |
| S4-02 whole-run review | keep | Nothing in SoulSync bears on it; its CI does not test the released commit (`SoulSync:.github/workflows/docker-publish.yml:4-12`), which argues for the review. |

### Spec delta: S1-01

*Status: draft, not applied.* Append to S1-01 (`ours:docs/specs/2026-10-22-downloads-and-requests.md:62-67`):

> Add scorer tests for these filename shapes, paraphrased from SoulSync's matching regressions (no code copied):
> `Title (Live)` vs `Title - Live`; two remixes of one song by different remixers; "Dani California" offered for
> "Californication" (rejected); a same-artist sibling track in the right album folder (rejected by the title slot).
> The expected result of the first two follows our identity rules (`identity.parse_title`, D26), not SoulSync's.

### Spec delta: S1-02

*Status: draft, not applied.* Append to S1-02 (`ours:docs/specs/2026-10-22-downloads-and-requests.md:68-72`):

> Exception: when every returned recording with a usable length is more than 10 s from the file's length, the result
> is a warning ("AcoustID's matches do not fit this file's length"), not a finding. Test: a lookup naming another title
> at 0.9 with all lengths 60 s off gives a warning.

(The 10 s figure is a draft value, *unverified*; SoulSync's own bound is 60 s or 35 % (`SoulSync:core/matching/acoustid_candidates.py:118-124`), used by the tie rule at `SoulSync:core/matching/acoustid_candidates.py:171-186`
and the S1 session should set ours from our fixtures.)

### Spec delta: S1-04

*Status: draft, not applied.* Add two bullets to S1-04 (`ours:docs/specs/2026-10-22-downloads-and-requests.md:76-81`):

> - Once a file is filed (or fails verify), fetch removes its own transfer record (`?remove=true`), so the next
>   attempt at the same file never sees it.
> - The "forget earlier attempts" loop before an enqueue (`sourcing/fetch.py`) removes only records whose ids fetch
>   logged as its own in the row's events; a record of the same file made by another slskd client is left alone.

(Not in S1: the "fewer bytes than the size" check needs `bytesTransferred`, which neither our fixtures nor the fake
carry; it goes to the follow-up spec after the S4-01 capture, step 6.)

### Spec delta: S2-03

*Status: draft, not applied.* Append to S2-03 (`ours:docs/specs/2026-10-22-downloads-and-requests.md:112-119`):

> With `mb_recording_id` stored, S1-07's library check pairs on it first: a library song with the same MusicBrainz
> recording id is a same-recording hit even when the names differ. When the ids differ or either is missing, the
> import's rules apply as before (a different recording can still be the same version under D22). The id is the song's `musicBrainzId`
> (`ours:subsonic/client.py:76`); test on the fake Navidrome's `mbz_recording_id` column (`ours:subsonic/fake_server.py:75`).

### Spec delta: S2-04

*Status: draft, not applied.* In S2-04 (`ours:docs/specs/2026-10-22-downloads-and-requests.md:123-126`), replace the "Group files" bullet with the first bullet below, and add the second after the "primary" bullet:

> - Group files by (peer, directory). In each folder, map rows to files one to one by maximum matching over the
>   scorer's per-file rules (S1-01 included, policy D24): an edge only where a file is acceptable for that row; no
>   file serves two rows.
> - Speed in the tie-break is the peer's measured throughput when the caller passes one in (a map peer → bytes/s
>   that the worker keeps in memory for 1 h from its own finished transfers), else the advertised speed as today. The
>   planner stays pure: the map is an input, like the search response.

### Spec delta: S2-05

*Status: draft, not applied.* Add to S2-05's worker bullets (`ours:docs/specs/2026-10-22-downloads-and-requests.md:142-148`):

> - An album job polls the global `GET /transfers/downloads` once per tick (the call `SlskdClient.downloads()` already
>   makes without a peer), not each peer, and reads only `id`, `filename` and `state`.

(Not in S2: a byte-based stall guard, "a folder whose bytes have not moved for 180 s is a transfer error", needs
`bytesTransferred`; it goes to the follow-up spec after the S4-01 capture, step 6. Until then S2-05's start timeout
covers a peer that never starts.)

### Spec delta: S2-06

*Status: draft, not applied.* Append to S2-06's second bullet (`ours:docs/specs/2026-10-22-downloads-and-requests.md:171-173`):

> If the album folder already holds files (an earlier request for the same album), the new track takes their album,
> albumartist, year and release id instead of the request's, and the files already there are never rewritten. A
> conflict between the two (another release id) makes the row `review`, not filed.

### Spec delta: S3-01

*Status: draft, not applied.* Append to S3-01 (`ours:docs/specs/2026-10-22-downloads-and-requests.md:191-196`):

> The link parser maps the path keyword to a kind: `track` → track, `album` → album, `playlist` → playlist, and takes
> `spotify:<kind>:<id>` URIs the same way; other keywords are 400 "unknown link kind". Tests on each form.

### Spec delta: S3-03

*Status: draft, not applied.* Append to S3-03 (`ours:docs/specs/2026-10-22-downloads-and-requests.md:207-211`):

> Each request carries a derived `status`, the first that applies: `done` (every row filed or in the library),
> `failed` (no row filed and none left that can still be filed), `partly` (some rows filed, the rest open, in
> progress or failed), `approved` (approved, none filed yet), `open` (nothing approved). Derived from the rows each
> time (S2-01), never stored.

### Spec delta: S3-06

*Status: draft, not applied.* Add a bullet to S3-06 (`ours:docs/specs/2026-10-22-downloads-and-requests.md:219-221`):

> - On a 429 it stops: it prints the `Retry-After` value and exits non-zero, with no sleep and no retry. Tested with
>   the stub opener.

### Spec delta: S4-01

*Status: draft, not applied.* Append to S4-01 (`ours:docs/specs/2026-10-22-downloads-and-requests.md:224-227`):

> Add the slskd capture steps from `docs/research/2026-10-22-soulsync/04-soulseek.md` ("What our S1-04 and S2 should
> capture"): a multi-file enqueue response, transfer records for each state including two records of one file,
> `DELETE …?remove=true` on a running and a finished record, `POST /searches` with each timeout key, and `GET /server`
> during a VPN drop. Each transfer record keeps `bytesTransferred` and `averageSpeed`, which the follow-up's checks
> read. The sixth capture there, the peer browse, stays out, as the spec says (`ours:docs/specs/2026-10-22-downloads-and-requests.md:235`).
> Each step says where the fixture goes and which feature reads it.

## Questions for Michael

Each has the simplest assumption taken; answer in `INBOX.md` to change it. The brief keeps this run's writes under
`docs/research/` (`ours:.harness/runs/dj-soulsync-review-2026-10-22/brief.md:2`), so none is recorded as a `D<n>` in
the pivot spec; a later run that applies a delta records the ones it needs there.

| # | Question | Assumption taken | Used in |
|---|---|---|---|
| 1 | What is one harness night worth? (initializer 1) | 6-10 features, 1-2 human days | every effort figure in `## Options` and every size in `## Recommendation` |
| 2 | Which B option is the baseline? (initializer 2) | option 1: Amperfy, our web client as a phone web app, an iOS Shortcut | (c) row 12, step 6, the B paragraph of README `## Fit to goals` that the cost lines rest on |
| 3 | Should SoulSync be tried for real? (initializer 3) | no; only if the recommendation were (a) or (b), as Michael's own isolated trial, never on `/srv/music` | `## Recommendation` (no trial, since it is (c)); the (a) and (b) risk rows |
| 4 | Are streaming-service sources out (Deezer, Tidal, Qobuz, Amazon, HiFi, YouTube, and SoundCloud, which the initializer's list missed)? (initializer 4, V2-04) | out | the (c) "not candidates" list; (a)'s gains |
| 5 | Does Spotify stay "his own developer app only"? (initializer 5) | yes; SoulSync's public and scraper paths are lessons only | (c) row 9, the S3-06 delta, step 7 |
| 6 | Should the web client get a service worker and a `share_target`? (V2-07) | yes, as a small follow-up once B is answered; nothing built now | (c) row 12, step 6 |
| 7 | Hold an album's verified files in `.staging` until the job ends, so Navidrome never shows half an album? (V2-05) | no: file each row as it lands (today's behaviour) | the S2-05 and S2-06 rows and deltas |
| 8 | Does D7 mean "every download needs an approval"? Its text is "Automatic downloads only after Michael has approved at least one manual download and said go" (V3-01) | yes: nothing downloads without his approval, and a retry counts against the same approval | (a) and (b) conflicts, the S1-06 row |
| 9 | Should ours log in to Spotify with his own app (authorization code) so private playlists are reachable? (V3-02's goal C cost) | no for the queued runs: Client Credentials only (S3-06); the login is a later feature of about 0.5 harness night | the S3-06 row, step 7 |
| 10 | Should the eleven spec deltas be applied before the S-runs start? (this feature) | yes, all eleven as drafted, by a short docs session before each run; none applied by this run | `## Recommendation` steps 1 and 3, `## What it means for the queued runs` |
