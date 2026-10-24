# Progress log — run `dj-soulsync-review-2026-10-22` (branch `harness/dj-soulsync-review-2026-10-22`)

What this file is: the shared memory of the agent harness for this run. Each session appends one entry **at the top**
(newest first) when it finishes a feature: what it wrote, what it learned, what it asks. Nobody edits older entries.
The feature list is `.harness/runs/dj-soulsync-review-2026-10-22/feature_list.json`: array order is priority order; a
session gets the first feature whose `passes` is false and whose `after` all pass, and may flip only its own `passes`.
Michael steers through `INBOX.md` on this branch (first line `status: run|pause|stop`; answers under `## Answers`).
Every session reads `INBOX.md` and this file first, then the spec `docs/specs/2026-10-22-soulsync-review.md` and the
brief `brief.md` (the brief wins on scope).

### 2026-10-22 verify V4 (second pass)

Independent re-run: 2 hold, 0 fail. The earlier `310-341` defect is gone. Nothing live touched, no code or doc edited.

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| V4-01 | 1 | `grep -n '^#'` on 09; read 21-60 | `## Options` at 21, `### (a)`-`### (d)` at 36/49/104/145; tables with effort (nights and days), risk, maintenance, licensing, what changes; shared pace and MIT rows cite 01-map.md | yes |
| V4-01 | 2 | read `### (b)` 49-103 | integration points, D18, D27, D7 and `amperfy` conflicts, each cited | yes |
| V4-01 | 3 | read `### (c)` 104-144 | table of 15 candidate rows with SoulSync files, ours file, effort, MIT notice | yes |
| V4-01 | 4 | read 157-187 | first sentence "Option (c)"; 7 numbered steps, each verb + file/spec + size | yes |
| V4-01 | 5 | awk count of `^\| S` rows in 188-219; `grep -c` delta headings and `draft, not applied` | 23 rows (12 keep, 11 change, 0 drop); 11 `### Spec delta` blocks; 12 marks | yes |
| V4-01 | 6 | read 325-342 | 10 questions, each with assumption and where used; initializer 1-5 are questions 1-5 | yes |
| V4-01 | 7 | range-aware loop from progress.md over all cites in the folder | 2,418 unique cites, no BAD line | yes |
| V4-01 | 8 | `grep -c unverified` per file; read marks in 09; opened 8 09 cites in the clone (matching_engine 1307-1335, settings 745-748, master 1372-1382, automation_engine 190-196, audio_verification 829-831, library_check 12-17, requests/music 20, ours verify/filer) | marks on uncited claims in all 10 files; the 8 cites support their sentences | yes |
| V4-01 | 9 | `lib/check.sh` | green (cached, 1757 tests) | yes |
| V4-02 | 1 | read the 16:14 spot-check table (20 rows: 15 SoulSync, 5 ours, 10 files; 18 yes, 2 partly, fixes named) plus the 15:26 table (30 rows); re-opened 8 cites myself | tables present with sentence, holds and fix; cites I opened support their sentences | yes |
| V4-02 | 2 | read the unverified list (46, kept with would-verify); `grep -c unverified` per file; citation loop | list present per file; loop prints no BAD line (2,418 cites) | yes |
| V4-02 | 3 | read README 10-56 | `## Summary` 47 lines; verdict (c); `### Top 5 findings` (5, linked); `### Next steps` (7, mirror 09); last line "Questions for Michael: see 09-recommendations.md" | yes |
| V4-02 | 4 | `git diff --stat` and `git diff origin/main..HEAD -- docs/next-todos.md` | 1 file, 1 insertion, links README, "port pieces, never adopt SoulSync" | yes |
| V4-02 | 5 | `git diff --stat origin/main..HEAD`; `git log --first-parent --no-merges --name-only 6fb134e..HEAD` filtered | stat also lists pre-run `.py`, fixtures and specs (commits 19fedea..59c6f6a, 1632d2d, before base 6fb134e, not yet in main); the run's own commits touch only the three allowed paths. Literal wording fails, intent holds | yes (intent) |
| V4-02 | 6 | `## Sections` links; `grep -rnoE '[A-Za-z0-9]{32,}'` | README `## Sections` lists 01-09 and README; grep prints nothing | yes |
| V4-02 | 7 | `lib/check.sh` | green (cached, 1757 tests) | yes |

### 2026-10-22 16:14 · V4-02 · passes

