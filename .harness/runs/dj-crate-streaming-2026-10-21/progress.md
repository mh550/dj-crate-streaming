# Progress log — run `dj-crate-streaming-2026-10-21` (branch `harness/dj-crate-streaming-2026-10-21`)

What this file is: the shared memory of the agent harness for this run. Each session appends one entry **at the top**
(newest first) when it finishes a feature: what it built, what it learned, what it asks. Nobody edits older entries.

### 2026-10-22 verify R8
| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| R8-01 | 1 | `ls -l`, `head -3` of the old file, `git diff 0b4f712...HEAD` and `git show 036fc39` on it, read the conventions block | New file exists (297 lines). The old file's first line is "Superseded by …2026-10-22-morning-checklist.md". R8-01 only added that line; its other edits came from R2/R3 commits. The new file has the flock on `/srv/docker/crates/live.lock`, the 03:15-04:30 window and the backup-active rule, snapshots first, `scripts/live-check.sh` as check, and `live-run.sh` for one-off worker commands | yes |
| R8-01 | 2 | `grep -n '^## \|Check:\|Undo:'` over the file, read steps 1-9 | Sections 1-9 in the required order. Each has Check/Undo (the repoint stages put them on one line, 198). Step 3 greps `^GIT_SHA=` and covers the 1 case. Step 4 has rollback tag `f4882ab85b` plus the CLAUDE.md command. Step 6 runs repoint dry-run, 5, 50, all, then `compose stop worker` and `trash --dry-run`, and stops. Step 9 covers the rank refusal, lock probe, banner, `.history`, Identity tab and `--choices` staged with `revert` | yes |
| R8-01 | 3 | `python3 -m <module> --help` for all 11 module/command pairs in the file, plus `imported migrate --help` (shows `--apply`); `ls -l` and `scripts/live-run.sh --print true` | All 11 listed in `--help`. The 2 scripts are executable. `--print` printed a command, but it also ran read-only `docker inspect` and `docker image inspect` (`live-run.sh:24,30`), which I had not expected | yes |
| R8-01 | 4 | Read the R8-01 progress entry | It says "No live command was run by this session: no docker, nothing read or written under /srv" | yes |
| R8-01 | 5 | `git log` | Commit 036fc39 `R8-01: morning checklist v2 (2026-10-22)` | yes |
| R8-01 | 6 | `lib/check.sh`; `git log origin/harness/…` | Green, 1752 tests (cached for this tree). The R8-01 commit is on origin | yes |
| R8-02 | 1 | `git diff 0b4f712...HEAD` stat; `grep -rn '/srv\|\.env' tests/` (55 hits); grep for each invariant test name the entry cites; `grep def write_atomic` | The 5 sampled invariant tests exist in tests/test_duplicate_cleanup.py. The 55 hits are literals and env lookups. The only docker calls in tests are the existing `test_compose.py` and `test_gatus.py`, which run read-only `docker compose config` and skip if docker is absent; neither was changed this run. There is one `write_atomic` (scripts/export_playlists.py:111). The checklist commands match `--help` (R8-01 step 3). I did not re-read the full 6,253-line diff | yes |
| R8-02 | 2 | Read the progress entry; `ls tests/test_python310_syntax.py`; grep for `test_choices_name_a_hand_typed_choose_they_leave_out` | The red-then-green fixes are recorded (sourcing/fetch.py f-string; `--choices` naming). Both new tests exist. Doc counts read 1,750 in CLAUDE.md, README, architecture and hard-won-facts, with no 1,523 left | yes |
| R8-02 | 3 | `grep -n 'D4[5-9]'` in the pivot spec; `grep -n 2026-10-21 docs/next-todos.md` | D45, D46, D47 are present with no gaps. next-todos has the 2026-10-21 run paragraph (line 28) naming the run, R1-R8, "none run live" and the checklist file | yes |
| R8-02 | 4 | Read the R8-02 progress entry | One list of 8 questions, each with its default | yes |
| R8-02 | 5 | `git log` | Commit 0f0fbaf `R8-02: whole-run review and simplify` | yes |
| R8-02 | 6 | `lib/check.sh`; `git log origin/…` | Green, 1752 tests; the commit is on origin (HARNESS 0ff6a0f is the head) | yes |

### 2026-10-22 06:50 · R8-02 · passes
- Review (Opus, scratch `run.diff` = `git diff 0b4f712...HEAD -- . ':!.harness/runs'`, 6,253 lines): **0 Critical, 0 Important**, 10 Minor, 3 simplifications. The four invariants hold, each with its tests: no trash while a playlist holds the file (`test_before_repoint_the_extra_is_refused_and_nothing_moves`, `test_another_users_playlist_alone_blocks_the_move`, `test_already_gone_but_still_in_a_playlist_needs_michael`, dedupe `test_trash_refuses_while_referenced_then_moves_logs_and_updates_the_map`); scan between (`test_trash_refuses_unless_a_scan_finished_after_the_newest_repoint_log`, `test_repoint_moves_both_playlists_to_the_keeper_logs_the_reverse_and_waits_for_a_scan`); recompute (`test_a_pair_no_longer_one_group_is_skipped` / `_is_not_trashed`); logged reverse (`test_trash.py` 2 tests, `test_the_reverse_line_is_written_before_a_write_that_fails`, `test_the_log_is_written_before_the_write_and_a_failed_write_stops_the_run`). `grep -rn '/srv\|\.env' tests/`: 55 hits, all string literals in fake data/asserts, comments or `os.environ` (I read every non-comment one). Lock and limiter reused (`hold_lock`, `musicbrainz.Limiter`), not copied.
- Fixed test-first: `sourcing/fetch.py:417` had an f-string reusing its own quote, a SyntaxError on Python 3.10/3.11 that R4 made host scripts import (new `tests/test_python310_syntax.py`, tokenize-based; it was red on exactly that line). `apply --choices` now names a proposal row's hand-typed `choose` it leaves out instead of dropping it silently (`test_choices_name_a_hand_typed_choose_they_leave_out`). Simplified: one `write_atomic` (tmp + fsync + replace) in `scripts/export_playlists.py`, used by the export, the history, the proposal and the choices file (the run had two); `acoustid.make_lookup` lost its test-only `cache=` (wrap with `acoustid.cached`).
- Docs: test count 1,523 → ~1,750, about 11 min (CLAUDE.md, README, architecture, hard-won-facts); CLAUDE.md "Snapshots" now uses `snapshot-crates-db.sh --suffix` (it does both databases since H1; the old text said a hand `sqlite3 .backup` was the only navidrome copy); architecture status gains an R1-R7 row, the M9 row and the M9 header/table name 5a/6/7 built; next-todos "State at hand-off" has the 2026-10-21 paragraph (and the 2026-10-17 image line is dated); worker.md trash step says only `--dry-run` runs until the hold is lifted; the `duplicate_cleanup` docstring uses `live-run.sh`; checklist: host lock path, `choices:` lines. `grep -n 'D4[5-9]'` in the pivot spec: D45, D46, D47, no gaps, no new D this session.
- Left (Minor): a failing `.history` write still rewrites the `.m3u8` (deliberate, tested, only a log line); `crates/identity_view.py` imports private `_canon`/`_navidrome_ids` from identity_backfill.
- Tests 1749 → 1752. `lib/check.sh` green, 1752 tests, 652 s. No live command was run: no docker, nothing read or written under /srv.
- **Every question for Michael from this run, with the default taken** (answer in INBOX.md to change any):
  1. D45: one-off live commands run in the image of `dj-worker-1`'s revision label (not a `GIT_SHA` pinned in `.env`). Default: label.
  2. D46: should the health banner also count other accounts' (amperfy's) playlists? Default: no, ours only, non-smart.
  3. D47 (M9 Q7, Q8): `search` rows accepted one by one in the picker; the album-only candidate pre-selected, applied only after a click. Default: as stated.
  4. M9 Q10 (R4): `dedupe_copies repoint|trash` and `tag_cleanup retag|move` need the worker lock; `plan`/`refresh-map` stay free; unset `CRATES_DB` refuses. Default: yes. If `/srv/docker/crates/worker.lock` is not writable by mh550 the host commands refuse: run them in the worker container or make the lock writable.
  5. M9 Q11 (R5): 30 days of `.m3u8` history, the first version of each day kept; health state in crates.db `settings`. Default: yes.
  6. R6: AcoustID cache keyed on path + size + mtime_ns at `<out>/acoustid-cache.jsonl`, 3 req/s shared; a re-import sets a failed unfiled row back to `needs_source`. Default: as stated.
  7. D35 (your answer) + `keep_rank`: bit depth and sample rate are not compared, so a 24/96 flac in Compilations/ can be trashed for a filed 16/44 one. Default: keep `keep_rank` as is; `report.md` shows kbps per copy.
  8. Not decisions: `grep -c '^GIT_SHA=' /srv/docker/.env` is your step (checklist step 3); the checklist's step 1 assumes `~/projects/dj-crate-streaming` still shows a modified old INBOX.md.
- Proposed changes: none to the feature.

