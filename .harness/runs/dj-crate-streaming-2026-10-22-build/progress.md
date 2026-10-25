# Progress log — run `dj-crate-streaming-2026-10-22-build` (branch `harness/dj-crate-streaming-2026-10-22-build`)

What this file is: the shared memory of the agent harness for this run. Each session appends one entry **at the top**
(newest first) when it finishes a feature: what it built, what it learned, what it asks. Nobody edits older entries.

How to read the run: `feature_list.json` in this directory is the build list, in priority and dependency order; a
session takes the first feature with `passes: false` whose `after` features pass, and may flip only its own `passes`.
Michael steers from `INBOX.md` on this branch (status line `run | pause | stop`; answers under `## Answers`); every
session reads it at startup. Policy: **build-only** (`.harness/config.sh`) and the brief in `brief.md`: nothing live,
no docker, no `/srv`, no network, no client UI, PRs only (open, never merge).

### 2026-10-23 verify S4

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| S4-01 | 1 | `pytest tests/test_downloads_checklist_doc.py`; read `test_sections_4_and_6_each_have_a_check_and_an_undo`, `test_every_live_run_command_is_a_python_module_and_every_write_holds_the_lock` | 9 tests in file pass; they assert sections 4/6/Captures, Check/Undo, `scripts/live-run.sh python3 -m` prefix, flock on writes; grep of the doc agrees | yes |
| S4-01 | 2 | Read checklist §4 (lines 103-222) | add/preview/approve with Check lines (9 rows, ≥8 of 9, no peer name, events plan/pick/filed/ok, ≤1 switch), path with year only if MB matched (D53), Undo `wanted reopen`, rollback `<the sha step 2 deployed>` | yes |
| S4-01 | 3 | Read checklist §6 | Spotify app, capture command, Check greps (secret via pipe, access_token, tok_ = 0), git add of the two fixtures, Undo with rotate, secret location left as a question | yes |
| S4-01 | 4 | Read `## Captures for the fixtures` | enqueue, transfer states, `?remove=true` captures, each with fixture file and reading test; peer-name scrub rule | yes |
| S4-01 | 5 | grep morning checklist, architecture, next-todos | morning line 103 `PR #16 must be on main first` once; link to checklist §4/§6 at line 302 (§9 starts 238); architecture §4(e) and next-todos State say not deployed, PRs open; items 11, 12 present | yes |
| S4-01 | 6 | `python3 -m sourcing.cli request --help`; `python3 -m scripts.capture_spotify --help` | both exit 0; checklist commands only `--help`-verified, no docker/live | yes |
| S4-01 | 7 | harness `check.sh` | "green (cached, 2369 tests)", up from 2361 | yes |
| S4-02 | 1 | Read progress entry S4-02 | review of `1eb4259..HEAD`: 0 Critical, 9 Important (8 fixed, A4 kept per spec), 23 Minor, each with what it became | yes |
| S4-02 | 2 | `git diff 1eb4259..HEAD` on trash/playlist_edit/placement; grep D-numbers; spec Built lines | no diff in those files; D48-D53 each present (origin/main tops at D47, no gap); Built lines at spec lines 62, 101, 196, 235; docs say not deployed; approve tests in `tests/test_approvals.py`, `test_album_job.py` | yes |
| S4-02 | 3 | `pytest tests/test_python310_syntax.py`; `grep -rn "/srv/" sourcing/album*.py sourcing/requests.py sourcing/catalog.py scripts/capture_spotify.py` | passes; grep printed nothing | yes |
| S4-02 | 4 | Read progress S4-02 entry | tests 2361 → 2369, run 1906 → 2369; PRs #27-29 open, draft PR command given; questions collected | yes |
| S4-02 | 5 | harness `check.sh` | green, 2369 tests | yes |

### 2026-10-23 09:34 · S4-02 · passes

- **Changed.** Whole-run Opus review of `git diff 1eb4259..HEAD` (`run.diff`, 11,315 lines, split in two for two reviewers), then an Opus review of the fixes. Results: **0 Critical, 9 Important (8 fixed), 23 Minor**. Fixes are in `crates/service.py`, `crates/store.py`, `sourcing/requests.py`, `sourcing/musicbrainz.py`, `sourcing/catalog.py`, `sourcing/fetch.py`, docs (`api.md`, `architecture.md` §4(e), `next-todos.md` State, downloads checklist §4, spec S4 `**Built**` line) and **D53 *default*** in the pivot spec. Tests 2361 → 2369; **the run: 1906 → 2369**.
- **Important, each fixed red → green:**
  - (B1) `POST /api/requests` / `request add` with a Spotify album link now runs `match_request_release`, outside the app lock and best effort: MusicBrainz down → ids null, one `release` event `#<id> musicbrainz not asked: …`, still 201. This closes S4-01's gap (1).
  - (B2) Release lookups ask `inc=recordings artist-credits release-groups`. Without `artist-credits`, a `mbReleaseId` pick made a request with `artist=""`.
  - (B3) A catalog query without " - " sends `release:(words) OR artist:(words)` (Lucene-escaped; uppercase AND/OR/NOT become words), not one title phrase that finds nothing. `api.md` documents `Artist - Title`.
  - (A1) A first match before any approval fills an unknown `requests.year` from the release group's `first-release-date`, so the folder is `… (1972)` (D53 *default*). This closes gap (2) and question (a).
  - (A2) In planned mode, one slskd transport error (unreachable or 5xx) is waited out with `retry_pause_s` on the same transfer, instead of distrusting a good folder.
  - (A3) `forget_new` cancels each record in its own `try`.
  - (R1, the fix review) The year is not filled after a row was approved, so one album never lands in two folders.
  - (R2, the fix review) The `rq` test fixture reached musicbrainz.org after B1; it now uses the offline stub.
