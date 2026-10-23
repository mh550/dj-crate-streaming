# Progress log — run `dj-crate-streaming-2026-10-22-fixes` (branch `harness/dj-crate-streaming-2026-10-22-fixes`)

What this file is: the shared memory of the agent harness for this run. Each session appends one entry **at the top**
(newest first) when it finishes a feature: what it built, what it learned, what it asks. Nobody edits older entries.

How to read the run: `feature_list.json` in this directory is the build list, in priority and dependency order; a
session takes the first feature with `passes: false` whose `after` features pass, and may flip only its own `passes`.
Michael steers from `INBOX.md` on this branch (status line `run | pause | stop`; answers under `## Answers`); every
session reads it at startup. Policy: **build-only** (`.harness/config.sh`) and the brief in `brief.md`: nothing live,
no docker, no `/srv`, no network, no client UI, PRs only.

### 2026-10-22 verify · verify S1

Independent re-run. `git log`/`git status`: commit exists, branch == origin/harness/… (e18006e); harness `check.sh`: green, 1906 tests. I re-ran the touched test files on HEAD (753 + test_fetch 47 passed) and the S1 tests against a worktree of the pre-S1 base 307d62b (they fail there). All 10 features hold; no `passes` changed. Nothing live was run (no docker, no `/srv`).

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| S1-01 | 1 | Copied HEAD's tests/ into a worktree at 307d62b and ran `check.sh tests/test_scorer.py` | 4 failed (ext-74 shape accepted); same file passes on HEAD (33 pass) | yes |
| S1-01 | 2 | Read `score_candidate`, `title_slot`, `slot_names_another_song` in sourcing/scorer.py | slot parsed with `parse_filename`, base compared by `loose`; rejected = `title slot is <slot>`, score 0; no-slot files untouched (`test_a_file_without_a_title_slot_is_unchanged`); `(12'' Version)` / `(Live)` slots pass (`test_a_labelled_title_slot_is_left_to_the_version_rules`) | yes |
| S1-01 | 3 | Ran tests/test_scorer.py, test_scorer_versions.py, test_fetch.py on HEAD; read the added cases | all pass; `…_a_title_slot_naming_the_wanted_song_stays_acceptable` has Love and Happiness / Love And Happiness; Live-label case asserts `not rejected.startswith('title slot is')` | yes |
| S1-01 | 4 | Built my own ext-74 fixture JSON and ran `python3 -m sourcing.cli rank --fixture … --artist 'Al Green' --title "I'm Still In Love With You" --duration 196`; same on 307d62b | HEAD: `0.0 … ✗ title slot is One of These Good Old Days`, exit 3 (no pick); old tree: `82.5` acceptable | yes |
| S1-01 | 5 | `git log`, `git status`, harness check | commit `S1-01: reject a candidate whose title slot names another song` (0493bc2) present, pushed; suite green 1906 | yes |
| S1-01 | 6 | Harness `check.sh` result for this tree; `git status -sb` vs origin | green (cached for this code tree, 1906 tests); branch in sync with origin/harness/dj-crate-streaming-2026-10-22-fixes (I also re-ran this feature's test files on HEAD: pass) | yes |
| S1-02 | 1 | Ran tests/test_acoustid.py on 307d62b with HEAD tests | 6 failed; on HEAD all pass (not skipped: ffmpeg/flac present). `test_a_confident_acoustid_title_…` asserts ok False and problem `AcoustID says this is One of These Good Old Days, not I'm Still In Love With You` | yes |
| S1-02 | 2 | Read `verify`/`_acoustid_check` in sourcing/verify.py | `asked_title` param passed on; rule only when recording_id None; `m['acoustid']['asked']` recorded; lookup error/empty stay warnings; id rule unchanged. Deviation (stronger, review-driven): any confident result and `can_be_song` over all returned titles instead of top only; behaviour per step holds | yes |
| S1-02 | 3 | Read sourcing/fetch.py:560 and tests/test_fetch_filing.py diff | `extra['asked_title'] = row.get('asked_title') or row['title']` with lookup; `kw ==` asserts updated; `test_a_renamed_external_row_passes_the_title_it_asked_for…` asserts asked 'Good Times' after rename to 'Good times' | yes |
| S1-02 | 4 | Ran test_acoustid, test_verify, test_verify_rows, test_fetch_intent (+ filing) | all pass; finding case, other-spelling/Live case (`test_any_returned_recording…`), score 0.5 case (`test_an_unconfident_…`), recording_id case unchanged | yes |
| S1-02 | 5 | `git log` | commit a3cc53d `S1-02: an AcoustID disagreement without a recording id is a hard finding` pushed; suite green | yes |
| S1-02 | 6 | Harness `check.sh` result for this tree; `git status -sb` vs origin | green (cached for this code tree, 1906 tests); branch in sync with origin/harness/dj-crate-streaming-2026-10-22-fixes (I also re-ran this feature's test files on HEAD: pass) | yes |
| S1-03 | 1 | Ran tests/test_fetch.py on 307d62b with HEAD tests; read `test_a_file_navidrome_lists_as_another_song_puts_the_row_in_review_not_renamed` | fails on old tree; on HEAD asserts review with reason `filed One of These Good Old Days as <rel>, asked for I'm Still In Love With You`, title unchanged, library_song_id None, no `renamed`, `due_placements()==[]` | yes |
| S1-03 | 2 | Read `finish`/`in_library` area of sourcing/fetch.py and the wrong_song test | base compare via `can_be_song`; `wrong_song` event holds rel and `s9`, no peer; same base → `renamed` path (`…_same_song_in_another_spelling_or_version_is_renamed_as_before`, 3 params pass) | yes |
| S1-03 | 3 | Read crates/store.py:193 and web/app.js:125 diffs, tests/test_m8_followup.py | both regexes gain `filed .+ as .+, asked for `; `filed_path` None / `retryable_review` True asserted at test_m8_followup.py:25-42; `test_a_recheck_that_finds_the_file_under_another_song_ends_review_not_ok` covers verify path | yes |
| S1-03 | 4 | Ran test_fetch, test_fetch_filing, test_placement, test_web_m8, test_m8_followup | all pass | yes |
| S1-03 | 5 | `git log` | commit 6fc9dd1 `S1-03: never rename a row onto another song` pushed; suite green | yes |
| S1-03 | 6 | Harness `check.sh` result for this tree; `git status -sb` vs origin | green (cached for this code tree, 1906 tests); branch in sync with origin/harness/dj-crate-streaming-2026-10-22-fixes (I also re-ran this feature's test files on HEAD: pass) | yes |
| S1-04 | 1 | Ran a script against `FakeSlskdServer`: plain DELETE, `?remove=true`, unknown id; read tests/test_fake_slskd.py | plain DELETE on InProgress → 204 b'', record kept as `Completed, Cancelled`; `?remove=true` → 204 and record gone; unknown id → 404; `seed_transfer(..., transfer_id=)` exists; tests for each present | yes |
| S1-04 | 2 | Ran test_fetch.py on 307d62b with HEAD tests; read `test_a_retry_tells_its_own_transfer_from_a_stale_record_of_the_same_file` | fails on old tree; on HEAD: `~stale` Errored seeded, status ok, one enqueue, no `~stale` left | yes |
| S1-04 | 3 | Read slskd_client.remove_download and fetch.py attempt (lines ~475-525) | DELETE …?remove=true; 404 quiet via SlskdError status; module docstring updated; own transfer = ids not in `before`; waits until one appears, bounded by timeout | yes |
| S1-04 | 4 | Read `test_a_stale_succeeded_record_is_not_taken_for_this_download`; ran test_fake_slskd, test_worker | stale Succeeded + complete=False → `failed`/`download timed out`, one enqueue; both files pass | yes |
| S1-04 | 5 | `git log` | commit 71022f4 `S1-04: slskd transfer hygiene…` pushed; suite green | yes |
| S1-04 | 6 | Harness `check.sh` result for this tree; `git status -sb` vs origin | green (cached for this code tree, 1906 tests); branch in sync with origin/harness/dj-crate-streaming-2026-10-22-fixes (I also re-ran this feature's test files on HEAD: pass) | yes |
| S1-05 | 1 | Ran script: `SlskdClient(url,'k').search_state('nope')`, closed-port client; read `test_slskd_failing_on_both_peers…` | message exactly `slskd GET /searches/<id>: HTTP 404`; closed port → `SlskdError: slskd POST /searches: Connection refused`, no key/host; fetch test asserts reason has no peer, `@` or api key (now both-peer form, S1-06). Old-tree run of tests/test_slskd_client.py errors at collection | yes |
| S1-05 | 2 | Read `SlskdError`, `_req` in sourcing/slskd_client.py; tests/test_slskd_client.py::test_every_endpoint_has_its_template | class SlskdError(OSError) with method/endpoint/status; templates `<id>`, `<peer>`; HTTPError/URLError mapped; 404 handlers use status==404 | yes |
| S1-05 | 3 | `grep HTTPError|urllib sourcing/fetch.py sourcing/worker.py` | only a comment mentioning urllib at fetch.py:396; no dead handlers; fake test asserts SlskdError | yes |
| S1-05 | 4 | Ran test_fetch, test_worker, test_approvals, test_slskd_client | all pass; peer/key absence asserted over reason and all events | yes |
| S1-05 | 5 | `git log` | commit 06fceb0 `S1-05: slskd errors name the step and the endpoint, never the peer` pushed; suite green | yes |
| S1-05 | 6 | Harness `check.sh` result for this tree; `git status -sb` vs origin | green (cached for this code tree, 1906 tests); branch in sync with origin/harness/dj-crate-streaming-2026-10-22-fixes (I also re-ran this feature's test files on HEAD: pass) | yes |
| S1-06 | 1 | Read FakeSlskdServer `errored_peers`/`fail_enqueue` set; tests/test_fake_slskd.py (130,142) | errored peer ends `Completed, Errored` with no file; `fail_enqueue={…}` 500s only those; both tested | yes |
| S1-06 | 2 | Read `test_a_transfer_error_tries_the_next_peer_once` (4 states); ran on 307d62b | fails old; HEAD: ok, `enqueued == [('p-vpn',…),('p-ok',…)]`, one `retry` event with basename + `download ended: <state>`, no peer name | yes |
| S1-06 | 3 | Read `attempt` and retry code in sourcing/fetch.py (~475-560) | trigger set Errored/TimedOut/Rejected/Cancelled or SlskdError status None/>=500; next cand = first unrejected with other username, once; second failure → combined reason; timeout/4xx/verify unchanged. Added 20 s `RETRY_PAUSE_S` via `sleep` (review I-2) | yes |
| S1-06 | 4 | Read tests for both-errored, verify-failure, 500-switch, 404 no-switch | `…second_transfer_error_fails_with_both_attempts_and_tries_no_third`, `…verify_failure_is_not_retried…` (one enqueue), `…5xx…tries_the_next_peer`, `…4xx…does_not_switch` all pass; docs/worker.md has the second-source/`retry` lines | yes |
| S1-06 | 5 | `git log` | commit 6caff39 `S1-06: one more source on a transfer error` pushed; suite green | yes |
| S1-06 | 6 | Harness `check.sh` result for this tree; `git status -sb` vs origin | green (cached for this code tree, 1906 tests); branch in sync with origin/harness/dj-crate-streaming-2026-10-22-fixes (I also re-ran this feature's test files on HEAD: pass) | yes |
| S1-07 | 1 | Read `test_a_song_already_in_the_library_is_linked_not_downloaded[True/False]`; ran on 307d62b | fails old; HEAD: `enqueued == []`, `ok`, reason `already in the library: …`, library_song_id s7, one `matched` event `same version: …`, `due_placements()` lists the row for pl-1 | yes |
| S1-07 | 2 | Read `in_library` and call site (fetch.py ~389-440) | only `if external and copy_id is None`, before search; uses `match_in_library` with the row's asked names; matched + same recording/version → set song, `ok`, `matched` event, FetchResult; ambiguous/missing/other version/errors fall through; runs in previews too (parametrized approve False) | yes |
| S1-07 | 3 | Same placement assertion in the test above; `test_a_library_hit_is_kept_after_a_restart` | `due_placements` includes the ext row with pl-1/s7; passes | yes |
| S1-07 | 4 | Read the three negative tests plus `test_a_crate_row_is_not_asked_about`, `test_a_provisional_copy_is_upgraded_not_linked_to_itself`; ran listed files | other-song → one enqueue; length 240 → searched, no matched event; 3 outage types → searched with `library not asked: <Type>` event; all listed test files pass | yes |
| S1-07 | 5 | `git log`; docs/worker.md Approvals | commit 89c5bbf `S1-07: ask the library before downloading` pushed; worker.md lines at 81-88; suite green | yes |
| S1-07 | 6 | Harness `check.sh` result for this tree; `git status -sb` vs origin | green (cached for this code tree, 1906 tests); branch in sync with origin/harness/dj-crate-streaming-2026-10-22-fixes (I also re-ran this feature's test files on HEAD: pass) | yes |
| S1-08 | 1 | Read tests/test_wanted_reopen.py; ran on 307d62b | 30 failed there (no method/command); HEAD passes. My own run on a scratch crates.db (ext-1 renamed, s9, ok, placement done): dry run printed plan, row unchanged (count placements 1); `--apply` → asked names, asked_* kept, library_song_id empty, provisional 0, `needs_source`, reason `reopened: was ok (filed as …)`, 0 placements, one `reopened` event JSON with artist,title,library_song_id,status,reason,placements | yes |
| S1-08 | 2 | Ran `crates.cli wanted reopen` for ext-9, `crate-1`, and a `sourcing` row; read `reopen_external`, `wanted reopen --help` | exit 1 each: `no such row`, `not an external row id (ext-<n>)`, `is sourcing … a download is in flight`; dry run exit 0 with `dry run: add --apply`; `wanted --json` unchanged (needs Subsonic env as on old tree; `test_cli_wanted_json_still_works` passes) | yes |
| S1-08 | 3 | File listing of scratch dirs before/after `--apply`; read the untouched-assert tests | no file created or changed outside crates.db; no trash/renamed event beyond the seeded one; docs/worker.md "Reopen a row filed as the wrong song" (line 122-141) has the SELECT detail / UPDATE reverse | yes |
| S1-08 | 4 | `git fetch`; origin/main D-numbers; pivot spec rows 43-44 | origin/main ends at D47; branch adds D48 and D49 (`D49 *default*` reopen deletes placements, wrong entry stays, alternative named) at table end | yes |
| S1-08 | 5 | Ran tests/test_wanted_reopen.py (31), test_crates, test_placement; CLI test via `crates.cli.main` | all pass; tests use main([...]) | yes |
| S1-08 | 6 | `git log` | commit aa701e3 `S1-08: crates.cli wanted reopen` pushed | yes |
| S1-08 | 7 | harness check | suite green, 1906 tests (cached for this tree) | yes |
| S1-R1 | 1 | Read progress entry S1-R1 (Opus review of 307d62b...HEAD) | review recorded: no Critical; I-1, I-2, I-3, M-1, M-3 fixed test-first; Minor items listed as left (M-4 etc.) | yes |
| S1-R1 | 2 | Re-checked the four named points: grep of added fetch.py lines for username, `remove_download` call sites, `best = next(… != first.username)`, `copy_id is None` guard, reopen scratch run | username only passed to slskd client calls, never into text/events (tests assert absence); client always sends `?remove=true`; one switch per fetch call; library check skipped for copy upgrades (test); reopen touched only crates.db | yes |
| S1-R1 | 3 | Read diff of fetch.py/slskd_client.py/fake_slskd.py | `attempt` is one path (list once, enqueue, poll own id, forget on failure); `_req(method, template, *args)` builds paths from the template; suite green means no behaviour change (cannot diff-prove, mutation notes in progress) | yes |
| S1-R1 | 4 | Read diffs of docs/worker.md, architecture.md (§4 step 4/7, §7 rows), hard-won-facts.md, next-todos.md, spec S1 header, CLAUDE.md | all present: library-first, retry once, events, Reopen section, 3 hard-won facts, 2026-10-22 paragraph, `Built 2026-10-22 … 0493bc2…` header, CLAUDE.md ~1,870 tests | yes |
| S1-R1 | 5 | `git log` | commit 5f750b0 `S1-R1: review and simplify the download fixes` pushed | yes |
| S1-R1 | 6 | harness check | green, 1906 tests | yes |
| S1-09 | 1 | Read docs/plans/2026-10-22-downloads-checklist.md in full | header says built against fakes, never live; conventions by reference (flock live.lock, window 03:15-04:30, backup status/check/snapshots, live-check.sh, live-run.sh); sections 1,2,3,5,7 in order each with Check:/Undo:; commands, rollback `dj-crates:41fcc5bc01`, `59c6f6a` (exists as a commit here), closing line puts steps 4 and 6 in the S2-S4 run | yes |
| S1-09 | 2 | Ran `crates.cli wanted reopen --help`, `scripts.duplicate_cleanup --help` and `plan --help` with sandbox env; `ls -l` the scripts | all exit 0 and list the commands; `live-run.sh`, `live-check.sh` are `-rwxrwxr-x`; `--print` not run. Check lines match what I saw of the reopen output (`ext-…: A → B`, `placed when the right file arrives:`, `dry run: add --apply`, `reopened <id>; …`) | yes |
| S1-09 | 3 | Read docs/plans/2026-10-22-morning-checklist.md diff and docs/next-todos.md | line `PR #16 must be on main first (see …downloads-checklist.md step 1)` added at the top of section 4 (directly under its heading, accepted as before the deploy steps); next-todos paragraph links the file | yes |
| S1-09 | 4 | Read progress S1-09 entry ("Nothing live"); I ran no docker/compose/scripts/*.sh; `git diff` of the session touches only docs | explicit statement present; I found no live command in the diff | yes |
| S1-09 | 5 | `git log` | commit c6d6927 `S1-09: downloads checklist (S1 live steps)` pushed | yes |
| S1-09 | 6 | harness check | green, 1906 tests | yes |

### 2026-10-22 21:27 · S1-09 · passes

- **Changed:** new `docs/plans/2026-10-22-downloads-checklist.md`: the spec's addition steps 1 (PR #16 then the S1 PR on main, merge commits), 2 (morning sections 1-3, then section 4 with rollback `dj-crates:41fcc5bc01`), 3 (`wanted reopen ext-74` dry run → `--apply`, remove the stale playlist entry, approve ext-74/ext-78, events/Navidrome checks), 5 (`duplicate_cleanup plan`, plan only) and 7 (gluetun logs). Each has Check and Undo; conventions by reference to the morning checklist. One line before morning-checklist section 4 ("PR #16 must be on main first …"); next-todos' 2026-10-22 paragraph links the file. Docs only: tests 1906 → 1906.
- **Verified:** `python3 -m crates.cli wanted reopen --help` and `python3 -m scripts.duplicate_cleanup --help` / `plan --help` exit 0 with `MUSIC_ROOT`, `CRATES_DB`, `NAVIDROME_DB` etc. in a scratch dir and live credentials unset; `scripts/live-run.sh` and `scripts/live-check.sh` are `-rwxrwxr-x`. Full `check.sh` green in 691 s, 1906 tests.
- **Nothing live:** this session ran no docker, no `scripts/*.sh`, no `--print`, read and wrote nothing under `/srv`, no network.
- **Opus review (13 findings, all fixed):** the first output line is `live-run: image …` (now the S1-is-live gate); no hand trash in an undo (stop and ask; D49's leftover playlist entry is removed by hand before the re-test); a `placed` event check; the gluetun undo recreates slskd too (`network_mode: service:gluetun`) and reverts `deploy/compose.yml` in the main checkout; morning sections 1-3 (pull) before the deploy; length can't tell track 01 from 09 (check the filed path); `matched` "library not asked" still downloads; the `.1.flac` pair is under "Lossless pairs, will be trashed"; snapshot suffix `pre-<date>-s1`.
- **Also in the file:** the three slskd behaviours S1-R1 asked to capture (InProgress `DELETE ?remove=true`, duplicate enqueue, a transfer through a logout), as notes to observe, no transfer started for them. Steps 4 and 6 go to the S2-S4 run.
- **Next:** S1 is complete; the harness opens the PR. No questions for Michael.

### 2026-10-22 22:45 · S1-R1 · passes

- **Review (Opus, `s1.diff` 307d62b...HEAD):** no Critical. The 8 checks hold: no peer or key in any reason or event, `?remove=true` on every forget, one switch per fetch, no library check for a copy upgrade (now tested), reopen writes only crates.db. **Fixed test-first:** I-1 `identity.can_be_song` was substring containment ("Take Me Home" passed for "Home"). Now the shorter title's first part must be a whole part of the other's, split at ` - `, dashes, brackets, `,` `:` `/` and feat., with track numbers (`_TRACKNO`: `1-01`, `A1.`) dropped. I-2: 20 s `RETRY_PAUSE_S` before the second source, through `sleep`. I-3: every failed attempt, our own timeout included, cancels and forgets (remove=true) its own new transfer; this replaced `abandon`/`befores`. M-1: a Navidrome OSError/ValueError is logged by type only (the URL holds the token). M-3: non-JSON from slskd is `SlskdError` "invalid JSON". M-5: test that a provisional copy is upgraded, not linked to itself. M-6: reopen refuses a provisional copy of the asked song. M-7: reopen refuses a missing db file instead of creating one. S1-03 Minor: play-now on a wrong-song review says "approve it again, or reopen it".
- **Second Opus pass on the fixes:** it found that my first I-1 rule broke common same-song titles (two-sided extras, `1-01 Song`, `, Pt. 1`, `Intro: Song`). Fixed, and 15 cases were added. Its claim that `_why`'s InvalidURL branch was dead was wrong: a test failed when I removed it, so it stays.
- **Simplified (no behaviour change):** `attempt` lists the peer's records once and keeps `before` local. `SlskdClient._req` takes the endpoint template plus args and builds the quoted path, so each endpoint is written once. Tidied the fake's docstring and its `fail_enqueue` test.
- **Docs:** worker.md Approvals (events `matched`/`retry`/`wrong_song`/`reopened`, pause, cancel, reopen refusals), architecture §4(b) step 4/7 and §7 (4 new rows), hard-won-facts (per-peer 404, the AcoustID same-length case), next-todos 2026-10-22 paragraph, spec S1 marked built, CLAUDE.md count ~1,870.
- **Tests:** 1871 → 1906. Mutation checks: the forget off fails the timeout and connection-blip tests; the pause off fails the pause test; `if external:` fails the provisional test. Full `check.sh` green in 691 s, 1906 tests.
- **Left as is (Minor):** M-4 (a non-SlskdError in the second attempt drops the first reason); a 4xx during the poll skips the forget (a 401 would fail the forget too); `7 Seconds` still matches `Seconds`; spelling-only matches (`Good Vibration`/`Good Vibrations`) and `(Sittin' On) The Dock of the Bay` vs `Dock of the Bay` are now a wrong-song review; a failed transfer no longer stays visible in slskd's UI; reopen can't reopen a provisional cover with the asked title; status reads "downloading <second>" during the 20 s pause; M-2 previews still link/log (S1-07's design; comment fixed).
- **For S1-09 (capture steps):** whether slskd 0.26.1 removes an *InProgress* transfer on `DELETE ?remove=true`, its answer to a duplicate enqueue, and how a transfer behaves while slskd is logged out (is 20 s enough?). No questions for Michael.

### 2026-10-22 20:35 · S1-08 · passes

- **Changed:** `crates/store.py` `reopen_external(ext_id, apply)` (+ `_reopen_plan`): asked names back (a row without them keeps its own), `library_song_id` None, `provisional` 0, `needs_source` "reopened: was <status> (filed as <artist> – <title>)", its `placements` and preview deleted, one `reopened` event = JSON of the old artist/title/library_song_id/provisional/status/reason/placements. `crates/cli.py`: `wanted reopen <ext-id> [--apply]` (optional sub-parser, `wanted --json` unchanged), run before the SUBSONIC check and on crates.db only; prints the plan, `dry run: add --apply to write this` or `reopened <id>`; a refusal exits 1. `docs/worker.md` "Reopen a row filed as the wrong song" (the reverse SQL); **D49 *default*** in the pivot spec (reopen deletes placements; the wrong song's playlist entry stays).
- **Tests:** 1843 → 1871, new `tests/test_wanted_reopen.py` (28): plan/dry run, apply, the right file placed after reopen, S1-03 review row, no asked names, the refusals, write lock, CLI dry run → apply with the fake Navidrome's requests empty, playlists and a music dir unchanged, no `trash`/new `renamed` event. They failed first with `AttributeError: reopen_external`; mutation checks (placements/preview delete, in_flight refusal, lock) each fail a test.
- **Opus review, all 5 fixed:** refuse a `failed` row with a filed path and a non-retryable `review` (`in_flight`, retryable reviews allowed), refuse an open copy replacement (`replace._settle` would undo the reopen), `BEGIN IMMEDIATE` around check + write with rollback and "database is locked" → exit 1, the plan lists every `import_order` slot it will be placed into. Beyond the step: also refused are `removed`, an approval waiting, a placement `writing`, a row already open.
- **Verified:** full `check.sh` green in 687 s, 1871 tests.
- **Left as is:** the row's `verifications` entry still describes the wrong download until the next one overwrites it (cosmetic).
- **Michael:** D49: OK to delete the placements on reopen (the right file then lands in the playlist and the wrong one stays until you remove it), or keep them `done`? **Next:** S1-09 (checklist plan).

### 2026-10-22 22:20 · S1-07 · passes

- **Changed:** `sourcing/fetch.py` `in_library()`: before the Soulseek search, an external row with `copy_of(row) is None` is matched against Navidrome with `import_playlist.match` (asked names, `sep="; "` so a comma in the stored lead stays whole, D26 `accept` empty). `same recording`/`same version` → `ok` "already in the library: <title> (<id>)", `set_external_song(id, False)` (library song + provisional 0), a `matched` event "<how>: <title>", one commit; `FetchResult("ok", "already in the library; nothing downloaded")`. Previews too. Ambiguous/other version/missing searches as before; `SubsonicError`/`OSError`/`ValueError` → `matched` event "library not asked: …" and the search. `docs/worker.md` Approvals + fetch header.
- **Fakes/tests:** `subsonic/fake_server.py` `state.unscanned`: songs hidden from search3/getSong/navidrome.db until the next startScan (`new_song`, `al_green` use it). New fixture `tests.test_fetch.not_in_library` (stubs `sourcing.fetch.match_in_library` → missing) on 36 download tests whose world library already holds Chic – Good Times (s1, s4) or lists the play-now copy before the tick; a tripwire run found 8 of them (e.g. `test_external_wanted_row_files_without_playlist_swap`) passing vacuously via the link. Tests 1832 → 1843: `test_fetch.py` +9 (link with approve True/False incl. `due_placements` for pl-1; committed across a restart; ext-74's other song still downloads; another length searches; outage ×3; crate row not asked), `test_play_now.py` +2 (worker tick: approval and play-now tap end `ok`, s1, provisional 0, approval result "ok: already in the library; nothing downloaded"). The main test failed first (one enqueue); with the check disabled all 8 positive tests fail.
- **Verified:** full `check.sh` green in 686 s, 1843 tests.
- **Opus review:** blocker (play-now tests linked to their own pre-listed copy) fixed by the stub fixture; findings 3 (comma lead), 4 (non-JSON answer), 6 (doc wording) fixed; worker-tick tests added (finding 2).
- **Proposed change (no client UI this run):** a web Preview that links the row only reloads the queue, where the `ok` row drops out silently; the client should show the preview's reason first (`web/app.js` ~363).
- **Next:** S1-08 (`wanted reopen`, D49), which also reverses a wrong S1-07 link. No questions for Michael.

### 2026-10-22 21:05 · S1-06 · passes

- **Changed:** `sourcing/fetch.py`: the download is `attempt(cand) -> (landed, why, again)`. These trigger one switch per fetch call to the next unrejected candidate from another peer: a final `Completed, Errored|TimedOut|Rejected|Cancelled` (`TRANSFER_ERRORS`), or an `SlskdError` with `status` None or ≥ 500 during forget/enqueue/poll. Each switch logs a `retry` event "<basename>: <why>; trying another peer". Before the switch, `abandon(first)` cancels and forgets (remove=true, best effort) that peer's new records, so a transfer still running after a connection error can't land later. A second failure (a 4xx included) gives `<why1> (<b1>); then <why2> (<b2>)`. With no other peer, the first reason stands. Our timeout, a 4xx on the first attempt (re-raised), a missing landed file and verify findings are not retried. `intent`/`expected` are computed per candidate, and `prefer` covers the first attempt only. `sourcing/fake_slskd.py`: `errored_peers` (+ `error_state`, default `Completed, Errored`) and `fail_enqueue` as a set of peers. `docs/worker.md` Approvals: a paragraph on the second source and the `retry` event.
- **Behaviour change:** a 5xx or connection error no longer raises out of fetch. The row is `failed` and returned, so the worker records `failed: SlskdError: …` instead of `error: …`. The Opus review found no caller that parses the prefix. `test_exception_after_sourcing_marks_failed_and_reraises` became `test_slskd_failing_on_both_peers_fails_the_row_naming_steps_not_peers`: same S1-05 checks, no peer name or key anywhere.
- **Tests:** 1819 → 1832. `tests/test_fake_slskd.py` +2. `tests/test_fetch.py` +11: the switch for each of the 4 states; both errored with no third try; no other peer; no retry on a verify failure; a 500 from the enqueue; a connection blip mid-poll (p-vpn record removed); a 404 doesn't switch; a 400 on the second peer keeps both reasons. The switch test failed first with `download ended: Completed, Errored`, and the cancel assertion failed before `abandon`. Full `check.sh`: green in 674 s, 1832 tests.
- **Deviation:** `attempt` returns a 3-tuple (the `again` flag) rather than the step's 2-tuple.
- **Opus review, left as they are (proposed for S1-R1 / S2-05):** (1) `_find_landed` checks size only in its fallback walk, so on a same-path collision it could still take another file. Fix: size or mtime ≥ t0 on the guess path. (2) A connection error (`status` None) usually means slskd/gluetun itself is down, so the retry fails at once with the error doubled. Fix: probe slskd once before switching. (3) Soulseek.NET may also report `Completed, Aborted` (unverified), and `Cancelled` also covers Michael cancelling in slskd's UI.
- **Next:** S1-07. No questions for Michael.

### 2026-10-22 19:10 · S1-05 · passes

- **Changed:** `sourcing/slskd_client.py`: `SlskdError(OSError)` with `method`, `endpoint`, `status`. Every call passes its endpoint template to `_req`. An HTTP error reads `slskd POST /transfers/downloads/<peer>: HTTP 500`; a connection error reads `slskd POST /searches: Connection refused` with `status=None`. `downloads(peer)` still reads 404 as empty and `remove_download` still reads 404 as gone (both now via `status`). `fetch.py` and `worker.py` had no `HTTPError`/`urllib` handling to remove.
- **Beyond the step (Opus review, two Important findings):** an SSL error's text names the host, so `_why` gives only its kind (`reason` or the type name). A bad base URL (`slskd.home:5030`, no scheme, bad port) raised `ValueError`/`URLError` with the host and peer in it; it is now `: invalid URL`. A cut-off body (`IncompleteRead`) and a hang-up are `SlskdError` too, which S1-06 can read as connection errors (`status is None`).
- **Tests:** 1806 → 1819. New `tests/test_slskd_client.py` (12): 404/500/401 strings, the closed port with key `secret-key-7f3a`, all 8 templates, SSL, 3 bad URLs, 3 dropped connections. In `tests/test_fetch.py`, the fail_enqueue fetch's reason is exactly `SlskdError: slskd POST /transfers/downloads/<peer>: HTTP 500`, with no `vinylhead77`, `@` or key, in the reason or any event. Its `run()` now uses `srv.api_key`. The new tests failed first with `ImportError: SlskdError`.
- **Deviation:** `tests/test_fake_slskd.py`'s two raw-wire 404 tests (urllib straight at the fake) still assert `HTTPError`, because they check the fake's wire, not the client. Its client-level 500/401 tests now assert `SlskdError.status`.
- **Verified:** full `check.sh` green in 665 s, 1819 tests.
- **Next:** S1-06 (retry on a transfer or connection error): `SlskdError.status is None or >= 500` is the test. No questions for Michael.

### 2026-10-22 18:05 · S1-04 · passes

- **Changed:** `sourcing/fake_slskd.py`: a transfer DELETE acts as slskd 0.26.1 does. Without `?remove=true` it cancels an `InProgress` record (`Completed, Cancelled`) and keeps every record; with `?remove=true` the record goes; both answer 204 with no body; an unknown id is 404. `seed_transfer(..., transfer_id=)`, and a user's transfers are listed sorted by id (the real order isn't captured). `sourcing/slskd_client.py` `remove_download` sends `?remove=true`, and a 404 means already gone. `sourcing/fetch.py` records the ids of this file's transfers right before the enqueue and follows only a new id; it no longer uses `mine[-1]` or the enqueue response. `docs/hard-won-facts.md` gets the slskd fact.
- **Tests:** 1801 → 1806. `tests/test_fake_slskd.py` +3: plain DELETE keeps, unknown id 404, order by id; the remove case now asserts the record is gone. `tests/test_fetch.py` +2: a `~stale` `Errored` retry ends `ok`, one enqueue, stale record forgotten; this failed first with `download ended: Completed, Errored`. Two surviving stale `Succeeded` records (`!stale`, `~stale`) with `complete=False` end `download timed out`.
- **Verified:** mutation checks. Without the new-id filter, the `Succeeded` test fails whether fetch reads `mine[0]` or `mine[-1]`. `test_fetch.py`, `test_fake_slskd.py` and `test_worker.py`: 90 passed. Full `check.sh`: green in 661 s, 1806 tests.
- **Opus review:** no blocking bugs. **Proposed change (S1-06 or S2-05):** the forget loop forgets only `Completed*` records. A still-running transfer of the same file from a timed-out or killed attempt goes into `before`. If slskd refuses the duplicate enqueue, the retry ends `download timed out`; it never files a wrong file. Fix: cancel and forget non-terminal records of the file too (`remove=true`), once slskd's handling of a duplicate enqueue is known. Low: with two new records for one enqueue, fetch reads the lowest id.
- **Next:** S1-05. No questions for Michael.

### 2026-10-22 20:05 · S1-03 · passes

- **Changed:** `sourcing/fetch.py` `finish`: when Navidrome lists the filed file under a title that can't be the asked song (`asked_title or title`), the row becomes `review` "filed <X> as <rel>, asked for <Y>". It keeps its names and `library_song_id` (None), gets a `wrong_song` event (path + song id), no rename, no proposals, no placement. This applies to the first filing, the `verify` re-check, play-now and crate copy upgrades (no replacement starts). `RETRYABLE_REVIEW` (`crates/store.py`, `web/app.js`) accepts the reason; `filed_path` is None for it.
- **Deviation from step 2 ("compare `loose` bases"):** the comparison is the new `identity.can_be_song`: one `loose` base contains the other. This is S1-02's rule, now shared by `verify` and `fetch`. An Opus review showed that equality sends real same-song pairs to `review`: an old copy titled `02 Can You Feel It`, an unbracketed `feat. Bob`, `- From "Movie"`. ext-74 is still caught.
- **Tests:** 1781 → 1801 (`tests/test_fetch.py` +7: ext-74, same song ×3 (spelling, `(Live)`, `feat.`), re-check, play-now, crate copy; `tests/test_identity.py` +10; `tests/test_m8_followup.py` +3). The ext-74 test failed first (`'ok' != 'review'`). Full `check.sh`: green in 657 s, 1801 tests.
- **Decision D48 *default*** (pivot spec): a wrong-song review is retryable. Approving downloads again; the wrong file stays as its own song. **Michael:** keep it retryable, or require `wanted reopen` first? **S1-08 takes D49.**
- **Known limits / proposed changes:** (1) The retry doesn't remember the rejected file. If AcoustID isn't confident, the same peer's mislabelled file can be downloaded and filed again, each time as an extra copy. Proposed: a later feature (S1-R1 or S1-08) rejects the `wrong_song` pick in `rank`. (2) `play_now` refuses this review row with "pick a version first", which is the wrong wording (Minor; for S1-R1). (3) Containment is lenient: asked `Love` vs filed `Lovely Day` still renames (today's behaviour).
- **Next:** S1-04.

### 2026-10-22 18:45 · S1-02 · passes

- **Changed:** `sourcing/verify.py`. `verify(..., asked_title=)` is passed through to `_acoustid_check`. With no recording id, a confident result (a recording scoring at least `ACOUSTID_CONFIDENT` = 0.8) where no returned recording can be the asked song is the hard `recording` finding "AcoustID says this is <title>, not <asked>". `m["acoustid"]["asked"]` records the asked title. `sourcing/fetch.py` passes `asked_title = row.get("asked_title") or row["title"]` whenever a lookup is configured.
- **Deviation from the step ("equals"):** "can be the asked song" means one `loose(parse_title(t).base)` contains the other, not that they are equal. An Opus review showed that equality hard-rejects the same song in common forms: `Song ft. X`, `Song (Acoustic)` (a label `parse_title` doesn't know), and a Navidrome title such as `Al Green - Love and Happiness` or `01 Love and Happiness`. A hard reject throws a good download away, while a miss only keeps today's behaviour. ext-74 still fails. Any returned recording, at any score, can clear the check (the spec's "no returned recording").
- **Tests:** 1774 → 1781 (6 new in `tests/test_acoustid.py`, 1 new in `tests/test_fetch_filing.py`; two `kw ==` asserts there updated). The ext-74 test failed first with `TypeError: unexpected keyword 'asked_title'`.
- **Verified:** full `check.sh` green in 654 s, 1781 tests.
- **Known limits:** `Song, Pt. 1` vs `Song, Part 1` and a title in another script (Japanese vs romanised) still give the hard finding when AcoustID's titles differ that way.
- **Next:** S1-03. No questions for Michael.

### 2026-10-22 17:50 · S1-01 · passes

- **Changed:** `sourcing/scorer.py`. New helpers `title_slot(basename)` (shared with `name_match`) and `slot_names_another_song`. A candidate whose title slot's song differs from the wanted title's song is rejected as `title slot is <slot>`, score 0. Songs are compared as `loose` base titles, with feat./ft. credits and labels ignored; D26 version rules are unchanged.
- **Review findings fixed:** an Opus review of the first diff found that `- 09. Title`, the en dash `– 09 –` and underscore names bypassed the rule. It also found false rejects for an unbracketed `feat.` and for compilation slots (`Chic - Good Times`, `Good Times - Chic & Nile Rodgers`, `VA_Disco_Hits_07_Chic_Good_Times`). The slot regex now also takes `–` and `NN. `. Any ` - ` part of the slot, or the slot without the lead artist in front, may be the title.
- **Tests:** 1757 → 1774 (17 new in `tests/test_scorer.py`). Every existing scorer, version, fetch and identity test passes unchanged.
- **Verified:** `python3 -m sourcing.cli rank --fixture <scratch>/ext74.json --artist 'Al Green' --title "I'm Still In Love With You" --duration 196` prints `✗ title slot is One of These Good Old Days` and exits 3 (no acceptable pick). Full `check.sh`: green in 651 s, 1774 tests.
- **Known limits (left as they are):** strict key equality still rejects slots like `Lovin' You` for "Loving You" and `Satisfaction` for "(I Can't Get No) Satisfaction". A slot after a bare `- 09 Title` (space only) isn't read as a slot, because that would collide with numeric titles ("Nena - 99 Luftballons").
- **Next:** S1-02 (`verify._acoustid_check`). No questions for Michael.

### 2026-10-22 17:05 · initializer

**Scope.** Milestone S1 of `docs/specs/2026-10-22-downloads-and-requests.md` (the eight download fixes from the Al
Green attempts), a closing review, and the S1 live checklist: **10 features, one milestone**: S1-01…S1-08 (build),
S1-R1 (review + simplify), S1-09 (docs: `docs/plans/2026-10-22-downloads-checklist.md`). S2–S4 are the later run
`dj-crate-streaming-2026-10-22-build`. No plan file: the spec is the plan (nothing in S1 trashes files or writes tags).

**Base.** `307d62b` = the run's start (`94fd950`: `main@5b3e370` + PR #16's four hotfix patches + the spec) **merged
with `origin/main` at `e4e806e`** (R6–R8 of the 10-21 run, D47, the 2026-10-22 morning checklist). The merge was
clean; the suite on the merged tree is in this entry's last line. Why: R6-02 changed `strip_trackno` and
`parse_filename` (now `(basename, artist, wanted)`) and R8-02 touched `fetch.py`, the exact lines S1 edits, and the
milestone verify merges `origin/main` anyway. PR #16 itself is still **not** on `main` (`git merge-base
--is-ancestor 59c6f6a origin/main` → 1); the checklist's step 1 (S1-09) is about that.

**Where things live (what S1 touches)**
- `sourcing/scorer.py`: `name_match` already computes the title slot (`nums`/`slot`, the words after the last
  ` - NN - ` or `_NN_`); `score_candidate` parses versions with `parse_filename(c.basename, w.artist, w.title)` →
  `Title` (`base`, `label`, `kinds`, `key`). `rank` sorts rejected last. `explain(peers=False)` is what reaches events.
- `sourcing/identity.py`: `parse_title`, `parse_filename`, `strip_trackno(s, wanted)`, `loose` (the text fold for
  "same song": accents, punctuation, `&`→`and`), `song_key`. A **song** is `loose(Title.base)`; `Title.key` is the
  **version** (kinds + credits). The spec's "song key" in S1-01/02/03 means the base title, labels ignored.
- `sourcing/verify.py`: `verify(path, expected, tier=, reference=, recording_id=, lookup=, intent=, listed_length_s=)`
  → `Verdict(ok, problems, info, warnings, measurements)`; `_acoustid_check` (line ~387) is the one to extend;
  `HARD_EVERY_TIER` already holds `recording`. `lookup(path) -> [{"id","title","score","acoustid"}]` is
  `sourcing.acoustid.parse`'s shape (best score first). AcoustID "confident" = 0.8 (`docs/identity.md` line 122).
- `sourcing/fetch.py` (504 lines; read the module docstring): status gates → `slskd.search` → `rank` → `prefer` →
  intent → forget/enqueue/poll (`mine[-1]`, the S1-04 bug) → `verifier(...)` → staging → `filer.file` → `finish`
  (`locate_in_navidrome`, `set_wanted_names` = the S1-03 rename, then `ok`/provisional/replacement). Row dicts come
  from `store.find_wanted`: external rows carry `asked_artist`, `asked_title`, `library_song_id`, `provisional`,
  `playlist_id`, `position`, `album`, `duration`, `year`. `copy_of(row)` is None for a plain external row.
- `sourcing/slskd_client.py` (93 lines): `_req` builds every request; `downloads()` already maps a 404 to no
  transfers; `remove_download` is the one missing `?remove=true`. `transfer_files` flattens the per-user shape.
- `sourcing/fake_slskd.py`: `FakeSlskdServer(responses, downloads_dir, files, complete=, fail_enqueue=)`,
  `seed_transfer`, `empty_reads`; **`do_DELETE` matches `self.path` including the query string**, so
  `…/<id>?remove=true` falls through to the search branch today: split the query first (S1-04).
- `sourcing/import_playlist.py`: `match(client, Row, accept=frozenset()) -> Match(status, song_id, how, title, why)`;
  `choose` is the pure part. `Row` is `sourcing.playlist_sources.Row(position, title, artist, duration_s, album=…)`.
  No import cycle with fetch (import_playlist never imports fetch).
- `crates/store.py` (1109 lines): `external_wanted` columns in the `CREATE TABLE` at line ~63 and the additive
  `_migrate` at ~290; `set_wanted_names` (the `renamed` event), `set_library_song`, `set_external_song`,
  `set_wanted_status`, `log(playlist_id, song_id, kind, detail)`, `events`; `RETRYABLE_REVIEW` / `filed_path`
  (reason regexes, mirrored in `web/app.js` ~125); `placements` table (deleting rows re-arms placement, D44).
- `crates/cli.py`: argparse, `wanted` has only `--json` today; `imported migrate [--apply]` is the dry-run pattern.
- `crates/service.py` `preview`/`approve`: the crates container calls `fetch(..., approve=False)`; the worker
  (`sourcing/worker.py` `_spend`) calls `fetch(wanted_id, approve=True, prefer=candidate, **common)` and records
  `r.approval_result or f"{status}: {reason}"`; its `except Exception` writes `TypeName: message` as the outcome.
- Tests: `tests/test_fetch.py` (`world` fixture: fake Navidrome `FakeSubsonicServer`, in-memory `CrateStore`,
  `FakeSlskdServer`, `fake_beet` filer, `header_only` verifier, `new_song` to make Navidrome "find" the filed file),
  `tests/test_fetch_filing.py` (`fetched(...)` captures the verifier's kwargs), `tests/test_fake_slskd.py`,
  `tests/test_scorer.py` (`_named(...)` builds candidates from basenames; the ext-74 test from the hotfix is at
  line 81), `tests/helpers.py` (`load_responses`, `make_flac`, `beets_items_db`, `fake_beet`).
- Fixtures for S1: `fixtures/search_responses.sample.json` (8 peers, slskd response shape: copy it, never invent
  keys), `fixtures/musicbrainz_release_al-green-still-in-love.json` (track 1 `cdac1a50-…` 195.7 s, track 9
  `83f06455-…` 195.6 s), `fixtures/spotify_embed_album_al-green-still-in-love.json` (9 tracks, "Oh ,Pretty Woman"),
  `fixtures/acoustid_lookup.docs-example.json` (raw AcoustID shape; `acoustid.parse` flattens it).

**Gotchas**
- Every feature starts with a failing test on the merged tree; run the touched test files while iterating
  (`.harness/check.sh tests/test_fetch.py`), the full suite once before `passes` (about 1,750 tests, 10–11 min,
  `-x`: it stops at the first failure).
- `git add` files by name; never `-A` (scratch sweeps in). `git show --stat HEAD` before pushing.
- Peer names (`username`), absolute library paths and the API key never reach a reason, an event, an API payload or a
  doc (`store.public`, `explain(peers=False)`, `test_approved_event_never_names_the_peer`). New reason strings:
  write `<peer>` literally.
- Don't depend on an slskd shape that isn't captured: the enqueue response, `/users/*`, the order transfers are
  listed in. S1-04 makes the fake sort by id for that reason.
- `tests/conftest.py` sets `CRATES_OWNER=comment` and the legacy policy file; the suite's env (`.harness/check.sh`)
  points every path into scratch and unsets the live credentials. Keep it that way in new tests.
- Several features edit `sourcing/fetch.py`; sessions are sequential, so no conflicts, but read the file fresh each
  session (S1-04 and S1-06 reshape the download loop; S1-R1 simplifies it).
- A new decision that is Michael's: the simplest reversible default, recorded in
  `docs/specs/2026-10-17-amperfy-pivot.md` as `D<n> *default*` at the **end** of the table. D47 is taken on
  `origin/main` (the identity picker); this branch has it since the merge. Another run (`harness/dj-soulsync-review-2026-10-22`)
  is active in parallel: before numbering, `git fetch -q` and check `origin/main` and that branch for the highest D.
- Nothing in this run writes to the live box. No `docker`, no `scripts/live-run.sh`, no `scripts/deploy.sh`, no
  `/srv`, no network; the fixtures are enough. S1-09 verifies commands with `--help` only.

**Docs the milestone touches** (S1-R1 and S1-09): `docs/worker.md` "Approvals" (+ a "Reopen" paragraph),
`docs/architecture.md` §4 and §7, `docs/hard-won-facts.md` (slskd 0.26.1 DELETE semantics; AcoustID same-length
songs), `docs/next-todos.md` State, the spec's S1 header, the pivot spec (one `D<n> *default*` from S1-08),
`docs/plans/2026-10-22-downloads-checklist.md` (new), `docs/plans/2026-10-22-morning-checklist.md` (one line before
section 4).

**Decisions taken by default (Michael: answer in INBOX.md to change any)**
1. **S1-08 reopen also resets placement** (`D<n> *default*`, recorded by S1-08): `wanted reopen --apply` deletes the
   row's `placements` rows so the right file is placed at its Spotify position when it arrives; the wrong song's
   playlist entry is left where it is (no playlist edit; the N1 cleanup or you remove it). Alternative: leave the
   placement `done`, so the right file is never placed automatically.
2. **S1-03's review row is retryable**: approving a "filed <X> as <rel>, asked for <Y>" row is a fresh download
   attempt (S1-01/02 now refuse the wrong song); the wrong file stays in the library as its own song. Alternative:
   require `wanted reopen` first.
3. **S1-07 runs in previews too**: a `Preview` from the web client that finds the song in the library marks the row
   `ok` without a download (`wanted reopen` reverses it). Alternative: only on approval.
4. **S1-06 retries once, on transfer end states and 5xx/connection errors only**: our own `download timed out`, a
   4xx, and every verify finding keep today's one-attempt behaviour.
5. **S1-05 error text**: `slskd <METHOD> <endpoint with <peer>/<id> placeholders>: HTTP <code>` or `: <reason>`.

**Questions that are not decisions**
- PR #16 (the hotfix) is not on `main`; this branch carries its commits, so the S1 PR will show them too. Merge #16
  first (checklist step 1), then the S1 PR.
- `origin/main` was merged into this branch at the start (`307d62b`); if the harness's milestone verify merges
  again it will be a no-op unless `main` moves.

Suite on the merged base `307d62b`: `.harness/check.sh` green, **1757 passed in 649 s** (10:48). No live command was run by the initializer: no docker, nothing read or written under /srv.