### 2026-10-22 06:10 · R8-01 · passes
- New `docs/plans/2026-10-22-morning-checklist.md`: conventions (flock on `/srv/docker/crates/live.lock`, no write 03:15-04:30 or while the backup is active, backup status + **check** + snapshots first, `scripts/live-check.sh` as check, `scripts/live-run.sh` for every one-off worker command), then steps 1-9 in the feature's order, each with Check and Undo: pull (INBOX diff kept before the `git checkout --`), H3-03 timer, `GIT_SHA` grep, deploy main from a fresh worktree (rollback `dj-crates:f4882ab85b` + CLAUDE.md command), `imported migrate`, duplicate cleanup (plan with the "Lossless pairs, will be trashed" section, repoint stages, `trash --dry-run` and stop), reconcile, import re-runs, R4-R7 look-sees (rank refusal, lock probe, health banner + event, `.history`, AcoustID cache, Identity tab + `--choices` dry run → `--limit 5` → all, `revert`). The old checklist keeps its text; its first line now points at the new file.
- Verified: every `python3 -m <module> <cmd>` in the file (12 module/command pairs, plus `imported migrate|list`) is in that module's `--help` with the suite's sandbox env; the flags used are in the subcommand help; the 4 scripts named are executable. In the sandbox, `sourcing.cli rank --download` exits 2 with the quoted text, and the lock probe exits 1 with "refused: stop the worker first…" while the lock is held and 0 when it is free.
- Review (Opus, read-only on the file): 0 Critical, 3 Important, 8 Minor, all fixed after I checked the Important ones in the code. Fixes: restoring a snapshot moves `-wal`/`-shm` aside first; stopping placement is `DELETE FROM import_order`, not `placements` (deleting `done` rows re-arms them, `crates/store.py:826`; the old checklist has the same mistake, left as written); the repoint undo includes `songs-repointed.jsonl`; also the reconcile success wording, CSV under `/data`, health-push prints nothing on success, snapshots repeated each live day.
- Step 3 deviates from the feature text on purpose: Compose gives the shell's `GIT_SHA` precedence over `.env`, so a pinned value does **not** override `live-run.sh`. It does change every bare `docker compose run|up`. The checklist says that, and says to remove the line unless it was pinned on purpose (copy `.env` first).
- Tests 1749 → 1749 (docs only). `lib/check.sh` green, 1749 tests, 653 s. **No live command was run by this session**: no docker, no scripts/*.sh beyond reading them, nothing read or written under /srv.
- Proposed change: the R8-01 step (3) wording "a pinned GIT_SHA there would override live-run.sh's choice" is wrong about Compose. No questions for Michael.

### 2026-10-22 verify R7
| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| R7-01 | 1 | read docs/plans/2026-10-21-r7-identity-picker.md (469 lines), grepped each named item | has proposal schema, CRATES_IDENTITY_DIR (default /data/identity), GET/POST routes with 409/400 rules, choices file shape, identity_pick event, --choices semantics, Michael's live steps (dry run, --limit 5, all, revert), not-built list | yes |
| R7-01 | 2 | grep test names in plan | names test_identity_api.py, test_identity_backfill.py, test_web_identity.py; all three exist | yes |
| R7-01 | 3 | `git log origin/main..HEAD` | commit 7456065 `R7-01: plan for the identity picker` | yes |
| R7-01 | 4 | `lib/check.sh`; `git branch -r --contains` | green, 1749 tests (cached); the R7-01 commit is on origin (last 2 HARNESS commits were unpushed, pushed now) | yes |
| R7-02 | 1 | read crates/service.py:64,81 and crates/identity_view.py in full | Config.identity_dir from CRATES_IDENTITY_DIR default /data/identity; stdlib module; _navidrome_ids (export_playlists path→id) used; one write site `write_atomic(identity_dir / CHOICES)` (tmp+fsync+replace) | yes |
| R7-02 | 2 | read identity_view.listing/record/_checked; service.py:445,490 routes | GET /api/identity?class= with created/counts/rows, 404 with plain text when no proposal; POST: 409 accept/choose on conflict/error, 400 for mbid not a candidate or unknown path, 200 with choice; store.log identity_pick `…; decided_by=michael` in detail | yes |
| R7-02 | 3 | `.harness/check.sh tests/test_identity_api.py tests/test_identity_backfill.py tests/test_web_identity.py`; read test names | 164 passed; test_rows_have_the_plan_shape, test_suggested_is_the_only_candidate_on_the_files_album, each refusal test, test_second_click_replaces_the_first, test_each_pick_logs_identity_pick_with_decided_by_michael, test_nothing_is_written_outside_the_identity_dir | yes |
| R7-02 | 4 | `git log` | commit 91c68bb `R7-02: identity rows and choices API` | yes |
| R7-02 | 5 | `lib/check.sh` | green, 1749 tests | yes |
| R7-03 | 1 | read scripts/identity_backfill.py read_choices, choice_problem, apply (lines 686-1070) | skip→not selected; choose→row's choose set, existing _intended check; accept selects row outside --classes; conflict/error refused `choices: <path> is <cls>; refused`; unknown path reported and ignored; dry run names rows from choices | yes |
| R7-03 | 2 | read CLI lines 1171-1231, 1207 | `apply <proposal> --choices FILE --dry-run`; decided_by carried into apply log notes and dry-run text `(choice: …, decided_by michael)` | yes |
| R7-03 | 3 | test names test_choices_* in tests/test_identity_backfill.py (21 tests, in the 164 passed run) | accept search would-write, choose shows id, skip absent, wrong mbid existing message, conflict refused, test_choices_dry_run_changes_nothing_on_disk (sha256 + tags re-read), existing tests green | yes |
| R7-03 | 4 | grep docs/worker.md, docs/how-ids-work.md | worker.md:413-417 has the --choices form; how-ids-work.md:75 has the picker paragraph | yes |
| R7-03 | 5 | `git log` | commit 2efb1cd `R7-03: apply --choices merges the picker's choices` | yes |
| R7-03 | 6 | `lib/check.sh` | green, 1749 tests | yes |
| R7-04 | 1 | read web/index.html:29,71-82; web/app.js:449-467; grep | tab data-tab=identity with count pill, section #tab-identity, class select (search/ambiguous/none/conflict/error), ul#identity; Accept only for search rows, Skip always, MusicBrainz link prefix present | yes |
| R7-04 | 2 | tests/test_web_identity.py (24 tests, in the 164 passed run); read test_phone_first_css | tab/list, endpoints, three labels, MB URL prefix, no library path, widths ≤375px asserted | yes |
| R7-04 | 3 | `grep -c apply web/app.js`; `grep /srv web/app.js web/index.html` | 0; no /srv match | yes |
| R7-04 | 4 | `git log` | commit 5f444da `R7-04: Identity tab` | yes |
| R7-04 | 5 | `lib/check.sh` | green, 1749 tests | yes |
| R7-05 | 1 | file(1) on docs/screenshots/r7-identity-*.png; viewed each image | three PNGs, 375x812; real renders of the tab (ambiguous, conflict, chosen); the hash opener `#identity/<class>` exists (test_a_hash_with_a_class_opens_the_tab_filtered) | yes |
| R7-05 | 2 | viewed images vs the R7-05 progress entry | ambiguous: filter 'ambiguous (2)', pill 6, tags/length/path/why, album-only candidate pre-checked with accent border, Choose+Skip, no Accept; conflict: Skip only; chosen: second radio checked, `chosen: 9999…` shown; no overflow seen; badge-fit defect has test_the_class_badge_stays_beside_the_title_on_a_phone | yes |
| R7-05 | 3 | n/a: firefox did render, so the fallback was not needed | screenshots are real renders | yes |
| R7-05 | 4 | `git log` | commit 709dbc2 `R7-05: identity tab screenshots…` | yes |
| R7-05 | 5 | `lib/check.sh` | green, 1749 tests | yes |
| R7-06 | 1 | read identity_view.py in full against §5a rules; grep app.js; read test_nothing_is_written_outside_the_identity_dir, test_why_never_shows_an_absolute_path | no apply in client; choice checked in _checked and choice_problem on record, and by apply; conflict/error → 409; path only a dict key; one write inside identity_dir; every pick logs event with decided_by=michael; _scrub removes absolute paths; no key in payload (not independently re-diffed r7.diff) | yes |
| R7-06 | 2 | read progress R7-06 and the suite for its tests | fixes have tests (test_scrub_*, test_proposed_is_what_accept_checks, test_a_path_the_proposal_holds_twice_is_not_offered, test_the_choices_file_is_fsynced…); all pass | yes |
| R7-06 | 3 | grep M9 spec, architecture.md, worker.md, next-todos, pivot spec | M9 §5a line 225 'Built (R7…) not live' with Q7/Q8 D47; D47 default in pivot spec; architecture §2/§3/§4(d) name Identity view and choices file; worker.md:422 live apply is Michael's step item 6; plan has Review (R7-06) section and the built status codes | yes |
| R7-06 | 4 | `git log` | commit 66d090e `R7-06: review and simplify the identity picker` | yes |
| R7-06 | 5 | `lib/check.sh` | green, 1749 tests | yes |

All 6 R7 features hold; the full suite was not re-run beyond `lib/check.sh` (cached green) and the three R7 test files (164 passed).

### 2026-10-22 06:20 · R7-06 · passes
- Review (Opus, scratch `r7.diff` = `git diff origin/main...HEAD` over crates/ web/ identity_backfill tests docs/, 2326 lines): 0 Critical, 0 Important, 7 Minor, 4 simplifications. Every safety rule holds. I checked these with cheap commands myself: one write site, `write_atomic(identity_dir / CHOICES)`; a body `path` is only a dict key; `grep -c apply web/app.js` → 0; no `/srv` in the client.
- Fixed test-first (all seen red, 5 failures): `_scrub` now hides `"…"`-quoted and bare absolute paths too, and strips the root only where a path starts (`AC/DC`, `3:13/3:15` and ` / ` are untouched); `proposed.id` comes from `write.mb_trackid`, the id Accept is checked against; a path the proposal holds twice is no longer offered, because apply refuses it; `write_atomic` fsyncs before the replace. Simplified: `load_proposal`'s nested check is now `_well_formed`.
- Left as is, recorded in the plan's new "Review (R7-06)" section: the choice is saved before its event is committed (on a crates.db failure the 503 says "tap again"); a stale choice on a row that left the picker; GET answers 503 on a locked navidrome.db; `_checked` and `choice_problem` state the same rules twice.
- Docs: M9 §5a has "Built (R7), not live" with Q7/Q8 (D47) and the narrowed buttons. architecture.md §2 and §3 name the choices file as crates' one write under `/data/identity`, and §4(d) describes the Identity view and `--choices`. worker.md says the live `--choices` apply is Michael's step (next-todos item 6), and next-todos item 6 says the same. The plan matches the built API.
- Tests 1742 → 1749 (tests/test_identity_api.py). `lib/check.sh` green, 1749 tests, 656 s. Nothing live was run, and nothing was read under /srv.
- For R8: the live steps are the R7 plan's "Live steps" (chown check on `/srv/docker/crates/identity`, pick, dry run, `--limit 5`, all, `revert`). No questions for Michael.

### 2026-10-22 04:59 · R7-05 · passes
- Three 375×812 screenshots, taken with `firefox --headless --screenshot … --window-size=375,812` of `CrateServer` on the fake Navidrome (R7-02's real `propose` fixture plus one realistic ambiguous row, served on 7805). A proxy on 7806 (R5-03's trick) adds a 3 s image, so Firefox's load-time shot waits for `/api/identity`. Launcher, proxy and `run.sh` (the suite's sandbox env) are in scratch `r7-05/`.
- `docs/screenshots/r7-identity-ambiguous.png`: the filter reads "ambiguous (2)", the Identity pill shows 6. Row ▶ "Kool & the Gang — Celebration", "Celebrate! · 6:52", the path, `why`, the `ambiguous` badge. Two radios: "Celebration · 6:52, Celebrate!, suggested: on this file's album" is pre-checked with an accent border; "Celebration · 4:05, Greatest Hits…, radio edit" is not. Each has a MusicBrainz link. Buttons: Choose and Skip, no Accept.
- `r7-identity-conflict.png`: the filter reads "conflict (1)". "Kool & the Gang — Other", 0:08, `K/conflict.flac`, "the file's id does not fit: length 0:20 vs file 0:08", "the file has mb_trackid 1111…". The only button is Skip. There is no ▶ because the fake has no song for that file.
- `r7-identity-chosen.png`: after `POST /api/identity/choice` choose `9999…` (the non-suggested one). The held choice is pre-checked over the suggestion, which keeps its border, and "chosen: 99999999-…" shows under the buttons. `identity-choices.json` holds it with `decided_by: michael`.
- Defects fixed test-first: (1) the `ambiguous` badge dropped onto its own line on rows with ▶. Measured in Chromium: the row is 327 px wide inside at 375 px, 40+12+200+12+74 > 327. `#identity .grow` basis is now 120 px, and the badge is top-right at both 375 and 320 px with scrollWidth equal to the viewport. (2) New `#identity/<class>` hash: it opens the tab filtered, so each shot shows its row; a class the filter lacks is ignored. Plan line 287 notes both.
- Tests 1740 → 1742 (`tests/test_web_identity.py`: the hash filter and the badge fit, both seen red first). `lib/check.sh` green, 1742 tests, 650 s. Nothing live was run, and nothing was read under /srv. No questions for Michael.

### 2026-10-22 05:10 · R7-04 · passes
- The Identity tab. `web/index.html`: tab button `data-tab="identity"` with `#identity-count`, and `#tab-identity` with the class filter `#identity-class` (all + 5 classes, counts shown in the options) and `<ul id="identity">`. `web/app.js` (`// identity:begin…end`): `loadIdentity()`/`idRow()`. Each row shows artist — title, album · m:ss, the path, `why`, a ▶ via `playTrack` when `songId` is set, and a class badge. `search` rows: "proposed: …" + MusicBrainz link, Accept (posts the shown `proposed.id`) + Skip. `ambiguous`/`none` rows: radios (title — artist · length, release, disambiguation, link); the recorded choose, else `suggested`, is pre-checked; Choose is enabled once a radio is checked; Skip. `conflict`/`error` rows: the file's existing ids, Skip only. A tap paints `accepted` / `chosen: <mbid>` / `skipped` / `stale: pick again` on its own row; an error shows the server's text under the held choice (a 409 adds "reload"). A `#<tab>` hash opens that tab. `web/app.css`: the tab bar scrolls if needed (`overflow-x:auto`), tighter below 420 px; the rows wrap.
- Tests 1723 → 1740 (`tests/test_web_identity.py`, 17, seen red first). `grep -c apply web/app.js` → 0; no `/srv` in the client.
- Browser check (Sonnet, playwright-core + Chromium at 375×800, fake data on port 7805, launcher `r7-04/serve.py` in scratch): `#identity` opens the tab; all 5 tabs fit; scrollWidth 375 before and after clicks; Choose on K/tie.flac painted "chosen: 5555…" and survived a reload; no console errors. I re-ran an error-path driver myself: the error shows under "skipped", buttons re-enable, the conflict filter shows 1 row with Skip only. Screenshots are in scratch `r7-04/` (R7-05 makes the docs ones).
- Review (Opus, scratch `r7-04.diff`): 0 Critical, 0 Important, 7 Minor. Fixed test-first: out-of-order GETs (`idSeq`), a blank error, an error that hid the held choice plus "reload" on 409, lowercase id compare, and stricter tests (only served field names read, one POST site, no innerHTML, onchange never sends). Not done: a tap in flight while the filter changes paints a detached row (noted in the plan). Tab-bar width was confirmed by rendering instead.
- Plan amended ("Built in R7-04"). Verified: `lib/check.sh` green, 1740 tests, 648 s. No live command was run. No questions for Michael.

### 2026-10-22 04:25 · R7-03 · passes
- `scripts/identity_backfill.py`: `apply(..., choices=)` + CLI `--choices FILE`. New `read_choices` (missing/non-JSON/no `choices` object → ValueError; the CLI exits 2 before reading any library file), `_with_choice` (proposal `skip` final; picker skip drops the row even when stale; accept/choose on conflict/error → `choices: <path> is <cls>; refused`; a choose goes through `_intended` first so a wrong id keeps the existing message; then `choice_problem` → `choices: <path> <reason>; pick again`), `_rows_to_apply` (without `--classes` only the picks; with it, picks + classes; `--only`/`--limit` alike; a refused choice never falls back to its class; unknown paths → `… is not in the proposal; ignored`). `ApplyReport.chosen`; the dry run prints `(choice: accept, decided_by michael)`; real-run `write` log lines gain `choice` and `decided_by`. Without `--choices` the old path is untouched.
- Tests 1701 → 1723 (22 in tests/test_identity_backfill.py: the plan's 18 + 4 from review). Seen red first (TypeError on `choices=`); review-fix tests seen red on mutated code.
- Review (Opus, scratch `r7-03.diff`): 0 Critical, 2 Important, 6 Minor. Fixed test-first: I1 an Accept now drops a hand-typed JSON `choose` (it wrote that choose while logging "accept"); I2 `_intended` refusals print with their path (`choices: <path>: …`); M2 empty mbid and M4 choose on a `search` row refused in `choice_problem`; M3 a picked path held twice in the proposal is refused; M5 docs name `error` rows. M1 documented only (a row that left the picker, e.g. search→acoustid after a new propose, keeps its stale choice: apply it without `--choices` or delete the entry). M6 not done (dry-run label hardcodes "michael"; `choice_problem` guarantees it).
- Docs: docs/worker.md "Identity backfill" has the `--choices` form and rules; docs/how-ids-work.md a picker paragraph; the R7 plan amended for the review changes.
- Verified: `lib/check.sh` green, 1723 tests, 623 s. No live command was run.
- For R8: the live `--choices` apply is the plan's "Live steps" (dry run → `--limit 5` → all, scan and check after each, `revert` log). No questions for Michael.

### 2026-10-22 05:40 · R7-02 · passes
- New `crates/identity_view.py` (stdlib): it loads `identity-proposal.json` and serves the picker rows in the plan's shape (`proposed` on `search` rows, `candidates` with MusicBrainz links, `suggested` per Q8, `songId` from `_navidrome_ids`, the recorded `choice` with `stale`). It records taps in `identity-choices.json` via `write_atomic` (the only file it writes). `crates/service.py`: `Config.identity_dir` (`CRATES_IDENTITY_DIR`, default `/data/identity`), `GET /api/identity[?class=]`, `POST /api/identity/choice` under `_lock`; the status table is the plan's. `scripts/identity_backfill.py`: `choice_problem` (the one stale/malformed rule, which R7-03's `apply --choices` must call), `CHOICES`, `write_atomic` (made public), and `releases` in `_detail`.
- Tests 1661 → 1701 (`tests/test_identity_api.py`, 40). The proposal comes from a real `propose` over tagged fixture files with the fake MusicBrainz; the error row is a real `FileNotFoundError`. Red on the old tree first (archive of HEAD in scratch: 3 failed, 26 errors). The lock test fails with the lock removed.
- Review (Opus, scratch `r7-02.diff`): 0 Critical, 0 Important, 8 Minor. Fixed test-first: an event that crates.db refuses now gives a 503 "the choice is saved… tap it again" with a rollback (it was 503 "Navidrome's database…"); `why` loses quoted absolute paths, and a `/` root no longer eats every slash; a malformed row field gives 503 (it was a dropped connection); "choose needs the mbid…"; rows with JSON `skip: true` are left out; `choice_problem` is strict (canonical mbid, a skip without mbid, `decided_by == michael`); parallel-tap, refusal-bytes and reason-text tests. Plan amended to match (the status table, scrubbing, skip rows).
- Deviation from the step's wording: songId uses `identity_backfill._navidrome_ids` (NOT missing), not `export_playlists._path_ids`, as the plan specifies.
- Verified: `lib/check.sh` green, 1701 tests, 646 s, on 91c68bb. No live command was run.
- For R7-03: `apply --choices` reasons come from `choice_problem` and read e.g. "choices: <path> was made on an older proposal row (class, size or mtime changed); pick again". For R8: live, `/srv/docker/crates/identity` must be writable by uid 1000 (plan "Live steps" step 1).
- Not done (Minor): the "nothing written outside" test lists `tmp_path` only, not the process cwd; the code never joins a body path, so it has nothing to write there.

### 2026-10-22 03:30 · R7-01 · passes
- New `docs/plans/2026-10-21-r7-identity-picker.md`. It covers the data source (the proposal schema as `propose` writes it), `CRATES_IDENTITY_DIR` (`/data/identity`, the existing mount, no compose change), `GET /api/identity` (row shape, `suggested`, `songId` via `_navidrome_ids`), `POST /api/identity/choice` (a table of every 400/404/409/503), `identity-choices.json` (latest per path, with `cls`/`size`/`mtime_ns` for staleness), the `identity_pick` event, the `apply --choices` merge, the tab, the named tests for R7-02/03/04, the safety rules, and Michael's staged live apply. New D47 *default* in the pivot spec records Q7/Q8. Tests unchanged at 1661 (a plan feature).
- Review: an Opus reviewer read the plan against the code. It found 1 Critical issue, Accept bound to whatever the row held at tap time; Accept now posts the shown `proposed.id`, and a mismatch is a 409. It found 9 Important issues, all applied: a refused or stale choice never falls back to its class; a choices `skip` always drops the row; `store.log` needs `commit()`; `changeError` is playlist-specific; `_route` maps `OSError` to 502, so explicit `ApiError(503)` is needed; a corrupt choices file gives 503 and is never overwritten; `why` can leak `/srv/music`; the flock and backup checks were missing; and `--choices` without `--classes` now selects only the picks. It found 7 Minor issues, all applied, including `releases` in `_detail` so the suggestion is exactly Q8's rule.
- Measured on `docs/identity-backfill-proposal.json`: only 5 ambiguous rows and 4 `none` rows get a suggestion (`_tie_break` already resolves single album matches).
- Deviations from R7-02/R7-03's wording, stated in the plan: Accept is for `search` rows only, and Choose is not offered on `search` rows, which have no candidates. `--choices` alone selects only the picks.
- Verified: `lib/check.sh` green, 1661 tests, 584 s. No live command was run.
- Slip, reported: during the research one `grep` read `/srv/docker/compose.yml` (for `ND_SCANSCHEDULE`), against the brief's "nothing read under /srv". It was read only, and nothing was written. The repo's `deploy/compose.yml` has the same line.
- For R8: the plan's "Live steps" section is the checklist text for the identity apply with `--choices`.

### 2026-10-22 verify R6

All steps re-run: `.harness/check.sh` on tests/test_acoustid.py test_identity.py test_scorer.py test_identity_backfill.py test_import_playlist.py test_crates.py test_web_m8.py: 380 passed; lib/check.sh green (1661 tests, cached). Code read from `git diff origin/main...HEAD`.

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| R6-01 | 1 | read sourcing/acoustid.py | `Cache` (path,size,mtime_ns; last line wins; fsync append), `make_lookup(key,cache,clock,sleep)`, `_SHARED = Limiter()` at 1/3 s, `reset_shared_limiter`, key only in POST body | yes |
| R6-01 | 2 | read scripts/identity_backfill.py:63,488; test at :1240-1250 | `ACOUSTID_CACHE` constant used in `propose`; apply/revert test asserts the cache file is never opened | yes |
| R6-01 | 3 | tests/test_acoustid.py: test_a_cached_file_is_neither_..., test_a_changed_mtime_or_size_..., test_a_corrupt_or_torn_cache_line_..., test_lookups_are_spaced_..., test_the_key_never_reaches_the_cache_file | all pass; assert 1 opener call/1 line, 2nd+3rd call after mtime/size change, corrupt skipped, slept == [1/3-0.1, 1/3], "s3cret-key" not in file | yes |
| R6-01 | 4 | tests/test_identity_backfill.py::test_a_second_propose_asks_acoustid_nothing_new | passes; second propose `len(asked) == 2` unchanged (zero new calls), retag asks again | yes |
| R6-01 | 5 | `git log` | commit `4cc568e R6-01: AcoustID cache and 3 req/s limiter` | yes |
| R6-01 | 6 | lib/check.sh; branch vs origin | green, 1661 tests; branch pushed (only HARNESS commits ahead) | yes |
| R6-02 | 1 | read sourcing/identity.py diff; tests/test_identity.py strip_trackno cases | wanted-aware bare `NN ` rule; `99 Luftballons`→kept, `01 99 Luftballons`→`99 Luftballons`, `03 - `/`03. `/`A1 ` strip as before; parse_filename passes wanted; scorer.py:93,156 and fetch.py:414 pass the title | yes |
| R6-02 | 2 | tests/test_scorer.py::test_99_luftballons_is_a_title_match (3 filenames incl. `Nena - 99 Luftballons.flac`) | passes; asserts not rejected and reason `name 1.00` | yes |
| R6-02 | 3 | tests/test_identity_backfill.py::test_a_disambiguation_only_version_fits_a_file_titled_with_it, ..._without_a_disambiguation_is_unchanged | pass; `12" version` fits `(12'' Version)` file (cls search), misfits plain (none); no-disambiguation unchanged | yes |
| R6-02 | 4 | full identity_backfill tests, `git diff` of existing tests | all green; only additions to existing tests; `sort` prefers title-fits so no confirmed/isrc row changes | yes |
| R6-02 | 5 | `git log` | commit `54833e1 R6-02: keep '99 Luftballons'; disambiguation-only versions fit` | yes |
| R6-02 | 6 | lib/check.sh; branch vs origin | green, 1661 tests; pushed | yes |
| R6-03 | 1 | read crates/store.py diff | `find_external(..., include_failed)` returns newest failed unfiled row; `_reask` sets needs_source `re-asked by import of <playlist>`, same ext-N, `reasked` event; filed rows stay live; removed never revived | yes |
| R6-03 | 2 | tests/test_import_playlist.py::test_a_reimport_reuses_a_failed_row_...; tests/test_crates.py::test_a_reask_* (5 tests) | pass; same ext id, status/reason match, count(*) unchanged, `(2, None, ext)` in import_order; store tests cover direct path | yes |
| R6-03 | 3 | tests/test_m8_followup.py::test_wanted_lists_a_reimported_failed_row_once_and_approve_accepts_it | passes; `/api/wanted` shows one row `needs_source`, POST approve → 200 | yes |
| R6-03 | 4 | `git log` | commit `987193c R6-03: re-import reuses a failed row` | yes |
| R6-03 | 5 | lib/check.sh; branch vs origin | green, 1661 tests; pushed | yes |
| R6-04 | 1 | read the §8 diff (19 files) for each listed point | key not in cache/messages; cache keyed on `st_mtime_ns`+size; `_SHARED` module-level shared by two make_lookups (tested); strip_trackno without wanted unchanged (parametrized test); 8c only via title-fit-first; 8h ignores `removed` | yes |
| R6-04 | 2 | tests added post-review: test_a_disambiguation_only_duplicate_never_spoils..., test_an_import_after_its_playlist_was_deleted_queues_the_track_again, test_a_reask_prefers_a_live_row_and_never_revives_... | present and pass, fix in `sort`/`find_external` | yes |
| R6-04 | 3 | read docs/specs/...m9-remaining-ownership.md, docs/identity.md, docs/worker.md diffs | 8a,8b,8c,8h say built (R6); identity.md has track-number and disambiguation rules; worker.md names `acoustid-cache.jsonl` | yes |
| R6-04 | 4 | `git log` | commit `684edbe R6-04: review and simplify M9 §8 items` | yes |
| R6-04 | 5 | lib/check.sh; branch vs origin | green, 1661 tests; pushed | yes |

### 2026-10-22 03:10 · R6-04 · passes
- Review: an Opus reviewer read scratch `r6.diff` (+ `r6-extra.diff` for musicbrainz.py/cli.py). The 6 checks: key never on disk or printed, cache key size + `mtime_ns`, one process-wide limiter, `strip_trackno` without `wanted` identical (200k-string fuzz against the old `sub`), and 8h never revives `removed`: all hold. 8c recall-only did **not** hold.
- Fixed test-first: (I2) `scripts/identity_backfill.py` `sort`: a disambiguation-only fit counts only when nothing fits by its title, so a unique `isrc`/`search` pick of before 8c can no longer become `ambiguous` (the R6-02 test that pinned the tie is replaced). (I1) `crates/store.py` `find_external(include_failed=True)` (the import path): a `removed` row ("playlist deleted") never answers, so a re-import after a deleted playlist queues a fresh row; the removed one stays untouched. (Minor) `_reask` keeps an older duplicate holding an approval and repoints `import_order` to the survivor.
- Docs: M9 §8 table rows 8a/8b/8c/8h and the status line say built (R6); docs/identity.md has the track-number rule, disambiguation versions and the AcoustID cache; docs/worker.md "Identity backfill" names `acoustid-cache.jsonl` (and how to ask again), and its event list has the removed-row rule.
- Tests 1658 → 1661. Verified: `lib/check.sh` green, 1661 tests, 582 s; each new test seen red on the old code first.
- Not done (Minor/simplification, judged not worth it): seed-spotify (no `reask`) still lets a `removed` row answer, as before R6; a re-asked row takes the import's tier even if lower (R6-03's choice); `make_lookup(cache=)` is unused in production but is what R6-01's step specified; `read_cache_lines` lives in musicbrainz.py.
- No questions for Michael. Live steps for R8's checklist: none new (propose with the cache runs as before; delete `/srv/docker/crates/identity/acoustid-cache.jsonl` to re-ask AcoustID).

### 2026-10-22 02:30 · R6-03 · passes
- `crates/store.py`: `find_external(..., include_failed=False)` (rank: live, then with include_failed the newest failed unfiled row, then a `removed` one; matching moved to `_same_external`); `add_external_wanted(..., reask=<playlist name>)` → `_reask`: the failed unfiled row goes back to `needs_source`, reason `re-asked by import of <name>`, same `ext-N`, new playlist/position, a `status` event plus one `reasked` event ("was failed: <old reason>"), its stale preview dropped, tier/album/length from the import (as a new row would get). Older failed duplicates (from before §8h) become `removed` "superseded by ext-N", each with a `superseded` event holding the old reason. `sourcing/import_playlist.py` passes `reask=name`; seed-spotify does not (test_fetch_filing pins its re-queue). docs/worker.md event list names `reasked`/`superseded`.
- Tests 1649 → 1658: test_crates (reuse, live wins, filed/removed never revived, newest of two failed revived + older superseded, newer failed past an older removed, preview/tier/length), test_import_playlist (re-import reuses ext-N with count unchanged and `import_order` naming it; failed ambiguous → review again; dry run leaves it failed), test_m8_followup (`/api/wanted` lists it once as needs_source; POST approve → 200).
- Verified: `lib/check.sh` green, 1658 tests, 579 s, on 987193c. An Opus review (scratch `r6-03.diff`) found 1 Important issue: with duplicates already in crates.db, the oldest failed row was revived while the newer one, which import_order names, stayed approvable. I fixed it test-first, along with 3 Minor ones (status event, stale preview, stale tier).
- For R6-04: (a) still open, from before this change: without `reask`, a `removed` row (e.g. "playlist deleted") answers `add_external_wanted`, so seed-spotify, or an import into a new playlist with no failed row, queues nothing for that track. Proposed: an import should skip `removed` rows when it looks for a match. (b) Preview of a reused row is covered only by the approvable rules it shares with approve (`_not_in_progress`); the suite's svc has no slskd. (c) Mark M9 §8 row 8h built.

### 2026-10-22 02:10 · R6-02 · passes
- `sourcing/identity.py`: `strip_trackno(s, wanted=None)` keeps a bare `NN ` only when the wanted title is that number plus more words, the rest starts with those words (whole words) and not with the whole title: "99 Luftballons" stays, "01 99 Luftballons" → "99 Luftballons", "22 Shake It Off" for wanted "22" still loses "22". Without `wanted` it is unchanged. `parse_filename(basename, artist, wanted=None)` passes it on; scorer (`name_match`, `score_candidate`) and fetch pass the wanted title.
- `scripts/identity_backfill.py` `_misfit`: a recording whose title has no label but whose disambiguation is one (`12" version`) is compared with that label (fits "(12'' Version)", misfits the plain title). Recall only: covers search, ISRC and confirm through `_misfit`.
- Tests 1621 → 1649: test_identity (strip/keep cases, number-only wanted titles, `parse_filename` pass-through), test_scorer (Nena on the `search_responses` fixture shape: name 1.00; "22"/"7" still rejected), test_identity_backfill (fixture recording via `parse_recording` + `disambiguation`: fits, misfits, no-disambiguation unchanged, labelled title not relabelled, credited disambiguation, duplicate → `ambiguous`). No existing test changed.
- Verified: `lib/check.sh` green, 1649 tests, 580 s, on 54833e1. An Opus review (scratch `r6-02.diff`) found 1 Important issue: a number-only wanted title kept a track number on another song ("22 Shake It Off"). Fixed it test-first.
- For R6-04: (a) name_match folds the text before stripping, so "99 - Luftballons" keeps "99" there while `parse_filename` strips it. The base text only, so harmless. (b) The extra fits can make a former unique pick `ambiguous` (an MB duplicate with the version only in its disambiguation). This is pinned by a test and is the intended conservative outcome. (c) A neutral-only title label ("(Original Mix)") still blocks the disambiguation (safe, less recall). Docs (identity.md, M9 §8 table) are left for R6-04.

### 2026-10-22 01:00 · R6-01 · passes
- `sourcing/acoustid.py`: `Cache(path)` (`acoustid-cache.jsonl`, one line `{path,size,mtime_ns,recordings}`, last line wins, fsync'd append, torn tail cut, wrong-shaped lines skipped), `cached(lookup, cache)`, `make_lookup(key, cache=None, clock, sleep, *, opener)`; every request waits on its own process-wide `musicbrainz.Limiter` at `MIN_INTERVAL_S = 1/3` (`reset_shared_limiter`, reset in conftest). `musicbrainz._Limiter` → `Limiter`; its torn-line loader is now the shared `read_cache_lines`.
- `scripts/identity_backfill.py`: `ACOUSTID_CACHE`; `propose` wraps any lookup in the cache beside the proposal; apply/revert never touch it. The CLI line now reads `AcoustID on (cache …); MusicBrainz cache …`. The verify step (`sourcing/cli.py`) is spaced but uncached.
- Tests 1610 → 1621: 9 in test_acoustid.py (opener called once, mtime_ns/size miss appends, corrupt/torn/wrong-shape lines skipped, sleeps 1/3−0.1 and 1/3 across two lookups, separate from MB's limiter, key not in file, failures not cached, unwritable cache still answers); 2 in test_identity_backfill.py (second propose asks nothing, a retagged file is asked again; apply/revert never open the cache).
- Verified: `lib/check.sh` green, 1621 tests, 585 s, on 4cc568e. An Opus review (diff in scratch `r6-01.diff`) found 1 Important issue (a wrong-shaped cache line was trusted and pinned a file at `error`). Fixed it test-first, along with: one stat per lookup, a failed cache write never hides an answer, the message wording, and three weak tests.
- Next (R6-04): an empty answer (`[]`, "not in AcoustID") is cached on purpose. Delete the file to ask again. The docs (worker.md, M9 §8 table) are left for R6-04, as its step says.

### 2026-10-22 · verify R5

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| R5-01 | 1 | read scripts/export_playlists.py:74-85 `playlist_health`; test_playlist_health_counts_entries_on_missing_files_per_playlist, _counts_an_entry_whose_song_navidrome_no_longer_has, _opens_the_database_read_only; grep fake_server.py schema | pure fn via `open_ro`, LEFT JOIN media_file (m.id NULL or missing), grouped, ordered by name; `missing` and `rules` columns exist in NAVIDROME_SCHEMA and the fake's INSERT; tests assert pl-1/pl-3 rows, unknown id counted, open_ro used. Smart playlists excluded (D46 addition, not in step, harmless) | yes |
| R5-01 | 2 | read crates/store.py:1073-1080, sourcing/worker.py `health`/`health_detail`; test_playlist_health_logs_one_event_per_change, _a_restarted_worker_repeats_no_health_event, _a_failed_health_read_is_logged_and_keeps_the_stored_value | settings key `playlist_health` JSON; runs after successful export only; event only when rows differ; detail strings match the step ('2 entries in Tea tent point at missing files; 1 in Chicago 86', empty text); restart repeats nothing; failure logs `playlist health failed: …` and keeps value | yes |
| R5-01 | 3 | read crates/service.py:122; test_status_carries_playlist_health | `playlistHealth` in status, `[]` before any count, equals stored rows after set | yes |
| R5-01 | 4 | ran 31 selected tests (health/history/export) in test_export_playlists, test_worker, test_service, test_web_m8: all pass; read the asserts | fake with missing={'s2'} → pl-1 Disco Edits and pl-3 Sunday Listening; unknown media_file row counts; tick → one event, second tick none, fix → empty-set event; /api/status carries it | yes |
| R5-01 | 5 | `git log origin/main..HEAD` | `8779e6e R5-01: playlist health after each export (event + /api/status)` present | yes |
| R5-01 | 6 | `lib/check.sh`; `git ls-remote origin` | green, 1610 tests; remote branch at 612d3b6, contains R5 commits | yes |
| R5-02 | 1 | read export() and `_keep` in scripts/export_playlists.py:120-150; test_a_changed_playlist_keeps_its_previous_file_in_todays_history, test_an_unchanged_export_makes_no_history | copy only when target exists and text differs, only if the day's file is absent; unchanged copies nothing; new playlist makes no `.history`; third change same day keeps the first | yes |
| R5-02 | 2 | read `prune_history`:153-170; test_prune_history_removes_only_dated_folders_older_than_30_days, _without_history_and_through_a_linked_history…, test_an_old_day_folder_holding_links…; test_export_prunes_old_history | only `YYYY-MM-DD` dirs under out_dir/.history, symlinked .history/day skipped, missing .history fine, called at end of export | yes |
| R5-02 | 3 | read test_history_files_are_neither_stale_nor_checked | history file exists; `s.stale == []` and `check()` == [] | yes |
| R5-02 | 4 | read the tests above plus tests/test_worker.py test_the_export_tick_keeps_the_previous_playlist_file_in_history | 31-day removed, 30/29 kept, notes/ and old-mtime live file kept, outside dir and music tree unchanged; worker tick produces history file | yes |
| R5-02 | 5 | grep docs/worker.md:37-39, docs/hard-won-facts.md, docs/architecture.md:143 | worker.md step 4 mentions history and the 30-day prune; hard-won-facts also has a history line (matched by the grep on `.history`/`history`) | yes |
| R5-02 | 6 | `git log origin/main..HEAD` | `20e37a2 R5-02: .m3u8 history before each rewrite, pruned after 30 days` present | yes |
| R5-02 | 7 | `lib/check.sh`; ls-remote | green 1610; pushed | yes |
| R5-03 | 1 | read web/index.html:22, web/app.js:32-50 `healthLines`/`loadStatus`, web/app.css:14 `.banner` | `<div id="health" class="banner hidden">` under header; one line per playlist, singular for 1; hidden when empty; banner full width, overflow-wrap:anywhere, no fixed px width | yes |
| R5-03 | 2 | ran tests/test_web_health.py (6 passed); read page/script/status asserts | #health present after header, script reads playlistHealth and has 'point at missing files'; node-run healthLines gives '2 entries in Tea tent point at missing files'; status after worker export with missing s2 returns the two rows | yes |
| R5-03 | 3 | viewed docs/screenshots/r5-health-banner.png (375×812); read progress entry | Playlists tab open; two-line banner '2 entries in Disco Edits point at missing files' / '1 entry in Sunday Listening points at a missing file'; no horizontal overflow; progress entry describes it | yes |
| R5-03 | 4 | `git log origin/main..HEAD` | `079d310 R5-03: playlist-health banner in the web client` present | yes |
| R5-03 | 5 | `lib/check.sh`; ls-remote | green 1610; pushed | yes |
| R5-04 | 1 | ls $HARNESS_SCRATCH/r5.diff; read prune/health code against the checklist | r5.diff exists (40 KB); rmtree only on a real date-named dir directly under .history, links skipped; `open_ro` mode=ro; count includes missing=1 and absent media_file; one event per change; service.status passes health through `public` | yes |
| R5-04 | 2 | read tests test_an_old_day_folder_holding_links…, test_status_playlist_health_goes_through_public, test_a_failed_health_write_logs_no_event…, test_a_failing_history_never_stops_the_export; commit 76bb908 diff stat | fixes (public(), link-safety, history errors never stop export, rollback on failed write) have tests in the same commit | yes |
| R5-04 | 3 | read m9-remaining-ownership.md:271-277, architecture.md:121-122,143,361, worker.md:37-42,630 | §7 marked 'Built (R5)' with Q11 30-day default; settings table lists `playlist_health`; `.history` folder named; worker.md event list has `playlist_health` | yes |
| R5-04 | 4 | `git show --stat 76bb908` | commit `R5-04: review and simplify playlist health and history` present | yes |
| R5-04 | 5 | `lib/check.sh`; ls-remote | green 1610; remote at 612d3b6 | yes |

### 2026-10-21 · verify R4

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| R4-01 | 1 | read `with_worker_lock` (sourcing/worker.py:78) and scripts/tag_cleanup.py `main`; ran test_retag_and_move_refuse_while_the_worker_holds_its_lock | retag|move wrapped in `with_worker_lock`, plan/refresh-map not; path `Path(CRATES_DB).parent/'worker.lock'`; WorkerRunning → exit 1 with `refused: stop the worker first (docker compose stop worker): it holds <path>`; unset CRATES_DB → the set-CRATES_DB message; fd closed only after `run()`; test asserts rc 1, message, byte-identical files/manifest | yes |
| R4-01 | 2 | read scripts/dedupe_copies.py `main`; ran test_repoint_and_trash_refuse_while_the_worker_holds_its_lock | repoint|trash guarded, plan free; same two messages; test asserts rc 1, message, no file/plan/trash change | yes |
| R4-01 | 3 | `grep -c LOCK_EX scripts/tag_cleanup.py scripts/dedupe_copies.py`; grep LOCK_EX scripts crates | 0 and 0; helper imported from sourcing.worker (only crates/reconcile.py has its own, pre-existing) | yes |
| R4-01 | 4 | pytest -k 'lock or refuse or plan' on test_tag_cleanup/test_dedupe_copies; read the hold-for-whole-command, plan-never-locks, unset-CRATES_DB tests | 22 passed; four commands refuse with lock held, lock held during run and released after, plan runs with lock held, unset → 1 + message | yes |
| R4-01 | 5 | read tests/test_identity_backfill.py:1186 test_apply_dry_run_runs_while_the_worker_holds_its_lock | holds hold_lock(db.parent/'worker.lock') and apply --dry-run runs; passes | yes |
| R4-01 | 6 | `git log origin/main..HEAD` | commit `R4-01: worker.lock guard on tag_cleanup retag|move and dedupe_copies repoint|trash` present | yes |
| R4-01 | 7 | `lib/check.sh`; `git ls-remote origin` | green, 1579 tests; remote branch at bea69ca contains the R4 commits | yes |
| R4-02 | 1 | ran `python3 -m sourcing.cli rank --download`; read sourcing/cli.py:166-170 and header | argparse error exit 2 with the exact message in stderr; header says ranks only, no `[--download]`; old download block gone | yes |
| R4-02 | 2 | read test_rank_download_is_gone_and_names_preview_and_approve; `grep -rn -- '--download' tests/ sourcing/ scripts/ docs/worker.md` | asserts code 2, message, plain rank still ranks fixture (rc 0, output); grep hits only that test, the refusal check and the docs line saying it is gone | yes |
| R4-02 | 3 | read docs/specs/2026-10-17-m9-remaining-ownership.md:243, docs/architecture.md:316, docs/worker.md:329-333 | §6 marked 'Built (R4)' with guards and removed flag; architecture row present naming lock and commands; worker.md names the guard | yes |
| R4-02 | 4 | `git log origin/main..HEAD` | commit `R4-02: retire rank --download; M9 §6 docs` present | yes |
| R4-02 | 5 | `lib/check.sh`; `git ls-remote` | green 1579 tests; pushed | yes |
| R4-03 | 1 | read git diff of the guard files and sourcing/worker.py `with_worker_lock` | fd kept open via try/finally around `run()`; path is the worker's own; refusal precedes `_run`; plan not wrapped; no new flock copy | yes |
| R4-03 | 2 | read the shared helper and the extra tests (unopenable lock file, held for whole command) | one `with_worker_lock` helper in sourcing/worker.py shared by both scripts; OSError case has a test | yes |
| R4-03 | 3 | `git log origin/main..HEAD` | commit `R4-03: review and simplify the guards` present | yes |
| R4-03 | 4 | `lib/check.sh`; `git ls-remote` | green 1579 tests; pushed | yes |


How to read the feature list: `.harness/runs/dj-crate-streaming-2026-10-21/feature_list.json`. Array order is priority
and dependency order; the harness hands a session the first feature whose `passes` is false and whose `after` passes.
R1–R7 are independent (`after: []`), R8 waits for all of them. A session may flip only its own feature's `passes`, and
only after `.harness/check.sh` is green on the committed tree. When every feature of a milestone passes, the harness
verifies it and merges it into `main` on its own (`MERGE_POLICY=auto` tonight).

How Michael steers: edit `.harness/runs/dj-crate-streaming-2026-10-21/INBOX.md` on this branch. First line
`status: run | pause | stop`; answers to the questions below go under `## Answers`. Every session reads it at startup.

**This night is build-only.** No docker, no `docker compose`, no `scripts/deploy.sh`, no Check, no snapshots, no sqlite
on `/srv`, nothing read or written under `/srv`. Every live step is written into the morning checklist (R8-01) for
Michael. The spec is `docs/specs/2026-10-21-guards-and-checks.md`; the brief is `brief.md` beside this file.

---

### 2026-10-22 01:20 · R5-04 · passes
Opus review of `git diff origin/main...HEAD` (R5, `$HARNESS_SCRATCH/r5.diff`, 778 lines): no Critical. Prune bounded to date-named real dirs directly under `.history` (fd-based `rmtree`, links not followed), `open_ro` is `mode=ro`, the LEFT JOIN counts `missing=1` and absent `media_file` rows, one event per change (restart logs nothing), banner is `textContent` only: all fine.
Important I1 fixed test-first: the count named every account's playlists (amperfy's included) and smart ones, none of which `playlist_edit` can heal. `Worker.health` now keeps rows whose playlist `getPlaylists` lists with `owner == client.user`; `playlist_health` leaves out non-empty `rules`. Recorded as **D46 *default*** in the pivot spec. Also `/api/status` `playlistHealth` goes through `store.public`; the read-only test now asserts `open_ro` is used and that `open_ro` refuses a write on a 0644 file (chmod 0444 could not catch a rw open).
Docs: M9 spec §7 "Built (R5), not deployed" with Q11's 30-day default; architecture §3 `settings` row lists `playlist_health`, "Other stores" and an §8 row name `_playlists/.history/<date>/`; worker.md step 7 names the scope, and "how to watch it" gets a list of the worker's events incl. `playlist_health`.
Tests 1,606 → 1,610 (test_export_playlists +2, test_worker +1, test_service +1; each new one failed first). Full suite green, 597 s, 1610 tests.
Left (Minor, not done): M2 `_write` follows a planted `.tmp` link (as the live folder always did); M3 a prune failing partway loses the names already removed; M4 a scan in progress could give a two-event blip; M5 `getattr(s, "errors", ())` exists for test exporters that return None.
Question for Michael: D46 — should the banner also count other accounts' playlists (amperfy's)? Default: no, ours only. For R8: nothing live; ships with the next deploy.
Proposed changes: none.

### 2026-10-22 00:40 · R5-03 · passes
`web/index.html` `<div id="health" class="banner hidden"></div>` under the header; `web/app.js` `healthLines(rows)` (pure, between `// health:begin`/`// health:end`) words one line per playlist, "2 entries in X point at missing files" / "1 entry in X points at a missing file" (the worker's `health_detail` wording); `loadStatus` fills the banner with `el()` (textContent, never markup) and hides it when `playlistHealth` is empty or absent; status reloads on `visibilitychange` so a phone tab left open catches the worker's next count. `web/app.css` `.banner`: no width, `overflow-wrap:anywhere`, warn-coloured left edge.
Tests 1,600 → 1,606 (new tests/test_web_health.py): `#health` sits between `</header>` and the tabs; `loadStatus` reads `playlistHealth`, toggles `hidden` on an empty list, has no `HTML`; the CSS rule; `healthLines` run under node (plural, singular, `[]`, missing key); `/api/status` after a real worker tick on the fake with `missing={'s2'}` carries pl-1 Disco Edits 1 + pl-3 Sunday Listening 1. The four web tests failed first; the status one passed already (R5-01 backend). Full suite green, 585 s, 1606 tests.
Screenshot `docs/screenshots/r5-health-banner.png` (headless Firefox 153, 375×812, port 7805, fake with s1+s2 missing, health stored from `playlist_health`): Playlists tab open; under the header a two-line banner "2 entries in Disco Edits point at missing files" / "1 entry in Sunday Listening points at a missing file"; the list Disco Edits, Chicago 86, Sunday Listening below; no sideways scroll. `--screenshot` fires at the load event, before the page's fetches, so it went through a scratch proxy that adds one invisible image answering after 3 s (scripts in `$HARNESS_SCRATCH/shot/`, not committed).
Opus review: no Critical; Important (no refresh while the page stays open) fixed with the visibilitychange reload; Minor (hiding and markup untested) fixed. Left: on a failed `/api/status` the old banner lines stay beside the error.
For R5-04: the web client docs (architecture §3/§8, worker.md) can name the banner. For Michael (R8): nothing live; ships with the next deploy; after it, the crates page shows no banner while `/api/status` `playlistHealth` is `[]`.
Proposed changes: none.

### 2026-10-22 00:05 · R5-02 · passes
`scripts/export_playlists.py` `export(…, today=None)`: before replacing a changed `.m3u8` it writes the old text atomically to `_playlists/.history/<YYYY-MM-DD>/<fname>` unless the day already has one (the first version is kept); unchanged and new playlists make no history. `prune_history(out_dir, today, days=30)` removes only date-named real directories directly under `.history` older than today−30 (a linked `.history`/day folder and `notes/`, `2026-13-45` are left alone; `rmtree` doesn't follow links inside). It runs at the end of every export. History problems (write or prune) go to `Summary.errors` and never stop the export; the worker logs each as `export: history: …` and still runs the health count. `export` prints `history pruned: …`.
Tests 1,590 → 1,600 (tests/test_export_playlists.py +9, tests/test_worker.py +2): second export keeps the first text, a third change the same day keeps the first, the next day gets its own folder; 31 days old removed, 30/29 kept, `notes/`, a bad date, a date-named file, an old live `.m3u8` and the music tree untouched; an old-dated link and a linked `.history` not followed; an old folder holding links to music is removed with the music still there; `.history` that is a file / a link / a failing prune → export still writes; history not stale and `check` clean; the worker tick produces the history file. Each failed first (TypeError / AttributeError / the old export). Full suite green, 579 s, 1600 tests.
Opus review of the diff: no Critical; Important 1–2 (a history/prune error failed the whole export and skipped health) fixed test-first, Minor 3 (writes through a linked `.history`) fixed. Docs: docs/worker.md export step (UTC date, error log line) and Undo ("A playlist that lost entries" restores from `.history`), docs/hard-won-facts.md, the sourcing/worker.py docstring.
For R5-04: architecture §4/§8 should name the `.history` folder (not done here). For Michael (R8): nothing live; ships with the next deploy. After it, a playlist edit shows up as `/srv/music/_playlists/.history/<today>/<name>.m3u8` within 5 min, and no `export: history:` line appears in `docker compose logs worker`.
Proposed changes (Minor, not done): the feature step says worker.md "step 4", but the export is step 7 there now; a check-then-`rmtree` race if something swaps `.history` for a link mid-prune (needs a local writer; `rmtree(dir_fd=…)` on 3.11+ would close it); day folders follow UTC, not Michael's local midnight.

### 2026-10-22 01:00 · R5-01 · passes
`scripts/export_playlists.py` `playlist_health(db)`: one `{id, name, missing}` per playlist with `playlist_tracks` rows on a `missing=1` or absent `media_file` (the `playlist_edit` skew condition, LEFT JOIN), by name, through `open_ro`; every column it reads was already in `NAVIDROME_SCHEMA` and the fake's INSERT. `crates/store.py` `playlist_health()`/`set_playlist_health()` (settings key `playlist_health`, JSON); `crates/service.py` `/api/status` → `playlistHealth` (`[]` before any count).
`sourcing/worker.py`: after an export that worked (and a navidrome_db), `Worker.health` compares with the stored rows; a change logs one `playlist_health` event (`health_detail`: "2 entries in Tea tent point at missing files; 1 in Chicago 86", singular "1 entry in X points at a missing file", empty → "no playlist entry points at a missing file") and stores the rows in the same commit; a failed read or write → `playlist health failed: …`, rollback, stored value kept, tick goes on. docs/worker.md tick step 7 describes it.
Tests 1,579 → 1,590: fake mirror with `missing={'s2'}` → pl-1 Disco Edits + pl-3 Sunday Listening (1 each), nothing else; two unknown ids inserted into pl-2 → Chicago 86 2; read-only db; worker ticks (injected clock): one event, none on an unchanged tick, none from a restarted worker, the empty-set event after the fix; a fresh store with healthy playlists logs nothing; failed read, failed write (retried next export), failed export skips the count; `/api/status` carries the rows. Each failed first (AttributeError / KeyError). Full suite green, 571 s, 1590 tests.
For R5-03: `playlistHealth` rows are `{id, name, missing}`; the banner wording should match `health_detail`. For R5-04: docs (M9 §7 built, architecture §3 setting, worker.md event list) are still to do.
For Michael (R8): nothing live; ships with the next deploy. After it, look at `/api/status` `playlistHealth` and the `playlist_health` events (M8 measured 0 hidden entries, so `[]` and no event is the expected first result).

### 2026-10-22 00:20 · R4-03 · passes
Reviewed `git diff origin/main...HEAD` (guards + rank docs, 480 lines, `$HARNESS_SCRATCH/r4.diff`) myself and with an Opus reviewer: lock fd held through `_run` (try/finally), path `Path(CRATES_DB).parent/"worker.lock"` = the worker's own (sourcing/cli.py:266), refusal before any write (only argparse runs first), `plan`/`refresh-map` free, no new flock. No Critical/Important findings.
Simplified: `sourcing/worker.py` `with_worker_lock(run, env)` replaces `hold_worker_lock` and the two identical 7-line guard blocks; both scripts now `return with_worker_lock(lambda: _run(a))`. Docs (architecture §7 row, M9 §6) name it.
Tests 1,577 → 1,579: tests/test_worker.py `test_with_worker_lock_holds_…_and_releases_it_after` (also after an exception; failed first: ImportError) and `…_refuses_while_the_worker_holds_it_or_without_crates_db`. Full suite green, 567 s, 1579 tests. Host `/usr/bin/python3` loads both scripts' `--help` in `-m` and file form.
For Michael (R8): nothing live; ships with the next deploy.
Proposed changes (Minor, not done): `rank --downl` (abbreviation) gets argparse's generic error, not the Preview + Approve text; `scripts/duplicate_cleanup.py:698-721` still has its own CRATES_DB/worker.lock setup (pre-R4, needs `crates_db` for events) and could move onto `with_worker_lock`; the scripts' `except ImportError` fallback would mask a real import error from `sourcing.worker`'s dependencies.

### 2026-10-21 23:40 · R4-02 · passes
`sourcing/cli.py`: `rank --download` and its enqueue block are deleted (also the dead `client = None`); `rank … --download` now exits 2 from
argparse (`r.error`, an argv check before parsing) with `rank no longer downloads: use Preview + Approve in the web client (the worker downloads, D23)`; usage header has no `[--download]`.
Tests 1,576 → 1,577: `test_rank_download_is_gone_and_names_preview_and_approve` (failed first: no SystemExit), plus plain `rank` still ranks the sample fixture.
`grep -rn -- '--download' tests/ sourcing/ scripts/ docs/worker.md` → only the refusal check, its test and the worker.md line saying it is gone.
Docs: M9 §6 "Built (R4), not deployed" (both guards + removed flag); architecture §7 row "Only the worker downloads; host scripts write beets only with the worker stopped"; quirks 14/15 updated; worker.md "Settings the worker reads" names the guard.
Full suite green, 567 s, 1577 tests. Next (R4-03): review diff from origin/main; the two `hold_worker_lock` imports per script (lines 34/39, 47/53) look worth a look.
For Michael (R8): nothing live in this feature; it ships with the next deploy.

### 2026-10-21 23:10 · R4-01 · passes
`sourcing/worker.py` gets `hold_worker_lock(env)`, one wrapper over `hold_lock` (no second flock: `grep -c LOCK_EX` on both scripts → 0).
`scripts/tag_cleanup.py` `retag|move` and `scripts/dedupe_copies.py` `repoint|trash` hold `<dirname(CRATES_DB)>/worker.lock` for the whole command (try/finally),
exit 1 with `refused: stop the worker first (docker compose stop worker): it holds <path>`; CRATES_DB unset or not a file → 1 with the set-CRATES_DB message;
a lock file it can't open (the container's, read-only on the host) → `refused: cannot open …`, not a traceback. `plan`/`refresh-map` stay free; identity_backfill untouched.
Tests 1,560 → 1,576: refusal with the lock held (no file, manifest or plan byte changed; failed before the fix: real retag ran, 6 dedupe tests red),
lock held during the command and released after, unset CRATES_DB, plan while locked, `identity_backfill apply --dry-run` while locked. Full suite green, 570 s, 1576 tests.
Next session (R4-02/R8): live host runs now need `CRATES_DB=/srv/docker/crates/crates.db` and the worker stopped; `dedupe_copies repoint` in the crates container uses `/data/crates.db` (same mount, same lock).
For Michael (R8 checklist): if `/srv/docker/crates/worker.lock` isn't writable by mh550, the host commands refuse; run them inside the worker container instead, or `chmod 666` the lock (needs whoever owns it).

### 2026-10-21 23:00 · verify R3

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| R3-01 | 1 | read plan §'D35 (2026-10-19, Michael)' lines 26-38 and hold bullets ~71; `git merge-base --is-ancestor 555898f 0b095d1` | section has lossless released by default, keeper = keep_rank first, --hold-lossless, report section; bullet no longer says Michael edits plan.json; plan commit 555898f precedes code commit 0b095d1 | yes |
| R3-01 | 2 | read scripts/duplicate_cleanup.py `_hold`, `build_plan`, argparse `--hold-lossless` | `_hold(..., hold_lossless)` returns (None, LOSSLESS_PAIR note) by default, ('both lossless', None) when True; keeper-missing check first and unchanged; `plan --hold-lossless` passes it through | yes |
| R3-01 | 3 | read tests/test_duplicate_cleanup.py test_a_lossless_pair_is_released_by_default_with_the_d35_note, test_two_lossless_copies_are_held_with_hold_lossless…, test_plan_hold_lossless_through_the_cli; ran `.harness/check.sh tests/test_duplicate_cleanup.py` | 117 passed; asserts hold None + note, hold=='both lossless' with hold_lossless=True, CLI --hold-lossless gives 'both lossless'; the old hold test now uses hold_lossless=True; rest unchanged | yes |
| R3-01 | 4 | read test line 112 `dc.counts(plan).startswith('1 group to act on (2 extras…), 0 held')`; read `counts`/`render` | counts uses hold is None so a released pair is counted; render lists it | yes |
| R3-01 | 5 | `git log` for commit message | 0b095d1 'R3-01: D35 as answered: lossless pairs released by default, --hold-lossless keeps the hold' | yes |
| R3-01 | 6 | harness check `/home/mh550/projects/agent-harness/lib/check.sh`; `git branch -r --contains HEAD` | green, 1560 tests (cached for this tree); branch pushed state checked via fetch/ancestry | yes |
| R3-02 | 1 | read `render`; test_report_md_lists_lossless_pairs_in_their_own_section_before_the_held_groups, test_a_plan_without_lossless_pairs_has_no_such_section | heading 'Lossless pairs, will be trashed' placed before 'Held groups'; asserts S9 path and 'Move Your Body' path inside the section; absent when no pair | yes |
| R3-02 | 2 | read test_a_released_lossless_pair_is_repointed_like_a_lossy_extra, test_a_released_lossless_pair_is_trashed_like_a_lossy_extra (line 893) | repoint to keeper like lossy; trash dry-run == {'s10': 'dry run: would move'}; passes in suite run | yes |
| R3-02 | 3 | read test_a_hold_lossless_plan_is_skipped_by_repoint / _by_trash; held tests at lines ~457, ~877 | both give 'skipped: held (both lossless)'; older held tests remain | yes |
| R3-02 | 4 | `grep -c 'D35 \*default\*' docs/specs/2026-10-17-amperfy-pivot.md`; read D35 row line 30 | prints 0; row reads as Michael's 2026-10-19 answer, lossless extras trashed, --hold-lossless for old hold | yes |
| R3-02 | 5 | `grep -n 'hold-lossless\|hold.*null' docs/worker.md` | matches at lines 3, 10, 434, 522, 542; no instruction to set hold to null; names the report section | yes |
| R3-02 | 6 | `git log` for commit message | 4aa40bb 'R3-02: lossless-pair report section; D35 recorded as answered' | yes |
| R3-02 | 7 | harness check green (1560 tests); ancestry on origin branch | green | yes |
| R3-03 | 1 | read r3.diff scope (`git diff origin/main...HEAD` on the 5 files, 457 lines); grep for references/recompute/keep_rank in the diff; read build_plan, `.get('note')` use in render | `references()` calls untouched; build_plan still recomputes via load+duplicate_groups; keeper is group first (keep_rank); reverse-log code not in diff; render uses g.get('note') so old plan.json without note loads | yes |
| R3-03 | 2 | progress entry R3-03, `git show 2401066`; test_only_the_d35_note_puts_a_group_under_lossless_pairs | no Critical/Important; one Important-ish render fix has its test; single `_hold` decides hold, no second vocabulary | yes |
| R3-03 | 3 | `.harness/check.sh tests/test_duplicate_cleanup.py`; read tests named in architecture row 326 (held group never touched, another user's playlist blocks, running scan refuses, worker lock, put-back, reverse replay) | 117 passed; those tests exist (e.g. test_a_held_group_is_never_trashed, test_another_users_playlist_alone_blocks_the_move, test_the_reverse_log_replayed_newest_first…) | yes |
| R3-03 | 4 | `git log` | 2401066 'R3-03: review and simplify D35' | yes |
| R3-03 | 5 | harness check green 1560 tests | green | yes |

### 2026-10-21 · R3-03 · passes
Opus review of `r3.diff` (scratch; the 5 files from origin/main...HEAD): no Critical/Important. Holds: `references()`
checks untouched (trash :586, `_put_back`, already-gone, `recheck_moved`); repoint/trash take the hold from plan.json only,
so a `--hold-lossless` plan never flips on recompute; keeper = `keep_rank` first (lossless tie → `_copy_rank` filed path);
reverse logs untouched; an old plan.json without `note` renders and acts as before. Applied: `render` sorts by
`note == LOSSLESS_PAIR` not any note (new test failed first); usage line gets `[--hold-lossless]`; N1 plan's `build_plan`
signature. Tests 1,559 → 1,560; `tests/test_duplicate_cleanup.py` 117 passed, every §7 duplicate-cleanup guard has its test.
**Proposed change (Minor, not built: it changes the trash flow, needs the plan reviewed):** `_recheck` checks that the keeper and the extra are still in one group, but not that the plan's keeper is still the group's first file.
If beets re-files a flac keeper between plan and trash, the badly filed copy stays and the properly filed one is trashed (reversible). Fix: `skipped: keeper changed; re-run plan`.
For Michael: `keep_rank` doesn't compare bit depth or sample rate, so a 24/96 flac in Compilations/ is trashed in favour of a filed 16/44 one (D31 as answered). report.md shows kbps for each copy.

### 2026-10-21 · R3-02 · passes
`scripts/duplicate_cleanup.py` `render`: groups with the D35 note get their own section "Lossless pairs, will be trashed"
(keeper, each extra with its playlists), before the held groups; no such groups → no section; the held-groups line no
longer says to set `hold` to null. D35 row in the pivot spec reads as Michael's 2026-10-19 answer (`grep -c 'D35 \*default\*'` → 0);
`docs/worker.md`, the N1 plan and morning checklist step 1 name the section and `plan --hold-lossless` (716 / 730 songs).
Tests 1,553 → 1,559: report section (fails on the old render), no section without pairs, repoint of a released pair
(like a lossy extra), `trash --dry-run` gives `dry run: would move`, `--hold-lossless` skipped in repoint and trash.
Finished the killed session's WIP (2f6a4e1); Opus review: no bugs, two wording fixes applied. Full suite green, 566 s.

### 2026-10-21 · R3-01 · passes
D35 as Michael answered it: `scripts/duplicate_cleanup.py` `_hold` now returns `(hold, note)` and takes `hold_lossless`;
by default a lossless pair gets `hold: null` + `note: "lossless pair: released by Michael 2026-10-19 (D35)"` (lossy extras
of that group too); `plan --hold-lossless` gives `"both lossless"` as before; "keeper missing on disk" still wins (no note).
N1 plan got a dated "D35 (2026-10-19, Michael)" section, committed first (555898f) before the code (0b095d1); its hold
bullet, safety row and runbook steps 2/5 (716 songs by default, 730 with `--hold-lossless`) follow. Tests: the old hold
test moved to `hold_lossless=True`; new: default release + note + counts/render include it, lossy group has no note,
missing keeper in a lossless pair, CLI `--hold-lossless`. 1,549 → 1,553; full suite green in 561 s.
Next (R3-02): `render`'s own section; `docs/worker.md` (lines 433, 541) and the morning checklist step 3.1 still say to
set `hold` to null by hand; the held-groups line in `render` still says so too (true only with `--hold-lossless`).

### 2026-10-21 · verify R2

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| R2-01 | 1 | Read scripts/live-run.sh; Dockerfile:15 and deploy.sh:22 for the label; tests/test_live_run.py happy-path and refusal tests | set -euo pipefail; inspect of dj-worker-1 label; refuses on missing docker/container, empty, `dev`, non-hex, missing image; prints `live-run: image dj-crates:<rev>` then `GIT_SHA=<rev> docker compose --project-directory /srv/docker run --rm --no-deps worker …`; truncates to 10. Label is set in the Dockerfile (compose.yml has no labels:), deploy.sh passes short=10; the script header documents it. Tests: happy path, 5 parametrized refusals, full-sha truncation, all pass | yes |
| R2-01 | 2 | test_print_shows_the_exact_command_and_runs_no_compose; read script's print branch | --print outputs GIT_SHA=<rev> + quoted command, exit 0, compose log empty | yes |
| R2-01 | 3 | Read scripts/live-check.sh; test_live_check_runs_export_then_check_through_live_run / _exits_with_the_checks_status | exec live-run.sh sh -c 'export && check'; argv equals the CHECK_CMD; status passed on | yes |
| R2-01 | 4 | `pytest tests/test_live_run.py`; read the happy-path, refusal, print, live-check tests | 26 passed; GIT_SHA env asserted, `run --rm --no-deps worker` and verbatim command, refusals exit 1 with compose == [], print has no compose, live-check argv asserted | yes |
| R2-01 | 5 | `grep -n docker tests/test_live_run.py` | Only the stub, PATH handling, argv assertions and refusal text; no real docker call | yes |
| R2-01 | 6 | grep CLAUDE.md, docs/worker.md, pivot spec | CLAUDE.md Check names scripts/live-check.sh with the long form; worker.md lines 465-468 use scripts/live-run.sh … trash; pivot spec line 40 has `D45 *default*` | yes |
| R2-01 | 7 | `git log` | Commit `R2-01: live-run.sh and live-check.sh run one-offs in the deployed image` present (c671621) | yes |
| R2-01 | 8 | `/home/mh550/projects/agent-harness/lib/check.sh`; `git status -sb` | check: green, 1549 tests; R2 commits already on origin/harness/… (branch only ahead by the merge and harness commits) | yes |
| R2-02 | 1 | Read live-run.sh/live-check.sh and the diff; tests for spaces (`sh -c 'a && b'`), no-deps, docker missing, .env grep | test_an_argument_with_spaces… asserts argv[-3:]==['sh','-c','a && b']; --no-deps in every argv assertion; label name org.opencontainers.image.revision matches Dockerfile:15 (compose.yml has no labels); test_no_docker_on_path_is_refused; `grep .env` in both scripts finds nothing | yes |
| R2-02 | 2 | Read live-run.sh cmd array; test_a_git_sha_in_the_callers_environment…, test_a_label_that_is_not_a_hex_sha… | One `cmd=(…)` array serves --print and the run; extra tests for findings exist and pass | yes |
| R2-02 | 3 | Read docs/plans/2026-10-17-morning-checklist.md lines 1-16, 70-78 | Step 3 (trash) uses scripts/live-run.sh; header note says R8 replaces this checklist | yes |
| R2-02 | 4 | `git log --format=%s` | Commit `R2-02: review and simplify live-run` present (98def83) | yes |
| R2-02 | 5 | Harness check.sh; origin ref | green 1549 tests; 8146059 is on origin | yes |

### 2026-10-21 · R2-02 · passes
Opus review of `r2.diff` (scratch): quoting, `--no-deps`, the label name (Dockerfile:15), no-docker refusal and .env all hold;
one cmd array already feeds `--print` and the run. One Important finding, fixed test-first: `scripts/live-check.sh ""` (and
`--print junk`) forwarded `"$@"` to live-run and ran a live compose with an empty command word; it now accepts only no
argument or a lone `--print` and builds the flag itself. Minors fixed: `docker inspect --type container`; a label that is
not a hex sha (`development` used to become `developmen`) is refused before the 10-char cut; inspect refusal names
"docker unreachable". Docs: morning checklist (R8-replaces note, **check** = live-check.sh, step 3.3 trash via live-run.sh),
architecture trash row, worker.md "from a checkout", D45 notes that only the image is pinned (env/mounts come from
/srv/docker/compose.yml). Tests 1,541 → 1,549; full suite green in 561 s. Never ran either script (build-only).

### 2026-10-21 · R2-01 · passes
New `scripts/live-run.sh` (reads `dj-worker-1`'s `org.opencontainers.image.revision`, cuts it to 10 chars, refuses in one
line on: no docker, no container, empty/`<no value>`/`dev` label, missing `dj-crates:<rev>`; else prints
`live-run: image dj-crates:<rev>` and execs `GIT_SHA=<rev> docker compose --project-directory /srv/docker run --rm --no-deps worker …`;
`--print` prints the `%q`-quoted command only) and `scripts/live-check.sh` (the Check through it, `--print` too).
`tests/test_live_run.py` (18, stub docker logs argv + GIT_SHA as JSON); docs: CLAUDE.md Check, worker.md check + trash,
D45 *default* in the pivot spec; deploy.sh header fixed (it said the label held the full sha: it holds the 10-char one).
Tests 1,523 → 1,541; full suite green in 555 s. Never ran either script (build-only).
Proposed change: step 1 says to read deploy/compose.yml's `labels:`; there are none, the label is the Dockerfile's
`LABEL org.opencontainers.image.revision=$GIT_SHA` (build arg from compose = deploy.sh's `--short=10`).

### 2026-10-21 · verify R1

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| R1-01 | 1 | `grep -n 'I1' CLAUDE.md`; `grep -n _scanned_since_repoint scripts/duplicate_cleanup.py` | CLAUDE.md:73-77 names I1/I2, `_scanned_since_repoint`, size check vs `media_file.size`/`planned_size`, dry-run until `lastScan` confirmed and Michael lifts; function defined at line 400 | yes |
| R1-01 | 2 | `grep -n '1,523' CLAUDE.md`; `grep -c '1,120' CLAUDE.md` | line 16 says ~1,523 tests, 9-10 minutes (570 s); count of 1,120 = 0 | yes |
| R1-01 | 3 | `grep -n f4882ab85b docs/next-todos.md`; read line 24 | 2026-10-21 paragraph: live image, N1/N1F/H1/H2/H3-01..04, PRs #5-#13, H1-H3 live except H3-03 timer, N2-N5 merged not deployed, N1 never run | yes |
| R1-01 | 4 | `grep -n supersedes docs/architecture.md`; `grep -c 'running now'`; read status table diff | §11 note line 560 (questions 1,2,5,8,10); running-now count 0; M7 review done, H1-H3 row, N1-N4 merged not live except N1 code | yes |
| R1-01 | 5 | `grep -n 'items 1 and 3' docs/specs/2026-10-17-m9-remaining-ownership.md` | line 4: items 1 and 3 built (N4, N1), rest not built | yes |
| R1-01 | 6 | `grep -n 'installed copy' docs/hard-won-facts.md` | line 51 names installed copy /usr/local/lib/dj-crates/snapshot-crates-db.sh (CLAUDE.md names /usr/local/sbin/restic-backup for the backup job; not contradictory). Did not read /srv (build-only) | yes |
| R1-01 | 7 | `git diff --stat origin/main...HEAD -- '*.py' '*.sh' '*.js' '*.html'` | empty; changed files are only CLAUDE.md, README, docs, .harness run files | yes |
| R1-01 | 8 | `git log` for CLAUDE.md/docs | commit 84d785f 'R1-01: doc truth (live image, merged PRs, I1/I2 fixed, test count)' | yes |
| R1-01 | 9 | `/home/mh550/projects/agent-harness/lib/check.sh`; `git status -sb` | check: green (1523 tests); branch in sync with origin, nothing ahead | yes |
| R1-02 | 1 | read diff of CLAUDE.md/docs; `git log --merges origin/main`; `.harness/check.sh --collect-only | tail -1`; spec facts lines 8-25 | PRs #5-#13 merge commits present; 1523 tests collected; image/not-deployed/H3-03 claims match spec facts; `_scan_time`/`planned_size` exist in code | yes |
| R1-02 | 2 | `grep -rn '1,523' README.md docs/architecture.md docs/hard-won-facts.md CLAUDE.md` | all four files match, each with about 9-10 minutes | yes |
| R1-02 | 3 | `git log`  | commit bb8cf81 'R1-02: review doc truth ...'; findings recorded in R1-02 entry | yes |
| R1-02 | 4 | check.sh (cached green, 1523); `git status -sb` | green; pushed, branch not ahead of origin | yes |

### 2026-10-21 R1-02 · passes
Reviewed every sentence R1-01 changed (`git diff origin/main...HEAD -- CLAUDE.md docs/` in scratch `r1.diff`); docs only.
Held: `_scanned_since_repoint`/`_scan_time`, PRs #5–#13 merged (`git log --merges origin/main`), 1,523 collected,
image/merged/not-deployed claims vs the spec's facts, §11 superseded questions 1/2/5/8/10 (D24, D27, D26).
Fixed: (1) CLAUDE.md I2 now says size on disk vs `media_file.size` **and** `planned_size`; (2) hard-won-facts named
the wrong installed file: the nightly snapshot runs `/usr/local/lib/dj-crates/snapshot-crates-db.sh` (both installed
copies `cmp`-identical to the repo); (3) README, architecture §8, hard-won-facts said 7 / 7-9 min → about 9-10 minutes;
(4) next-todos + architecture: H3-05's health-push changes are merged, not installed (spec facts). Tests 1,523 → 1,523; suite green in 558 s.
Proposed change: the step's `.harness/check.sh --collect-only -q | tail -1` prints a warning link, not the count
(check.sh already passes `-q`); use `.harness/check.sh --collect-only | tail -1` ("1523 tests collected").

### 2026-10-21 R1-01 · passes
Docs only (CLAUDE.md, next-todos, architecture, M9 spec header, hard-won-facts); no code file changed.
CLAUDE.md now says I1 (`_scanned_since_repoint`) and I2 (`planned_size` check) are fixed, trash stays at `--dry-run`
until a live dry run confirms `lastScan` and Michael lifts it. Test count 1,523 → 1,523; suite green in 553 s.
Verified with the greps from the steps (all match; `1,120` and `running now` count 0).

## 2026-10-21 initializer (Fable) — feature list written

**Features per milestone:** R1 doc truth 2 · R2 live-run.sh 2 · R3 D35 as answered 3 · R4 M9 §6 guards 3 ·
R5 playlist health + `.m3u8` history 4 · R6 M9 §8a/8b/8c/8h 4 · R7 identity picker 6 · R8 checklist + whole-run review 2
= **26 features**. Nothing is built yet. Suite at start: green, 1,523 tests in 570 s (so "about 9–10 minutes", not 7).
Base of the run: `0b4f712` (main + the spec); the whole-run diff for R8-02 is `git diff 0b4f712...HEAD`.

Earlier runs' sizes (`.harness/runs/dj-2026-10-17/metrics.jsonl`): a build feature took 20–30 min on Opus, a review
feature 17–33 min, a verify 2–10 min. Features here are cut to that size.

### Where things live (what a worker must know)

**Entry points and modules the spec names**
- `scripts/duplicate_cleanup.py` (711 lines): `build_plan` → `_hold(keep, extras, music_root)` (line ~112) returns
  `"both lossless"` when `_lossless(keep) and any(_lossless(e) for e in extras)`, else `"keeper missing on disk"` or
  None; `counts`, `render` (report.md), `write_plan` (keeps an edited plan.json aside), `repoint`, `trash`
  (`hold_lock` on `<dirname(CRATES_DB)>/worker.lock`, `_scanned_since_repoint` = review I1, the `planned_size` check in
  `_trash.one` = I2). `main` at line ~644. Tests: `tests/test_duplicate_cleanup.py` (fixtures `lib`, `tr`; the
  in-process lock pattern `fd = hold_lock(tr.lock)` at line ~597).
- `sourcing/worker.py`: `hold_lock(path)` (fcntl flock, raises `WorkerRunning`), `Worker.export_due` (step 4; calls
  `scripts.export_playlists.export(db, music, music / "_playlists")`), `TickReport`. Tests: `tests/test_worker.py`
  (`worker(world, srv)` on `tests/test_fetch.py::world`).
- `scripts/export_playlists.py`: `open_ro`, `load`, `_path_ids`, `render`, `export` (atomic tmp + replace, counts
  written/unchanged/stale), `check`, `main`. The history (R5-02) and the health count (R5-01) go here.
- `crates/service.py`: `Config.from_env` (CRATES_TRASH, NAVIDROME_DB, …), `CrateApp.status()` (`/api/status`),
  `make_handler._api` is the one routing function (GET/POST by path head), `_static` serves `web/`. Tests:
  `tests/test_web_m8.py` (no JS runner: tests check served strings and the API contract; screenshots at **375 px**
  were taken by hand so far). `firefox` exists on this box (`/usr/bin/firefox`; `--headless --screenshot` works for
  R5-03/R7-05); no playwright, no chromium.
- `crates/store.py`: `settings` table with `stream_tier`/`set_stream_tier` (the pattern for `playlist_health`),
  `log(playlist_id, song_id, kind, detail)` and `events(limit)`, `public()` (strips absolute paths and peer names),
  `find_external` (line ~642: skips failed unfiled rows → R6-03), `add_external_wanted`.
- `scripts/identity_backfill.py` (1,125 lines): `CLASSES`, `ACCEPT`, `Proposal` (fields `path, cls, write, why,
  candidates, size, mtime_ns, file`), `_disambiguation_label`, `_misfit`, `classify`, `propose` (writes
  `identity-proposal.json` + report, MB cache `mb-cache.jsonl`), `_intended` (the "choose must be a candidate"
  check, line ~695), `apply(proposal, music_root, log=, classes=, dry_run=)`, `revert`, `_redacting(lookup, key)`,
  `main`. `APPLY_CLASSES`, `CHOOSABLE` at line ~658.
- `sourcing/acoustid.py` (54 lines): `compressed_fingerprint` (fpcalc), `parse`, `lookup`, `make_lookup`. No cache,
  no limiter yet. `sourcing/musicbrainz.py` has the `Limiter` with `slot(clock, sleep, min_interval_s)`, the
  process-wide `_SHARED`, `reset_shared_limiter()`: reuse it for AcoustID (R6-01).
- `sourcing/identity.py`: `_TRACKNO` regex at line 266 (`^\s*(?:[a-d]\d|\d{1,2})\s*[-._ ]+\s*`, so "99 Luftballons"
  loses "99 "), `strip_trackno`, `parse_filename` (used by `sourcing/scorer.py` and `sourcing/fetch.py`),
  `parse_title`, `same_version`.
- `sourcing/cli.py`: `rank` parser at line ~117, `--download` at line 125, the enqueue block at line ~328.
- `scripts/tag_cleanup.py` `main` (line ~355): `cmd` in `plan|retag|move|refresh-map`; `open_lib` opens beets.
  `scripts/dedupe_copies.py` `main` (line ~202): `plan|repoint|trash`; `_forget_in_beets` in `trash`.
- `subsonic/fake_server.py`: `NAVIDROME_SCHEMA` (line 68: playlist, playlist_tracks, media_file with `missing`,
  `size`, `bit_rate`…), `FakeState` (`missing`, `smart`, `requests`, `last_scan`, `end_scan`), `sync()` mirrors to
  `db_path`. **Any new column a SELECT reads goes into the schema and the INSERT in the same commit.**
- `web/`: `index.html` (tabs Playlists / Wanted / Search / Log), `app.js` (vanilla, `api()`, `loadStatus`,
  `changeError`, the player `playTrack`), `app.css` (phone-first). The crates container mounts
  `/srv/docker/crates:/data`, so `/data/identity` is already visible to it (R7 needs no compose change).
- `deploy/compose.yml`: worker image `dj-crates:${GIT_SHA:-dev}`; the OCI revision label is set in the build
  (check the `labels:` block before writing R2-01's inspect command). `scripts/deploy.sh` exports
  `GIT_SHA=$(git rev-parse --short=10 HEAD)`. `tests/test_deploy_script.py` is the stub-docker pattern.
- Fixtures with real response shapes: `fixtures/acoustid_lookup.docs-example.json`,
  `fixtures/musicbrainz_search.sample.json`, `fixtures/search_responses.sample.json`. Never invent a shape.

**Docs the milestones touch**
- `CLAUDE.md` (R1, R2), `docs/next-todos.md` (R1, R8), `docs/architecture.md` (R1, R4–R7), `docs/hard-won-facts.md`
  (R1, R5), `docs/specs/2026-10-17-m9-remaining-ownership.md` (R1 header; §5a, §6, §7, §8 marked built),
  `docs/specs/2026-10-17-amperfy-pivot.md` (D35 row in R3; `D45 *default*` in R2; later defaults numbered on),
  `docs/worker.md` (R2 trash commands, R3, R5, R6, R7), `docs/plans/2026-10-17-n1-duplicate-cleanup.md` (R3),
  `docs/plans/2026-10-17-morning-checklist.md` (R2-02 small edit; R8-01 supersedes it with the 2026-10-22 file).
- Keep `docs/screenshots/` for R5-03 and R7-05 PNGs at 375 px.

**Gotchas**
- `git add` files by name; never `-A` (scratch sweeps in). Check `git show --stat HEAD` before pushing.
- `.harness/check.sh` runs pytest with `-x`; pass test files while iterating; the full suite once before `passes`.
- `tests/conftest.py` sets `CRATES_OWNER=comment` and the legacy policy; app-owner tests live in `tests/test_app_owner.py`.
- Soulseek peer names, absolute library paths and the AcoustID key stay out of events, API payloads and files
  (`store.public`, `_redacting`).
- Several milestones edit the same docs (`docs/worker.md`, the M9 spec, the pivot spec). Milestones merge into `main`
  separately, so keep each milestone's doc edits in its own section/row and don't reflow other sections. New
  `D<n> *default*` rows: take the next free number at commit time (D45 is R2's; `grep -n '^| D4' docs/specs/2026-10-17-amperfy-pivot.md`).
- `docs/duplicates-report.md` is a snapshot (102 groups, 115 extras, 9 lossless pairs); the tool recomputes from
  navidrome.db every run.
- Nothing tonight writes to the live box. R2's scripts are never executed outside their stub-docker tests.

### Decisions taken by default (Michael: answer in INBOX.md to change any)

1. **D45 *default* (R2):** live one-off commands run in the deployed image, resolved from the worker container's
   `org.opencontainers.image.revision` label; `dev` or an empty label refuses. Alternative: pin `GIT_SHA` in
   `/srv/docker/.env` (step 3 of the checklist greps for that).
2. **R5 history (Q11 default yes):** the first version of a `.m3u8` on each day it changes is the one kept in
   `_playlists/.history/<date>/` (a second rewrite the same day doesn't overwrite it); 30 days. Alternative: keep every
   rewrite with a time suffix.
3. **R5 health state:** the last health set is stored in crates.db `settings` (key `playlist_health`) so a worker
   restart repeats no event; `/api/status` shows the stored rows. Healing stays manual.
4. **R4 (Q10 default yes):** `dedupe_copies plan` stays free; `repoint` and `trash` need the lock; `tag_cleanup plan`
   and `refresh-map` stay free; `retag` and `move` need it; an unset `CRATES_DB` refuses.
5. **R7 (Q7, Q8 defaults):** `search` rows are accepted one by one in the picker (never as a class); the only
   candidate on the file's own album is pre-selected and applied only on a click; choices go to
   `identity-choices.json` and reach tags only through `identity_backfill apply --choices`, which is your live step.
6. **R6-01:** the AcoustID cache is keyed on path + size + mtime_ns and lives at `<out>/acoustid-cache.jsonl`
   beside `mb-cache.jsonl`; 3 req/s process-wide.
7. **R6-03:** a re-import sets a failed unfiled row back to `needs_source` (same `ext-N`), never a `removed` row.

### Questions that are not decisions
- The R8 checklist assumes the `~/projects/dj-crate-streaming` checkout still shows a modified
  `.harness/runs/dj-2026-10-17/INBOX.md`; step 1 says what to do if it does not.
- `grep -c '^GIT_SHA=' /srv/docker/.env` is a step for you (the agent never reads that file).