- **Important, not fixed: (A4).** A verified file whose AcoustID recordings lack the release's exact `mb_recording_id` (a remaster's own recording) is a hard `recording` finding and distrusts the folder. Spec S2-03 and S2-05 prescribe exactly this ("the existing hard AcoustID check applies", a wrong recording distrusts the folder), so I kept it. Proposed: treat an id mismatch whose AcoustID title `can_be_song` as a warning. It is a question for Michael, below.
- **Minor fixed:** request ids longer than 18 digits → 404 (were OverflowError/ValueError); `_release` catches any error like `mark_in_library`; `api.md` approve says `approved` or `partly`; the example's year is noted.
- **Minor listed, each with its reason:**
  - (B4/A8) A track request's preview/approve searches the bare artist: it works, and it's slow. Next: a plain `download` approval for a track request.
  - (B6) An odd MusicBrainz search reply → 400, not 502. It is rare, and the message names the KeyError.
  - (B8, = S3's M7) Searches are cached for the process's life. It's Michael's question.
  - (B9) A request's approvals are not one transaction: the window is milliseconds and the worst case is two jobs.
  - (B10) The peer-name test checks paths only.
  - (A5) `listed_lengths` is never passed (same-release preference inert when the folders share no track): it needs a design for which lengths.
  - (A6) An ordinary finding in a trusted folder gets no per-track try: a plan choice (S2-05c).
  - (A7) Filing or import failures count toward a folder's 2.
  - (A9) A stalled peer's folders stay failed for the request.
  - (A10) An album job runs inline before play-now.
  - (A11) The restart test does not interrupt a running job.
  - (R) Repeat adds query MusicBrainz again; the planned timeout can double after a drop.
  - Each of these is a next-run item: none loses a file or downloads without an approval.
- **Cross-run checks:**
  - No new trash path and placement is unchanged, so the four CLAUDE.md safety invariants are untouched.
  - D7 holds: every enqueue comes from a claimed approval, `album` included, and preview only searches.
  - No peer name or `/srv` path appears in any payload, event or doc example (`store.public`, basenames).
  - D48–D53 follow `origin/main`'s D47 with no gap or clash (checked on every `origin/*` branch).
  - S2, S3 and S4 carry `**Built**` lines.
  - `tests/test_python310_syntax.py` is green.
  - `grep -rn "/srv/" sourcing/album*.py sourcing/requests.py sourcing/catalog.py scripts/capture_spotify.py` finds nothing.
- **Verified.** Each new test failed before its fix (red seen for B1, B2, B3, A1, A2, A3, R1 and the id). The touched files pass (190 + 98 + 225). Full suite: `check: green in 928 s, 2369 tests`.
- **PRs.** PRs are open, none merged: #27 (S1), #28 (S2), #29 (S3); the harness opens S4's from this branch (`gh pr create --base main --head harness/dj-crate-streaming-2026-10-22-build --draft` if it does not). PR #16 (draft) must reach `main` first (checklist step 1).
- **Questions for Michael (the whole run):**
  - (1) D51/D53: is it OK that a Spotify album takes MusicBrainz's first-release year, and that it clears the year when there is none?
  - (2) D52: should a second playlist URL with the same name join the first (now), or get a 409?
  - (3) A4: should a recording-id mismatch whose title fits become a warning?
  - (4) Should MusicBrainz searches skip the cache (B8)?
  - (5) Where does the Spotify secret live for good?
  - (6) Question B (the client UI) is still open.
  - (7) The defaults in the initializer entry: rows are filed as they land; the status words; one distrusting finding or 2 failures switch a folder.

### 2026-10-23 17:40 · S4-01 · passes

- **Changed.** `docs/plans/2026-10-22-downloads-checklist.md` gains **§4 Album request through the request API** (merge cases + rollback per case, snapshot before the deploy, `dj_album:1:` key check, `seed-spotify --musicbrainz` then `request add|preview`, one row first, then `request approve`, `request show`, a distinct-`album_id` check on a fresh snapshot, another album if Al Green has nothing left), **§6 Spotify developer app and the capture** (worktree from `origin/main` after the run's PR, the docstring command, secret checks without the secret on argv, commit + draft PR, rotate), and **Captures for the fixtures** (enqueue / transfer states / `?remove=true`, each with its fixture, its masking and `tests/test_fake_slskd.py` as its future reader). Morning checklist §9 links §4 and §6 (its PR #16 line kept, once). Architecture §4 (e) and next-todos State say **not deployed, PRs open**, items 11–12 added. New `tests/test_downloads_checklist_doc.py` (9 tests). Tests 2352 → 2361.
- **Verified.** Doc test red first (8/8), then green; 4 mutations (lock dropped, non-module live-run, drifted output, missing Undo) each turn it red. `python3 -m sourcing.cli request --help` and `python3 -m scripts.capture_spotify --help` exit 0. Nothing live: no docker, no `scripts/*.sh`, nothing under `/srv`. Opus review: 0 Critical, 2 Important (the album-tags plan's staged live steps were missing; the capture PR would have carried the whole unmerged run), 16 Minor; all fixed. Full suite green: 2361 tests, 926 s.
- **Next session (S4-02) must know.** Two code gaps the checklist works around: (1) `POST /api/requests` / `request add` with a Spotify album link never calls `match_request_release`, so its rows have no recording ids and verify skips the recording check (only `seed-spotify --musicbrainz` matches); (2) a release match stores no year, so a Spotify album request always files at `Artist/Album/` without ` (year)` (D51 clears it). Both are worth a test-first fix in S4-02; the checklist's `seed-spotify` step stays harmless after (1) is fixed.
- **Proposed change (S4-01 step 2).** It expected `Al Green/I'm Still in Love With You (1972)/`; the code files at `…/I'm Still in Love With You/` (the embed's `releaseDate` is null, gap 2 above). Written as the code does it. It also said `request add` alone; `seed-spotify --musicbrainz` comes first because of gap 1.
- **Questions for Michael.** (a) Should a matched MusicBrainz release's year become the request's year (folder `… (1972)`)? It also settles D51's question (clear an unknown year, or take one). (b) Where should the Spotify secret live for good (`/srv/docker/.env` plus compose, or elsewhere)? Only once the provider is built.

### 2026-10-23 15:30 · verify S3

All 8 features hold (50 step rows). Ran the 10 S3 test files (380 passed, 242 s); the full 2352-test suite is the harness's cached green run, not re-run here. No `passes` flags changed.

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| S3-01 | 1 | read `tests/test_requests_api.py::test_an_album_url_answers_201_with_the_request_and_its_nine_rows`; ran the file | asserts 201, request {kind album, artist, album, year, mbReleaseId, status open, id, createdAt}, 9 rows ext-1..9 ordered by trackNo, row-1 dict exact camelCase, one fetch; passes | yes |
| S3-01 | 2 | `test_a_track_link_is_a_track_request_with_one_row` (both forms), `test_a_playlist_url_is_the_merge_import_plus_a_playlist_request` | track → kind track, one row; playlist → merge import + playlist request, rows = wanted rows, calls == [PLAYLIST_URL] (one fetch); pass | yes |
| S3-01 | 3 | parametrized 400 test, 502 tests, `test_parse_link_*` | `url is required`, `unknown link kind: music.apple.com`, `…: artist`, HTTPError/URLError → 502 `cannot reach Spotify`; parse_link covers intl path/query/URI/refusals; pass | yes |
| S3-01 | 4 | `test_the_same_album_again_answers_200_with_the_existing_request_and_no_new_rows` | intl-de/?si and `spotify:album:` forms → 200 equal to first body, 1 request, 9 rows; pass | yes |
| S3-01 | 5 | `.harness/check.sh` on the 10 S3 test files (test_requests_api, test_service, test_import_playlist, test_musicbrainz_client, test_catalog, test_album_job, test_sourcing_cli, test_api_doc, test_capture_spotify, test_python310_syntax) | 380 passed in 242 s | yes |
| S3-01 | 6 | harness `check.sh` / `.harness/check.sh` full suite | green, 2352 tests (harness output, cached for this tree; S3-R1 commit says 2319 → 2352, count only grew); pass | yes |
| S3-01b | 1 | `test_an_mb_release_id_is_an_album_request_with_the_releases_tracks`, `test_an_mb_recording_id_is_a_track_request_with_one_row`, `test_an_id_musicbrainz_does_not_know_is_404` | 201 album, mbReleaseId, 9 rows w/ mbRecordingId/trackNo/durations, year 1993; recording → track, 1 row; unknown → 404 `MusicBrainz has no release/recording <id>`; pass | yes |
| S3-01b | 2 | `sourcing/requests.py` add_release/add_recording/mark_in_library use; `test_mark_in_library_links_only_open_rows`, `test_navidrome_unreachable_leaves_the_rows_open_with_one_event_on_the_request` | all adders end in mark_in_library; ok + library_song_id, one `matched` event; unreachable → rows needs_source, `library not asked: URLError` event, no exception; pass | yes |
| S3-01b | 3 | `test_an_album_row_the_library_has_answers_ok_with_its_library_song` | FakeSubsonic song for row 5 → row 5 ok with `ag5`, other 8 needs_source, one matched event; pass | yes |
| S3-01b | 4 | `test_two_keys_or_a_malformed_id_is_400_and_asks_nothing` | url+mbReleaseId → 400 `one of url, mbReleaseId, mbRecordingId`, nothing asked; pass | yes |
| S3-01b | 5 | `.harness/check.sh` on the 10 S3 test files (test_requests_api, test_service, test_import_playlist, test_musicbrainz_client, test_catalog, test_album_job, test_sourcing_cli, test_api_doc, test_capture_spotify, test_python310_syntax) | 380 passed | yes |
| S3-01b | 6 | harness `check.sh` / `.harness/check.sh` full suite | green, 2352 tests (harness output, cached for this tree; S3-R1 commit says 2319 → 2352, count only grew); pass | yes |
| S3-02 | 1 | `tests/test_catalog.py` album/track/dash-split/registry/stub-provider tests | Hit fields incl. provider, ids, in_library; 10 album hits, 3c9a52ee year 1993, 9 tracks, CD; track via recording parse; PROVIDERS == {musicbrainz}; stub provider hit with provider `stub`; pass | yes |
| S3-02 | 2 | `test_an_album_the_library_has_by_name_and_artist_is_in_library`, `test_a_track_is_in_library_when_import_playlist_would_match_it`, `test_navidrome_unreachable_leaves_in_library_unknown_for_every_hit`, `test_any_navidrome_failure_is_unknown` | track via match, album via search3 + loose equality; unreachable/odd errors → inLibrary None, 200; pass | yes |
| S3-02 | 3 | `test_an_album_search_answers_200_with_camel_case_hits`, kind/q 400 tests, `test_musicbrainz_busy_after_the_clients_retries_is_503` | 200 `{hits}` camelCase; 400 `kind must be album or track`, 400 `q is required`; 503 `MusicBrainz is busy, try again` after client's 4 attempts; pass | yes |
| S3-02 | 4 | read `sourcing/catalog.py` docstring; `test_the_registry_has_musicbrainz_only_and_spotify_is_named_as_not_yet` | docstring says Spotify deliberately not a provider and names `scripts/capture_spotify.py`; asserted; pass | yes |
| S3-02 | 5 | `.harness/check.sh` on the 10 S3 test files (test_requests_api, test_service, test_import_playlist, test_musicbrainz_client, test_catalog, test_album_job, test_sourcing_cli, test_api_doc, test_capture_spotify, test_python310_syntax) | 380 passed | yes |
| S3-02 | 6 | harness `check.sh` / `.harness/check.sh` full suite | green, 2352 tests (harness output, cached for this tree; S3-R1 commit says 2319 → 2352, count only grew); pass | yes |
| S3-03 | 1 | `test_get_requests_lists_them_newest_first_with_status_and_row_counts`, `test_get_one_request_is_the_post_shape_plus_preview_and_each_rows_approval`, `test_an_unknown_request_is_404_and_a_word_is_400` | list newest first with status + rowCounts {ok,needsSource,sourcing,verify,failed,review}; detail = rows + preview (None) + approval {id,purpose,ts,usedAt,result}; unknown id 404 `no request #99`; pass | yes |
| S3-03 | 2 | `test_preview_plans_the_album_caches_it_and_names_no_peer`, `test_preview_without_slskd_is_503` | plan {folders[label folder 1, coverage 8 of 9, rows{id,file}], perTrack, ts}; json has no PEER/username/DIR; cached as req-<id> with username server-side; 503 `slskd is not configured`; pass | yes |
| S3-03 | 3 | `test_approve_records_the_album_approvals_of_the_previewed_plan`, 409 tests, `test_the_worker_runs_the_album_from_the_approvals_post_approve_answered` (tests/test_album_job.py:1092) | approved [{wantedId, approvalId, candidate{basename}}], no peer; sourcing/verify → 409 `ext-3 is sourcing (in progress): the worker finishes it`; done → 409 `nothing to approve`; album_job test drives HTTP approve then a worker tick spends exactly those 9 approvals; pass | yes |
| S3-03 | 4 | read `crates/service.py` preview_request/approve_request and route wiring; test_service in the run | routes inside CrateApp/_api with the ApiError mapping; test_service green; pass | yes |
| S3-03 | 5 | `.harness/check.sh` on the 10 S3 test files (test_requests_api, test_service, test_import_playlist, test_musicbrainz_client, test_catalog, test_album_job, test_sourcing_cli, test_api_doc, test_capture_spotify, test_python310_syntax) | 380 passed | yes |
| S3-03 | 6 | harness `check.sh` / `.harness/check.sh` full suite | green, 2352 tests (harness output, cached for this tree; S3-R1 commit says 2319 → 2352, count only grew); pass | yes |
| S3-04 | 1 | `test_request_add_prints_the_request_and_its_rows_and_again_finds_it` | exit 0; line 1 `request 1: Al Green – I'm Still in Love With You (album, 9 rows, 0 in library)`, row line `  01 ext-1  I'm Still In Love With You  needs_source`; repeat prints `; already requested`; pass | yes |
| S3-04 | 2 | `test_request_list_and_show`, `test_request_add_json_is_the_apis_shape` | show has source, musicbrainz release, rows with status/reason (no /srv/music), plan line; list newest first; --json equals API shape via json.loads; pass | yes |
| S3-04 | 3 | `test_request_preview_without_slskd_exits_2`, `test_request_preview_prints_the_plan_without_peers_and_show_has_it` | exit 2 `preview needs --slskd or $SLSKD_URL`; plan printed with coverage, row → file, no PEER/DIR; fake slskd enqueued == []; pass | yes |
| S3-04 | 4 | `test_request_approve_records_approvals_and_downloads_nothing`, `test_request_approve_of_a_row_in_progress_prints_the_409_and_exits_1` | `approved 9 rows of request 1; the worker downloads them on its next tick`, exit 0; in-progress → 409 text on stderr, exit 1; enqueued == []; pass | yes |
| S3-04 | 5 | read `sourcing/cli.py` docstring lines 11-14, `docs/worker.md` lines 160-168 | docstring lists request add/list/show/preview/approve; worker.md Album jobs names the morning path; pass | yes |
| S3-04 | 6 | `.harness/check.sh` on the 10 S3 test files (test_requests_api, test_service, test_import_playlist, test_musicbrainz_client, test_catalog, test_album_job, test_sourcing_cli, test_api_doc, test_capture_spotify, test_python310_syntax) | 380 passed | yes |
| S3-04 | 7 | harness `check.sh` / `.harness/check.sh` full suite | green, 2352 tests (harness output, cached for this tree; S3-R1 commit says 2319 → 2352, count only grew); pass | yes |
| S3-05 | 1 | read `tests/test_api_doc.py`; ran it | asserts doc exists, six route strings in backticks, statuses 400/404/409/502/503 present and no other ApiError status raised in the handlers' source; pass | yes |
| S3-05 | 2 | read `docs/api.md` headings and statuses | Auth and exposure (tailnet), Statuses, six endpoint sections, examples from test assertions, approve = Michael's click, no peer/path; all five statuses found; pass | yes |
| S3-05 | 3 | `grep '^## ' docs/api.md`; test asserts | `## For a client` at line 156; `/api/events` asserted; pass | yes |
| S3-05 | 4 | `grep api.md docs/architecture.md docs/worker.md` | architecture line 73 and worker.md link api.md; pass | yes |
| S3-05 | 5 | `.harness/check.sh` test_api_doc + test_requests_api (inside the 380) | passed | yes |
| S3-05 | 6 | harness `check.sh` / `.harness/check.sh` full suite | green, 2352 tests (harness output, cached for this tree; S3-R1 commit says 2319 → 2352, count only grew); pass | yes |
| S3-06 | 1 | `test_captures_search_and_first_album` | token POST with grant_type + Basic base64, search URL prefix, album URL, Bearer on both, two pretty-printed files under out_dir; pass | yes |
| S3-06 | 2 | `FAILURES` parametrized (19 paths), `assert_no_secret`, `test_verbose_prints_urls_only` | token 401/bad JSON/search 500/album 404 etc. exit 1, no secret/token in stdout, stderr, files or exceptions; verbose prints URLs only; pass | yes |
| S3-06 | 3 | `test_refuses_without_both_variables`, `test_429_on_any_call_stops_without_retry` | exit 2 with `set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET (read -rs …)`, zero calls; 429 → exit 3 `rate limited; Retry-After: 17`, time.sleep patched to fail, one call; pass | yes |
| S3-06 | 4 | `test_docstring_has_the_morning_usage`; read module docstring; test_python310_syntax in the run | exact usage line, 'catalog data only', Michael commits; stdlib only; syntax test green; pass | yes |
| S3-06 | 5 | `git show --stat 46f8e26 | grep fixtures/spotify`; `ls fixtures | grep captured`; read `no_sockets` fixture | no captured fixtures committed or present; sockets blocked in tests; pass | yes |
| S3-06 | 6 | `.harness/check.sh` test_capture_spotify + test_python310_syntax (inside the 380) | passed | yes |
| S3-06 | 7 | harness `check.sh` / `.harness/check.sh` full suite | green, 2352 tests (harness output, cached for this tree; S3-R1 commit says 2319 → 2352, count only grew); pass | yes |
| S3-R1 | 1 | read the progress entry for S3-R1 and `s3.diff` in scratch | diff file exists (3499 lines); entry lists 0 Critical / 2 Important / 9 Minor with details; pass | yes |
| S3-R1 | 2 | `test_a_playlist_url_matches_its_tracks_without_holding_the_apps_lock`, `test_preview_plans_nothing_when_the_job_claimed_a_row_during_its_search`, `test_a_list_body_is_400`, `test_failures_exit_1_and_leak_nothing`; read preview_request/plan_request | RED→GREEN tests for I1/I2 exist; no username in payloads; POST creates no transfer (enqueued == []); malformed body 400 `body must be a JSON object`; capture leaks nothing. Preview takes `_lock` for every store read/write but, by design, not during the slskd search (asserted `held == [False]`), unlike `/api/wanted/<id>/preview`, which holds it throughout: meets the intent; flagged | yes |
| S3-R1 | 3 | read `sourcing/cli.py` request commands and `crates/service.py` | CLI builds `CrateApp` and calls the same add/preview/approve methods; one PROVIDERS dict, one class; pass | yes |
| S3-R1 | 4 | `git show --stat 76d4f05`; grep architecture, next-todos, spec; ran test_api_doc | api.md, architecture §4(e) entry points (line 284), next-todos S3 paragraph + Spotify provider line, spec `**Built 2026-10-23**` all present; pass | yes |
| S3-R1 | 5 | `git show --stat 76d4f05` | 15 files, all code/tests/docs/harness state; no stray files; pass | yes |
| S3-R1 | 6 | harness `check.sh` / `.harness/check.sh` full suite | green, 2352 tests (harness output, cached for this tree; S3-R1 commit says 2319 → 2352, count only grew); pass | yes |

### 2026-10-23 14:40 · S3-R1 · passes

- **Review:** an Opus review of `git diff a399566..HEAD -- crates sourcing scripts tests docs` (3499 lines, `$HARNESS_SCRATCH/s3.diff`) found 0 Critical, 2 Important and 9 Minor. A second Opus review of the fixes found 0 Critical, 0 Important and 6 Minor.
- **Fixed, each with a failing test first:**
  - **I1:** a playlist link's `POST /api/requests` searched Navidrome once per row while holding the app's `_lock`. Now `requests.add_link(lock=)` and `import_playlist(lock=)` take the lock only for crates.db and the playlist edit. The playlist is looked up again under the lock, so two imports of one name still make one playlist.
  - **I2:** a preview whose search ran while Michael approved and the worker claimed a row could replace the job's cache. Now `plan_request(idle=True)` re-checks after the search and answers 409 `album_job.InFlight`, caching nothing. The check is shared with `approve_request` as `_not_in_flight`.
  - **Minor:** every POST with a body that is not a JSON object (a list, string, number or `null`) now answers 400 `body must be a JSON object`. Before, the older routes dropped the connection.
  - **Minor:** `capture_spotify.write_both` no longer deletes an earlier capture when a later write fails.
  - **Minor:** a MusicBrainz reply of another shape is now 502, not 400.
  - **Minor:** the `_playlist_open` alias is removed.
  - **Minor:** `docs/api.md` is corrected: `usedAt` and `result` are set when the worker claims, a playlist's album groups get album approvals, there is no Spotify entry in the registry, and the relative paths that can appear in a `reason` are described.
- **Checked and holding:** every request and catalog body passes `store.public`. POST never reaches slskd; only approve records approvals. Preview searches outside the lock on purpose (S3-03), and its store reads and writes are under it. Every malformed body is 400. `capture_spotify` leaks nothing on any failure path. The CLI and HTTP call the same `CrateApp` methods. The catalog is one class plus the `PROVIDERS` dict.
- **Docs:** architecture §4 (e) lists the API and CLI entry points, next-todos State has the S3 paragraph and the "Spotify provider: after S3-06's capture" line, and the spec's S3 header has its **Built** line.
- **Tests:** 33 new, 2319 → 2352. Full `check.sh` green (2352 tests, 923 s). Each new test was confirmed to fail without its fix (mutants, and the second review).
- **Not fixed (Minor; for S4-02 if it wants them):**
  - The tier `at` is computed from the first playlist lookup.
  - Two identical playlist POSTs at once can both answer 201.
  - NameCollision now comes after lead-artist resolution, which only costs time.
  - An approval made but not yet claimed doesn't stop a preview from replacing the plan. This was already the case before S3-R1.
  - The MusicBrainz search cache is never refreshed in the crates process.
  - `approve_request` commits row by row.
  - The CLI doesn't map KeyError/ValueError.
  - Small duplicates: `_format`, `_credit` and `_year`.
  - CLI `list` re-reads the store; S3-04 kept that on purpose (M5).
- No question for Michael.

### 2026-10-23 12:50 · S3-06 · passes

- **What changed:** new `scripts/capture_spotify.py`, stdlib only, **never run in this run**. It makes 3 requests: a Client Credentials token, one `GET /v1/search?type=album,track&limit=10&q=…`, and one `GET /v1/albums/<first album id>`. It writes `fixtures/spotify_search.captured.json` and `fixtures/spotify_album.captured.json`, pretty-printed, both or neither (through `.tmp` + rename).
  - Exit codes: 2 when either env variable is unset (before any request), 3 on a 429 (prints `Retry-After`, no sleep, no retry), 1 on any other failure, with one line on stderr naming the call, the HTTP status and Spotify's short reason (e.g. `invalid_client`).
  - The secret, the Basic value and the token are never printed or written. A reply that repeats one of them is refused, and a redirect is an error, because urllib would carry `Authorization` to the new host. The docstring holds the checklist step 6 usage. `docs/api.md` points to the script.
  - Tests: 40 new in `tests/test_capture_spotify.py`, all on a stub opener; an autouse fixture fails the test if a socket connects. The suite went from 2279 to **2319**.
- **Verified:** `test_capture_spotify` + `test_python310_syntax`: 42 passed. Five hand mutants were each caught: printing the error body, printing the headers in `--verbose`, dropping the echo check, `and` instead of `or` in the env check, and echoing a non-numeric `Retry-After`. Full `check.sh` green, 2319 tests. No `fixtures/spotify_*.captured.json` exists or was committed.
- **Opus review (0 Critical, 1 Important, 10 Minor):** I1 and M2–M10 were fixed test-first.
  - I1: the secrecy check now also looks for the base64 Basic value, `Basic `, `Bearer ` and `Authorization`.
  - The other fixes: both-or-neither writes, the redirect refusal, Spotify's short error reason, a null first album skipped, the echo check on the exact written text, the untested exception types (ValueError, http.client, SSL, a read that fails), a missing or odd `Retry-After`, and the default out dir.
- **Proposed change (M11):** add `; unset SPOTIFY_CLIENT_SECRET` to the end of the morning usage, so the secret doesn't stay exported in Michael's shell. The spec's checklist step 6 and this feature's step 4 pin the exact string, so S4-01 can add it as a separate line in the checklist. No question for Michael.

### 2026-10-23 11:30 · S3-05 · passes

- **What changed:** new `docs/api.md`: auth/exposure, row and request statuses, one section per endpoint (`POST/GET /api/requests`, `GET /api/requests/<id>`, `preview`, `approve`, `GET /api/catalog/search`) with 2xx bodies taken from the tests' assertions and every error status with its reason text, plus `## For a client` (flow, and what is missing: UI, Spotify provider, DELETE/cancel). Linked from `docs/architecture.md` §2 and `docs/worker.md` `## Where things are`. 5 new tests in `tests/test_api_doc.py` (routes, statuses 400/404/409/502/503, no unlisted status raised in the handlers, flow section and links, peer/path/tailnet statement).
- **Verified:** `test_api_doc` + `test_requests_api`: 94 passed. Full `check.sh` green, 2279 tests (was 2274), 895 s.
- **Next session:** timestamps and some ids in the doc's examples are illustrative where the tests assert only their type. No question for Michael.

### 2026-10-23 10:45 · S3-04 · passes

- **What changed:** `python -m sourcing.cli request add <link> | list | show <id> | preview <id> | approve <id>`, each with `--json` (the API's JSON). The code is `request_cmd` in `sourcing/cli.py`, which calls the five `CrateApp` methods the HTTP routes use, so add, preview and approve have no second implementation.
  - `add` takes a Spotify link, and also a `musicbrainz.org/release|recording/<id>` link, the same as POSTing `mbReleaseId`/`mbRecordingId`.
  - The `CRATES_DB` guard is now `_crates_db`, shared with `fetch --approve`.
  - The module docstring lists the new commands. `docs/worker.md` `## Album jobs` gains "The morning path, without a client".
  - Tests: 19 new in `tests/test_sourcing_cli.py`. The suite went from 2255 to **2274**.
- **Verified:** `test_sourcing_cli` + `test_album_job`: 86 passed. Full `check.sh` green, 2274 tests in 906 s. In the tests, approve leaves the fake slskd's `enqueued` empty, and the preview output has no peer and no `@@` directory.
- **Opus review (0 Critical, 2 Important, 6 Minor):** these were fixed test-first.
  - I1: Navidrome down (a `URLError`), `CommentNotKept` or `sqlite3.Error` gave a traceback. Each now prints one line and exits 1, as the HTTP handler maps them.
  - I2: a playlist request's headline printed `None – <name>`.
  - M3: a playlist plan that went stale now says it is stale.
  - M4: the wording when nothing new is requested.
  - Added tests: slskd away, a missing API key, a stale plan, a playlist's per-track preview.
- **Not fixed (for S3-R1):**
  - M5: `list` builds its text from `requests.view` and not from `app.requests()`, because `listed` has no rows and a track request has no album to name it by.
  - M6: `add --json` cannot tell new from existing (the API's 201/200). Text mode says `; already requested`.
  - M8: `show` prints the plan text as cached, so rows that are done since then still appear in it, the same as the API's `folders`.
- **Next session:** S3-05's `docs/api.md` can point to the CLI as the shell equivalent. No question for Michael.

### 2026-10-23 09:20 · S3-03 · passes

- **What changed:** four new routes in `crates/service.py`, with the same handler and error mapping as the other routes.
  - `GET /api/requests` → `{requests: [...]}`, newest first. Each entry is view's request plus `rowCounts {ok, needsSource, sourcing, verify, failed, review}` (from `requests.listed`).
  - `GET /api/requests/<id>` → the S3-01 shape plus `preview` (the cached plan or null). Each row also gets `approval {id, purpose, ts, usedAt, result}`: its newest approval of any purpose, so a play-now shows too (from `requests.detail`).
  - `POST /api/requests/<id>/preview` → `{plan: {folders: [{label, coverage, rows: [{id, file}]}], perTrack, ts}}`. A playlist's plan is `{albums: [...+artist, album], perTrack}`; one with no album group answers `albums: []`, never null (from `album_job.shown`).
  - `POST /api/requests/<id>/approve` → `{approved: [{wantedId, approvalId, candidate: {basename}|null}]}`.
  - Errors: 503 when no slskd is configured; 502 `cannot reach slskd (…)`; 409 with `_not_in_progress`'s wording for a row that is sourcing, verify or claimed; 409 `nothing to approve|plan`; 404 `no request #N`; 400 for a non-digit id.
  - Tests: S3-03 section of `tests/test_requests_api.py`, plus 3 in `test_album_job.py` (one is the HTTP approve → worker tick) and 1 in `test_playlist_request.py`. The suite went from 2223 to **2255**, green in 886 s.
- **Opus review (0 Critical, 2 Important, 6 Minor):** these were fixed test-first.
  - I1: `plan_request(lock=)` searches outside the app lock.
  - I2: the failed folders are read again after the search, so a folder the job distrusted meanwhile stays out.
  - M3: `approve_request` takes no file from a plan marked stale (`at` 0).
  - M5: the GETs read under the lock.
  - M7: `open_rows` drops a `review` row that is waiting for a pick, for every kind and not only playlists.
  - M8: ASCII-digit ids.
- **Not fixed (for S3-R1):** M6. An approve commits row by row, and a crates.db `sqlite3.Error` answers "Navidrome's database can't be read". That mapping is the same on every existing route.
- **Verified:** the step-5 subset plus `test_playlist_request` and `test_fetch_filing`: 225 passed. Full `check.sh` green, 2255 tests.
- **Next session:** S3-04's CLI should call `CrateApp.preview_request` / `approve_request` / `request_detail` so the rules stay in one place. S3-05's `docs/api.md` should document the shapes above. No question for Michael.

### 2026-10-23 07:40 · S3-02 · passes

- **What changed:** `GET /api/catalog/search?q=&kind=album|track` answers 200 with `{hits: [...]}`. Each hit has `provider, kind, title, artist, year, trackCount, lengthS, format, ids, inLibrary`.
  - Code: new `sourcing/catalog.py` (`Hit`, `MusicBrainzCatalog`, `PROVIDERS`, `search`, `CatalogBusy`) and `CrateApp.catalog_search` in `crates/service.py`.
  - `MusicBrainz.phrase_query` leaves a blank field out of the query, so `release_search("", album)` is `release:"…"`.
  - `requests.match_request_release` no longer searches an album request that has no artist (it would match anyone's album of that name).
  - Tests: new `tests/test_catalog.py` (36), plus 1 in `test_musicbrainz_client.py` and 1 in `test_requests.py`. The suite went from 2185 to **2223**, green in 844 s.
- **Errors:** 400 `kind must be album or track`; 400 `q is required`; 503 `MusicBrainz is busy, try again` (after the client's 4 tries, or no network). Navidrome down or answering oddly gives 200 with `inLibrary: null` on every hit, asked only once.
- **inLibrary:**
  - Tracks use `fetch.library_match` (same recording or same version).
  - Albums use search3 *song* results with `identity.loose` equality on `album` and on the artist, `displayAlbumArtist` or `albumArtists[].name` (the captured 0.64 shape), retrying with the title's words alone. Album search3 results are not captured, so no `search_albums` was invented.
  - Each search page is asked once per call (`_Library` memoises `search_songs`). A hit with no artist, or a name that folds to nothing ("÷", "!!!"), is `null`, not `false`.
- **Verified:** step-5 subset plus neighbours (catalog, requests_api, musicbrainz_client, requests, service, musicbrainz, sourcing_cli, import_playlist, fetch): 279 passed. Full `check.sh` green, 2223 tests.
- **Opus review (0 Critical, 3 Important, 8 Minor):**
  - Fixed, test-first: I1 (album artist read from a key Navidrome never sends), I2 (18 Navidrome calls for 10 track hits, now 2), M1 to M5, and the en dash in M6.
- **Proposed changes / questions for Michael:**
  - (I3) Step 1 prescribes `release:"<q>"` for a query without " - ". On real MusicBrainz, "Al Green I'm Still in Love" as one title phrase finds nothing; only `Artist - Title` works. Should a plain query be sent as unfielded words? `docs/api.md` (S3-05) should state the " - " rule either way.
  - (M7) Every distinct search stays in the MusicBrainz client's cache: in memory until a restart, and in `MUSICBRAINZ_CACHE` forever if that is set. Should searches skip the cache (keeping the limiter and backoff)?
  - (Step 2) It says "search3 album results"; this uses search3's song results instead (reason above). Capturing a real `search3` with `albumCount>0` would allow a `search_albums`.
- **Next session:** S3-05's `docs/api.md` should document the hit shape and that a pick posts `ids` to `POST /api/requests`.

### 2026-10-23 06:10 · S3-01b · passes

- **What changed:** `POST /api/requests` also takes `{"mbReleaseId"}` (an album request: the release's tracks across all media, recording ids, lead credit, year from `date[:4]`, lengths; source `https://musicbrainz.org/release/<id>`) or `{"mbRecordingId"}` (a track request). Code: `sourcing/requests.py` (`add_release`, `add_recording`, `mark_in_library`, shared `_record`), `sourcing/fetch.py` (`in_library` split into `library_match` / `library_error` / `link_library_song`, behaviour unchanged), `crates/service.py` (`CrateApp(musicbrainz=…)`, built from `MUSICBRAINZ_CACHE` by default; `_add_pick`). Tests: 22 new in `tests/test_requests_api.py`. The suite went from 2163 to **2185**, green in 834 s.
- **Library marking:** every new album or track request (Spotify or MusicBrainz) has rows the library already has set to `ok`, with `librarySongId` and a `matched` event (S1-07's rules). If Navidrome is down or answers oddly, the rows stay `needs_source`, one event `#<id> library not asked: <type>` is logged, and the request is still 201. Playlists are not re-marked, because their import has just matched them.
- **Errors:** 404 `MusicBrainz has no release|recording <id>` and `… lists no tracks`; 400 `one of url, mbReleaseId, mbRecordingId` and `<key> is not a MusicBrainz id`; 502 `cannot reach MusicBrainz (…)`.
- **Verified:** step-5 subset 130 passed. Full `check.sh` green, 2185 tests.
- **Opus review (0 Critical, 3 Important, 7 Minor), fixed test-first:**
  - I1: Navidrome is now asked outside the app lock (`mark_in_library(lock=)`); a hit is linked under the lock only if its row is still open.
  - I2: any error during the library check is an event, never a 4xx/5xx or a dropped connection.
  - I3: a release with no tracks is a 404, not an empty request.
  - Added tests for the skips, a pick whose rows another request holds, a repeat recording pick, and a mid-way Navidrome failure.
- **Not done (Minor), for S3-R1:**
  - The service's in-memory MusicBrainz cache keeps 404s until a restart.
  - A repeated POST while Navidrome is down logs another event.
  - `seed-spotify` still marks nothing; fetch asks the library before it downloads anyway.
- **Next session:** S3-04's `request add` should call `add_link`, `add_release` / `add_recording` and then `mark_in_library`, as `CrateApp._marked` does. No question for Michael.

### 2026-10-23 05:10 · S3-01 · passes

- **What changed:** `POST /api/requests {"url"}`. Code in `sourcing/requests.py` (`parse_link`, `fetch_link`, `add_link`, `view`, `UnknownLink`, `SpotifyUnreachable`) and `crates/service.py` (`CrateApp(fetch_entity=…)`, `add_request`, the route). New `tests/test_requests_api.py` (39 tests). Suite went from 2124 to **2163** tests, green in 816 s.
- **Behaviour:**
  - An album or track answers 201 with `{request, rows}` in camelCase, through `public`.
  - The same link again (URL, `intl-xx/`, `?si=` or URI form) answers 200 with the same body, and Spotify is fetched once per call.
  - A playlist is imported with `merge=True` and then becomes add_playlist's request; the reply also has `playlist {id, name, matched, wanted, ambiguous}`. A playlist the library already has whole answers 200 with `request: null`.
  - Errors: 400 `url is required`, 400 `unknown link kind: <host|kind>`, 409 for another user's playlist of that name, 502 `cannot reach Spotify (…)` for a fetch error or an unreadable embed.
- **Verified:** step 5 subset (`test_requests_api`, `test_service`, `test_import_playlist`): 92 passed. Full `check.sh`: green, 2163 tests.
- **Opus review (0 Critical, 1 Important, 4 Minor), all done test-first:**
  - I1 (Important): an `IncompleteRead` or `TypeError` from the page left the client with no HTTP response. Fixed: any fetch failure is now a 502.
  - M2: an embed this code can't read used to answer 400; it is now 502 (`_readable`).
  - M3: an empty `url` now answers `url is required`.
  - M4: a playlist is known by its name. Recorded as **D52 *default*** in the pivot spec, with a test.
  - M5: added tests for the CommentNotKept path, the wrong-kind embed, and Navidrome being untouched on 409.
- **Next session (S3-01b):** `add_link` and `view` are what the CLI `request add` (S3-04) should call too. The fetch runs outside `_lock`; the import and add run inside it.
- **Question for Michael (D52):** should a second, different playlist URL whose playlist has the same name join the first one (the default now), or be refused with 409?
- **Proposed change:** step 1 says the payload is "camelCase as `/api/wanted` does", but `/api/wanted` is snake_case (`song_id`, `library_song_id`). I followed the camelCase shape the step lists; `docs/api.md` (S3-05) should say the two differ.

### 2026-10-23 verify S2

All 11 S2 features hold; none set to false. Init check green (2124 tests). I also ran the union of S2 test files (605 passed) and re-ran the S2-06a beets measurement in scratch.

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| S2-01 | 1 | read `tests/test_s2_plan_doc.py`; grep `^## ` of the plan | test asserts the 4 headings (+ status words equal `REQUEST_STATUSES`); plan has Schema, Request status, Album job, Live steps (+ Closing review) | yes |
| S2-01 | 2 | read `test_store_migrates_old_db_to_requests`, ran the file | old db gains `requests` and `request_id INTEGER`,`track_no INTEGER`,`mb_recording_id TEXT`; requests columns asserted; second open is a no-op | yes |
| S2-01 | 3 | ran a script on in-memory `CrateStore()`: add_request, add_external_wanted(request_id,track_no), set_recording_id, set_release_id, request(), requests() | ids/track_no visible in find_wanted; rows ordered by track_no; status 'open'; `test_request_status_is_not_stored` asserts no status column; parametrized `request_status` test covers each outcome | yes |
| S2-01 | 4 | ran `store.public(request)`; read `test_public_request_names_no_peer_and_no_absolute_path` | no peer/absolute path asserted; 13 new tests in test_crates.py (>=6) | yes |
| S2-01 | 5 | `.harness/check.sh` on the union of every S2 test file (19 files) | 605 passed, 0 failed (4m54s) | yes |
| S2-01 | 6 | `/home/mh550/projects/agent-harness/lib/check.sh` | green, 2124 tests (cached for this tree); per-feature counts not re-derivable, the S2 diff only adds tests | yes |
| S2-02 | 1 | ran `rows_from_spotify` on the album fixture | 9 rows, album set, track_no 1..9, row 6 `Oh ,Pretty Woman`, year None for all | yes |
| S2-02 | 2 | copy with releaseDate 1972-10-23; playlist fixture tea-tent-1 | year 1972 on all rows; 99 playlist rows have album/track_no/year None; tests `test_spotify_album_rows_carry_...`, `..._playlist_rows_have_no_...` | yes |
| S2-02 | 3 | read `add_spotify` in sourcing/requests.py | album/track become requests, artist from subtitle, rows carry request_id/track_no/source; playlist -> None unless imported (S2-07 extends) | yes |
| S2-02 | 4 | read `test_seed_spotify_album_records_one_request` | prints `request <id>: Al Green – I'm Still in Love With You (9 rows)`; 9 rows with request_id, track_no 1..9; `test_seed_spotify_adds_external_rows` unchanged and green | yes |
| S2-02 | 5 | same test, URL run twice | still 1 request, 9 rows; find_request(source) first | yes |
| S2-02 | 6 | `.harness/check.sh` on the union of every S2 test file (19 files) | 605 passed, 0 failed (4m54s) | yes |
| S2-03 | 1 | read `test_release_search_*`, `test_release_*` in test_musicbrainz_client.py | query artist/release phrase, one request, 10 releases; `release/<id>?inc=recordings`, 9 tracks, rec ids; 404 None; 503 backoff; cached | yes |
| S2-03 | 2 | read tests in test_musicbrainz.py (match_release) | (a) 3c9a52ee matched with rec ids and positions == track_no; (b) digital wins; (c) 8 rows None; (d) `Love and Hate` None; tie order asserted | yes |
| S2-03 | 3 | read `match_request_release` + test_requests.py / test_sourcing_cli.py musicbrainz tests | stores mb_release_id and recording ids, one `release` event (id, format, date; no peer); no match -> False, nothing stored; CLI uses MUSICBRAINZ_CACHE/--musicbrainz else skips | yes |
| S2-03 | 4 | read `test_a_request_rows_musicbrainz_recording_reaches_verify` and neighbours | row id passed as recording_id; copy upgrade keeps old copy's id; row without id passes None + asked_title | yes |
| S2-03 | 5 | `.harness/check.sh` on the union of every S2 test file (19 files) | 605 passed, 0 failed (4m54s) | yes |
| S2-03 | 6 | `/home/mh550/projects/agent-harness/lib/check.sh` | green, 2124 tests (cached for this tree); per-feature counts not re-derivable, the S2 diff only adds tests | yes |
| S2-04 | 1 | read helper `folder()` in tests/test_album_plan.py | built from a search_responses.sample.json copy, ext-74 filename shape, no new keys | yes |
| S2-04 | 2 | read `plan_album`/`FolderPick`/`AlbumPlan` in sourcing/album.py | signature, primary/secondary/per_track/alternates, assignments(), FolderPick fields as specified | yes |
| S2-04 | 3 | read the five case tests (one folder; 7+2; two peers 1000 vs 900; parametrized shared-track/listed-lengths; nine peers) | all assert the stated primary/secondary/alternates/per_track | yes |
| S2-04 | 4 | read `test_describe_names_folders_by_number_never_by_peer` | folder 1/2/3, `7 of 10`, basenames, peer names absent unless peers=True | yes |
| S2-04 | 5 | `.harness/check.sh` on the union of every S2 test file (19 files) | 605 passed, 0 failed (4m54s) | yes |
| S2-04 | 6 | `/home/mh550/projects/agent-harness/lib/check.sh` | green, 2124 tests (cached for this tree); per-feature counts not re-derivable, the S2 diff only adds tests | yes |
| S2-05a | 1 | read tests/test_album_job.py helpers (world, header_only, album_folder, FakeSlskdServer) | 9-file folder, FLAC bodies, request from add_spotify, not_in_library | yes |
| S2-05a | 2 | read `test_plan_request_*`, `test_approve_request_*` | one search, cached `req-<id>` plan, public shape; approvals purpose `album`; ValueError while sourcing/verify; `album` in APPROVAL_PURPOSES (store.py:146) | yes |
| S2-05a | 3 | read `test_worker_runs_the_whole_album_from_one_enqueue`, `test_a_stale_plan_is_made_again...`, `test_a_row_already_in_the_library_is_linked...` | one POST (PEER,9); stale plan replanned; library hit -> ok, `ok: in library (s7)`, matched event; ALBUM_PLAN_MAX_AGE_S (album_job.py:62, CLI env) | yes |
| S2-05a | 4 | read `test_planned_fetch_polls_the_jobs_transfer_without_searching_or_enqueueing` | no search/enqueue in planned mode; fetch/worker tests green in the subset | yes |
| S2-05a | 5 | happy-path test + `test_after_a_restart_the_request_reads_its_rows` | 9 rows ok, request done, one `plan` event `folder 1: 9 of 9`, no peer in events; restart: rows failed `interrupted: worker restarted`, request open/failed/partly as rows change | yes |
| S2-05a | 6 | `.harness/check.sh` on the union of every S2 test file (19 files) | 605 passed, 0 failed (4m54s) | yes |
| S2-05a | 7 | `/home/mh550/projects/agent-harness/lib/check.sh` | green, 2124 tests (cached for this tree); per-feature counts not re-derivable, the S2 diff only adds tests | yes |
| S2-05b | 1 | read tests: ordinary finding, transcode switch, never-starts (0.2 s), transfer error | (1) no switch, no DELETE of others (2) 8 rows -> B, remove=true, switch event as spec (3) start timeout (4) Completed, Errored switches rest | yes |
| S2-05b | 2 | read DISTRUST (album_job.py:64), run() trigger code, `test_two_failures_in_one_folder_switch_it` | triggers: again, timeout, DISTRUST kinds, 2 failures; remove=true; excluded folder never re-planned | yes |
| S2-05b | 3 | transcode test asserts | first row keeps status ok and library_song_id al01 after the switch | yes |
| S2-05b | 4 | `no_peer_anywhere` in the switch tests | events/results/reasons free of both peer names; switch text uses folder labels and basenames | yes |
| S2-05b | 5 | `.harness/check.sh` on the union of every S2 test file (19 files) | 605 passed, 0 failed (4m54s) | yes |
| S2-05b | 6 | `/home/mh550/projects/agent-harness/lib/check.sh` | green, 2124 tests (cached for this tree); per-feature counts not re-derivable, the S2 diff only adds tests | yes |
| S2-05c | 1 | read `test_a_row_no_folder_covers_goes_per_track_from_the_start`, `test_a_row_gets_its_folder_one_switch_and_one_per_track_fetch` | (1) 8 from folder + 9th per-track fetch (prefer None), plan event `8 of 9; 1 row per track`, pick event (2) failed with the 3-attempt reason exactly as spec; posts only (A,9),(B,1) | yes |
| S2-05c | 2 | same tests + `test_fetch_exclude_drops_those_peers...` | fetch(exclude={peers}) applied after rank and in the retry; reason format asserted as string | yes |
| S2-05c | 3 | `test_rows_moved_with_their_folder_name_its_cause`, attempt tests | all failed -> request failed; some ok + failed -> partly | yes |
| S2-05c | 4 | grep docs/worker.md | `## Album jobs` (plan/switch/matched events, triggers, caps, D7) and `## Approvals` mentions `album` | yes |
| S2-05c | 5 | `.harness/check.sh` on the union of every S2 test file (19 files) | 605 passed, 0 failed (4m54s) | yes |
| S2-05c | 6 | `/home/mh550/projects/agent-harness/lib/check.sh` | green, 2124 tests (cached for this tree); per-feature counts not re-derivable, the S2 diff only adds tests | yes |
| S2-06a | 1 | read tests/test_album_tags_plan_doc.py; grep plan headings | 6 headings present; Writer names write_minimal, When names .staging | yes |
| S2-06a | 2 | read plan Fields/Writer/When/Reverse | fields incl. comp=False, write_minimal only, staging only, one `tagged` event with old values, reverse via write_minimal, plain rows keep fill_missing_tags, SoulSync delta under ## Out | yes |
| S2-06a | 3 | re-ran the measurement myself in scratch (BEETSDIR, scratch yaml with deploy/beets.yaml import block, make_flac+write_minimal, `beet import -q -s -m -W --set dj_album=1`) | rc 0; `Al Green/Alb (1972)/01 - One.flac`; `beet ls -f '$path $dj_album' dj_album:1` lists it with 1; plain file went to `X/Singles/`; matches the plan's result | yes |
| S2-06a | 4 | grep pivot spec D50/D51 | D50 present, not marked *default* (Michael's answer + measurement); D51 *default* separate | yes |
| S2-06a | 5 | read `## Review` | Opus review recorded: 1 Critical, 4 Important, 8 Minor, all addressed in plan text; no code besides the measurement | yes |
| S2-06a | 6 | `.harness/check.sh` on the union of every S2 test file (19 files) | 605 passed, 0 failed (4m54s) | yes |
| S2-06a | 7 | `/home/mh550/projects/agent-harness/lib/check.sh` | green, 2124 tests (cached for this tree); per-feature counts not re-derivable, the S2 diff only adds tests | yes |
| S2-06b | 1 | read test_filer.py album tests (428-683) | write_minimal fields read back, `--set dj_album=1` in argv via fake_beet, old values returned; no album= -> no write, no --set | yes |
| S2-06b | 2 | read test_fetch_filing.py album tests (519-640) | identity built from the request (album kind only), `tagged` event with old values committed before beets, playlist request row gets no album tags, plain row unchanged | yes |
| S2-06b | 3 | read deploy/beets.yaml paths + order test test_filer.py:678 | dj_album:1 before singleton, exact form; measured key takes so no Singles fallback | yes |
| S2-06b | 4 | grep docs/worker.md ## Filing | album path and `tagged` reverse described | yes |
| S2-06b | 5 | `.harness/check.sh` on the union of every S2 test file (19 files) | 605 passed, 0 failed (4m54s) | yes |
| S2-06b | 6 | `/home/mh550/projects/agent-harness/lib/check.sh` | green, 2124 tests (cached for this tree); per-feature counts not re-derivable, the S2 diff only adds tests | yes |
| S2-07 | 1 | read `test_a_spotify_playlist_import_records_one_playlist_request_over_its_wanted_rows` | playlist request, 6 rows with request_id, playlist_id, track_no None, 4 rows with the album | yes |
| S2-07 | 2 | read `test_approve_request_groups_three_or_more_rows_of_one_album`, `test_two_rows_..._per_track` | album approvals for 3+ rows, download for the rest; search `Al Green <album>` | yes |
| S2-07 | 3 | read `test_a_mixed_playlist_runs_as_one_album_job_and_two_singles` | posts (PEER,4),(SINGLES,1)x2; 6 ok, request done; playlist songs == ids in position; test_placement green | yes |
| S2-07 | 4 | read `test_cli_import_playlist_request_...` and `..._without_request_records_none` | prints `request <id>: Tea tent (6 open rows; approve with sourcing.cli request approve <id>)`; without flag nothing; import tests green | yes |
| S2-07 | 5 | `.harness/check.sh` on the union of every S2 test file (19 files) | 605 passed, 0 failed (4m54s) | yes |
| S2-07 | 6 | `/home/mh550/projects/agent-harness/lib/check.sh` | green, 2124 tests (cached for this tree); per-feature counts not re-derivable, the S2 diff only adds tests | yes |
| S2-R1 | 1 | progress.md S2-R1 entry + plan `## Closing review` | Opus review recorded: 0 Critical, 2 Important, 10 Minor; plan lists fixes and not-done reasons | yes |
| S2-R1 | 2 | read 'S2-R1 review fixes' tests in test_album_job.py; grep fail_enqueue | Important fixes have tests; fail_enqueue test; remove=true on every switch asserted; no peer/path (no_peer_anywhere, public test); D7 checked in plan | yes |
| S2-R1 | 3 | read `test_album_module_is_pure`; fetch.py shared helpers | fresh-interpreter import check (no slskd_client/crates.store/sqlite3...); FetchResult.outcome, error_outcome, search, forget_* shared | yes |
| S2-R1 | 4 | grep architecture.md, hard-won-facts, next-todos, spec | architecture §2/§3/§4(e); hard-won releaseDate null + multi-file enqueue; next-todos S2 paragraph; spec `**Built 2026-10-23**` | yes |
| S2-R1 | 5 | `git show --stat a399566` (feature commit; HEAD is harness bookkeeping) | only crates/store.py, sourcing, docs, tests, harness run files; no scratch file | yes |
| S2-R1 | 6 | `/home/mh550/projects/agent-harness/lib/check.sh` | green, 2124 tests (cached for this tree); per-feature counts not re-derivable, the S2 diff only adds tests | yes |

### 2026-10-23 03:59 · S2-R1 · passes

- **Changed.** Opus review of `git diff 1eb4259..HEAD` (`$HARNESS_SCRATCH/s2.diff`, 5817 lines) against both S2 plans:
  **0 Critical, 2 Important, 10 Minor.** Fixed test-first in `sourcing/album_job.py`/`fetch.py`: **I1** a row whose
  planned file its own tier rejects (the plan uses the first row's tier) stopped at `needs_source` on every approval →
  now per track; **I2** a run's failed folders were forgotten and the cache reused, so approving again re-downloaded a
  distrusted folder → the cache keeps `failed` and goes stale (`at` 0), plans and per-track fetches exclude them.
  Minor fixed: planned timeout switches (`again`), an escaping error forgets every record sent, a playlist group plans
  only approvable rows, `CrateStore.wanted` skips `req-*` plans. Not done (reasons in the S2 plan's "Closing review"):
  5xx POST refusal stays `error:` (plan's choice), `forget_new` best effort, never-indexed row counts as going (S2-01
  test), CLI hint names S3-04's `request approve`, two `tagged` shapes (S2-06b), restart gap (known).
- **Simplified.** `fetch.py` now owns `FetchResult.outcome`, `error_outcome`, `search`, `forget_finished`, `forget_new`,
  `to_download`, `new_file`; album_job and worker use them (album_job −40 lines of copies). `album.py` purity test
  (fails with an slskd import). Docs: architecture §2/§3/§4 (e), hard-won-facts (embed `releaseDate` null; multi-file
  enqueue shape not captured), next-todos State S2, spec S2 `**Built 2026-10-23**`, worker.md Album jobs, S2 plan.
- **Verified.** 5 new tests red first (one, #6, passed at first and was rewritten to raise after the POST); the
  old `test_a_planned_file_the_policy_now_rejects_is_not_enqueued` now asserts the per-track fetch. Checklist held:
  no peer/absolute path in events, plan text or payloads; no enqueue without `album`/`download` approval (D7);
  every switch forgets with remove=true; `fail_enqueue` cannot loop. Subset 249 passed; full suite green, 2118 → 2124
  tests, 796 s.
- **Next session must know.** A request's cache `req-<id>` now has `failed` ([peer, dir] pairs, server side only);
  failed folders stay excluded for that request for good (a new request starts clean).
- **Question for Michael.** Still D51. None new.

### 2026-10-23 07:20 · S2-07 · passes

- **Changed.** `sourcing/requests.py` `add_playlist` (+ `add_spotify(…, playlist_id=)`): the import's last
  `import_order` wanted rows become one `playlist` request, found again by the playlist's name (`album` column);
  re-import rows join, dropped rows leave unless going; no empty request. `crates/store.py`: `attach_request`,
  `detach_request`, `find_playlist_request`, `takeable` (a playlist holds rows loosely: an album/track request
  asked later takes rows with nothing going, so the album files as one). `sourcing/album_job.py`: `groups` (3+
  open rows, `identity.loose` artist+album), `per_track`, `approvable`; `run` → one `_run` per group (cache
  `req-<id>:<group_key>`, events `#<id> <artist> — <album>: …`), `_plain` for a row that lost its album; ambiguous
  `review` rows neither grouped nor approved. CLI `import-playlist --request`. Docs: worker.md, S2 plan. Tests 2093 → 2118.
- **Verified.** New `tests/test_playlist_request.py` red first. The mixed-playlist test: posts `(soulfolder, 4)` +
  2× `(singlespeer, 1)`, 6 rows `ok`, request `done`, and Placement puts the playlist in Spotify order. 12
  mutations, each turns a test red (one survivor led to the two-album test). Opus review: 5 Important + 6 Minor;
  fixed test-first: #2 rows held from a later album, #3 dropped rows, #4 file path as key, #6–#11. Subset (step 5
  + worker/crates/fetch) 369 passed; full suite green, 2118 tests, 786 s.
- **Next session must know.** `request approve <id>` named in the CLI line is S3-04's to build. A Spotify playlist
  URL's embed has no album, so its rows all go per track; album groups need an Exportify CSV / SpotiFLAC report.
  `tests/test_fetch_filing.py` helper reads a playlist's cache by group key now.
- **Proposed change (S3-01/S3-04).** Look each playlist track's album up (track embed or MusicBrainz) so a pasted
  playlist URL forms album jobs. `plan_request` still passes no `listed_lengths` for album requests with a release
  (S2-07 step 2 implied it did).
- **Question for Michael.** Still D51 (from S2-06a). None new.

### 2026-10-23 05:10 · S2-06b · passes

- **Changed.** `sourcing/filer.py`: `AlbumIdentity`, `album_changes` (only differing fields; unknown year clears
  year/month/day, D51; no release clears `mb_albumid`/`mb_albumartistid`; `comp` only when true; a stray album-artist
  key or ID3 alias counts), `BeetsFiler.file(…, album=, on_tagged=)` records first, then `write_minimal`, then
  `beet import … --set dj_album=1`; `album=` without `on_tagged` is refused. `sourcing/fetch.py`: `album_identity`
  (kind `album` only) and a committed `tagged {json}` event. `deploy/beets.yaml`: `dj_album:1:` before `singleton:`.
  `scripts/tag_cleanup.restore_fields` (the reverse). New `requests.tracktotal` (migrated, set by `add_spotify`).
  `docs/worker.md` Filing, plan as-built. `fake_beet(fail_import=)`. Tests 2064 → 2093.
- **Verified.** Tests red first. Real beet 1.6.0 (offline, tmp library): album rows land at `Al Green/I'm Still in Love
  With You (1972)/01 - …` and `…/I'm Still in Love With You/09 - …`, plain row in `Singles`, `dj_album=1` in
  `item_attributes`. FLAC plus mp3/m4a/ogg (ffmpeg) tag tests; kill test: event committed when beets starts and
  survives a rollback. 10 mutations, each turns a test red. Opus review: 1 Important (tracktotal fell when the last
  track belonged to another request → `requests.tracktotal`) + 4 Minor (2 fixed test-first, 2 in the plan's "Not
  restored"). Subset 163 passed; full suite green, 2093 tests, 766 s.
- **Next session must know.** The filed file's record is the row's last `tagged` event starting with `{` before
  `filed`. Old requests have `tracktotal` NULL (falls back to the highest row track number).
- **Proposed change (S2-06b step 2).** It said "the request's row count" for tracktotal; built as the plan says
  (highest listed track number), since a count can fall below a track number.
- **Question for Michael.** Still D51 (from S2-06a): clear an unknown year, or take the first filed file's year?

### 2026-10-23 03:40 · S2-06a · passes

- **Changed.** New `docs/plans/2026-10-22-S2-album-tags.md` (Fields, Writer, When, Reverse, beets measurement, Out,
  Live steps, Review) and `tests/test_album_tags_plan_doc.py` (3 tests); pivot spec gains **D50** (the album path,
  your answer, not default) and **D51 *default*** (an album request without a year clears year/month/day on its
  files so they share one folder). No code. Tests 2061 → 2064.
- **Verified.** Doc test red first. Measured in scratch (no /srv; MusicBrainz pointed at a closed local port, so
  offline) on /usr/bin/beet 1.6.0: `import -q -s -m -W --set dj_album=1` with `dj_album:1:` before `singleton:` files
  at `Al Green/I'm Still in Love With You (1972)/01 - …`; `beet ls dj_album:1` lists exactly the flagged files; the
  import leaves them byte-identical; a plain import still goes to `Singles`. Also measured: the reverse (delattr,
  `modify -W -M … dj_album!`, `move -p` → Singles). Opus review: 1 Critical (event not committed before the write), 4
  Important, 8 Minor, all fixed in the plan text (`## Review`). Subset (plan doc + tag_cleanup) 26 passed; full suite
  green, 2064 tests, 761 s.
- **Next session (S2-06b) must know.** Follow the plan's `## Writer` order: compute old → log **and commit** the
  `tagged` event → `write_minimal` → `beet import --set dj_album=1`. The reverse needs a new
  `scripts.tag_cleanup.restore_fields` (one save, year before month/day, `null` → delattr).
- **Proposed changes (S2-06b steps).** `tracktotal` = highest `track_no` of all the request's rows, not the row count;
  a missing `mb_release_id` also clears `mb_albumid` and `mb_albumartistid`; `restore_fields` is the reverse, not
  `write_minimal(path, old)` (that leaves `ALBUM=`, `TRACKNUMBER=0`); m4a/ogg tag tests.
- **Question for Michael.** D51: OK to clear an unknown year (one folder), or should the first filed file's year
  become the request's year?

### 2026-10-23 02:45 · S2-05c · passes

- **Changed.** `sourcing/fetch.py`: `exclude=<usernames>` drops those peers' candidates right after `rank` (S1-06's
  retry too); "no acceptable candidate from another peer" when it removed one; pick event `per track: <basename>`.
  `sourcing/album_job.py`: attempts per row in order (own failure `folder 1: transcode (<basename>)` / `folder 2:
  <fetch reason>`, or the folder's cause when moved along); per-track fetches pass every failed folder's peer as
  `exclude`; a row with attempts that files nothing fails with `<attempts>; per track: <why>`, outcome `failed: …`.
  `docs/worker.md` `## Album jobs` + `album` purpose under Approvals; plan as-built. Tests 2049 → 2061.
- **Verified.** New tests red first (pick, then reason); 6 mutations (no exclude filter, no pick, no moved-along
  attempt, no rewrite, job passes no exclude, rejected switched row not per track) each turn 1–4 red; one survivor
  showed `| stalled` redundant (removed). Opus review: 2 important (a per-track fetch raising before fetch's `try`
  kept a stale reason; a row held in its switched folder lost its first attempt) + 3 minor, all fixed test-first.
  Full suite green, 2061, 753 s.
- **Next session must know.** A row failing an ordinary check in its switched folder ends there (no per-track fetch),
  both folders in its reason. Still open from S2-05b: a `_forget` that fails (slskd away) is not retried.
- **Questions for Michael.** None. Proposed changes: none.

### 2026-10-23 01:15 · S2-05b · passes

- **Changed.** `sourcing/album_job.py` `run` switches folders: triggers `FetchResult.again` (fetch no longer retries
  in planned mode), `start_timeout_s` (`ALBUM_START_TIMEOUT_S`=600; worker `album_start_timeout_s`, CLI env), a
  `DISTRUST` kind, or 2 failed rows per folder; the folder's unfiled records forgotten (remove=true), moved rows
  re-planned over the cached first search (`responses` now in the `req-<id>` cache, server side) + one fresh search
  with `plan_album(exclude=, like=, min_rows=1)`; one `switch` event per failed folder. `Verdict.kinds` →
  `FetchResult.kinds`; `album.folder_of`; fake slskd `stalled_peers`, `deleted`. Tests 2032 → 2049.
- **Verified.** New tests red first; 8 mutations (no distrust, failures 99, no start check, no forget, no exclude,
  held not moved, no planned `again`, no kinds) each turn 1–5 red. Opus review: 3 important fixed test-first (switch
  ignored same release → `like`; one row could never switch → `min_rows=1`, weak "never the failed folder" test
  rewritten; a refused fresh search aborted every row → falls back to the cached responses), 1 minor fixed (a held
  row now moves on a stall too). Full suite green, 2049, 759 s.
- **Next session (S2-05c) must know.** A row switches once; then (or with no folder found) it goes per track as an
  ordinary fetch with `prefer=None` and **no exclude yet**, so it may pick the distrusted peer again: 05c adds
  `exclude` and the attempt list in the reason (today the reason is the last attempt's). Known gap: a `_forget` that
  fails (slskd away) is not retried. The switch event is `#<id> folder 1 distrusted: transcode (<basename>); 8 rows →
  folder 2` (with `#<id>`, as `plan` has).
- **Proposed changes.** S2-05b step 1 case 2 says "A's first file" and "8 rows": the failed row switches too (the spec
  and S2-05c's cap test need that), so with the first file it is 9 rows; the test puts the transcode on A's second
  file (track 1 filed, untouched: 8 rows), which also gives step 3 a filed row to check. Questions: none.

### 2026-10-23 01:20 · S2-05a · passes

- **Changed.** New `sourcing/album_job.py`: `plan_request` (one `"<artist> <album>"` search, plan cached as preview
  `req-<id>` with `at` + `assign`, returns a `public` view, one `plan` event `#<id> folder 1: 9 of 9`),
  `approve_request` (one `album` approval per open row, planned file or None; ValueError while a row is
  sourcing/verify or an approval is `started`), `run` (claim, `fetch.in_library` per row, re-plan past
  `ALBUM_PLAN_MAX_AGE_S`=3600 (CLI env), one enqueue per peer, each row `fetch(planned=True, prefer=, enqueued=)`).
  `fetch.py`: planned mode (no search, no library ask, no enqueue), `in_library` lifted to module level.
  `Worker._spend` groups `album` approvals by `request_id`. Fake slskd gains `posts`/`searched`; `fake_beet`
  takes a per-file target. New `tests/test_album_job.py` (23). Tests 2009 → 2032.
- **Verified.** First red at import, then mutation checks (no grouping, planned search, planned enqueue, no
  library first, no re-plan, approve every row, no busy refusal): each turns 1–7 tests red. Opus review: 3
  important fixed test-first (5 tests seen red): don't enqueue rows that are ok, in flight or rejected at their own
  tier; forget a planned file its fetch didn't file and a refused POST's records; refuse re-approval while claimed.
  Subset (album_job, worker, fetch, approvals, fake_slskd, fetch_filing) 189 passed; full suite green, 2032, 716 s.
- **Next sessions must know.** The happy-path FLACs are per-length (`flac_bytes`, not `good_flac_bytes`: header_only
  checks each row's own duration). The restart case leaves rows the job hadn't reached `needs_source` (request
  `open`), as `recover_interrupted` does for one row; their queued transfers stay in slskd (gap noted in the plan,
  for S2-05b/c). Per-track rows already go through an ordinary fetch; S2-05c adds the caps and `exclude`.
- **Questions for Michael.** None. Proposed change: none.

### 2026-10-23 00:30 · S2-04 · passes

- **Changed.** New `sourcing/album.py` (pure): `plan_album(responses, rows, *, policy, listed_lengths)` → `AlbumPlan`
  (`primary`, `secondary`, `per_track`, `alternates`, `assignments()`), `FolderPick(username, directory, rows, score)`,
  `describe(plan, peers=False)` (`folder N`, `7 of 9`, row → basename; no peer, no directory). Folders are
  (peer, directory); rows map via `scorer.rank` per folder, greedy by score, one file per row. New
  `tests/test_album_plan.py` (23 tests: the 5 spec cases + review fixes). Plan: "As built (S2-04)" in the S2 plan.
  Tests 1986 → 2009.
- **Verified.** Tests seen red first (no module; then 5 review-fix tests red); mutation checks (no bitrate tie-break,
  MIN_FOLDER_ROWS=1, no release rule, file reuse, rejected files used) each turn a test red. `check.sh
  tests/test_album_plan.py tests/test_scorer.py` 56 passed; full suite green, 2009 tests, 704 s. Opus review: 0
  critical, 1 important (the secondary ranked same release over coverage, against the spec: fixed, coverage first),
  lows fixed: share-root files (`directory ""`), per-folder `fileCount`, peer/directory final tie-break, rows kept by
  position (not `id()`).
- **Next session (S2-05) must know.** Spec case 3 ("bitRate 1000 vs 900") is decided by a summed-bitrate tie-break
  after slot and speed: the scorer gives a lossless file's bitrate no points, so the scores tie. `listed_lengths` is
  `{track_no: seconds}`, but S2-03's `ReleaseTrack` has no length: add it (MB `track.length` ms → s) or pass None.
  `repr`/`as_dict` carry peer names, so a cached plan goes out only through `store.public`. The secondary can be the
  primary's own peer in another directory, so a start timeout must switch both.
- **Questions for Michael.** None. Proposed change: none to the feature list.

### 2026-10-22 23:40 · S2-03 · passes

- **Changed.** `sourcing/musicbrainz.py`: `MusicBrainz.release_search` / `release` (shared limiter + cache) and pure
  `match_release` → `ReleaseMatch(id, format, date, tracks)` (track count, then titles in order across media by
  `loose(base)` + version key, `asked_title` first; tie order Digital Media, CD, earliest date, no date last).
  `sourcing/requests.py` `match_request_release` (live rows only: not removed, newest per track_no; a matched
  request refills a re-seeded row from its stored release); `CrateStore.set_request_release` writes rows + release in
  one commit, `updated_at` untouched. `fetch.py`: verify gets the row's `mb_recording_id` (a copy upgrade: Navidrome's
  id first). `seed-spotify --musicbrainz` / `$MUSICBRAINZ_CACHE`. Plan notes under `## Schema`. Tests 1954 → 1986.
- **Verified.** Each new test seen red first; the step's subset (client, musicbrainz, fetch_filing, fetch, requests,
  sourcing_cli) 155 passed before the review fixes; full suite green, 1986 tests, 698 s. Opus review: 2 medium
  (a re-seeded row got no recording id / blocked any later match; the hard check vs digital-only recordings, see
  below) and 6 low; fixed test-first: live rows, one transaction, version key, OSError from the cache, asked_title,
  the copy-upgrade fallback test.
- **Next sessions must know.** An album track already owned by another request leaves a gap in track numbers, so
  that album gets no ids (soft check, documented in the plan). The rate limit is per process (worker + seed-spotify
  at once are not spaced against each other). S4-01's checklist: first live `seed-spotify <album> --musicbrainz`
  with `MUSICBRAINZ_CACHE` set, and check the `release` event.
- **Questions for Michael.** None blocking. Proposed change: the spec's tie order picks Digital Media first; if a
  digital release has recordings of its own with few AcoustID submissions, a correct CD rip would fail verify's hard
  check. MusicBrainz usually shares recordings across remasters, so I kept the spec; S2-05 could accept the recording
  of any release that matched one to one (or treat a mismatch with the same title key as a warning).

### 2026-10-22 23:50 · S2-02 · passes

- **Changed.** `sourcing/playlist_sources.py`: `Row.track_no`/`Row.year`; `rows_from_spotify` fills album, track_no,
  year (`releaseDate[:4]`, null → None) for an album entity, reads a track entity as one row; `load` refuses a track
  URL. New `sourcing/requests.py` `add_spotify(store, url, *, fetch, tier, default_tier)` + `canonical(url)` (no
  `?si=`, no `/intl-xx/`). `crates/store.py` `find_request(source)`; a queued row joining a request also gets album/year
  (COALESCE). `spotify_csv.URL` matches `track` too. `seed-spotify` prints `request <id>: Al Green – I'm Still in Love
  With You (9 rows)` for an album or track; playlists unchanged. Plan: S2-02 notes under `## Schema`. Tests 1933 → 1954.
- **Verified.** New tests seen red first (the review-fix batch: check.sh stops at the first failure, so one of those
  was seen red); subset of the 4 touched test files 108 passed; full suite green, 1954 tests, 693 s. Opus review: 2
  important (track URL made a 1-track playlist via import-playlist; a track already in another request made an empty
  request that stays `open`) + 5 minor, fixed test-first; kept the `sourcing/requests.py` name (the spec's).
- **Next sessions must know.** `track_no` is embed order across discs (no disc number): S2-03 must compare against
  MusicBrainz tracks in order across all media, not `position` within one medium. A request whose rows all belong to
  another request is not made; that request is returned. The **track embed shape is not captured**: code assumes
  `name`, `artists[{name}]`, `duration`, `uri` (as `track_lead` reads); `releaseDate` as a string or `{isoString}`.
  S4-01 should add "capture one track embed to `fixtures/`" to the checklist.
- **Questions for Michael.** None.

### 2026-10-22 23:05 · S2-01 · passes

- **Changed.** `crates/store.py`: `requests` table (kind CHECK album|playlist|track, no status column) and
  `external_wanted.request_id/track_no/mb_recording_id`, additive in `SCHEMA` + `_migrate`; `add_request`,
  `set_release_id`, `set_recording_id`, `request(id)` (rows = `wanted_row` dicts by track_no), `requests()` newest
  first, pure `request_status(rows)` + `REQUEST_STATUSES`; `add_external_wanted(..., request_id=, track_no=)`.
  Plan `docs/plans/2026-10-22-s2-album-requests.md` (Schema, Request status, Album job, Live steps). Tests 1906 → 1933
  (`tests/test_crates.py` +25, new `tests/test_s2_plan_doc.py` +2). Fixed a garbled comment on `REPLACEMENT_OPEN`.
- **Verified.** Each test seen red first; `check.sh tests/test_crates.py tests/test_s2_plan_doc.py` 65 passed; full
  suite green, 1933 tests, 690 s. Opus review of the diff: 3 medium findings fixed test-first (a failed row approved
  again or filed-but-unindexed counts as going → `approved`; a request never attaches a `removed` row), plan wording
  ("prefer" the same release) and the rollback caveat added.
- **Next sessions must know.** A row belongs to the **first** request that asks for it (`request_id` set only when
  NULL). Known gap in the plan: an import's `_reask` can supersede a failed row another request holds; S2-07/S3-01
  decide whether to re-link. `review` rows count as open (no status of their own). S4-01's rollback step must first
  spend unused `album` approvals (an older worker would run them per track). Migration race on two containers
  starting at once (existing pattern) is unchanged.
- **Questions for Michael.** None new (status words = initializer question 2).

### 2026-10-22 22:10 · initializer

**Scope.** Milestones S2 (album requests), S3 (request API) and S4 (checklist, whole-run review) of
`docs/specs/2026-10-22-downloads-and-requests.md`, as the brief says; S1 is in the base and is not redone.
**21 features**: S2 = 11 (S2-01 plan+table, S2-02, S2-03, S2-04, S2-05a/b/c, S2-06a plan, S2-06b, S2-07, S2-R1),
S3 = 8 (S3-01, S3-01b, S3-02, S3-03, S3-04, S3-05 docs, S3-06, S3-R1), S4 = 2 (S4-01 docs, S4-02 review).
Splits against the spec: S2-05 is three sessions (happy path, switching, caps and last resort: seven fake-slskd tests
would not fit one session); S2-06 is plan+measurement (S2-06a, reviewed before any tag code, as CLAUDE.md requires)
then code (S2-06b); S3-01's MusicBrainz-id bodies and the library marking are S3-01b. The spec's S3-03..S3-06 keep
their numbers. S1 ran 16–35 min per feature at $1.6–4.5 on Opus; these are sized the same (S2-05b is the risky one).

**`after`.** S2-01 `[]`; S3-01 `[S2-01]` (the brief's words; array order still puts every S2 feature first, so S3-01
runs only once S2 is done or stuck); S4-01 after every S2 and S3 feature; S2-06b after S2-06a and S2-05a; S2-07 after
S2-05c and S2-02; the reviews after their milestone. S2-R1 is Opus; S3-05 is Sonnet (docs only). S4-01 is Opus on
purpose: it is a live runbook with undo steps (S1-09's checklist needed 13 review fixes on Opus).

**Base.** `1eb4259` = `origin/harness/dj-crate-streaming-2026-10-22-fixes` (S1-01..S1-09, S1-R1, D48, D49) which
contains `origin/main` at `e4e806e` (`git merge-base --is-ancestor origin/main HEAD` → yes). Suite on the base: green,
1906 tests, 710 s. S1's PR (#27 per its retro) is open, not merged; PR #16 is not on main either (checklist step 1).
Reviews diff from `1eb4259`.

**Where things live (what S2–S4 touch)**
- `crates/store.py` (1222 lines): schema string at line ~36 (`external_wanted` ~63, `approvals` ~105 with `purpose`
  download|play-now, `previews` keyed by song_id ~109); additive `_migrate` at ~292 (the pattern for the `requests`
  table and the new columns; test model `tests/test_crates.py::test_store_migrates_old_external_wanted_table` ~174);
  `APPROVAL_PURPOSES` ~131 (add `album`); `approve(wanted_id, by, candidate, tier, purpose)` ~562 supersedes an
  earlier unused approval of the same row; `add_external_wanted` ~670 returns the existing id for a same artist/title
  row (so a re-run of a request adds no row) and `_insert_external` ~719 is the INSERT to extend; `set_preview` /
  `preview` ~545; `recover_interrupted` ~617; `external_for_playlist` ~912; `public(v)` ~224 strips what must not
  leave (apply it to every new payload); `log(playlist_id, song_id, kind, detail)` ~1197; `events(limit)` ~1218.
- `sourcing/fetch.py` (609 lines; read the module docstring first): `fetch(wanted_id, *, store, slskd, navidrome,
  reconciler, music_root, downloads_root, approve, tier, policy, download_timeout_s, poll_s, scan_timeout_s,
  verifier, filer, navidrome_db, lookup, prefer, trash_root, score_tier, provisional, sleep, retry_pause_s)`.
  Closures: `in_library()` ~386 (S1-07), `intent_for` ~462, `attempt(cand)` ~475 with inner `records()`/`download()`
  (forget completed records → `before` set → `slskd.enqueue(username, [{filename, size}])` → poll for the record
  whose id is new, S1-04), the S1-06 retry ~534, `rid`/`extra`/`asked_title` for the verifier ~550–560 (S2-03 sets
  `rid = row.get('mb_recording_id')` for non-copies), `finish` ~239. `TRANSFER_ERRORS` line 97. Planned mode
  (S2-05a) adds `planned=True` + `enqueued=<ids before the job's enqueue>` and skips search and enqueue.
- `sourcing/worker.py` (363 lines): `Worker(store, slskd, navidrome, reconciler, fetch_kwargs, fetcher=fetch, log)`,
  `self.common` = the fetch kwargs; `_spend(approvals, results)` ~267 claims each approval and calls
  `self.fetcher(wanted_id, approve=True, prefer=candidate, **extra, **self.common)`; `_tick` ~297 order: play-now,
  reconcile, rechecks, the rest of the approvals, replacements, placement, export. Album approvals (purpose `album`)
  are grouped by the rows' `request_id` and handed to `album_job.run` from `_spend`. Env for the CLI's `worker`
  (`WORKER_RECHECK_S`) is read in `sourcing/cli.py`; add `ALBUM_START_TIMEOUT_S`, `ALBUM_PLAN_MAX_AGE_S` there.
- `sourcing/slskd_client.py` (142 lines): `search`, `downloads(username=None)` (404 → none), `enqueue(username,
  files)` takes a list (one POST for a whole folder works already), `remove_download(username, id)` sends
  `?remove=true` (S1-04), `transfer_files` flattens the per-user shape; `SlskdError.status`.
- `sourcing/fake_slskd.py` (170 lines): `FakeSlskdServer(responses, downloads_dir, files, api_key='k', complete=True,
  fail_enqueue=False|set)`; `do_POST` on `/transfers/downloads/<user>` answers one record per file in the body;
  `seed_transfer(username, filename, state)` plants an old record; `transfers` is the list to inspect; `complete`
  is global (S2-05b's "one peer never starts" needs a per-peer form: extend the fake first, as S1-04 did).
- `sourcing/scorer.py`: `Wanted(artist, title, album, duration_s, year, …)`, `Candidate(username, filename, size,
  …, basename, extension, score, rejected, reasons)`, `parse_responses`, `score_candidate`, `rank(responses, wanted,
  policy)` sorts rejected last, `explain(cands, peers=False)`. `sourcing/album.py` (S2-04) ranks per folder with it.
- `sourcing/identity.py`: `parse_title(title, artist).base`, `loose(s)` (the "same song" fold), `lead_artist`.
  Title keys for the 1:1 release match (S2-03) and the planner are `loose(parse_title(...).base)`.
- `sourcing/verify.py`: `HARD_EVERY_TIER` line 233 (`recording` is a hard finding), `HARD_WHEN_STRICT` 234
  (`transcode`, `fake_24bit`, `fake_hires`, …); `Verdict.problems` entries carry the kind. S2-05b's distrust set.
- `sourcing/musicbrainz.py` (233 lines): `MusicBrainz(opener, sleep, clock, min_interval_s, retries, timeout,
  cache)`, `get(path, **query)` (cache, 404 → None, 503 backoff), `recording`, `isrc`, `search(artist, title)`
  (recordings). S2-03 adds `release_search` and `release`. The shared limiter is process-wide (`reset_shared_limiter`
  in tests). `tests/test_musicbrainz_client.py` has the stub-opener pattern.
- `sourcing/playlist_sources.py`: `Row(position, title, artist, duration_s, spotify_id, album, note, sep, isrc)`;
  `rows_from_spotify(entity)` reads `trackList[].title/subtitle/duration/uri`; `load(src, fetch=fetch_entity)`.
  `sourcing/spotify_csv.py`: `fetch_entity(url)` is the one network call (tests `monkeypatch.setattr(cli,
  'fetch_entity', …)`), `rows(entity)`, `track_lead`.
- `sourcing/import_playlist.py`: `match(client, Row, accept)`, `choose`, `import_playlist(name, rows, client,
  store, source, dry_run, merge, resolve, tier) -> Report`; `--merge` adopts a same-named playlist.
- `sourcing/filer.py` (178 lines): `BeetsFiler(config, library, beet)`, `file(folder, log, *, names=…)` runs
  `beet import -q -s -m -W -l <log> <folder>` and `fill_missing_tags` (artist/title only); `scripts/tag_cleanup.py`
  `write_minimal(path, changes)` line 73 is the only tag writer allowed (M2 trap). `deploy/beets.yaml` `paths:`
  has `default`, `comp`, `singleton: $artist/Singles/$title`; a query key (`dj_album:1:`) must come before
  `singleton:` (beets takes the first matching query). `tests/helpers.py::fake_beet` is the stand-in `beet`;
  `tests/test_filer.py` drives it. `/usr/bin/beet` is beets 1.6.0 on this box (python 3.12): S2-06a measures with a
  scratch `BEETSDIR` and `directory:`, never `/srv`.
- `crates/service.py` (539 lines): `Config.from_env`, `CrateApp(cfg, policy, store, …)`, the HTTP router `_route`
  ~404 (error mapping) and `_api(method, parts, query)` ~431 (add routes beside `wanted`); `preview` ~216 and
  `approve` ~233 for one row (the `_lock`, `pick_token`, `_not_in_progress` 404/409 wording to reuse). Tests:
  `tests/test_service.py` `svc` fixture (`Config(subsonic_url=fake.url, username='demo', password='demo',
  db_path=':memory:', port=0)`, `CrateApp(cfg, store=CrateStore())`, `get`/`post` helpers).
- `sourcing/cli.py` (333 lines): argparse subcommands at ~113 (`rank`, `verify`, `fetch`, `worker`, `seed-spotify`
  ~151/~226, `import-playlist`, `retier`); `add_slskd_args`, `_fetch_env`. `tests/test_sourcing_cli.py` `_env`.
- `crates/cli.py`: `wanted reopen` (S1-08) is the dry-run-by-default model.
- Tests to copy from: `tests/test_fetch.py` (`world`, `run`, `header_only`, `new_song`, `not_in_library`,
  `good_flac_bytes`, `RESPONSES`), `tests/test_worker.py` (`worker(world, srv)`), `tests/test_fetch_filing.py`
  (`fetched(...)` captures verifier kwargs), `tests/test_fake_slskd.py`, `tests/test_playlist_sources.py`,
  `tests/test_crates.py`, `tests/test_approvals.py`, `tests/test_monitoring_doc.py` (a doc test).
- Fixtures (never invent a shape; copy a dict and change values): `search_responses.sample.json` (slskd responses,
  8 peers), `spotify_embed_album_al-green-still-in-love.json` (`type: album`, `name`, `subtitle: Al Green`,
  **`releaseDate: null`** — the year must be allowed to be None; MusicBrainz gives it), `spotify_embed_tea-tent-1.json`
  (playlist), `musicbrainz_release_search_al-green.json` (10 releases: 9-track CD `3c9a52ee…` 1993, CD `15e4ea1a`
  2009, digital `095b1ca3…` 2019-12-20 and `5ee0b926…` undated, vinyls 1972/2009/2022, an 11-track CD and an 18-track
  one), `musicbrainz_release_al-green-still-in-love.json` (the CD `3c9a52ee…`, 9 tracks with `recording.id`, track
  `length` ms; track 1 `cdac1a50-8ba6-4edd-8137-618928580d38` 195733, track 9 `83f06455…`),
  `musicbrainz_search.sample.json`, `musicbrainz_recording.docs-example.json`, `acoustid_lookup.docs-example.json`.
  Not captured (don't depend on it): the enqueue response body, `/users/*`, slskd's transfer listing order.

**Gotchas**
- Every feature starts with a failing test on the current tree; run the touched test files while iterating
  (`.harness/check.sh tests/test_album_job.py`), the full suite once before `passes` (1906 tests, ~11–12 min; `-x`
  stops at the first failure). `git add` files by name, never `-A`; `git show --stat HEAD` before pushing.
- Peer names (`username`), absolute library paths and API keys never reach a reason, an event, a plan, an API
  payload or a doc: label folders `folder 1`, `folder 2`; `store.public` on every response; a test per payload.
- D7: nothing is enqueued without an approval; `album` approvals are Michael's `approve` (HTTP or CLI). A preview or
  `plan_request` may *search* slskd (as today's preview does) but never POSTs a transfer.
- Nothing live: no `docker`, `scripts/live-run.sh`, `scripts/deploy.sh`, `scripts/live-check.sh`, no `/srv`, no
  network (`.harness/check.sh` unsets the live credentials and points every path into scratch; keep new env reads
  defaulting that way). `scripts/capture_spotify.py` (S3-06) is tested with a stub and never run.
- Decisions: D49 is the highest taken (this branch); `origin/main` and the SoulSync branch stop at D47. A new
  decision that is Michael's → `D<n> *default*` at the **end** of the table in
  `docs/specs/2026-10-17-amperfy-pivot.md`, after `git fetch -q` and a grep of `origin/main`,
  `origin/harness/dj-soulsync-review-2026-10-22` and this branch for the highest `| D`. The album path (S2-06a) is
  Michael's answer of 2026-10-22, recorded as `D<n>` **without** *default*.
- The SoulSync review (`origin/harness/dj-soulsync-review-2026-10-22`, `docs/research/2026-10-22-soulsync/`,
  not on this branch) is context only: its spec deltas (pair S1-07 on the MB id, maximum matching, measured speed,
  poll the global transfer list, reuse an existing album folder's identity, request status words, 429 stop, capture
  list) are **not** adopted unless the spec or an INBOX answer says so. Two cheap ones are in the steps because they
  cost nothing: `spotify:<kind>:<id>` URIs (S3-01) and the 429 stop (S3-06); the status words (S2-01) are ours too.
- Sessions are sequential, but `sourcing/fetch.py`, `sourcing/album_job.py`, `crates/store.py` and
  `sourcing/requests.py` are edited by several features: read them fresh each session.
- `tests/conftest.py` sets `CRATES_OWNER=comment`; the `world` fixture's library already holds Chic — Good Times,
  so album tests use `not_in_library` or the Al Green titles.
- beets measurement (S2-06a): `beet -c <scratch yaml>` with `BEETSDIR` in scratch; `--set dj_album=1` on `import -s`
  sets a flexible field on the items; the path-format query `dj_album:1:` is matched in yaml order, so it goes
  before `singleton:`. If it does not take, keep `Singles`, say so in the plan and the checklist, don't force it.

**Docs the run touches**: `docs/plans/2026-10-22-s2-album-requests.md` (new, S2-01), `docs/plans/2026-10-22-S2-album-tags.md`
(new, S2-06a), `docs/api.md` (new, S3-05), `docs/worker.md` (`## Album jobs`, `## Filing`, `## Approvals`),
`docs/architecture.md` §2 §3 §4(e), `docs/hard-won-facts.md`, `docs/next-todos.md` State, the spec's S2/S3/S4
headers, the pivot spec (D50+), `docs/plans/2026-10-22-downloads-checklist.md` sections 4, 6 and the captures (S4-01),
`docs/plans/2026-10-22-morning-checklist.md` (a link; its "PR #16" line is S1-09's, don't duplicate).

**Questions for Michael (defaults taken; answer in INBOX.md to change any)**
1. **Each album row is filed as it lands** (today's behaviour), so Navidrome may show a half album for a while;
   the alternative (hold verified files in `.staging` until the job ends) is not built. Recorded by S2-05a as a
   `D<n> *default*` only if a session finds it changes code; otherwise it stays this note.
2. **Request status words** `open | approved | partly | done | failed`, derived from the rows (S2-01's plan).
3. **A folder is distrusted on one `transcode`/`fake_24bit`/`fake_hires`/`recording` finding or on 2 failures of any
   kind**; an ordinary finding (`duration`, `truncated`) fails that row only (spec S2-05, taken literally).
4. **The album path** is built as you answered (`$albumartist/$album ($year)/$track - $title`, D<n>, not a default)
   **only if** beets 1.6.0 honours the `--set` field and the query path for `-s` imports in S2-06a's scratch
   measurement; otherwise the tags are written and the path stays `Singles` until you say otherwise.
5. **Question B (client UI)** stays open: S3 is server-only; `docs/api.md` is what a client would use.
6. **Spotify as a catalog provider** waits for the S3-06 capture you run (checklist section 6); where the client
   secret lives for good is not decided.