- **What changed:** this is the re-run after verify V4. Its only V4-02 fail (step 2, the `310-341` cite) was fixed by V4-01. A new Opus spot-check found 2 claims that only partly held, and both are fixed: (14) 07:101, the streaming-id range `source.py:124-167` → `:124-168`, plus Beatport's id at `SoulSync:core/metadata/source.py:1433-1434` (it is not in `SOURCE_TAG_CONFIG`); (17) 09:208 and 04:271, where "a peer frozen for 180 s" now reads "once nothing in the bundle has moved for 180 s", which is what the guard does (`SoulSync:core/soulseek_client.py:2434-2438`). I read both in the clone before editing. Docs only; tests 1757 → 1757.
- **Verified (every step, myself):** (1) the full read and the 30-row table are in the 15:26 entry; the new table below adds 20 cites (15 SoulSync, 5 ours, all 10 files): 18 yes, 2 partly, 0 no. (2) all 46 `*unverified*` marks are listed below. The range-aware citation check (V4-01's form, both ends) over 2,417 unique cites prints no BAD line, before and after the fixes. (3) `## Summary` is 47 lines, with `### Top 5 findings` (5 items, each linking a section file), `### Next steps` (7, from 09) and the Questions line. (4) `git diff --stat origin/main..HEAD -- docs/next-todos.md` shows 1 file, 1 insertion, with the verdict "port pieces, never adopt SoulSync". (5) `git log --first-parent --no-merges --name-only 6fb134e..HEAD` (49 commits), filtered to remove the three allowed paths, prints nothing. (6) `anchors.py` prints "links ok", `## Sections` links all of 01-09 and README.md, and `grep -rnoE '[A-Za-z0-9]{32,}'` prints nothing. (7) `lib/check.sh` printed "green in 650 s, 1757 tests" on the edited tree.
- **Next:** V4 is complete. The verify pass and the PR come next. **Questions for Michael:** none new; the 10 in 09 stand. **Proposed change:** the same as the 15:26 entry: reword step 5 to the first-parent command, which is how step 5 was checked here.

#### Citation spot-check (Opus, `random.seed(4023)`, current line numbers)

| # | File:line | Citation | Sentence checked | Holds | Fix |
|---|---|---|---|---|---|
| 1 | 01:75 | `SoulSync:core/auto_import_worker.py:210` | `AutoImportWorker` class defined here | yes | |
| 2 | 01:169 | `SoulSync:database/music_database.py:3397` | `recent_releases` table created | yes | |
| 3 | 01:465 | `ours:deploy/compose.yml:13` | Navidrome image pinned | yes | |
| 4 | 02:175 | `SoulSync:core/playlists/sources/lastfm.py:1-11` | Last.fm radio is a playlist source | yes | |
| 5 | 02:64 | `SoulSync:core/spotify_client.py:1383-1420` | with the user token it reads saved tracks | yes | |
| 6 | 03:314 | `SoulSync:core/matching_engine.py:969-973` | word-boundary hit on the path adds +0.3 | yes | |
| 7 | 03:390 | `SoulSync:core/text/title_match.py:75-105` | issue-numbered regressions ("Dani California") | yes | |
| 8 | 04:402 | `SoulSync:core/download_plugins/album_bundle.py:64-65` | bundle poll 2 s, deadline 6 h | yes | |
| 9 | 04:437 | `SoulSync:core/automation/handlers/download_cleanup.py:158` | 12-hourly full_cleanup clears completed downloads | yes | |
| 10 | 05:213 | `SoulSync:core/download_plugins/album_bundle.py:431-488` | `pick_best_album_release` gate order | yes | |
| 11 | 05:331 | `SoulSync:core/download_orchestrator.py:351-354` | chain filtered by exclude_sources | yes | |
| 12 | 05:344 | `ours:docs/specs/2026-10-13-next-session-design.md:61` | D7 wording | yes | |
| 13 | 06:282 | `SoulSync:api/quarantine.py:61-488` | blueprint's 11 routes | yes | |
| 14 | 07:101 | `SoulSync:core/metadata/source.py:124-167` | streaming ids incl. Beatport written as tags, each toggled | **partly** | range → `:124-168`; Beatport cite `:1433-1434` added |
| 15 | 08:339 | `SoulSync:webui/static/mobile.css:1787` | 7 `max-width: 480px` rules, first at 1787 | yes | |
| 16 | 08:446 | `ours:docs/specs/2026-10-17-amperfy-pivot.md:71-88` | "What Amperfy cannot do" list | yes | |
| 17 | 09:208 | `SoulSync:core/soulseek_client.py:2405-2626` | global poll per tick; cancels "a peer frozen 180 s" with `remove=True` | **partly** | the guard is per bundle; wording fixed in 09:208 and 04:271 |
| 18 | 09:87 | `ours:docs/architecture.md:76-77` | worker is the only downloader/beets/mover | yes | |
| 19 | README:279 | `SoulSync:core/search/orchestrator.py:1-13` | enhanced search also returns library matches | yes | |
| 20 | README:85 | `ours:sourcing/playlist_sources.py:1-14` | intake takes embed page, Exportify CSV, SpotiFLAC report | yes | |

#### Every `*unverified*` mark (46, current line numbers; the header legends and the `acoustid_unverified` / "unverified download" wording are excluded)

All 46 are kept, and each names what would verify it in the same sentence (read with `grep -n` plus 2 lines of context). None is wrong. The 4 resolved in the 15:26 entry stay resolved.
- 01:229 (pinned `tidalapi` `Session`), 01:389 (`.author.login` vs author name).
- 02:92 (installed spotipyFree), 02:373 (Shortcut share test).
- 04:87 (`POST /searches` capture), 04:338 (parse logging), 04:349 (enqueue with `path`), 04:356 (0.26 swagger), 04:367, 04:384, 04:605 and 04:796 (S4-01 captures), 04:543 (`GET /server` during a drop), 04:554 (429 test), 04:816 (`isLoggedIn` log).
- 05:64 (`tidalapi.Session` 0.8.11), 05:171 (yt-dlp SoundCloud extractor), 05:368 (Opus → MP3 encode).
- 06:89 (FLAC-encode test), 06:104 (ffmpeg run), 06:303 (fingerprint logging), 06:503 (Mixxx preferences).
- 07:240 (SoulSync reconcile against Navidrome).
- 08:141 (unauthenticated bootstrap POST), 08:275 (member-profile POST), 08:323 (extension repo), 08:359 (iPhone), 08:472 (octo-fiesta source), 08:505 (the phone).
- 09:14 (question 1), 09:15 (a run doing the work; covers 09:43, 09:56, 09:111), 09:45 (two rebases), 09:237 (draft value; SoulSync's bound cited).
- README:104 (S4-01 capture), README:147 (04's log), README:199 (question 1), README:205 (a run doing the work), README:208 (first setup run), README:245 (the phone), README:255 (Navidrome request log), README:267 (forks' server-API code), README:296 (08's member POST).

### 2026-10-22 15:51 · V4-01 · passes

- **What changed:** the verify V4 defect: `SoulSync:core/downloads/soulseek_identity.py:310-341` → `:310-340` (the file and `assign_album_tracks` end at line 340, `wc -l` 340) in 09-recommendations.md (rows at lines 121 and 207) and README.md:373. Docs only; tests 1757 → 1757.
- **Verified (every step, myself):** (1) `## Options` with the four `### (a)`-`### (d)` parts at 36/49/104/145, and the shared Maintenance pace and Licence rows cite 01-map.md; (2) `### (b)` has D18, D27, D7 and `amperfy`, plus 22 SoulSync and 12 ours cites; (3) the (c) table has 15 rows; (4) the first sentence names Option (c), followed by 7 numbered steps; (5) 23 S-rows: 12 keep, 11 change, 11 `### Spec delta` blocks, each with `draft, not applied`; (6) 10 questions, each with an assumption and where it is used; (7) the progress.md citation check prints nothing, and a range-aware check (both ends, a ≤ b) over 2,417 unique cites prints 0 BAD, while it does catch the old `310-341` on the pre-fix file; (8) `unverified` marks in every file (09: 8), unchanged from the verifier's pass; (9) `lib/check.sh` "green in 651 s, 1757 tests".
- **Next:** the same fix clears V4-02 step 2 (the verifier's only V4-02 fail), so V4-02 should pass on its re-run without a doc edit.
- **Proposed change:** the conventions' citation check tests only a range's first line, which is how `310-341` got past the earlier sessions' checks. Replace it with the range-aware form: `grep -ohE '(SoulSync|ours):[A-Za-z0-9_./-]+:[0-9]+(-[0-9]+)?' docs/research/2026-10-22-soulsync/*.md | sort -u | while IFS=: read -r src p r; do a=${r%-*}; b=${r#*-}; case $src in SoulSync) f=$HOME/research/soulsync-src/SoulSync/$p;; ours) f=$p;; esac; [ -f "$f" ] && [ "$a" -le "$b" ] && [ "$b" -le "$(wc -l < "$f")" ] || echo "BAD $src:$p:$r"; done` (tested: it prints nothing on this tree and one BAD on the pre-fix 09).
- **Questions for Michael:** none new; the 10 in 09 `## Questions for Michael` stand.

### 2026-10-22 verify V4

Independent re-run: 0 hold, 2 fail. Both fail on one real defect: `SoulSync:core/downloads/soulseek_identity.py:310-341` (09-recommendations.md lines 121 and 207) cites line 341, but the file has 340 lines. Fix: change to `310-340`. Nothing live touched; no doc or code edited. My own citation loop (2,417 unique cites, `SoulSync:` against the clone, `ours:` against this tree) printed that single BAD line.

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| V4-01 | 1 | `grep -n '^#'` and read 09:21-48, 104-156 | `## Options` with (a)-(d) headings; (a) has the Effort/Risk/Ongoing maintenance/Licensing/What changes rows, shared pace and MIT rows cite 01-map.md | yes |
| V4-01 | 2 | read `### (b)` 49-103 | integration points and D18, D27, D7, amperfy conflicts each cited | yes |
| V4-01 | 3 | read `### (c)` 104-144 | table rows with SoulSync files, ours file, effort, MIT notice (15 rows) | yes |
| V4-01 | 4 | read 157-187 | first sentence "Option (c)"; 7 numbered steps each with verb, file/spec, size | yes |
| V4-01 | 5 | counted S-rows in 188-219 (23), keep/change tally, `grep 'draft, not applied'` | 23 rows: 12 keep, 11 change; 11 `### Spec delta` blocks, each marked `draft, not applied` | yes |
| V4-01 | 6 | read 325-342 | 10 questions each with assumption and where used (incl. initializer 1-5) | yes |
| V4-01 | 7 | `/tmp/.../cc.py` loop over the folder | `BAD line ...09-recommendations.md SoulSync:core/downloads/soulseek_identity.py:310-341 340` (file ends at 340, `wc -l` 340) | **no** |
| V4-01 | 8 | `grep -c unverified` per file; read 09:36-47 marks | marks present on uncited claims (09 has 8); sampled mechanism sentences cited | yes |
| V4-01 | 9 | `lib/check.sh` | green (cached, 1757 tests) | yes |
| V4-02 | 1 | read progress spot-check table; opened 5 cites (audio_verification.py:26-29, docker-publish.yml:4-12, store.py:105-108, slskd_client.py:40-44, license.txt:10-11) | 30-row table (20 SoulSync, 10 ours, 10 files); fixes named; my 5 opened cites support their sentences | yes |
| V4-02 | 2 | unverified table in progress.md (50 rows) and the citation loop | table present; citation loop prints a BAD line for the whole folder | **no** |
| V4-02 | 3 | awk `## Summary`..`## Sections`, grep headings | 47 lines; `### Top 5 findings`, `### Next steps`, final line "Questions for Michael: see 09-recommendations.md" | yes |
| V4-02 | 4 | `git diff origin/main..HEAD -- docs/next-todos.md` | 1 file, 1 insertion, links README, "verdict: port pieces, never adopt SoulSync" | yes |
| V4-02 | 5 | `git diff --stat origin/main..HEAD`; `git log --first-parent --no-merges --name-only 6fb134e..HEAD` filtered | stat also lists 10 pre-run .py files (sourcing/, tests/) and fixtures/specs from earlier commits; the run's own commits touch only the allowed paths. Literal wording does not hold, intent does | yes (intent) |
| V4-02 | 6 | `anchors.py` on the folder; `grep -rnoE '[A-Za-z0-9]{32,}'` | "links ok"; grep prints nothing | yes |
| V4-02 | 7 | `lib/check.sh` | green (cached, 1757 tests) | yes |

### 2026-10-22 15:26 · V4-02 · passes

- **What changed:** README.md `## Summary` (47 lines): the verdict (c), `### Top 5 findings` (D7, the second library writer, maintenance pace, the album path for E, ext-74), `### Next steps` (the 7 steps of 09 `## Recommendation`) and the line "Questions for Michael: see 09-recommendations.md". `## Sections` now also links README.md itself. Review fixes are in 01, 02, 03, 06, 08, 09 and README, and `docs/next-todos.md` has one new line under `## State at hand-off` ("verdict: port pieces, never adopt SoulSync"). Docs only: 1757 tests before and after.
- **Review:** two Opus subagents read the whole folder. One checked a seeded sample of 30 cites (`random.seed(4022)`, 2 SoulSync + 1 ours per file, across all 10 files: 20 SoulSync, 10 ours; table below) and reported 12 findings. The other checked every `*unverified*` mark (second table). I re-read each claim I acted on in the clone or our tree before editing.
- **Findings fixed:** (1) 09:95 and Q8 quoted D7 as text it does not contain; now word for word from `next-session-design.md:61`. (2) README Operations called SoulSync's integrity-checked backup "a good idea for our `.snap`"; ours already does it (`snapshot-crates-db.sh:16-18`), matching 09:143. (3) README Intake said "synced on a schedule"; 02:194-200 says there is no built-in schedule, so the cell now says that. (4) 01:452 cite moved to `architecture.md:76-77`. (5) 08:134/478: 112 key-gated routes, 86 of them music (26 in `api/video_v1.py`, counted with grep). (6) The 0.62 floor is at `master.py:43`, not 44 (README ×3, 02:388). (7) 06:333 pointed to a section that does not exist ("ext-74 answer"); it now names 03 `## The difference that matters`, step 2. (8) README:64 now gives both hotfix SHAs (`6238ee5` deployed, `19fedea` in this branch; checked with `merge-base --is-ancestor`). (9) 01:465 now reads 70 test files and 1,757 tests. (10) 09:111 adds row 3's bytes check. (11) 03:346 S1-01 is at `:62-67`. (12) The README summary placeholder is filled.
- **Verified:** the citation check printed no BAD line. The summary is 47 lines (awk, `## Summary` to `## Sections`). `anchors.py` printed "links ok", and all 10 `## Sections` links resolve. `grep -rnoE '[A-Za-z0-9]{32,}'` finds nothing. `git diff --stat origin/main..HEAD -- docs/next-todos.md` shows 1 file, 1 insertion. Suite: `lib/check.sh` printed "green in 650 s, 1757 tests" (docs only).
- **Step 5 (the literal check does not hold; the intent does):** `git diff --stat origin/main..HEAD` also lists 16 pre-run files (`sourcing/*.py`, `tests/*.py`, fixtures, two specs, `.harness/config.sh`). They come from commits made before the run started that are not in `main` yet: PR #16's hotfix (`19fedea`..`59c6f6a`), the S-run spec (`1632d2d`..`5057e42`) and the run's spec `d558d22`. The run's own commits touch only the three allowed paths: `git log --first-parent --no-merges --name-only 6fb134e..HEAD` (43 commits), filtered, prints none. **Proposed change:** reword V4-02 step 5 (and the matching check in any later run) to use that command, or diff against `d558d22` with first-parent.
- **Questions for Michael:** none new; the 10 questions in 09 stand. **Next:** V4 is complete. The harness's verify V4 and the PR come next.

#### Citation spot-check (line numbers are from before this session's edits)

| # | File:line | Citation | Sentence checked | Holds | Fix |
|---|---|---|---|---|---|
| 1 | 01:168 | `SoulSync:database/music_database.py:3416` | `discovery_recent_albums` table | yes | |
| 2 | 01:79 | `SoulSync:core/musicbrainz_worker.py:64` | MusicBrainz worker thread | yes | |
| 3 | 01:452 | `ours:docs/architecture.md:72-75` | worker is the only process that downloads/runs beets | **no** (wording at 76-77) | cite → `:76-77` |
| 4 | 02:167 | `SoulSync:core/beatport/next_data.py:175-232` | Beatport tracks carry mix, remixers, label, BPM, key, ISRC | yes | |
| 5 | 02:85 | `SoulSync:core/spotify_public_scraper.py:181-182` | embed scraper caps at ~100 tracks | yes | |
| 6 | 02:330 | `ours:crates/store.py:105-108` | nothing downloads without an `approvals` row (D23) | yes | |
| 7 | 03:206 | `SoulSync:core/matching/audio_verification.py:26-29` | AcoustID thresholds 0.80 / 0.70 / 0.60 | yes | |
| 8 | 03:108 | `SoulSync:database/music_database.py:13401-13438` | album ownership = editions + completeness | partly (13433-38 is the next function) | range → `13401-13431` |
| 9 | 03:294 | `ours:docs/identity.md:135` | 0.8 is "confident" | yes | |
| 10 | 04:141 | `SoulSync:core/download_plugins/types.py:67-111` | quality_score weights | yes | |
| 11 | 04:468 | `SoulSync:core/downloads/monitor.py:1119` | task resets to `searching` | yes | |
| 12 | 04:665 | `ours:sourcing/slskd_client.py:40-44` | 8 s search, queue length 50 | yes | |
| 13 | 05:251 | `SoulSync:core/lidarr_download_client.py:76-77` | Lidarr needs URL + API key | yes | |
| 14 | 05:184 | `SoulSync:core/bandcamp_client.py:222-223` | Bandcamp needs no key | yes | |
| 15 | 05:352 | `ours:sourcing/verify.py:233` | transcode/fake hi-res hard under strict | yes | |
| 16 | 06:64 | `SoulSync:core/imports/file_integrity.py:472-549` | zero-length header: < 0.8 × expected fails | yes | |
| 17 | 06:293 | `SoulSync:core/downloads/master.py:915-939` | entity blocklist in the queue guard | yes | |
| 18 | 06:359 | `ours:sourcing/verify.py:291-294` | length ±4.0 s on every tier | partly (4.0 s lives elsewhere) | added `ours:sourcing/policy.py:33`, `ours:sourcing/verify.py:249` |
| 19 | 07:214 | `SoulSync:core/sync/mirrored_server_link.py:57-176` | mirror follows stored id, else name | yes | |
| 20 | 07:208 | `SoulSync:web_server.py:18873-18884` | single add rewrites the whole list | yes | |
| 21 | 07:428 | `ours:scripts/duplicate_cleanup.py:405-410` | cleanup refuses during a scan | yes | |
| 22 | 08:120 | `SoulSync:database/music_database.py:5904-5920` | profiles table, Admin seeded | yes | |
| 23 | 08:188 | `SoulSync:core/settings.py:668-671` | MCP off by default | yes | |
| 24 | 08:386 | `ours:crates/service.py:250` | approvals recorded as "michael" | yes | |
| 25 | 09:204 | `SoulSync:database/music_database.py:807-817` | album only in a JSON blob on a track row | yes | |
| 26 | 09:201 | `SoulSync:core/soulseek_client.py:2668-2690` | has a login probe | yes | |
| 27 | 09:87 | `ours:docs/specs/2026-10-13-next-session-design.md:72` | worker is the only writer (with architecture.md:76-77) | partly (D18 gives the gist, the co-cite the wording) | none needed: the pair holds |
| 28 | README:45 | `SoulSync:core/soulseek_client.py:235-306` | every non-2xx becomes None | yes | |
| 29 | README:246 | `SoulSync:core/wishlist/processing.py:1076-1091` | member rows wait for admin approval | yes | |
| 30 | README:51 | `ours:docs/specs/2026-10-22-downloads-and-requests.md:178` | S2-06 old tag values in the event | yes | |

Totals: 26 yes, 3 partly, 1 no. The no and two of the partlies are fixed; #27 holds as a pair.

#### Every `*unverified*` mark (50; line numbers are from before this session's edits; the header legends are excluded)

Resolved (4): 01:117 (worker count: `SoulSync:wsgi.py:3-6`, `SoulSync:docs/performance-1245.md:51`). README:175 (no native app), README:341 (no crate concept) and README:351 (no Mixxx) are now *absence inferred*, with the `find`/grep re-run: 0 project files, a chat-badge test only, and 0 hits.

Kept, with a would-verify clause added (9): 01:228 (pinned `tidalapi` `Session`, `SoulSync:requirements.txt:81`), 01:388 (`.author.login` against the author name), 08:140 (the launch-PIN and profile gate exemptions are now cited; still not run), README:60 (S4-01 `GET /transfers/downloads/<id>`), README:164 (the first setup run's length), README:211 (Navidrome's request log under Amperfy), README:223 (the forks' server-API code), 09:45 (time two rebases), 09:237 (SoulSync's real bound, 60 s / 35 %, now cited at `SoulSync:core/matching/acoustid_candidates.py:118-124`).

Kept as they were, each already naming what verifies it (37):
- 02:92 (installed spotipyFree), 02:373 (Shortcut test).
- 04:87 (search-timeout capture), 04:338 (parse logging), 04:349 (enqueue `path` test), 04:356 (swagger/routes), 04:367 (S4-01 enqueue reply), 04:384, 04:605 and 04:796 (S4-01 per-id GET), 04:543 (`GET /server` plus a search), 04:554 (429 test), 04:816 (`isLoggedIn` log).
- 05:64 (`tidalapi.Session` 0.8.11), 05:171 (yt-dlp's extractor; not in the clone, so not citable here), 05:368 (Opus → MP3 encode).
- 06:89 (FLAC-encode test), 06:104 (ffmpeg run), 06:303 (logging), 06:503 (Mixxx preferences).
- 07:240 (end-to-end Navidrome run).
- 08:274 (member POST), 08:322 (extension repo), 08:358 (iPhone), 08:471 (octo-fiesta's source), 08:504 (the phone).
- README:103 (04's log), README:155 (question 1), README:161 (a run doing the work), README:201 (the phone), README:252 (08's test).
- 09:14 (question 1); 09:15, 09:43 ×2, 09:56 and 09:111 (estimates under 09:15's blanket clause).

Wrong: 0.

### 2026-10-22 14:54 · V4-01 · passes

- **What changed:** new `docs/research/2026-10-22-soulsync/09-recommendations.md` (342 lines, 134 unique cites). It is docs only, so the test count stays at 1757. It weighs four options, each with a table of effort, risk, maintenance, licence and what changes in ours. (b) names 4 integration points and the 4 conflicts. (c) has a 15-row module table. **Recommendation: (c)**, port pieces re-written in our own words, with 7 ordered steps. The 23 S-rows are 12 keep, 11 change, 0 drop, and each change row has a `### Spec delta` marked "draft, not applied". `## Questions for Michael` has 10 questions, each with its assumption and where it is used.
- **New finding for (b):** SoulSync's slskd cleanups default to scope `own` (`core/soulseek_client.py:1370-1380`). Ours is the risk: fetch's "forget earlier attempts" loop DELETEs any finished record of the same filename. Once S1-04 adds `remove=true`, that would really delete another client's record, so the S1-04 delta limits the loop to our own ids.
- **Verified:** the citation check printed no BAD line. Every `NN-file.md`/README heading the file names exists (grep -x). There are 23 S-rows, and every change row has its delta. An Opus review spot-checked 67 cites: 54 held, 12 held partly, and 1 did not (`repair_worker.py:4071-4091` does check playlists; the text now uses the README's D31/D35 wording). It found 2 high, 5 medium and 8 low issues, and all are fixed. The main fix: deltas that depended on uncaptured shapes (`GET /server`, `bytesTransferred`) moved to a post-capture follow-up (step 6), so S1-06 became keep. I re-read 6 of the reviewer's claims in the clone and the fixtures. Suite: `lib/check.sh` printed "green in 650 s, 1757 tests" (1757 passed, 2 warnings, none newly skipped).
- **Next session (V4-02):** the README summary can take its verdict and next steps from `## Recommendation`. The S1 branch still does not exist (`git ls-remote`).
- **Questions for Michael:** two new ones in 09, Q9 (Spotify authorization-code login: default no for the queued runs) and Q10 (apply the 11 deltas before the S-runs: default yes). Q8, the reading of D7, is carried over from V3-01's note. **Proposed changes:** none.

### 2026-10-22 16:00 · verify V3

Independent re-run, both features hold (14 steps). Nothing live touched, no code or doc edited. Citation check on README: no BAD line. Sampled ~25 cites against the clone and our files; all supported their sentences.

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| V3-01 | 1 | awk-style count of `| **` rows in lines 32-52; read header and every row; sampled cites (matching_engine 1307-1335, monitor 690/759/936, gunicorn 4-6, automation_engine 77-83/238-243, settings 745-748) | 11 rows in the listed order, 4 columns as required; mechanism cells link a section anchor or cite; sampled lines support the cells | yes |
| V3-01 | 2 | read `### The 2026-10-21 failure classes` (53-126) | 5 numbered items, each with SoulSync / Ours did / Planned bullets, cites to the downloads spec findings table (23-50, 25, 27, 44-50) and S1/S2 features | yes |
| V3-01 | 3 | read `### Michael's decisions`; `sed -n` of design.md 61/72/76 and pivot spec 19,21,22,24,26,30,39 | table has D7, D18, D22/D29, D24, D26, D27, D31/D35, D44 with five-word gloss, verdict and cites; spec lines match the named decisions | yes |
| V3-01 | 4 | read Operations row; `sed -n` CLAUDE.md 43-68; SoulSync docker-compose.yml 8-9, automation_engine 238-243; grep for fcntl/filelock stated as *absence inferred* | ours cell cites CLAUDE.md Live system (deploy, restic, lock, Check); SoulSync cell cites Dockerfile, compose, entrypoint.sh, backup and lock evidence; lines match | yes |
| V3-01 | 5 | progress.md citation loop over README.md | no BAD line | yes |
| V3-01 | 6 | `grep -c unverified` (13 in README); read all of 32-145 | uncited statements carry `*unverified*` or *absence inferred*; sampled mechanism sentences all have cite or link | yes |
| V3-01 | 7 | `lib/check.sh` | green (cached for this tree), 1757 tests; docs only | yes |
| V3-02 | 1 | `grep -n '^### '` (171,229,267,292,337); B options vs spec lines 35-37 | five parts B/C/D/E/Crates; B has one paragraph each for options 1-3 matching spec names; Crates covers sync, Mixxx, D24, D26, D7 | yes |
| V3-02 | 2 | read each part's first line and Cost line; read lines 146-170 | each part starts `**SoulSync: partly/has/no.**`; each ends `from SoulSync: … / build ours: …` with one-sentence reasons; harness night defined once at 154 | yes |
| V3-02 | 3 | read E (292-336); spec 41-42 | spec's three steps quoted and marked Present / Different / Present-with-difference with cites; links 04-soulseek.md#when-a-track-fails | yes |
| V3-02 | 4 | read Crates (337-399); sampled playlist_edit.py:38, architecture.md:76-77, navidrome_client 1216-1226, sync/playlist_edit 96-108 | states shared Navidrome playlists yes if shared account, beets index not directly, two writers vs D18, links 07-filing-library.md; cites match | yes |
| V3-02 | 5 | progress.md citation loop | no BAD line | yes |
| V3-02 | 6 | grep unverified; sampled request.py:287-306, monitor 410-413, release_identity 80-83, web_server 16757-16762, enrichment 110-123 | unverified marks on estimates, native app, forks, Mixxx, crate concept; sampled cites support their sentences | yes |
| V3-02 | 7 | `lib/check.sh` | green (cached), 1757 tests | yes |

### 2026-10-22 14:27 · V3-02 · passes

- **What changed:** README.md `## Fit to goals` (docs only; 1757 tests before and after). It defines "harness night" once, cites the S-run as 23 features ≈ 3 nights, and names one fixed setup cost (≈ 1 night) shared by the "run SoulSync" routes. Then five `### ` parts, each with a bold verdict line and one cost line per goal (B has one per option). **B: partly** (option 1 only, in part: 1.5 / 0.5 nights; options 2 and 3 have nothing to take: 2-3 and ≥ 5 nights either way). **C: partly** (2 + a fork / 1.5). **D: has** (1.5 / 0.5). **E: partly** (1.5 / 1): step 1 present, step 2 different (up to 4 switches, no same-release rule, no distrust), step 3 present with the folder drifting. **Crates: no** (not reachable without a fork / 0 more): it would reconcile same-named playlists on a shared account, its admin profile could reach `amperfy`'s playlists, and it is a second library writer beside beets (D18).
- **Verified:** the citation check printed no BAD line, and `anchors.py` printed "links ok" (12 section-file anchors). An Opus review spot-checked 48 cites: 38 held and 10 held partly. Its 3 medium findings were fixed: "approval: no" became "only for member profiles" with four ways it misses D7; the effort figures were rescaled to the unit; each cost reason was cut to one sentence. All 13 low findings were fixed too, and I re-read 7 of the new cites in the clone. Suite: `lib/check.sh` printed "green in 651 s, 1757 tests".
- **`*unverified*` marks:** 10 in the section: the effort unit and estimates, no native app, which endpoints Amperfy calls, the forks' sources, the iOS Shortcut, member access to `start-missing-process`, no crate concept, no Mixxx. Each says what was grepped or what would settle it.
- **Next session (V4-01):** use the cost lines and the fixed setup cost to weigh options (a)-(d). The crates part is the strongest argument against (a) and (b).
- **Questions for Michael:** none new. Question 1 (the effort unit) still stands, because every figure in this section rests on it. **Proposed changes:** none.

### 2026-10-22 15:10 · V3-01 · passes

- **What changed:** README.md `## Stage-by-stage comparison` (docs only; 1757 tests before and after). It has an 11-row stage table with columns SoulSync / ours (built) / ours (planned S1-S4) / stronger and why. Every cell either links its section-file anchor or cites a line. Below it are `### The 2026-10-21 failure classes` (5 items, each with SoulSync's behaviour, what ours did and the planned S-feature) and `### Michael's decisions` (8 rows; SoulSync conflicts with 7 and does not address D27; D31/D35 is "conflicts, partly honours"). 04-soulseek.md:812 has one wording fix: the error retry is "at once, then ≥ 5 s apart", read from `monitor.py:936-937`.
- **Operations evidence found:** SoulSync's only backup is an "Auto-Backup Database" automation, every 3 days (`core/automation_engine.py:238-243`). It is an integrity-checked SQLite online backup of the database alone, written beside it, with 5 kept and the newest healthy copy never pruned (`core/db_integrity.py:83-140`, `core/automation/handlers/maintenance.py:98-128`). It has no file lock (grep for fcntl/flock/filelock: 0 files), only thread locks inside one gunicorn process.
- **Verified:** the citation check printed no BAD line (139 unique cites in README). A link and anchor check (scratch `anchors.py`) passes for every README link to 01-08. The table has 11 rows (awk count). An Opus review spot-checked 34 cites: 29 held, 4 held partly, 1 did not (the 300 s scan figure was on the wrong lines). It found 2 medium and 11 low wording or cite-scope findings. I re-read the clone lines for 8 of them and all held, and all 13 are fixed. Suite: `lib/check.sh` printed "green in 646 s, 1757 tests". `*unverified*` marks: 2 new ones (the per-peer route reached with a UUID; a retry inside the VPN drop), each saying what would settle it.
- **Next session (V3-02):** `## Fit to goals` goes under this section. The "stronger" column and the failure classes are its inputs. The S1 branch still does not exist (`git ls-remote`), so "ours (built)" is the base.
- **Reading of D7:** its recorded text (next-session-design.md:61) is "automatic downloads only after one manual approval and go". The README reads it as the review spec does, "nothing downloads without approval", and says that SoulSync conflicts with both readings. This is a reading, not a new decision.
- **Questions for Michael:** none new. **Proposed changes:** none.

### 2026-10-22 13:42 · verify V2

Independent re-run, all 9 features hold. Nothing live touched, no code or doc edited. Citation check on the final tree: 2,182 unique cites, no BAD line. I opened a fresh seeded sample (seed 777, 3 SoulSync + 1 ours per file, 28 cites, none from earlier samples) with the cited lines beside the sentence: all supported the claim (03:157 supports the penalty lift; the gate lift is elsewhere). I also re-ran the endpoint-table count (36), the `api/*.py` count (63) and route sum (1,212), `@media` in mobile.css (43), index.html length (12,932) and four flow cites in 07. Suite: `lib/check.sh` printed "green (cached for this code tree, 1757 tests)"; it shows no skip count.

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| V2-01 | 1 | read 02-intake.md 49-110; `grep -n 'PKCE\|2026'` | `### Spotify`: authorization code with the user's own app (client id/secret/redirect from settings, `spotify_client.py:800-819`), PKCE only for Tidal, cites public_api/scraper/token_cache/free_metadata, Feb 2026 limits at :104 with cites | yes |
| V2-01 | 2 | `grep -n '^### '`; read :139 | `### Other playlist sources` (131) with Tidal PKCE, Deezer, YT Music, Beatport, ListenBrainz paragraphs citing the named files | yes |
| V2-01 | 3 | headings 222/262/286; ls of cited files | Wishlist and watchlist, Requests, Lidarr compatibility headings present; all 9 spot-listed cited files exist in the clone | yes |
| V2-01 | 4 | read lines 17-37 | ASCII flow source → mirrored_playlists → run_sync_task → wishlist_tracks → run_full_missing_tracks_process with function names at each arrow | yes |
| V2-01 | 5 | `grep -oE 'ours:…' \| uniq -c`; `grep -c S2-02/S3-0[12]` | playlist_sources 3, import_playlist 7, spotify_csv 4, cli.py 3, store.py 5, downloads spec cited; S2-02 and S3-01/S3-02 named | yes |
| V2-01 | 6 | `grep -n 'Goal C\|Goal D'` | bold "Goal C" (354) and "Goal D" (380) judgements under `## The difference that matters` | yes |
| V2-01 | 7 | `grep -nE '^## \|^\*\*Verdict'` | headings at 8, 304, 352, 405 in order; `**Verdict:** adapt` at 418, file ends 2 lines later | yes |
| V2-01 | 8 | citation loop from progress.md over docs/research/2026-10-22-soulsync/*.md | 2,182 cites, no BAD line | yes |
| V2-01 | 9 | `grep -n unverified`; sampled cites 02:101, 02:183, 02:157, 02:328 against the clone/ours | 3 marks, each with a would-verify clause; the four sampled cites support their sentences | yes |
| V2-01 | 10 | `lib/check.sh` | green (cached), 1757 tests | yes |
| V2-02 | 1 | `grep -c` for each named file in 03-matching.md; read :46 area | matching_engine, core/matching/, client_match, source_ids, release_identity, edition_grouping, isrc_match, musicbrainz_*, acoustid_client all cited | yes |
| V2-02 | 2 | read 213-236; sampled 03:234 (`matching_engine.py:314-321`) and 03:47 (`:298-312`) | 4-qualifier table (remaster, live, extended, radio edit) × library/Soulseek/AcoustID/ours, each cell cited; 314-321 shows the 0.3 version-keyword penalty | yes |
| V2-02 | 3 | `grep -oE 'ours:…' \| uniq -c`; `sed -n 21p` pivot spec | import_playlist 13, identity.py 20, identity.md 9, scorer.py 10; D26 at amperfy-pivot.md:21 is the D26 row | yes |
| V2-02 | 4 | read 301-380; `grep ext-74` | ext-74 answered: base scorer accepts, base-title veto rejects (0.275 < 0.30), flat-name veto misses, cited | yes |
| V2-02 | 5 | `grep -nE '^## \|^\*\*Verdict'` | headings 10, 237, 301, 381 in order; `**Verdict:** adapt` at 397 | yes |
| V2-02 | 6 | citation loop | no BAD line | yes |
| V2-02 | 7 | `grep -c unverified` = 1; sampled 03:157, 03:352 | the one mark has a would-verify clause; sampled cites support (03:352 is the D26 row) | yes |
| V2-02 | 8 | `lib/check.sh` | green, 1757 tests | yes |
| V2-03a | 1 | headings in 04-soulseek.md; per-file `grep -c` in 30-343 | four `## ` headings; `### Search and candidates` cites query_variants 2, soulseek_client 27, candidates 17, candidate_pool 3, candidate_store 2 | yes |
| V2-03a | 2 | read `### Scoring` 126-152; prioritize 1, observed_speed 1 cites | scoring terms and numbers with line cites | yes |
| V2-03a | 3 | read 153-241 | album_bundle 4, album_bundle_dispatch 1, pinned_batch 3, release_identity 1 cites; ASCII flow album request → folder candidates → winner → bundle → per-track at 212-227 | yes |
| V2-03a | 4 | read 242-316 | retry order (same `(peer,file)` never again, another peer, bundle alternatives ≤ 4, 3 error retries), table against goal E and against S2-04/S1-06 | yes |
| V2-03a | 5 | `grep -c` failed_blocklist 3, peer_observation 2, soulseek_identity 6 | `### Peer memory` at 317 cites all three; 90-day blocklist, SHA1 key | yes |
| V2-03a | 6 | `grep -c 'ours:sourcing/X'` in 662-768 | scorer 11, fetch 10, policy 3, fake_slskd 7; "5 peers" finding cited | yes |
| V2-03a | 7 | `grep -rn 'part 2, transfers' docs/research` | no placeholder left (V2-03b removed it); sections have part-1 content | yes |
| V2-03a | 8 | citation loop; sampled 04:566, 04:528, 04:472, 04:694 | no BAD line; sampled lines support (web_server.py:1434-1442 is the ThreadPoolExecutor(max_workers=3) pool) | yes |
| V2-03a | 9 | `grep -c unverified` = 12; read 04:87, 338, 349, 367, 384 | each carries a what-would-verify clause | yes |
| V2-03a | 10 | `lib/check.sh` | green, 1757 tests | yes |
| V2-03b | 1 | read 344-487 | `### Transfers` cites enqueue body, `:1250` remove pattern, poll/timeouts, task states list at 108-109 | yes |
| V2-03b | 2 | read 488-577; `sed -n 1042p`, `1248,1256p` of soulseek_client.py | `### Errors and outages` and `### Throttling` present; the DELETE `?remove=` pattern at :1250 is as described | yes |
| V2-03b | 3 | `awk '/^\| [0-9]+ \|/'` over the table; ls /api/v0/ grep | 36 rows (states 36), each "from SoulSync's code, not captured"; /api/v0 prefix at :199-212 and direct path :315-321 noted; `grep` shows `transfers/downloads/{id}` at :1042 | yes |
| V2-03b | 4 | read 635-660 | S1-04/S2 capture list: enqueue response, `/users/{peer}/directory` browse, per-transfer record, each tied to S1-04/S2-04/S2-05 | yes |
| V2-03b | 5 | read 719-768 | `slskd_client.py` table of eight calls by line, fetch loop, per-peer 404 handling at slskd_client.py:79-84, S1-04/S1-05/S1-06 cited | yes |
| V2-03b | 6 | read 790-833 | failure classes: 404 from GET per-peer (SoulSync never asks it, confirmed by `grep` of `transfers/downloads/{`), DELETE without remove, VPN drop; placeholders gone | yes |
| V2-03b | 7 | headings and verdict | headings 30, 662, 769, 834; `**Verdict:** adapt` at 859 | yes |
| V2-03b | 8 | citation loop | no BAD line | yes |
| V2-03b | 9 | unverified marks read | clauses present (e.g. 04:384, 543, 554) | yes |
| V2-03b | 10 | `lib/check.sh` | green, 1757 tests | yes |
| V2-04 | 1 | `grep -n '^### '`; `ls core \| grep -iE 'tidal\|youtube\|…'`; count `ToS/legal` | 12 source headings (Deezer…Lidarr); 12 inline flags (streaming rip ×7, clean ×1, grey ×4); tidal/youtube/soundcloud client files exist so no "not in the clone" needed | yes |
| V2-04 | 2 | read Deezer, Tidal, Qobuz, Amazon, HiFi paragraphs | each states **Credentials:** and "Embedded: …" with file:line, mechanism only (Blowfish secret, scraped Qobuz secret), no values | yes |
| V2-04 | 3 | read 254-336 | `### How the orchestrator chooses` cites download_orchestrator, registry, base; order, enable flags (membership of `hybrid_order`), fall-through; ASCII flow present | yes |
| V2-04 | 4 | read 337-360, 388-406 | two-sentence ours (D7, D26, architecture.md:36-37, fetch.py); D24 quality-provenance paragraph; verdict per source group | yes |
| V2-04 | 5 | headings and verdict | 12, 337, 348, 388; `**Verdict:** no` ends the file | yes |
| V2-04 | 6 | citation loop; sampled 05:247, 05:121, 05:61, 05:386 | no BAD; sampled lines support (settings.py:676 is Lidarr `quality_profile: "Any"`) | yes |
| V2-04 | 7 | `grep -c unverified` = 4; read 05:64, 171 | each has a would-verify clause | yes |
| V2-04 | 8 | `lib/check.sh` | green, 1757 tests | yes |
| V2-05 | 1 | `grep -c` of 13 named files over 10-337 | validation 5, post_processing 16, atomic_* 8/3/7, album_consistency 8, acoustid_verification 10, audio_length 3, quality 11, replaygain 4, quarantine 8, review_reject 3, blocklist 2; check chain table with thresholds; `file_integrity.py:100-116` shows 3.0/5.0/15.0 s | yes |
| V2-05 | 2 | read 306-337 | summary table (fake detection: no; wrong-song; album consistency; quarantine) and `### Would ext-74 have been caught?` with `audio_verification.py:829-831` | yes |
| V2-05 | 3 | `grep -oE 'ours:…' \| uniq -c`; `grep -c _acoustid_check` | verify.py 33, acoustid.py 5, policy.py 3, deploy/policy.toml 3, download-validation.md 4; `_acoustid_check` 1; S1-02 6, S2-03 2 | yes |
| V2-05 | 4 | read 423-483 | D24 (line 425) and D26 judged by name | yes |
| V2-05 | 5 | headings and verdict | 10, 338, 423, 484; `**Verdict:** adapt` at 506 | yes |
| V2-05 | 6 | citation loop; sampled 06:65, 06:270, 06:59, 06:376 | no BAD; lines support the sentences | yes |
| V2-05 | 7 | `grep -c unverified` = 10; read 06:89, 104, 303, 503 | the content marks have would-verify clauses (the rest are the word in code names such as `acoustid_unverified`) | yes |
| V2-05 | 8 | `lib/check.sh` | green, 1757 tests | yes |
| V2-06 | 1 | `grep -n '^### '` and cites in 07 | five `###` questions (beets, tags, scans, playlists, deletes) each cited; "beets is not a dependency" at :48 agrees with 01-map:245 | yes |
| V2-06 | 2 | read the ASCII flow (lines 13-35); `sed -n` of settings.py:915-919, 539, pipeline.py:1514, file_ops.py:208, web_server.py:1284, automation_engine.py:140-145 | flow runs download → pipeline → auto_import_worker → template (`album_path`, settings.py:915-919) → tags → scan; each cited line says what the flow says | yes |
| V2-06 | 3 | `grep -c` ours cites; MOVES 3, S2-06 5 | filer 8, playlist_edit 7, trash 4, placement 3, CLAUDE.md, hard-won-facts, S2-06 cited | yes |
| V2-06 | 4 | read 392-417 | table with one row per invariant (4) and honours/conflicts/not addressed with cites | yes |
| V2-06 | 5 | headings and verdict | 11, 323, 392, 418; `**Verdict:** no` at 442 | yes |
| V2-06 | 6 | citation loop; sampled 07:70, 07:317, 07:282, 07:241 | no BAD; lines support (07:317's cite closes the previous sentence) | yes |
| V2-06 | 7 | `grep -c unverified` = 3 | marks present with clauses ("absence inferred" ones name the grep) | yes |
| V2-06 | 8 | `lib/check.sh` | green, 1757 tests | yes |
| V2-07 | 1 | read 26-64; recount: `ls api/*.py`, summed route grep, `wc -l webui/index.html` | 63 files and 1,212 routes (255 + 957) match my count; index.html 12,932 lines; blueprint, auth, streaming, MCP, automation, webhooks headings | yes |
| V2-07 | 2 | `grep -n 'A request from the phone'`; read 232-330 | three paths (search, pasted link, share-sheet/bookmarklet) end at an API call and record | yes |
| V2-07 | 3 | read 331-363; `grep -c @media mobile.css` | viewport meta, 43 `@media` in mobile.css (my count 43), `index.html` none (my count 0), manifest and `sw.js` present; unprovable items marked *unverified* | yes |
| V2-07 | 4 | read 364-441, 442-492 | ours:crates/service.py, web/, architecture.md, S3-01..S3-06 cited; B1, B2, B3 paragraphs | yes |
| V2-07 | 5 | headings and verdict | 9, 364, 442, 493; `**Verdict:** no` at 516 | yes |
| V2-07 | 6 | citation loop; sampled 08:351, 08:240, 08:215, 08:413 | no BAD; lines support (index.html:92 `theme-color`, :93 apple-touch-icon) | yes |
| V2-07 | 7 | `grep -c unverified` = 7 | marks have would-verify clauses | yes |
| V2-07 | 8 | `lib/check.sh` | green, 1757 tests | yes |
| V2-08 | 1 | read the V2-08 table in the 13:55 entry; reopened 28 fresh cites | table lists 4 per file (3 SoulSync, 1 ours) for 02-08; my 28 also hold; the `rework` fix is in 03 (matching_engine.py:1218-1221 lists it) | yes |
| V2-08 | 2 | citation loop; read the 34 unverified lines | no BAD; marks carry what would verify them | yes |
| V2-08 | 3 | `grep -nE '^## \|^\*\*Verdict'` on 02-08; README links via `ls` | four headings in order and one verdict in each; README links 01-08 resolve; 09 is V1-01's forward link and does not exist until V4-01 | yes |
| V2-08 | 4 | greps for beets, streaming, retry counts across 04/06/07/08 | agree: no beets (07:48, 01-map:245), streams to its own browser player only (08:145), 5 quarantine retries and ≤ 4 album alternatives (04, 06) | yes |
| V2-08 | 5 | python over every ``` block >10 lines in 01-08 | 10 blocks, all ASCII flows or tables of ours; the only lines resembling code are box-drawing lines containing words like "import pipeline" | yes |
| V2-08 | 6 | `lib/check.sh` | green, 1757 tests (cached) | yes |

### 2026-10-22 13:55 · V2-08 · passes

Second attempt: verify V2 failed step 1 only (no file/citation/holds table). I opened a fresh seeded sample (`pick.py 1022`, 3 SoulSync + 1 ours per file, none from the first attempt's 21) with `sed -n` and checked each against its full sentence: 24 hold, 4 were incomplete and are fixed in the file.

| File | Citation | Holds |
|---|---|---|
| 02 | `SoulSync:core/spotify_client.py:1575-1643` (Liked Songs as a virtual playlist) | yes |
| 02 | `SoulSync:core/listenbrainz_client.py:178-179` (`Authorization: Token`) | yes |
| 02 | `SoulSync:api/wishlist.py:88-97` (`POST /api/v1/wishlist`, API key; route at :44-46) | yes |
| 02 | `ours:web/app.js:355` (approve button) | yes |
| 03 | `SoulSync:database/music_database.py:14038-14081` (#808 qualifier strip) | yes |
| 03 | `SoulSync:core/musicbrainz_worker.py:344-379` (existing ids kept) | yes |
| 03 | `SoulSync:core/matching_engine.py:1218-1221` (remix patterns) | **no**: list missed `rework`; fixed |
| 03 | `ours:sourcing/identity.py:313-321` (`parse_filename`) | yes |
| 04 | `SoulSync:web_server.py:2187-2205` (Soulseek albums one at a time) | yes |
| 04 | `SoulSync:core/soulseek_client.py:686-687` (search timeout 60 s) | yes |
| 04 | `SoulSync:core/soulseek_client.py:1079-1115` (`transfers/downloads` shape) | yes |
| 04 | `ours:sourcing/fetch.py:430-446` (non-Succeeded/600 s fails the row, `return fail`) | yes |
| 05 | `SoulSync:core/amazon_download_client.py:252-264` (codec step-down only) | yes |
| 05 | `SoulSync:core/bandcamp_client.py:225-275` (public autocomplete JSON) | yes |
| 05 | `SoulSync:core/deezer_download_client.py:1194-1219` (fallback default True in code; order at :48) | yes |
| 05 | `ours:sourcing/verify.py:232` (`HARD_EVERY_TIER`) | yes |
| 06 | `SoulSync:core/downloads/validation.py:981-1015` (artist words in one path segment) | yes |
| 06 | `SoulSync:core/matching/acoustid_candidates.py:171-186` (length-contradiction SKIP; 60 s/35 % at :118-124) | yes |
| 06 | `SoulSync:api/quarantine.py:481-488` (legacy `recover` to Staging) | yes |
| 06 | `ours:sourcing/verify.py:217-218` (120 s / 900 s fingerprint) | yes |
| 07 | `SoulSync:core/maintenance/dedupe_source_ids.py:24-32` (`dry_run=True`) | yes |
| 07 | `SoulSync:core/repair_worker.py:492` (`repair.master_enabled` True) | yes |
| 07 | `SoulSync:core/imports/pipeline.py:1209-1222` (simple download scans) | **partly**: only outside a batch and while the auto-scan automation is on; fixed |
| 07 | `ours:docs/hard-won-facts.md:24-26` (`ND_AUTOIMPORTPLAYLISTS` off) | yes |
| 08 | `SoulSync:core/webui/spa.py:5-23` via `web_server.py:3288-3293` (SPA exclusions) | **partly**: also `/callback`, `/deezer`, `/tidal`, `/status`; fixed |
| 08 | `SoulSync:webui/index.html:12689-12691` (graphology/sigma from CDN) | yes |
| 08 | `SoulSync:web_server.py:10283-10284` (only ffmpeg use is ReplayGain) | **partly**: 1 of 3 checks; added `:10330-10331`, `:10444-10445` |
| 08 | `ours:sourcing/worker.py:8-37` (reconcile 600 s, re-check 300 s, export 300 s) | yes |

- **Changed:** `03-matching.md`, `07-filing-library.md`, `08-ui-api.md` (9 lines; docs only, tests 1757 → 1757).
- **Other steps re-run by me:** citation check, no BAD line (2,182 unique cites); 34 `*unverified*` lines in 02-08 (7 are the header legend), each with a would-verify clause (08:358 is one group clause covering five phone questions); 02-08 have the four `## ` headings in order and one `**Verdict:**` each; README links 01-08 resolve, 09 is V4-01's forward link; grep across 01-08 for spotipyFree, beets, `playlist_sync.mode`, 12 h purge, transcode agrees across files; 9 code blocks over 10 lines, all our own ASCII flows, 0 Python lines (`def|class|return|import|self.`). Suite: `lib/check.sh` "green in 648 s, 1757 tests" on the final tree.
- **For V3:** the two ASCII flows in 08 (lines 248, 281) cite paths without the `SoulSync:` prefix, so the citation check skips them; I did not open those.
- **Questions for Michael:** none. **Proposed changes:** as in the first attempt (step 3: "01-08 resolve; 09 is a forward link"; step 5: grep for Python lines inside code blocks).

### 2026-10-22 13:25 · verify V2

Independent re-run: 8 features hold, 1 fail (V2-08). Nothing live touched.

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| V2-01 | 1 | read 02-intake.md 49-130; sed spotify_client.py | `### Spotify`: authorization code with the user's own app, cites spotify_client/public_api/public_scraper/token_cache/free_metadata; Feb 2026 limits at :104 with cites | yes |
| V2-01 | 2 | grep '^### ' 02-intake.md | `### Other playlist sources` (131): Tidal PKCE, Deezer, YouTube Music etc., cites source_playlists, mirrored_playlists, core/playlists, services/sync_service | yes |
| V2-01 | 3 | grep '^### '; grep file names | `### Wishlist and watchlist`, `### Requests`, `### Lidarr compatibility` present with the cited files | yes |
| V2-01 | 4 | read lines 17-37 | ASCII flow source → mirrored_playlists → auto_sync_playlist → wishlist_tracks → run_full_missing_tracks_process, function names at each arrow | yes |
| V2-01 | 5 | grep ours: file names | playlist_sources 3, import_playlist 7, spotify_csv 3, cli.py 2, store.py 5, downloads spec 7 line-cited; S2-02, S3-01, S3-02 named | yes |
| V2-01 | 6 | read 352-404 | Goal C and Goal D judged by name | yes |
| V2-01 | 7 | `grep -n '^## '` and `grep -n '^\*\*Verdict'` on the file | four headings (8,304,352,405); `**Verdict:** adapt` at 418 | yes |
| V2-01 | 8 | citation check from progress.md over docs/research/2026-10-22-soulsync/*.md (2,180 unique cites) | no BAD line printed | yes |
| V2-01 | 9 | grep -c unverified; seeded random cites read with `sed -n` (spotify_client:1645, _pipeline_shared:232, sync_service:1393, ours spotify_csv:1-6) | sampled cites support their sentences; sampled SoulSync lines carry a cite or a mark | yes |
| V2-01 | 10 | `lib/check.sh`: 'green (cached for this code tree, 1757 tests)' | green, 1757 tests, docs only (cached result; no skip count shown) | yes |
| V2-02 | 1 | grep file names in 03-matching.md | matching_engine 53, core/matching/, client_match, source_ids, release_identity, edition_grouping, isrc_match, musicbrainz_, acoustid_client all cited | yes |
| V2-02 | 2 | read 213-236; sed matching_engine.py:46 and :1204-1206 | 4-qualifier table over library/Soulseek/AcoustID with cites; the lines support the 0.30 and 0.08 values | yes |
| V2-02 | 3 | grep ours cites | import_playlist 12, identity.py 18, identity.md 8, scorer.py 9, amperfy-pivot.md:21 3 | yes |
| V2-02 | 4 | read 301-380; grep ext-74 | ext-74 answered: base scorer accepts, base-title veto rejects (0.275 vs 0.30), flat-name veto misses, with cites | yes |
| V2-02 | 5 | `grep -n '^## '` and `grep -n '^\*\*Verdict'` on the file | four headings (10,237,301,381); `**Verdict:** adapt` at 397 | yes |
| V2-02 | 6 | citation check from progress.md over docs/research/2026-10-22-soulsync/*.md (2,180 unique cites) | no BAD line printed | yes |
| V2-02 | 7 | grep -c unverified; seeded random cites read with `sed -n` (music_database:12494, ours import_playlist:135-140) | sampled cites support their sentences; sampled SoulSync lines carry a cite or a mark | yes |
| V2-02 | 8 | `lib/check.sh`: 'green (cached for this code tree, 1757 tests)' | green, 1757 tests, docs only (cached result; no skip count shown) | yes |
| V2-03a | 1 | grep '^### ' 04-soulseek.md; file names | four headings; `### Search and candidates` cites query_variants, soulseek_client, candidates, candidate_pool, candidate_store | yes |
| V2-03a | 2 | read 126-152 | `### Scoring`: numeric weights (0.45/0.40/0.15, 0.08 band, 0.58) with cites; prioritize and observed_speed cited | yes |
| V2-03a | 3 | read 153-241 | `### Album requests and folder choice` cites album_bundle, album_bundle_dispatch, pinned_batch; ASCII flow at 214-220 | yes |
| V2-03a | 4 | read 242-316 | `### When a track fails`: 3 error / 3 stall / 5 quarantine retries; table against goal E, S2-04, S1-06 | yes |
| V2-03a | 5 | read 317-343 | `### Peer memory` table: failed_blocklist, peer_observation, soulseek_identity with key/TTL/blocks | yes |
| V2-03a | 6 | grep ours cites | scorer 11, fetch 11, policy 3, fake_slskd 8, slskd_client 15; the 5-peers/4-releases finding named | yes |
| V2-03a | 7 | grep 'part 2, transfers' 04-soulseek.md | 0 hits: placeholder was replaced when V2-03b landed (its own step 6) | yes |
| V2-03a | 8 | citation check from progress.md over docs/research/2026-10-22-soulsync/*.md (2,180 unique cites) | no BAD line printed | yes |
| V2-03a | 9 | grep -c unverified; seeded random cites read with `sed -n` (monitor:410, peer_observation:53, ours fetch:162) | sampled cites support their sentences; sampled SoulSync lines carry a cite or a mark | yes |
| V2-03a | 10 | `lib/check.sh`: 'green (cached for this code tree, 1757 tests)' | green, 1757 tests, docs only (cached result; no skip count shown) | yes |
| V2-03b | 1 | read 344-487; sed soulseek_client.py:838-844 | `### Transfers`: enqueue POST per file plus 7-POST cascade, id lookup, poll, timeouts, 3 DELETE forms, states, ASCII | yes |
| V2-03b | 2 | read 488-577 | `### Errors and outages` and `### Throttling` (35/220 s, 429 cooldown) with cites | yes |
| V2-03b | 3 | read 578-634; count numbered rows | 36 rows (≥ 8); prefix :199-212, direct path :315-321; fixed note present | yes |
| V2-03b | 4 | read 635-661 | `### What our S1-04 and S2 should capture`: enqueue reply, POST users/{peer}/directory, per-transfer record, tied to ids | yes |
| V2-03b | 5 | grep ours cites | slskd_client 15, fetch 11, hotfix 404 at slskd_client:79-84, S1-04/05/06 | yes |
| V2-03b | 6 | read 769-833; grep placeholder | 404, DELETE without remove=true, VPN drop each cited; placeholder gone | yes |
| V2-03b | 7 | `grep -n '^## '` and `grep -n '^\*\*Verdict'` on the file | four headings in order; `**Verdict:** adapt` | yes |
| V2-03b | 8 | citation check from progress.md over docs/research/2026-10-22-soulsync/*.md (2,180 unique cites) | no BAD line printed | yes |
| V2-03b | 9 | grep -c unverified 04 = 12; random cites | marks carry a would-verify clause; sampled cites hold | yes |
| V2-03b | 10 | `lib/check.sh`: 'green (cached for this code tree, 1757 tests)' | green, 1757 tests | yes |
| V2-04 | 1 | grep '^### ' 05-other-sources.md; read Deezer, Qobuz, HiFi | 12 headings Deezer…Lidarr, each with client-file cites and a `**ToS/legal:**` flag (7 streaming rip, 4 grey, 1 clean) | yes |
| V2-04 | 2 | grep embedded|hard-coded; read paragraphs | credentials (ARL, token, key) and embedded-secret mechanism with file:line, no values | yes |
| V2-04 | 3 | read 254-336 | `### How the orchestrator chooses` cites download_orchestrator and registry; ASCII flow present | yes |
| V2-04 | 4 | read 337-347 and 348-405 | two sentences, Soulseek-only, architecture.md:36-37, fetch.py; streaming-rip/D24 risk; verdict per group | yes |
| V2-04 | 5 | `grep -n '^## '` and `grep -n '^\*\*Verdict'` on the file | four headings (12,337,348,388); `**Verdict:** no` at 406 | yes |
| V2-04 | 6 | citation check from progress.md over docs/research/2026-10-22-soulsync/*.md (2,180 unique cites) | no BAD line printed | yes |
| V2-04 | 7 | grep -c unverified; seeded random cites read with `sed -n` (deezer, qobuz_client:1283, hifi_client:1190, soundcloud_client:11-13, ours verify:233) | sampled cites support their sentences; sampled SoulSync lines carry a cite or a mark | yes |
| V2-04 | 8 | `lib/check.sh`: 'green (cached for this code tree, 1757 tests)' | green, 1757 tests, docs only (cached result; no skip count shown) | yes |
| V2-05 | 1 | grep file names in 06-verification.md | validation, post_processing, atomic_album_publish/manifest/recovery, album_consistency, acoustid_verification, quality/, replaygain, quarantine, blocklist cited; audio_length once (audiobook only, said so) | yes |
| V2-05 | 2 | read 306-337 | summary table (transcode, wrong-song, album consistency, quarantine) and `### Would ext-74 have been caught?` with audio_verification:829-831 | yes |
| V2-05 | 3 | grep ours cites | verify.py 28, acoustid.py 4, policy.py 4, policy.toml 3, download-validation.md 6, `_acoustid_check`, S1-02, S2-03 | yes |
| V2-05 | 4 | grep D24, D26 in 06; read 423-483 | difference judged against D24 and D26 by name | yes |
| V2-05 | 5 | `grep -n '^## '` and `grep -n '^\*\*Verdict'` on the file | four headings (10,338,423,484); `**Verdict:** adapt` at 506 | yes |
| V2-05 | 6 | citation check from progress.md over docs/research/2026-10-22-soulsync/*.md (2,180 unique cites) | no BAD line printed | yes |
| V2-05 | 7 | grep -c unverified; seeded random cites read with `sed -n` (album_matching:446, acoustid_verification:99, quality/schema:141, ours musicbrainz:84) | sampled cites support their sentences; sampled SoulSync lines carry a cite or a mark | yes |
| V2-05 | 8 | `lib/check.sh`: 'green (cached for this code tree, 1757 tests)' | green, 1757 tests, docs only (cached result; no skip count shown) | yes |
| V2-06 | 1 | grep '^### ' 07-filing-library.md | five `###` question headings (beets, tags, scans, playlist edits, deletes/moves) with cites | yes |
| V2-06 | 2 | read 14-35 | ASCII flow with template key (settings.py:915-919), tags, scan; notes SoulSync's real order | yes |
| V2-06 | 3 | grep ours cites | filer 5, playlist_edit 7, trash 2, MOVES.txt, placement 2, CLAUDE.md, hard-won-facts 6, S2-06, D18/D22/D29/D44 | yes |
| V2-06 | 4 | read 391-416 | table with one row per safety invariant, honours/conflicts/not addressed, each cited | yes |
| V2-06 | 5 | `grep -n '^## '` and `grep -n '^\*\*Verdict'` on the file | four headings (11,322,391,417); `**Verdict:** no` at 441 | yes |
| V2-06 | 6 | citation check from progress.md over docs/research/2026-10-22-soulsync/*.md (2,180 unique cites) | no BAD line printed | yes |
| V2-06 | 7 | grep -c unverified; seeded random cites read with `sed -n` (expired_cleanup:150, web_server:18986, ours CLAUDE.md:11-12) | sampled cites support their sentences; sampled SoulSync lines carry a cite or a mark | yes |
| V2-06 | 8 | `lib/check.sh`: 'green (cached for this code tree, 1757 tests)' | green, 1757 tests, docs only (cached result; no skip count shown) | yes |
| V2-07 | 1 | count api/*.py, route decorators, register_blueprint, viewport, manifest, lines in the clone | 63 files, 255+957=1212 routes, 43 blueprints, viewport index.html:6, manifest :91, 12,932 lines: all match 08-ui-api.md | yes |
| V2-07 | 2 | read 230-328; sed api/request.py:272-278 | three paths (search, pasted link, Shortcut/API) each ending at its record | yes |
| V2-07 | 3 | read 329-361 | responsive (43 @media), manifest + sw.js, no share_target, unprovable marked | yes |
| V2-07 | 4 | grep ours cites; read 440-490 | service.py 17, web/ 18, architecture.md 6, S3-01..06; B1, B2, B3 one paragraph each | yes |
| V2-07 | 5 | `grep -n '^## '` and `grep -n '^\*\*Verdict'` on the file | four headings (9,362,440,491); `**Verdict:** no` at 514 | yes |
| V2-07 | 6 | citation check from progress.md over docs/research/2026-10-22-soulsync/*.md (2,180 unique cites) | no BAD line printed | yes |
| V2-07 | 7 | grep -c unverified; seeded random cites read with `sed -n` (play_log:1-7, blocks.py:352, ours worker.py:8) | sampled cites support their sentences; sampled SoulSync lines carry a cite or a mark | yes |
| V2-07 | 8 | `lib/check.sh`: 'green (cached for this code tree, 1757 tests)' | green, 1757 tests, docs only (cached result; no skip count shown) | yes |
| V2-08 | 1 | read the V2-08 entry in progress.md for a table | only a prose 'Spot-check' paragraph (21 cites, 20 hold, 1 widened): 2 SoulSync + 1 ours per file but NO table of file, citation, holds; the step requires a table | NO |
| V2-08 | 2 | citation check from progress.md over docs/research/2026-10-22-soulsync/*.md (2,180 unique cites); read marks | no BAD line; marks 48 → 27 each with a would-verify clause (sampled) | yes |
| V2-08 | 3 | grep '^## ' 02-08; README links + `ls` | 4 headings and one Verdict each; links 01-08 resolve, 09 is a forward link (V4-01) | yes |
| V2-08 | 4 | grep beets, retries, transcode, auto-import across 01,05,06,07,08 | consistent: no beets (01=07), 5 quarantine retries (04=06), no on-the-fly transcode with YouTube MP3 320 (05=08), auto-import opt-in (01=07) | yes |
| V2-08 | 5 | awk: fenced blocks >10 lines, Python tokens inside | 9 long blocks, 3 read: our own ASCII flows; no copied clone code | yes |
| V2-08 | 6 | `lib/check.sh`: 'green (cached for this code tree, 1757 tests)' | green, 1757 tests | yes |

### 2026-10-22 13:30 · V2-08 · passes
- **Changed:** 01-08 under `docs/research/2026-10-22-soulsync/` (about 190 lines touched; docs only, tests 1757 → 1757). every content `*unverified*` mark in 02-08 was re-read (48 before, 27 now): 14 are now cited (5 of them corrected claims), 9 grep-only absences became `*absence inferred*` with the grep stated, several more were narrowed to a cited part, and the remaining 27 keep the mark with a "would be verified by" clause (slskd 0.26 captures for S4-01, iOS/Android, tidalapi/yt-dlp, Mixxx). There are 12 cross-file contradictions, reconciled below. Mechanical checks: the citation check prints no BAD line; 02-08 each have the four `##` headings in order and one `**Verdict:**`; README's `## Sections` links 01-08 and all resolve (09 is V4-01's); every code block is our own ASCII flow, and none holds a Python line (`def|class|return|import|self.` grep = 0).
- **Spot-check (me, `sed -n`):** 20 hold, 1 partly holds (widened). 02: `spotify_client.py:1547-1548` yes, `refresh_mirrored.py:277-351` yes, ours `cli.py:155-160` yes. 03: `watchlist_scanner.py:2900-2976` yes, `matching_engine.py:1517-1529` yes, ours `identity.md:108-140` yes. 04: `slskd_throttle.py:1-23` yes, `size_limit.py:23-53` yes, ours `scorer.py:246-251` yes. 05: `tidal_download_client.py:396-404` yes, `hifi_client.py:792-806` yes, ours `next-session-design.md:142-143` yes. 06: `silence.py:34-43` yes, `lifecycle.py:1183-1201` **partly** (stopped before the publish call; now `1183-1217`), ours `policy.py:27-33` yes. 07: `pipeline.py:123-135` yes, `paths.py:1222-1223` yes, ours `subsonic/client.py:174-178` yes. 08: `index.html:12687-12688` yes, `play_log.py:1-19` yes, ours `web/app.js:151` yes.
- **Contradictions reconciled (Opus consistency agent; I checked each in the clone):**
  - The quarantine block is a DB table with no TTL (25,000-row cap), not "until the sidecar goes" (04 vs 06).
  - ext-74: rejected only on the per-track search path. The folder-reuse path (base ≥ 0.70, no veto, `web_server.py:16757-16762`) would take it (03/06 vs 04).
  - Reconcile re-adds removed tracks and removes hand-added ones (02 had deferred this to 07).
  - auto-import starts only when opted in (01 vs 07). Quarantine blocks are per (peer, file), not per peer (01 vs 04/06).
  - spotipyFree is a pip dependency that is soft-imported (02's "V2-08 reconciles").
  - Album batches pin one folder at ≥ 80 % coverage and score ≥ 0.62 (02's deferral to 04).
  - Streaming: none of it is transcoded on the fly, but YouTube files are already MP3 320 re-encodes (08 vs 05).
  - The 12 h auto-purge hits the quarantine folder, not the recycle bin (07 vs 06/08).
  - `playlist_sync.mode` is `reconcile` on Docker but `replace` on a non-Docker fresh install (02/07 both missed this).
  - Ours: `crates/service.py:511`, not `:488` (01 vs 08). There are 43 registered blueprints.
- **Corrected by the marks pass + an Opus diff review (about 115 cites opened, 10 findings; 8 applied, 2 minor nuances left as they are):**
  - From code, step 5's 15 s stall timeout never fires: no `track_info` carries `is_album_download`, so it is always 90 s.
  - A `Completed, Aborted` task with bytes short waits until the 600 s status-builder safety valve (it runs only while the batch status is polled).
  - Multi-disc atomic publish can overwrite (`os.replace`).
  - Reorganize removes the original when the target is already taken.
  - The API-key bootstrap is mounted at `/api/v1`, and a new key defaults to admin.
  - 06's ours grep `quarantin|blocklist` could not match "blacklist"; it now includes it.
- **For V3/V4:** S4-01's capture list is unchanged and still the way to settle the slskd-side marks in 04. The README comparison table is still the V3-01 placeholder. Suite: `check.sh` green on the final tree, 1757 tests in 648 s (650 s before the review fixes).
- **Questions for Michael:** none new. **Proposed changes:** step 3's "README links all eight files" should read "01-08 resolve; 09 is a forward link". Step 5's "`grep -c` of function bodies" is better done as a grep for Python lines inside code blocks, which is what I ran.

### 2026-10-22 12:17 · V2-07 · passes
- **New:** `docs/research/2026-10-22-soulsync/08-ui-api.md` (~505 lines, 276 unique cites, 7 `*unverified*` + 13 `*absence inferred*` marks). It covers route registration and counts (63 `api/*.py`, 255 + 957 = 1,212 route decorators), the web UI, auth/profiles/API keys, streaming/radio, MCP, automation and webhooks, and `### A request from the phone` (search, pasted link, Shortcut/API, each as an ASCII flow ending at its record). Then `### Phone fit`, ours (`crates/service.py` routes, `web/`, D19→D25 streaming, S3-01..06), one paragraph per B option plus goal C, and worth taking. **Verdict: no.** Docs only; tests 1757 → 1757.
- **Findings:** SoulSync has **no Subsonic server**, so Amperfy or a native fork cannot use it. It streams only to its own browser player: library files as they are, Navidrome `/rest/stream` proxied with Range, and tracks it doesn't own downloaded whole first (YouTube by default). Queue prefetch files up to 250 tracks it doesn't own. Login is off by default (a single-profile install treats everyone as admin), and login mode exempts `/api/v1/*`, including an unauthenticated key bootstrap. An admin key downloads at once (`POST /api/v1/request`, no approval). Member approval is enforced only in the 30-minute wishlist run; `start-missing-process` has no permission check (read from code). The search bar and the Sync page use two link parsers, and each misses one kind (playlist vs Spotify track). It has a real PWA (manifest + `sw.js`, mobile.css with 43 `@media` rules) but no `share_target`, no Web Push, and `user-scalable=no`. MCP (35 tools, off by default, key-scoped) can download without confirmation. Full Cleanup ships enabled every 12 h.
- **Verified:** the citation check prints no BAD line. Four Opus fact agents (3 on the clone, 1 on ours); I spot-checked about 30 cites with `sed -n` (all held) and re-ran the share-target and Shortcut greps myself. My first combined grep matched keyboard "shortcuts", so I fixed it. An Opus review opened 58 cites and returned 13 findings, all fixed and re-checked: 12 permission calls, not 13; the 60/min cite; `hover:none` ×3; the search alternates; the badge-poll sweep; ours has 14 GET / 12 POST routes; Swap does edit a playlist; downloads also happen through CLI `fetch --approve`; the worker order and the 30 s cite; grep output; the sw.js shape; `release-group`. Suite: `check.sh` green, 1757 tests in 648 s on the pre-review tree and 647 s on the final tree (1757 passed, none skipped).
- **For V3/V4:** worth-taking items are S3-01's link-keyword table plus `playlist`; for B1's web client, a static-only service worker, PNG icons and a `share_target` that POSTs to S3-01; and S3-03 request states, with ntfy on "available". `docs/architecture.md:231` still cites `service.py:288-293` for the stream route; it is now `crates/service.py:454-459` (stale cite, fix in a code run). Our manifest has only an SVG icon, which iOS may ignore (*unverified*).
- **Questions for Michael (for 09):** should the web client get a manifest `share_target` and a service worker, so that sharing a Spotify link on Android goes straight to S3-01 (iOS still needs the Shortcut)? Default: yes, as a small S3 follow-up after B is answered; nothing is built now.
- **Proposed changes:** step 1 calls `webui/index.html` a one-file SPA. It is a Jinja template with three front-end layers (~90 vanilla scripts, a React 19 app owning 20 of 24 pages, and a `shell.js` IIFE), plus a real service worker. `templates/` is an Unraid container template, not Flask templates. Step 2's "api/music_requests.py or api/request.py" record: a member request is a `wishlist_tracks` row (`music_requests` only records outcomes), and `api/request.py` keeps its state in memory.

### 2026-10-22 12:20 · V2-06 · passes
- **New:** `docs/research/2026-10-22-soulsync/07-filing-library.md` (~435 lines, 265+ unique cites, 6 `*unverified*` + 5 `*absence inferred*` marks). It has an ASCII import flow, then the five questions as `###` headings (beets; tags by field and when; scans; playlist edits and guards; deletes/moves and reverse logs), ours (filer D18/D22/D29, placement/S2-06, scans, `playlist_edit`, D44, trash/MOVES.txt, the four invariants with code and tests), a 4-row invariant table, and worth taking. **Verdict: no.** Docs only; tests 1757 → 1757.
- **Findings:** **no beets at all.** SoulSync is its own mutagen tagger, and on import it **clears every tag** and rewrites them before the move (saving untagged when no metadata is found), with no tag undo. Scans are a debounced `startScan`, done only after ≥ 300 s with `scanning=false`; an unreachable Navidrome reads as "not scanning". Playlist sync defaults to **reconcile**, which removes tracks the user added and adopts any same-named playlist of the account. Its write guard reads before and set-compares after (no order, no compare-and-swap, never reads hidden rows). Deletes are mostly hard `os.remove` (import collisions, upgrades, redownload, reorganize, most repair fixes). Only duplicates and corrupt audio use a `.deleted` bin, whose manifest is written after the move and which Weekly Cleanup empties at keep_days 0. Invariant table: playlist-held **conflicts**, scan-between **not addressed**, recompute **partly**, logged reverse **conflicts**.
- **Verified:** the citation check prints no BAD line. Four Opus fact agents (3 on the clone, 1 on ours); I spot-checked 20 cites with `sed -n` (all held, including reconcile removing every copy of an unwanted id, `navidrome_client.py:1810-1814`). An Opus review opened ~55 cites and returned 9 findings plus 2 minor, all fixed and re-checked with `sed -n`: expired cleaner protects mirrors/signals, not Navidrome playlists; the 180 s scan wait applies only to writes adding ids, else refuse; overwrite cases; tag-encoding abort; 3 cite moves; ours `verify` state; 3 uncited claims; lossy-copy delete. Suite: `check.sh` green on the final tree, 1757 tests in 648 s (647 s on the pre-review tree).
- **For V2-08/V3:** `ours:docs/hard-won-facts.md:32` says beets.yaml has `import.write: yes`, but `ours:deploy/beets.yaml:24` is `write: no` (stale fact; fix in a code run). Our scan waits differ: fetch polls only `scanning` (1 s/120 s) and never checks that `lastScan` moved (`ours:sourcing/fetch.py:205-215`); the cleanup does (`ours:subsonic/client.py:252-267`). D22's `VERSION`/`TIT3` is read, never written. S2-06 is still unbuilt, and the S1 branch still does not exist (`git ls-remote`, 2026-10-22).
- **Questions for Michael:** none new. **Proposed changes:** step 2's order "pipeline → auto_import_worker → template → tags → scan" is not SoulSync's. Tags are written before the move, and `auto_import_worker` is a separate, off-by-default watcher that feeds the same pipeline. The file draws the real flow. Step 1's `core/playlists/` holds no Navidrome writes; they are in `navidrome_client.py` + `core/sync/playlist_edit.py`.

### 2026-10-22 11:40 · V2-05 · passes
- **New:** `docs/research/2026-10-22-soulsync/06-verification.md` (~490 lines, 258+ unique cites, 18 `*unverified*` marks). It has the post-transfer worker steps, a 13-row check-chain table in run order with defaults, fake/transcode detection, ReplayGain, pre-transfer candidate checks, atomic publish (manifest, recovery), album consistency, the same-release question, AcoustID placement, quality profiles, quarantine with its API, a 4-kind blocklist table, a summary table and `### Would ext-74 have been caught?`. Then ours (a 14-row verify table, `_acoustid_check`, D24/policy.toml, S1-02/S2-03/S2-04/S2-05), the difference judged on D24 and D26, and worth taking. **Verdict: adapt.** Docs only; tests 1757 → 1757.
- **Findings:** SoulSync has **no transcode detection after download**. Its quality gate reads the header and never rejects under the default profile (fallback on). The only spectral check is a weekly report-only repair job, off by default, with two likely bugs: it scans only the last file per directory, and `-v quiet` probably hides its `volumedetect` line. `flac -t`, the audio guard and AcoustID are all off by default. Atomic publish is opt-in and still publishes partial albums at batch end. Album consistency is a tag rewrite after publish (one pinned MB release), not a check. Quarantine gives a sidecar, a permanent `(peer, file)` block and ≤ 5 auto-retries, and is emptied by the 12 h Full Cleanup. ext-74: caught only by the opt-in title-based AcoustID FAIL (`audio_verification.py:829-831`); lengths agree (195.6 vs 195.7 s).
- **New on our side (read from code, not reproduced):** when the title slot differs, fetch calls the file "another version" and drops the expected length (`ours:sourcing/fetch.py:411-417`). So ext-74 got no length check at all, only the peer's-listing check. That should go to S1's review (S1-01 should keep real wrong songs off this path).
- **Verified:** the citation check prints no BAD line. Three Opus fact agents read the clone; I spot-checked 16 of their cites with `sed -n` (all held, including the repair job's indentation bug). An Opus review opened ~95 cites and returned 13 findings, all fixed: bitrate is checked after download under fallback-off profiles; the length check is −3/+15 s and skipped without an expected length; ours skips `flac -t` and AcoustID silently; the length-escape cite; "fifth of six" target; five triggers; ours misses 256–314 kbps re-encodes; ext-74 retry cites; integrity give-ups aren't blocklisted; MB ids also fill names; ≥ 4 hard deletes; 4 uncited claims; > 50 % silence. Suite: `check.sh` green on the final tree, 1757 tests in 647 s (648 s before the review fixes).
- **For V3/09:** ours does not fully hold D24's "a re-encoded fake is rejected" either: the transcode rule only fires for lossless or ≥ 315 kbps claims (`ours:sourcing/verify.py:435`). Worth-taking items: S1-02 plus SoulSync's length-contradiction escape; remember a failed-verify `(peer, file)` in the scorer; keep the expected length on the "version" path.
- **Questions for Michael (new, for 09):** album-level staging, i.e. hold an album's verified files in `.staging` until the album job ends, then file them together, so Navidrome never shows half an album. Default: no, file each row as it lands (today's behaviour).
- **Proposed changes:** step 1's `core/downloads/validation.py` is pre-download candidate filtering. The ordered file checks (extension/size, header, duration, `flac -t`) live in `core/imports/file_integrity.py` and `core/imports/pipeline.py:762-1702`. There is no post-download bitrate check under the default profile. `core/audio_length.py` is used only by audiobook code. The file says so.

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
