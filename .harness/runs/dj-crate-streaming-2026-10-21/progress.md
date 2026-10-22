# Progress log — run `dj-crate-streaming-2026-10-21` (branch `harness/dj-crate-streaming-2026-10-21`)

What this file is: the shared memory of the agent harness for this run. Each session appends one entry **at the top**
(newest first) when it finishes a feature: what it built, what it learned, what it asks. Nobody edits older entries.

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
