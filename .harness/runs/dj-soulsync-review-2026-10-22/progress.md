# Progress log — run `dj-soulsync-review-2026-10-22` (branch `harness/dj-soulsync-review-2026-10-22`)

What this file is: the shared memory of the agent harness for this run. Each session appends one entry **at the top**
(newest first) when it finishes a feature: what it wrote, what it learned, what it asks. Nobody edits older entries.
The feature list is `.harness/runs/dj-soulsync-review-2026-10-22/feature_list.json`: array order is priority order; a
session gets the first feature whose `passes` is false and whose `after` all pass, and may flip only its own `passes`.
Michael steers through `INBOX.md` on this branch (first line `status: run|pause|stop`; answers under `## Answers`).
Every session reads `INBOX.md` and this file first, then the spec `docs/specs/2026-10-22-soulsync-review.md` and the
brief `brief.md` (the brief wins on scope).

### 2026-10-22 10:50 · V2-04 · passes
- **New:** `docs/research/2026-10-22-soulsync/05-other-sources.md` (~400 lines, 202 unique SoulSync cites, 4 `*unverified*` marks). It has 12 source paragraphs, each with mechanism, credentials, embedded secrets and a ToS/legal flag: 7 `streaming rip` (Deezer, Tidal, Qobuz, Amazon, HiFi, YouTube, SoundCloud), 4 `grey` (JioSaavn, torrent, Usenet/Prowlarr, Lidarr), 1 `clean` (Bandcamp). `### How the orchestrator chooses` has an ASCII flow; then ours, the difference and worth-taking sections. **Verdict: no.** The only ideas worth taking are the album-release gate order for S2 and two fallback lessons. Docs only; tests 1757 → 1757.
- **Findings:** Bandcamp and JioSaavn are metadata only (not download plugins). Amazon's T2Tunes host is dead (#1300) yet its `is_configured()` returns True. HiFi is Tidal through seven anonymous third-party proxies; Qobuz scrapes its app secret from the web player's bundle.js; YouTube re-encodes to MP3 320 by default (D24's "re-encoded fake"). Priority hybrid takes the first source with *any* results; `engine.download_with_fallback` has no caller; the give-up fallback reads `hybrid_order` only. Likely bug: the `deezer_dl`/`deezer` alias mismatch means an exhausted Deezer is never excluded from orchestrator search.
- **Verified:** the citation check prints no BAD line. Three Opus fact-gathering agents read the clone, and I spot-checked about 20 of their cites with `sed -n`. An Opus review opened about 120 cites and returned 21 findings, all fixed and re-checked. The main ones: torrent/usenet don't use the shared download path; the empty `hybrid_order` only affects configs never saved from the UI; the per-source toggles live in the UI only; the import duration check and quality guard; D7 wording; the second loop runs in priority mode only, with 2 queries; plus 15 cite moves. Suite: `check.sh` green on the final tree, 1757 passed in 648 s.
- **For V2-08/V3:** D7 (`next-session-design.md:61`) is "automatic downloads only after Michael's go", not "approve each download". The per-row approval is fetch's (`ours:sourcing/fetch.py:1-4`), and 05 cites both. Neither D7 nor D26 literally says "Soulseek-only": that comes from architecture.md and the SpotiFLAC note (`next-session-design.md:142-143`). Progress question 4 omits SoundCloud.
- **Questions for Michael:** none new. **Proposed changes:** in this feature's step 1, "torrent" is `core/download_plugins/torrent.py` plus `core/torrent_clients/`, and Bandcamp/JioSaavn are metadata clients, not sources. Step 4's "(D7, D26)" would be more precise as "(architecture, D26; D7 gates automation)".

### 2026-10-22 10:15 · V2-03b · passes
- **Changed:** `docs/research/2026-10-22-soulsync/04-soulseek.md`, 439 → ~840 lines, 421+ unique citations, 19 `*unverified*` marks. New sections: `### Transfers` (one POST per file plus a 7-POST fallback cascade over 4 paths, id from `enqueued[]` or the filename, own transfer found by (peer, path) in the global listing with last-wins, timeouts table, 3 DELETE forms, cleanup only by automations/batch end, searches never deleted per use, task state list + ASCII), `### Errors and outages`, `### Throttling` (35/220 s, 429 cooldown 5-120 s, rate_limit.py inert for Soulseek), a 36-row `### Every slskd endpoint SoulSync calls` table, and `### What our S1-04 and S2 should capture`. Also ours part 2 (8 `SlskdClient` calls, fetch's transfer loop, the hotfix 404, S1-04/05/06/S2-05), the three transfer failure classes plus "slskd down" in `## The difference that matters`, and take/don't-take in `## Worth taking?`. The `(part 2, transfers: V2-03b)` placeholders are gone. **Verdict: adapt** (unchanged). Docs only; tests 1757 → 1757.
- **Findings:** an unreachable slskd makes SoulSync's `_make_request` return None, so the monitor's "poll failed" guard never fires. Every Soulseek task idle more than 90 s is then retried at once and ends `not_found` (read from code; the guard's tests use a raising fake). Two SoulSync comments disagree on whether slskd 0.26's enqueue reply carries ids (soulseek_client.py:971 vs :998). Its DELETE forms 2 and 3 drop `remove`. Part 1 said `GET users/{peer}/directory`; it is `POST` with `{"directory"}` (fixed).
- **Verified:** the citation check prints no BAD line. An Opus review opened 120+ SoulSync cites and every ours claim, and returned 17 findings: 90 s counted from the last status change, the orphan cleanup, 3 more cleanup callers, form 2 drops `remove`, 7 POSTs over 4 paths, onboarding rows 22/24/25, dead `get_session_info`, `queued` is a UI-only status, 15 s InProgress, `max_wait` is video-only, `close()` drops only in-flight searches, the row-11 404 caveat, the ext-74 retry sentence, errors are logged, the chat probe has no session fallback, the web-root probe, the test comment. All were fixed; I spot-checked monitor 608/870-873/1169-1171, web_server 7392-7428/16202-16208, wishlist_failed 266-272, automation_engine 246-249, soulseek_client 835-837/1191-1193, and that `get_session_info` has no caller. Suite: `check.sh` green, 1757 tests in 650 s (pre-review tree) and 649 s on the final tree.
- **For V3/V4:** the capture list (enqueue reply for one and for many files, `POST /users/{peer}/directory`, the per-transfer record in every terminal state, `DELETE ?remove=true`, `searchTimeout` vs `timeout`, `GET /server` during a VPN drop) belongs in 09's next steps and S4-01's checklist. The S1 branch still does not exist (`git ls-remote`, 2026-10-22).
- **Questions for Michael:** none new. **Proposed changes:** the feature's step 1 says the state machine lives in monitor.py/cancel.py/lifecycle.py/staging.py. It is spread over `master.py:603`, `cancel.py:40-42`, `candidates.py:568`, `status.py` and `lifecycle.py`; `staging.py` is the drop-folder shortcut, and `connection_detect.py` is LAN auto-detect, not outage detection.

### 2026-10-22 09:40 · V2-03a · passes
- **New:** `docs/research/2026-10-22-soulsync/04-soulseek.md` (439 lines, 230 unique citations, 6 `*unverified*` marks): Soulseek query ladder (7 rungs + legacy queries, one at a time) and album queries, the search call and poll, candidate records, a scoring table (match, profile filter, `quality_score`, 0.08 confidence band, measured peer speed), album pre-flight and bundle (folder score weights, 0.62/0.58 floors, `assign_album_tracks`, ≤ 4 alternatives each covering 100 %), ASCII flow, the failure order table (3 error / 3 stall / 5 quarantine retries), compared with goal E, S2-04/S2-05 and S1-06; peer memory table; ours (scorer terms, fetch, D24, fake_slskd). **Verdict: adapt.** Docs only; tests 1757 → 1757.
- **Findings:** the per-track search drops files from folders with ≥ 2 hits (only ungrouped files are per-track candidates). The bundle maps files by title key (no base-title veto) and would not take ext-74's track 09, but the **source-reuse** path uses the base score ≥ 0.70 with no veto, no version gate, and the artist not required, which is the ext-74 shape (read from code, not run). SoulSync has no same-release test (no lengths, no MB release) and no per-peer block; a verify failure never distrusts a folder.
- **Verified:** citation check prints no BAD line. An Opus review opened ~125 citations, re-checked the claims and returned 16 findings (alternatives 4 not 5, quality filter before confidence, recovery pass, reuse artist check optional, folder drop only when nothing starts, store on start not success, crawler re-ask condition, first-query-wins dedupe, 15 s scope, 0.625 best ratio, timeout=20 fallback, band re-sort vs 0.62, uncited absences, `prefer`, 5 cites). All fixed; I spot-checked monitor 1113-1116, staging 365, task_worker 101, engine 430-432 and the 0.625 ratio. Suite: `check.sh` green on the final tree, 1757 tests in 646 s.
- **Corrections to the feature's steps (Proposed changes):** `query_variants.py` and `candidate_store.py` are torrent/usenet (indexer) code, not Soulseek; `prioritize.py` has no scoring terms (queue "download next"); `release_identity.py` lives in `core/download_plugins/` and covers torrent/usenet only; `album_bundle.py` is the torrent/usenet picker (Soulseek's bundle is `SoulseekClient.download_album_to_staging`). The file says so and cites what is used instead.
- **For V2-03b:** SoulSync sends `timeout` (ms) where ours sends `searchTimeout`; which key slskd 0.26 reads goes in the endpoint table. Bundle enqueues one POST per file (`_enqueue_album_tracks`, soulseek_client.py:2184-2195). Browse = `users/{peer}/directory`. The S1 branch `origin/harness/dj-crate-streaming-2026-10-22-fixes` still does not exist (`git ls-remote`, 2026-10-22).
- **Questions for Michael:** none new.

### 2026-10-22 09:00 · V2-02 · passes
- **New:** `docs/research/2026-10-22-soulsync/03-matching.md` (~400 lines, 195 unique citations). It covers the shared normaliser and `similarity_score` (remaster 0.75, version keyword 0.30), the library check `check_track_exists` (0.5 title + 0.5 artist, **no duration or id**, playlist sync at 0.7, wishlist adds a strict identity check), the Soulseek candidate score (0.45/0.40/0.15, gates, the base-title veto #1626, version gate, accept > 0.58), the ids kept, editions, MusicBrainz, ISRC and opt-in AcoustID. A remaster/live/extended/radio-edit table compares four columns. **Verdict: adapt.** Docs only; tests 1757 → 1757.
- **ext-74 answer:** SoulSync's base scorer accepts track 09 (about 0.89). The base-title veto rejects it at 0.275 against a 0.30 floor. Under a flat `Artist - Album - 09 - Title` name the veto misses (0.61), and AcoustID would FAIL it only if enabled (off by default) and both titles are ASCII. All of these are hand estimates from our own stdlib re-computation of the cited formulas; nothing from the clone was run.
- **Other findings:** in SoulSync's "have it", a "(Live)" track on a live album counts as owning the studio cut (#808 album-context strip), and so does "Live - Remastered 2011" on titles of 12+ characters. "(Radio Version)" counts as the original. On Soulseek, extended and radio-edit files are accepted for a plain row (contradicts D26). Ours also only ranks, and never rejects, an edit/plain swap (`ours:sourcing/scorer.py:171-177`).
- **Verified:** citation check prints no BAD line; 7 `*unverified*`/`*absence inferred*` marks. An Opus review opened ~115 citations and re-derived the ext-74 numbers; 16 findings (the #808 strip, "Radio Version", the flat-name veto miss, the AcoustID script skip, the request-path claim, 8 line numbers), all fixed and re-checked with `sed -n`. Suite: `check.sh` green on the final tree, 1757 tests in 645 s.
- **For V2-03a:** does the base-title veto run on album-bundle downloads? (marked *unverified* in 03). `core/downloads/soulseek_identity.match_track` is evidence only, never a rejection (`SoulSync:core/downloads/validation.py:888-896`). For V2-05: AcoustID's title-based FAIL and the `language_script_skip` sit at `SoulSync:core/matching/audio_verification.py:794-831`.
- **Questions for Michael:** none new. **Proposed changes:** none.

### 2026-10-22 08:30 · V2-01 · passes
- **New:** `docs/research/2026-10-22-soulsync/02-intake.md` (~410 lines): Spotify (auth-code flow with the user's own app, no embedded id; embed scrape + SpotipyFree without credentials; the Feb 2026 handling: `/items` before `/tracks`, followed-playlist 403, Premium-owner 403), the 12 playlist-source adapters and mirrored playlists (no default refresh schedule; pipeline refresh → identify → sync → wishlist), wishlist (30 min, retries forever with 4 h/24 h/7 d backoff), watchlist (24 h, track-by-track adds, auto-download on by default), member requests (wishlist rows pending admin approval; album|track only), the Lidarr shim, an ASCII flow; ours (playlist_sources, import-playlist, seed-spotify, `external_wanted`, S2-01/02/07, S3); judged on C and D. **Verdict: adapt.** Docs only; tests 1757 → 1757.
- **Verified:** citation check prints no BAD line; 5 `*unverified*` + 4 `*absence inferred*` marks. An Opus review opened ~150 citations and found 13 wrong or overstated (Lidarr call site, album-click path, ban-escalation range, `store.py:69`, wishlist insert line, iTunes route, 350 ms/10,000 constants, spotipyFree "hard dependency", "matched in the library" = manual matches only, Wing It opt-in, seed-spotify does not re-ask, Qobuz/Last.fm missing, empty-fetch guard): all fixed and re-checked with `sed -n`. Suite: `check.sh` green in 650 s, 1757 tests (on the final tree).
- **For V2-08 (cross-file disagreement):** 01-map.md calls `spotipyFree` a hard dependency; `SoulSync:requirements.txt:92-94` and `SoulSync:core/spotify_public_api.py:11-15` say it is soft-imported, "never a hard runtime requirement". 02-intake says the latter; 01-map needs the same wording.
- **For V2-03a/V3:** the wishlist run submits album batches (`SoulSync:core/wishlist/processing.py:211-279`) but a wishlist row is one track with the album only inside `spotify_data` JSON; whether a batch pins one folder is V2-03a's question. `core/downloads/master.py:run_full_missing_tracks_process` was not traced.
- **Likely SoulSync bug (not run):** `SoulSync:api/playlists.py:82-86` calls `.get()` on the `Playlist` dataclass `get_playlist_by_id` returns.
- **Questions for Michael:** none new. **Proposed changes:** none.

### 2026-10-22 · verify V1

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| V1-01 | 1 | Read README.md (38 lines) | `## Summary` + `(written by V4-02)`; `## Sections` lists 01-09 with the spec names; empty `## Stage-by-stage comparison` and `## Fit to goals` (HTML comments only); 01-map.md exists, 02-09 are named only | yes |
| V1-01 | 2 | Read `## Process model`; sed gunicorn.conf.py:3-6, wsgi.py:3, web_server.py:285/495/1243/21646/24629/24834, automation_engine.py:79/537/1058/1640, worker class lines in clone; grep `register_blueprint`, `start_background_task`, `threading.Thread(` | gunicorn gthread/workers=1 at 4-5; wsgi imports start_runtime_services; Flask/SocketIO at 285/495; every worker class sits on its cited line; AutomationEngine uses threading.Timer; 43 blueprints, 21 `_emit_*` loops, 56 thread starts all match; ASCII diagram present | yes |
| V1-01 | 3 | Read `## Data stores`; `grep -c 'CREATE TABLE' database/music_database.py`; sed table lines 592, 911, 1385, 1426, 3764, 27480; `grep -c 'ALTER TABLE'` | 118 CREATE TABLE; each sampled table's CREATE TABLE is on the cited line; ALTER count 320; subsystem table has all groups; DB path and WAL cites match; video/audiobook/podcast skipped once | yes |
| V1-01 | 4 | Read `## Settings and credentials`; sed core/settings.py:91,136,150,1225; core/credentials/store.py:22 (85 lines); qobuz_client.py:218-244; requirements.txt:95 | All lines match the claims; mechanism and file:line given, no credential value; states none embedded for Spotify and names the Qobuz bundle.js scrape | yes |
| V1-01 | 5 | Read `## Deployment`; sed Dockerfile:38-40,53,168 lines; docker-compose.yml:8,169; entrypoint.sh:58 (122 lines); `grep -i beet Dockerfile requirements.txt`; `find tests -name 'test_*.py' | wc -l`; `ls .github/workflows` | Dockerfile 168 / compose 197 / entrypoint 122 lines; pre-release yt-dlp at 38-40; no beets (0 hits); apt list has ffmpeg, flac, fpcalc; 1,669 test files; five workflow files each described | yes |
| V1-01 | 6 | Read `## Module map`; `wc -l` on web_server.py, music_database.py, soulseek_client.py, spotify_client.py, source_playlists.py, matching_engine.py, post_processing.py, album_consistency.py, tag_writer.py, navidrome_client.py, download_orchestrator.py; file counts of core/downloads (46), core/matching (9), core/wishlist (17, 5,461 lines), core/playlists (15), api (92), webui/src (1,321), core/video (120) | All counts equal the table; one row per V2 subsystem (7); corrected core/downloads paths used; skipped video/audiobook/podcast modules named in one paragraph | yes |
| V1-01 | 7 | Read `## License`; sed license.txt:1-18 | Line 1 `Copyright (c) [2025] [SoulSync]`; lines 10-11 are the retention clause; section says what porting requires | yes |
| V1-01 | 8 | `git show ca7fae1:…/01-map.md \| grep -A2 'Maintenance health'` | At V1-01's commit: heading + `(written by V1-02)`. V1-02 has since replaced the placeholder, as designed, so the literal line is gone from HEAD | yes (superseded by V1-02) |
| V1-01 | 9 | Ran the citation check from progress.md over docs/research/2026-10-22-soulsync/*.md (311 unique citations) | No BAD line printed | yes |
| V1-01 | 10 | `grep -n unverified 01-map.md`; read the file for uncited mechanism claims | 5 marks (lines 4, 113, 116, 227, 387), each on a claim with no cite; no uncited SoulSync mechanism sentence found; the ~25 claims I spot-checked against the clone were true | yes |
| V1-01 | 11 | `lib/check.sh` (first call wrongly passed `true` as a pytest arg: no tests ran, discarded); re-ran without args; read check.out | `check: green (cached for this code tree, 1757 tests)`; check.out tail `1757 passed, 2 warnings in 649.47s`; no skips reported | yes |
| V1-02 | 1 | Read releases table; `gh api --paginate '…/releases?per_page=100'` listing tag/date/prerelease; computed gaps for the 20 newest in Python | 101 releases (oldest v0.65); latest 10 tags and dates identical to table (3.5.9 2026-10-22 … 3.5.0 2026-10-04); median 2.157 d, mean 2.43 d; no prereleases | yes |
| V1-02 | 2 | `gh api 'repos/Nezreka/SoulSync/contributors?per_page=100'` summed in Python | 41 contributors, 8,544 total; Nezreka 7,590 (88.8%), kettui 258, Thundernerd 167, mandos21 68, nick2000713 65; bus factor 1 stated | yes |
| V1-02 | 3 | `gh api repos/Nezreka/SoulSync --jq …`; search/issues for open PRs and issues; closed-issue search sorted by updated | open_issues_count 30, PRs 14, issues 16, stars 2,309, forks 131, created 2025-07-09; the five closed issues (#1817, 1810, 1807, 1805, 1804) match titles and times | yes |
| V1-02 | 4 | `gh api --paginate …commits?since=2026-09-22…`; `path=` calls for soulseek_client.py and core/downloads; `gh api commits/<sha>` for the five merges | 1,592 commits, 377 merges; author-name counts match; soulseek_client.py 8 (latest ec0e61323d 10-06), core/downloads 71 (latest abeb005f8e 10-21); the five merges' files/+/− match (275/37,273/14,355 etc.); only #1821 touches core/downloads | yes |
| V1-02 | 5 | Read the section for dates, commands and the depth-1 note; `git status` shows no clone changes | Every figure carries 2026-10-22 and its `gh api` command; depth-1 clone said to be useless for history (`git log` shows 1 commit); nothing executed from the clone | yes |
| V1-02 | 6 | Same suite result as V1-01 step 11 | 1757 passed, none skipped, green | yes |

Both features hold; `passes` unchanged. Nothing was changed in the code or docs.

### 2026-10-22 · V1-02 · passes
- **New:** `## Maintenance health` in `docs/research/2026-10-22-soulsync/01-map.md` (releases, contributors, issues/PRs/stars, size of recent change), every figure with its `gh api` call, read 2026-10-22. Docs only; tests 1615 → 1615.
- **Numbers:** 101 releases (median 2.16 days between the latest 20); 41 contributors, Nezreka 7,590 of 8,544 (88.8%), bus factor 1; 16 open issues, 14 open PRs, 2,309 stars; 1,592 commits in 30 days (377 merges); `core/soulseek_client.py` 8 commits in 30 days (last 10-06), `core/downloads/` 71 (last 10-21); newest merge #1821 is 275 files, +37,273/−14,355.
- **Verified:** suite green in 580 s, 1615 tests. Release prerelease flags checked from the saved output (all false).
- **For later sessions:** `core/downloads/` churns daily, so cited line numbers are valid at 34bf7cf9c741 only (stated in the section). Commit author names ("BoulderBadgeDad", "Nez", "Claude") differ from the API login; I marked the identity *unverified*.
- **Questions for Michael:** none. **Proposed changes:** none.

### 2026-10-22 07:10 · V1-01 · passes
- **New:** `docs/research/2026-10-22-soulsync/README.md` (skeleton: `## Summary` "(written by V4-02)", links to 01-09, empty `## Stage-by-stage comparison` / `## Fit to goals` for V3) and `01-map.md` (380+ lines: process model + ASCII diagram, data stores with all music tables grouped by subsystem, settings/credentials, deployment, tests/CI, module map with `wc -l`, MIT license, `## Maintenance health` "(written by V1-02)", then the four comparison headings, **Verdict: adapt**). Docs only; tests 1615 → 1615.
- **Verified:** the citation check prints no BAD line (≈300 unique citations); an Opus review spot-checked ~190 and found 2 wrong lines (fixed) and some gaps (filled); every uncited claim carries `*unverified*` (4 marks). Suite: `check.sh` green in 582 s, 1615 tests.
- **Findings V2 should reuse:** the 118 `CREATE TABLE`s are 86 distinct live tables (5 comments, 8 markers, 17 `*_new`, a duplicate `hifi_instances`, `watchlist_podcasts_migrating`). There is no peer table: peer speed memory is in-process with a 1 h TTL (`core/downloads/peer_observation.py:11`). Secrets are Fernet-encrypted in `music_library.db` with the key file on the same volume, and they fall back to **plaintext** `config.json` (`core/settings.py:1225-1258`). No Spotify credential is embedded. Qobuz app secrets are scraped from its web player's bundle.js (`core/qobuz_client.py:218`). `spotipyFree` (GPL-3.0) is a hard dependency in `requirements.txt:95`, although its docstring says optional. No beets anywhere. `:latest` is published on every push to `main`, and CI never tests that merge commit.
- **Correction to the initializer's notes:** the UI is not only `webui/index.html`: `webui/src/` holds a React 19 + TanStack Router + Vite app (1,321 files) built into `webui/static/dist` (`Dockerfile:4-12`, `:101`). V2-07 must read both. `core/downloads/` has 46 `.py` files, and `api/` has 92 `.py` files recursively.
- **Questions for Michael:** none new.
- **Proposed changes:** none.

### 2026-10-22 · initializer

**This is a research run: documents only.** Every feature writes under `docs/research/2026-10-22-soulsync/`
(V4-02 also adds one line to `docs/next-todos.md`). No `.py` changes, nothing live, nothing executed from the clone.
Base: `6fb134e` on top of `origin/main` `5b3e3701c9`. Init: suite green, 1615 tests, 583 s.

**Features: 15.** V1 map: 2 (V1-01 map + README skeleton, V1-02 GitHub maintenance health). V2 subsystems: 9
(V2-01 intake, V2-02 matching, V2-03a Soulseek search/score/album/fallback, V2-03b Soulseek transfers + the slskd
endpoint table, V2-04 other sources, V2-05 verification, V2-06 filing/library/Navidrome, V2-07 UI/API/phone, V2-08
review of 02-08). V3 comparison: 2 (V3-01 stage table + failure classes + decisions, V3-02 fit to goals). V4: 2
(V4-01 recommendations, V4-02 whole-report review + summary + next-todos line). The spec's V2-03 is split in two
(a: search → folder choice → fallback → peer memory; b: transfers, errors, throttling, endpoint table) because
`core/soulseek_client.py` alone is 3,171 lines and `core/downloads/` has 48 files. V2-08 is added so V3 builds on
checked citations. Dependencies follow the brief: V1-01 `after: []`, every V2 feature `after: [V1-01]` (V2-03b also
after V2-03a), V3 after all of V2, V4 after V3.

#### The SoulSync clone (read-only, untrusted data)
- `~/research/soulsync-src/SoulSync`, commit `34bf7cf9c741` ("Merge pull request #1821 from Nezreka/dev",
  2026-10-21 19:01 -0700). The directory is mode `dr-xr-xr-x`: you cannot write into it, and you must not try.
- **Shallow clone, depth 1.** `git -C … log` shows exactly one commit. History, releases, issues and contributors come
  from `gh api repos/Nezreka/SoulSync/...` (read-only; `gh auth status` is logged in as mh550). At init: 30 releases on
  the first page (paginate for the total), newest `3.5.9` 2026-10-22, then 3.5.8 (10-20), 3.5.7 (10-17), 3.5.6 and
  3.5.5 (10-15); top contributor Nezreka 7,590 contributions, next kettui 258; 2,309 stars; `open_issues_count` 29.
- **Never execute anything from it:** no `python`, `pip`, `pytest`, `npm`, `docker`, `dev.sh`, `entrypoint.sh`. Read
  with `cat`, `sed -n`, `grep`, `wc`, `find`, `ls`, Read/Grep/Glob. Don't copy its code into our repo (paraphrase; a
  quoted line or two with a citation is fine, a function body is not).
- **Huge files; never Read them whole.** `web_server.py` 24,916 lines, `database/music_database.py` 28,019,
  `webui/index.html` 12,932 (the whole UI is this one file; `templates/` holds only a png and an xml),
  `core/repair_worker.py` 6,885, `api/source_playlists.py` 5,575, `core/watchlist_scanner.py` 5,340. Grep first, then
  `sed -n 'A,Bp'`. `grep -c 'CREATE TABLE' database/music_database.py` = 118.
- **Spec paths that differ in the clone** (the spec's basenames are right, the folders are not always):
  `post_processing.py`, `atomic_album_publish.py`, `atomic_manifest.py`, `atomic_recovery.py`, `review_reject.py` are
  in `core/downloads/`; `library_reorganize.py` exists twice (`core/` 3,066 lines and `core/repair_jobs/`);
  `lifecycle.py` and `staging.py` also exist in `core/issues/` and `core/imports/` (use `core/downloads/`); the
  Spotify files (`spotify_client.py` …) are under `core/`; `core/matching_engine.py`, `core/client_match.py`,
  `core/source_ids.py`, `core/edition_grouping.py`, `core/acoustid_client.py`, `core/soulseek_client.py`,
  `core/slskd_throttle.py`, `core/download_orchestrator.py`, `core/tag_writer.py`, `core/navidrome_client.py`,
  `core/auto_import_worker.py`, `core/automation_engine.py`, `core/replaygain.py`, `core/album_consistency.py`,
  `core/acoustid_verification.py`, `core/audio_length.py` all exist as named. `core/` has 203 entries, `api/` 64.
- **slskd calls** are built as `f"{self.base_url}/api/v0/{endpoint}"` (`core/soulseek_client.py:210`) with a
  no-prefix "direct" path at `:316`, so grep for `transfers/`, `searches`, `users/`, `server`, not for `/api/v0/`.
  Line 1250 documents `/transfers/downloads/{username}/{download_id}?remove=…`; 2901-2902 probe `/server` vs
  `/server/state`. Process model hints: `gunicorn.conf.py:4-5` (`gthread`, 1 worker); `wsgi.py`; CI in
  `.github/workflows/` (build-and-test, cleanup-dev-images, dev-nightly, docker-publish, visual-baselines).
- `grep -rli beets core --include=*.py` hits `core/settings.py`, `core/auto_import_worker.py`,
  `core/library_reorganize.py`, `core/library/reorganize_tag_source.py` (V2-06 starts there). SoulSync's own
  `docs/api-response-shapes.md` and `docs/download-engine-refactor-plan.md` are worth a read for V2-03.
- Non-music, skip after naming once: `core/audiobook_*`, `core/podcast_*`, `database/video_database.py`
  (10,460 lines), `api/video*`, `api/audiobook*`, `api/podcasts.py`, anything `movie`/`tv`/`youtube` video.

#### Our side (this worktree; cite as `ours:<path>:<line>`)
- The spec's `import_playlist.py` is `sourcing/import_playlist.py`; `fake_slskd.py` is `sourcing/fake_slskd.py`
  (tests use it via `tests/test_fake_slskd.py`); `seed-spotify` is a subcommand in `sourcing/cli.py`. Other names
  are as the spec says: `sourcing/{playlist_sources,spotify_csv,identity,scorer,fetch,slskd_client,verify,acoustid,
  policy,filer,musicbrainz,worker}.py`, `crates/{service,store,playlist_edit,trash,placement,reconcile}.py`, `web/`.
- Decisions by line: `docs/specs/2026-10-13-next-session-design.md` D7 :61, D18 :72, D22 :76;
  `docs/specs/2026-10-17-amperfy-pivot.md` D24 :19, D26 :21, D27 :22, D29 :24, D31 :26, D35 :30, D44 :39.
- The planned S1–S4 and the 2026-10-21 failure findings: `docs/specs/2026-10-22-downloads-and-requests.md` (S1 at
  :61-96, S2 :97-187, S3 :188-222, S4 :223-230, the findings table under `## What was found` :16-51).
- **The S1 branch `origin/harness/dj-crate-streaming-2026-10-22-fixes` did not exist at init** (`git ls-remote`).
  Check again at the start of V2-03a/b and V4-01; if it exists, read it with `git fetch` + `git show`/`git diff`, read only.
- `docs/research/` does not exist yet; V1-01 creates `docs/research/2026-10-22-soulsync/` and `README.md`.
- Tests that read docs: `tests/test_monitoring_doc.py` (docs/monitoring.md) and `tests/test_web_health.py`; none
  reads `docs/next-todos.md` or `docs/research/`, so the one next-todos line (V4-02) is safe.

#### Conventions every section file follows
- Citation form: `SoulSync:<path>:<line>` or `SoulSync:<path>:<a>-<b>`, likewise `ours:…`. Paths are relative to the
  clone root / the worktree root, with no leading `./`.
- A claim with no citation carries the literal mark `*unverified*` (and ideally what would verify it).
- Four headings, in order: `## What SoulSync does`, `## How ours does it`, `## The difference that matters`,
  `## Worth taking?`, ending in a `**Verdict:** yes|adapt|no` line. Dense and technical; no marketing language.
- **Citation check** (run before committing; the verifier runs it too; it prints nothing when all is well):
  ```
  cd /home/mh550/worktrees/dj-crate-streaming/dj-soulsync-review-2026-10-22
  grep -ohE '(SoulSync|ours):[A-Za-z0-9_./-]+:[0-9]+' docs/research/2026-10-22-soulsync/*.md | sort -u |
  while IFS=: read -r src p l; do
    case $src in SoulSync) f=$HOME/research/soulsync-src/SoulSync/$p;; ours) f=$p;; esac
    [ -f "$f" ] && [ "$l" -le "$(wc -l < "$f")" ] || echo "BAD $src:$p:$l"
  done
  ```
  It checks the first line of a range. Write citations with no space before the colon and no trailing punctuation
  inside the token (`SoulSync:core/x.py:12.` is fine: the regex stops at the digit).
- The suite still runs at the end of every feature (`.harness/check.sh`, ~10 min, 1615 tests): docs-only, so it
  must stay at 1615 passed with no new skips. Nothing under `/srv`, no docker, no compose, no live scripts.
- Keep the whole report free of credential values: report a mechanism and a `file:line`, never a key.

#### Questions for Michael (each has a default; answer in INBOX.md to change it; V4-01 copies them into 09-recommendations.md)
1. **Effort unit.** Estimates are given in "harness nights" (one overnight run of this harness) with a days/weeks
   equivalent; default assumption: one harness night ≈ 6-10 features ≈ 1-2 human days.
2. **Baseline for goal B.** B is undecided; the comparison takes option 1 (Amperfy + our web client as a phone web app +
   an iOS Shortcut) as the baseline, since it needs the least new code, and treats options 2 and 3 as deltas.
3. **Trying SoulSync for real.** The brief forbids running it; the report judges from source and public GitHub only.
   Default: no sandbox trial is proposed unless the recommendation is (a) or (b), in which case the next steps include
   an isolated trial Michael runs himself (separate compose project, its own library copy, never `/srv/music`).
4. **Streaming-service sources.** SoulSync's Deezer/Tidal/Qobuz/Amazon/HiFi/YouTube getters are described and flagged
   for terms-of-service and legal risk, and never recommended for our stack (D7, D26, provenance for D24). Default: out.
5. **Spotify auth.** The report assumes Spotify stays "Michael's own developer app only" (goal C) and judges SoulSync's
   public/scraper paths as mechanisms to learn from, not to adopt.
