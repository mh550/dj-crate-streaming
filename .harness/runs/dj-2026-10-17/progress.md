# Progress log — run `dj-2026-10-17` (branch `harness/dj-2026-10-17`)

What this file is: the shared memory of the agent harness for this run. Each session appends one entry **at the top**
(newest first) when it finishes a feature: what it built, what it learned, what it asks. Nobody edits older entries.

How to read the feature list: `.harness/runs/dj-2026-10-17/feature_list.json`. Array order is priority and dependency
order; the harness hands a session the first feature whose `passes` is false. A session may flip only its own
feature's `passes`, and only after `.harness/check.sh` is green on the committed tree. Milestones `N1`…`N5` map to
`docs/next-todos.md` items 1–4 plus docs; each milestone starts with a plan feature and ends with a review feature.

How Michael steers: edit `.harness/runs/dj-2026-10-17/INBOX.md` on this branch. First line `status: run | pause |
stop`; answers to the questions below go under `## Answers`. Every session reads it at startup.

---

### 2026-10-17 21:10 · H3-04 · not yet
- **Still blocked:** INBOX Answers still has no "gatus vars set" (fetched 21:09), so no deploy. **Live:** none. No live command was run.
- **Changed:** after `up -d gatus`, `scripts/deploy.sh gatus` now waits up to `GATUS_WAIT` (default 30 s) for `http://127.0.0.1:4590/api/v1/endpoints/statuses`. If Gatus never answers, it exits 1, names the two vars and prints the `logs` and rollback (`stop gatus && rm -f gatus`) commands. This closes the last session's review leftover: `up -d` exits 0 even when Gatus exits at start. Crates/worker deploys don't wait. `tests/test_deploy_script.py` +3 tests (stub `curl`). Tests 1,356 → 1,359.
- **Verified:** the new tests were red first. Making the curl check always succeed turns the failure test red. `lib/check.sh` green, 1,359 tests (492 s). No Opus review: the change is 17 lines of bash.
- **Next session (H3-04 again):** unchanged from the 20:50 entry. Once INBOX says "gatus vars set": `flock -n /srv/docker/crates/live.lock scripts/deploy.sh gatus`. Exit 0 now means Gatus answered. Exit 1 means roll back with the printed command and stop.
- **Question for Michael:** please set the Gatus vars and write "gatus vars set" under Answers (INBOX, H3-02 section). Until you do, every H3-04 session can only wait.
- **Proposed change:** the harness could skip H3-04 (and move on to H3-05/N2) while INBOX lacks "gatus vars set", instead of rerunning a blocked session.

### 2026-10-17 20:50 · H3-04 · not yet
- **Blocked:** no "gatus vars set" under INBOX Answers (fetched 20:47), and Gatus exits at start without `GATUS_NTFY_TOPIC`/`GATUS_BACKUP_TOKEN`. Agents can't check `/srv/docker/.env`, so I didn't deploy. Step 3 (INBOX has the spec's one-time steps verbatim) is done; steps 1–2 need the deploy.
- **Changed (build prep for the deploy, fixes H3-02 review I1/I2):** `scripts/deploy.sh gatus` now copies `git show HEAD:deploy/gatus/config.yaml` to `${GATUS_DIR:-/srv/docker/gatus}/config/` (mkdir as mh550, rename into place). It refuses `gatus` together with other services, and refuses a config dir it can't write (printing the `sudo chown`). `deploy/compose.yml` mounts `${GATUS_DIR}/config:/config:ro` and `${GATUS_DIR}:/data`, so the mount no longer follows `CRATES_SRC`. Recorded as **D41 *default*** in the pivot spec. New `tests/test_deploy_script.py` (8 tests, stub docker, temp repo); `tests/test_gatus.py` mount test updated, plus 1 test for `GATUS_DIR`. INBOX: the H3-03 section had landed inside the header's HTML comment (hidden on GitHub); I moved it out and added the H3-04 section. Tests 1,347 → 1,356.
- **Verified:** new tests were red first. Changing the rename to `cp` turns a test red. `lib/check.sh` green, 1,356 tests (487 s).
- **Review (Opus, `/tmp/…/h3-04.diff`):** 0 Critical. It checked the image (`GATUS_CONFIG_PATH` empty, WorkingDir `/`), so Gatus reads `/config/config.yaml` and reloads it when the rename changes its mtime. Fixed: Important 1 (a root-owned dir made by Docker; now a clear refusal, and INBOX says to start Gatus only through deploy.sh), Minor 2 (a combined deploy could copy the checks and then fail the build), Minor 5 (the stub now records `GATUS_DIR`). Left: `up -d` exits 0 even when Gatus exits at start, so the deploy's status check is the real gate; a `GATUS_DIR` in .env would be overridden by deploy.sh's; `/data` exposes the config read-write.
- **Live:** none. Read-only `docker ps` (crates/worker `dj-crates:caef38ce9b`, up 2 h; navidrome 2 h; slskd 42 h; gluetun 4 days) and `ls /srv/docker/gatus` (doesn't exist yet).
- **Next session (H3-04 again):** once INBOX says "gatus vars set": record `docker ps`, check backup status and the window, run `flock -n /srv/docker/crates/live.lock scripts/deploy.sh gatus`, then `curl -s http://127.0.0.1:4590/api/v1/endpoints/statuses`, and confirm the other containers' uptimes didn't change. Rollback: `docker compose --project-directory /srv/docker -f deploy/compose.yml stop gatus && docker compose --project-directory /srv/docker -f deploy/compose.yml rm -f gatus`.
- **Questions for Michael:** (1) Please set the Gatus vars and write "gatus vars set" (INBOX, H3-02 section). (2) D41: should Gatus read a deployed copy of the config (my default), or mount `~/projects/dj-crate-streaming/deploy/gatus`?
- **Proposed changes:** H3-04's step "backup and disk may stay grey" → "disk may be red until H3-03's timer is enabled" (D40, as H3-02 said).

### 2026-10-18 00:50 · H3-03 · passes
- **Changed:** new `deploy/health-push.sh` (POSTs to Gatus `_disk`/external: `/srv` < 85 %, `/mnt/backup` mounted and < 90 %; failure carries the reason in `?error=`; token on stdin; unset URL/token → warning, exit 0, no request; failed push exits 1; `GATUS_DISK_KEY` overrides the key) and `deploy/systemd/dj-health-push.{service,timer}` (user units, oneshot, every 10 min, `EnvironmentFile=-%h/.config/dj-health-push.env`, ExecStart is an installed copy `~/.local/lib/dj-crates/health-push.sh` so it survives a removed worktree). New `tests/test_health_push.py` (14, stub df/mountpoint/curl). INBOX has Michael's install/enable lines. Tests 1,333 → 1,347.
- **Verified:** 14/14 pass; `systemd-analyze --user verify` passes in a test on a copy whose ExecStart points at the script (on the real unit it only complains the installed copy doesn't exist yet); `lib/check.sh` green, 1,347 tests (486 s).
- **Live:** none. Nothing installed or enabled.
- **Next session (H3-04):** still blocked on Michael's Gatus vars. `disk` stays red until he enables the timer.
- **Questions / proposed changes:** none. (Not done: no mutation run on the 85/90 boundaries beyond the exact-limit tests.)

### 2026-10-18 00:20 · H3-02 · passes
- **Changed:** `deploy/compose.yml` adds `gatus`: `twinproduction/gatus:v5.37.0` (released 2026-09-24), uid 1000, `127.0.0.1:4590:8080`, `${CRATES_SRC}/deploy/gatus:/config:ro` (the directory, so a checkout's new file is reloaded), `/srv/docker/gatus:/data`, `unless-stopped`, no `depends_on`. The vars are passed with `:-`, so the rest of the stack works while they're unset. New `deploy/gatus/config.yaml`: navidrome `/ping`, crates `/api/status` (200, `has(workerHeartbeatAge)`, `< 180`), slskd `gluetun:5030` (connected, `< 500`), each every 60 s, ntfy after 3 failures, sent on resolve. External `backup` (26 h heartbeat) and `disk` (30 m heartbeat, **D40 *default***), each alerting after 1 failure and resolving on 1 success. sqlite history, `skip-invalid-config-update: true`. Also `deploy/.env.example` (+2 vars), D40 in the pivot spec, INBOX. New `tests/test_gatus.py`. Tests 1,316 → 1,333.
- **Verified:** v5.37.0's source and README support `external-endpoints[].heartbeat`. Real image, throwaway network `gtest-7821` with fakes: the config loads as uid 1000. `workerHeartbeatAge: null` fails, but **only because of `has()`**: without it, null reads as 0 and passes `< 180`. An age of 200 alerts and then resolves (fake ntfy got both). A push to `_backup` returns 200, and 401 with a wrong token. The disk heartbeat goes red when it lapses. With the vars unset, Gatus exits 2. Mutations (`:latest`, no `:ro`, `4590:8080`, a commented-out env var) each turn a test red. `lib/check.sh` green, 1,333 tests (487 s).
- **Review (Opus):** 0 Critical. Fixed: a broken config edit would stop Gatus, so `skip-invalid-config-update` is now set; the env test accepted `#` lines; D40's timing is corrected. Open, for H3-04/05: **(I1)** the config mount follows `CRATES_SRC`. A deploy from this worktree mounts the worktree, so after the worktree is removed a restart crash-loops. Proposal: `deploy.sh gatus` copies `git show HEAD:deploy/gatus/config.yaml` to `/srv/docker/gatus/config/`, or Gatus is re-upped from `/srv/docker` after the merge. **(I2)** `/srv/docker/gatus` doesn't exist. H3-04 must `mkdir -p` it as mh550 first, or Docker creates it root-owned and Gatus can't write. **(I3)** The heartbeat ticker starts with Gatus, so a missed backup alerts 26–52 h after the last one, and every Gatus restart resets the clock.
- **Live:** none. Only a pull of the Gatus image and throwaway `gt7821-*` containers, all removed. Nothing in `dj` was touched.
- **Next session (H3-03):** push to `_disk` with `GATUS_BACKUP_TOKEN`. **H3-04 is blocked until Michael sets the two vars** (INBOX). `disk` will go red 30–60 min after the deploy until the H3-03 timer runs, so "may stay grey" won't hold for it.
- **Questions for Michael:** (1) D40: should `disk` alert when its pushes stop (my default), or keep its last result? (2) Please set the Gatus vars (INBOX).
- **Proposed changes:** H3-04's step "backup and disk may stay grey" → "backup may stay grey; disk may be red until H3-03's timer is enabled". To fix I3, H3-03's push could also report `backup` from `systemctl show restic-backup.service -p ExecMainExitTimestamp -p ExecMainStatus` (a spec change; Michael's call).

### 2026-10-17 23:00 · H3-01 · passes
- **Changed:** `crates/service.py`: `/api/status` now has `workerHeartbeatAge` (seconds since `worker.heartbeat` beside the crates db was touched; `null` if missing or the db is `:memory:`). New `test_status_reports_the_worker_heartbeat_age` in `tests/test_service.py` (none → null, fresh → under 10, mtime 300 s ago → ~300). Tests 1,315 → 1,316.
- **Verified:** replacing the field with `None` turns the new test red; `lib/check.sh` green, 1,316 tests (488 s).
- **Live:** none (not deployed; H3's later features deploy).
- **Next session:** Gatus can check `[BODY].workerHeartbeatAge` is a number and `< 90` (same limit as `healthcheck.py worker`); null means no heartbeat.
- **Questions / proposed changes:** none.

### 2026-10-17 22:00 · verify H2

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| H2-01 | 1 | read `deploy/restic-backup`; `.harness/check.sh tests/test_restic_backup.py tests/test_install_backup.py`; read `test_order_is_lock_snapshot_mount_backup_unlock_then_forget_and_check` | 32/32 pass; asserts log = lock create, snapshot lock=held, mountpoint, restic backup lock=held, forget lock=free, check lock=free; script order matches | yes |
| H2-01 | 2 | read `test_unmounted_drive_exits_1…`, `test_restic_backup_failure…`, `test_a_failed_snapshot_warns_backs_up_then_fails…` | unmounted: rc 1, "not mounted", no restic/curl; backup fail: no curl; snapshot fail: "WARNING: DB snapshot failed", backup/forget/check still run, rc 1, no curl | yes |
| H2-01 | 3 | read `test_a_held_lock_makes_it_wait…`, `test_past_the_timeout…`, `test_a_lock_file_it_creates…` (+ FIFO/symlink tests) | waits ≥1.2 s then proceeds; timeout 1 s logs "live.lock held for 1 s; backing up anyway" and proceeds; created lock is uid of backup user, mode 0664 (mh550 = uid 1000, `id -u mh550`) | yes |
| H2-01 | 4 | read `deploy/install-backup.sh` and `test_install_backup.py` (dirty ×2, not-on-main, unpushed-main, diff-against-installed, temp targets) | dirty tree and non-origin/main commit exit 1 before any diff or install; diff shown and `[y/N]` asked; targets are temp paths in tests | yes |
| H2-01 | 5 | read INBOX.md and the H2-01 progress entry; `grep -c live.lock /usr/local/sbin/restic-backup`; `ls /usr/local/lib/dj-crates` | INBOX has `cd ~/projects/dj-crate-streaming && git checkout main && git pull && sudo deploy/install-backup.sh`; entry says no sudo; installed script has 0 live.lock and no installed dir, so nothing installed | yes |
| H2-01 | 6 | `/home/mh550/projects/agent-harness/lib/check.sh` | green, 1315 tests (cached for this tree) | yes |
| H2-02 | 1 | read the H2-02 progress entry (21:30) | review's findings: 0 Critical, Important 1 (FIFO/symlink lock) and 2 (failed snapshot exit 0 + heartbeat) fixed, Minors listed; FIFO/symlink tests present and pass | yes |
| H2-02 | 2 | read `docs/backup-plan.md` item 4 against `deploy/restic-backup` | lock path, 30 min wait + message, `sudo -u mh550 …/snapshot-crates-db.sh`, exit 1 on unmounted/failed snapshot, unlock after backup, `_backup` heartbeat with GATUS_BACKUP_KEY all match; no mention of running from ~/projects; `--suffix` exists in the snapshot script | yes |
| H2-02 | 3 | `/home/mh550/projects/agent-harness/lib/check.sh` | green, 1315 tests | yes |

### 2026-10-17 21:30 · H2-02 · passes
- **Review (Opus, `git diff 5efcd02..HEAD` → `/tmp/…/h2.diff`):** 0 Critical. It confirmed that the includes, excludes, tag, forget, check and the mount exit 1 match the installed script. **Important 1** (fixed): root opened `/srv/docker/crates/live.lock` (mh550's directory, so `protected_symlinks` doesn't apply) with `exec 9>>`. A FIFO there hung the job forever, and the unit has `TimeoutStartUSec=infinity` (checked). A dangling symlink made root create its target. Now mh550 creates the file (`sudo -u mh550 install -m 0664`), and root opens only a plain file, read-only (`exec 9<`). Anything else gets "not a plain file I can open; backing up without the lock". **Important 2** (fixed): a failed DB snapshot exited 0 and sent the heartbeat. Now it still backs up, forgets and checks, then exits 1 with no heartbeat (**D39 *default***, pivot spec). Minor, fixed: tests never run the real installed snapshot script (stub `SUDO_NOEXEC`). The installer re-installs a target whose mode or owner drifted. Its header says sudo runs the working-tree installer, so check `git diff origin/main` first. `exec 9<&-` replaces `flock -u`. The `GATUS_BACKUP_KEY` knob is documented. Not done: a 60 s "held for 1 min" test (too slow; the default is still checked by grep), and an installer order test.
- **Changed:** `deploy/restic-backup`, `deploy/install-backup.sh`, `docs/backup-plan.md` (item 4 now follows the script step by step: lock, installed snapshot path, HDD, unlock, heartbeat; it no longer says the job runs from `~/projects`; the table says a missing HDD exits 1), D39 in `docs/specs/2026-10-17-amperfy-pivot.md`, INBOX. Tests 1,312 → 1,315: new FIFO, symlink and mode-drift tests; the snapshot and lock tests were rewritten. The stubs' lock probe now skips non-plain files.
- **Verified:** all 7 new or changed tests were red first. The FIFO and symlink tests are also red against the old script with the new stubs. `lib/check.sh` green, 1,315 tests (488 s).
- **Live:** none. Only read `systemctl show/cat restic-backup.service` (status 0 at 03:41 today; `TimeoutStartUSec=infinity`).
- **Next session (H3-01):** nothing from H2 blocks it. H3-05's `docs/monitoring.md` should say that a red or missing `backup` heartbeat can now also mean a failed DB snapshot.
- **Questions for Michael:** (1) D39: should a failed DB snapshot fail the nightly run (my default, so it shows in systemd and Gatus), or only warn? (2) Optional: the 3 h `TimeoutStartSec` drop-in in INBOX.
- **Proposed changes:** CLAUDE.md's Backups → Status could add "status 0 also means the DB `.snap` files are fresh (D39)", once the H2 script is installed.

### 2026-10-17 20:55 · H2-01 · passes
- **Changed:** new `deploy/restic-backup`, the nightly backup in git. It keeps the installed script's steps and adds four things: it takes `live.lock` first (`exec 9>>`, then `flock -w 1800`); past 30 min it logs "live.lock held for 30 min; backing up anyway", and if the lock can't be opened it warns and backs up anyway. If it creates the lock file, that file is `install -m 0664 -o mh550 -g mh550`. It snapshots with the installed copy, `sudo -u mh550 /usr/local/lib/dj-crates/snapshot-crates-db.sh`; a failure logs "WARNING: DB snapshot failed" and the backup goes on. It releases the lock after `restic backup`, before forget and check. Only when every step succeeds does it POST `${GATUS_BACKUP_URL%/}/api/v1/endpoints/_backup/external?success=true`, with the Bearer token piped on stdin (`-H @-`, never in `ps`); a failed POST only warns. New `deploy/install-backup.sh` (sudo, Michael only): refuses a dirty tree or a HEAD that isn't on **origin/main**, runs git as the checkout's owner with `--no-optional-locks` (never root: repo config can name commands), takes the files from `git show HEAD:` (so it installs exactly what it diffed), shows `diff -u` against what is installed, asks `[y/N]`, installs the snapshot script first, then restic-backup (0755), and prints the commit. The snapshot script's header now names the installed path. Tests 1,283 → 1,312 (`tests/test_restic_backup.py` 17 with stub restic/mountpoint/curl/sudo, `tests/test_install_backup.py` 12 with a temp repo and a bare origin).
- **Verified:** `lib/check.sh` green, 1,312 tests (487 s). Mutations each turn a test red: no `flock -u` → order test; no lock wait → lock tests; mode 0644 → lock-file test; no snapshot warning → 2 tests; `restic check || true` → no-heartbeat test; no main check / no dirty check → refusal tests; no `--no-optional-locks` → the index-mtime test.
- **Review (Opus, `/tmp/…/h2-01.diff`):** 0 Critical. Important, both fixed: (1) git ran as root under `safe.directory`, so a `core.fsmonitor` in the checkout's config would run as root; git now runs as the owner. (2) The clean check, the diff and the install read the working tree at three different moments; install now uses `git show HEAD:`. Minor, fixed: local `main` → `origin/main`; snapshot script installed first; token off the command line; trailing slash; `Y` accepted; new tests for the default snapshot path, a failed forget, and the index (behavioural instead of a grep). Minor, left as is: `restic backup` exit 3 (snapshot saved, some files unreadable) fails the run and sends no heartbeat, the same as today. H3's docs/monitoring.md should say so. Two tests still grep the source (the 30-min default, `install -o`), because the root-only behaviour can't run as mh550.
- **Live:** none. No sudo, nothing installed, `/etc/restic/env` not read (only `/usr/local/sbin/restic-backup` was read, to compare).
- **Next session (H2-02):** `docs/backup-plan.md` item 4 still describes the old `~/projects/…/snapshot-crates-db.sh || true` line; that is H2-02's step. The Gatus key defaults to `_backup` (an endpoint named `backup` with no group); `GATUS_BACKUP_KEY` overrides it if H3 puts it in a group. The installed script stays the old one until Michael installs.
- **Questions for Michael:** none new. Your install command is in INBOX, for after H2 is merged: `cd ~/projects/dj-crate-streaming && git checkout main && git pull && sudo deploy/install-backup.sh`.
- **Proposed changes:** none.

### 2026-10-17 20:10 · verify H1

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| H1-01 | 1 | ran snapshot script with tmp WAL c.db/n.db (CRATES_DB, NAVIDROME_DB), no args; `pragma integrity_check` on each .snap; also read tests/test_snapshot_script.py (23 pass in the 50-test subset) | c.db.snap + n.db.snap written, exit 0, both print ok | yes |
| H1-01 | 2 | `--suffix pre-x` after md5sum of the two .snap files | c.db.pre-x.snap and n.db.pre-x.snap written, integrity ok; md5sum -c: both .snap unchanged | yes |
| H1-01 | 3 | made n.db garbage, then mode 000; ran script | exit 1 both times ('file is not a database' / 'unable to open'); md5sum -c: existing snapshots unchanged; no .new left in ls | yes |
| H1-01 | 4 | NAVIDROME_DB=nope.db | one stderr note 'no navidrome.db … skipped', c.db.snap written, exit 0 | yes |
| H1-01 | 5 | `git diff 60a23d0..HEAD -- CLAUDE.md`; read progress H1-01 entry | H1-01 did not touch CLAUDE.md (only H1-03's commit 198ce81 did, --no-deps, flagged to Michael); H1-01 entry has 'Proposed changes' with Snapshots wording | yes |
| H1-01 | 6 | `/home/mh550/projects/agent-harness/lib/check.sh` | green, cached, 1283 tests | yes |
| H1-02 | 1 | read tests/test_worker.py:522 test_cli_worker_once_writes_the_heartbeat_beside_crates_db | runs `worker --once` on fakes, asserts tmp_path/worker.heartbeat is a file with mtime <10 s old; test passes (subset run) | yes |
| H1-02 | 2 | `healthcheck.py worker` with CRATES_DB in scratch, WORKER_POLL_S=30: missing / fresh / touched 5 min ago | missing exit 1 'no heartbeat'; fresh exit 0 'healthy: 0 s old (limit 90 s)'; stale exit 1 '300 s old' | yes |
| H1-02 | 3 | `CRATES_PORT=1 healthcheck.py crates` timed; read tests/test_healthcheck.py:84 and :103 | closed port exit 1 in 0.07 s; test_crates_is_healthy_when_status_answers_200 asserts code 0 against CrateServer /api/status; closed-port test asserts code 1 and took<6 | yes |
| H1-02 | 4 | lib/check.sh | green, 1283 tests | yes |
| H1-03 | 1 | `CRATES_SRC=$PWD GIT_SHA=test docker compose -f deploy/compose.yml config` | exit 0; healthcheck blocks under crates, navidrome, worker; depends_on service_healthy for crates and worker | yes |
| H1-03 | 2 | read H1-03 progress Live entry (verbatim commands); `docker image ls dj-crates` | flock + deploy.sh recorded outside backup window, rollback b2df730b1d recorded and image still present; I did not redeploy (not needed for verify) | yes |
| H1-03 | 3 | `docker compose ps`, `docker inspect dj-worker-1 dj-crates-1` | crates, worker, navidrome all 'Up (healthy)' on dj-crates:caef38ce9b; Check pass recorded in progress (not re-run live) | yes |
| H1-03 | 4 | read docs/worker.md 559-590 | 'Deploying, and what healthy means': what healthy is per service, docker compose ps/inspect commands, 2-minute expectation | yes |
| H1-03 | 5 | lib/check.sh; ran tests/test_compose.py in subset | green, 1283 tests; 50 passed in subset | yes |
| H1-04 | 1 | read progress H1-04 entry | Opus review: 0 Critical, 1 Important (runbooks' up -d) + Minor, with fixes and test-first notes listed | yes |
| H1-04 | 2 | read docs/backup-plan.md 32-44 | says script now writes crates.db.snap AND navidrome.db.snap; runs from ~/projects/dj-crate-streaming so main must be checked out there | yes |
| H1-04 | 3 | lib/check.sh | green, 1283 tests | yes |

### 2026-10-17 19:30 · H1-04 · passes
- **Changed:** `docs/backup-plan.md` item 4: the nightly job's first line (`sudo -u mh550 /home/mh550/projects/dj-crate-streaming/scripts/snapshot-crates-db.sh || true`, read from `/usr/local/sbin/restic-backup`) now writes `crates.db.snap` **and** `navidrome.db.snap`. It runs from `~/projects/dj-crate-streaming`, so **main must be checked out (and pulled) there**. `|| true` hides a failed snapshot. The recovery order puts the `.snap` files in place. Fixes from the review are listed below. Tests 1,281 → 1,283.
- **Review (Opus, whole H1 diff `/tmp/…/h1.diff`, `git diff 60a23d0..HEAD`):** 0 Critical. **Important 1** (fixed): five runbook lines (`docs/worker.md` settings + policy.toml, `docs/architecture.md` §6, §8 and the M-steps) still said `docker compose up -d [--build] crates worker` from `/srv/docker`. That recreates Navidrome, crates and worker from main's compose file without healthchecks. They now say `scripts/deploy.sh` from a clean, pushed checkout. Minor, fixed test-first: `.backup` had no busy timeout, so a locked source failed at once. It now runs `sqlite3 -cmd '.timeout 10000'`, and a new test holds an exclusive lock for 1.5 s: red "database is locked", then green. `healthcheck.py` did not catch `http.client.HTTPException`, so a garbage reply printed a traceback. A new test was red, then green. Minor, docs only: the snapshot header no longer claims the rename of the two databases is atomic, and `docs/worker.md` names the Soulseek search (up to 30 s, no beat) as a step that can read unhealthy. No simplification needed.
- **Verified:** `lib/check.sh` green, 1,283 tests (483 s). The two new tests failed before their fixes. `grep -n "up -d" docs/worker.md docs/architecture.md` leaves only the `start worker` comment and the historical D25 question.
- **Live:** none.
- **Next session (H2-01):** `/usr/local/sbin/restic-backup` is world-readable (677 bytes, 2026-10-17 00:19). Its snapshot line ends in `|| true`.
- **Questions for Michael:** none new (D38 is still open; please also confirm or revert H1-03's `--no-deps` in CLAUDE.md's Check). Until main has H1, please run `git -C ~/projects/dj-crate-streaming checkout main && git -C ~/projects/dj-crate-streaming pull` (yours) so the nightly run snapshots navidrome.db and `/srv/docker/compose.yml` has the healthchecks.
- **Proposed changes:** none.

### 2026-10-17 18:42 · H1-03 · passes
- **Changed:** `deploy/compose.yml` healthchecks: navidrome `wget -q --spider -T 5 http://127.0.0.1:4533/ping` (the image has busybox wget, no curl); crates and worker `python scripts/healthcheck.py crates|worker`. All three: every 30 s, 10 s timeout, 3 retries, `start_interval` 5 s; start_period navidrome 60 s, crates 30 s, worker 120 s. crates and worker `depends_on: navidrome: service_healthy` (worker: gluetun `service_started`). New `tests/test_compose.py` (10 tests, reads `docker compose config --format json`, project dir in tmp). `docs/worker.md` → "Deploying, and what healthy means" (table, `docker compose ps`, `docker inspect … .State.Health`). Runbooks in `docs/worker.md` and `docs/architecture.md`: `run --rm --no-deps worker …`, and resume with `start worker` instead of `up -d worker`. **CLAUDE.md's Check now has `--no-deps`.** Reason: `/srv/docker/compose.yml` links to `~/projects/dj-crate-streaming` (main, no healthchecks), and a `run` with dependencies recreates Navidrome whenever that file differs from what runs. Tests 1,271 → 1,281.
- **Verified:** `lib/check.sh` green, 1,281 tests (484 s). The step 1 command exits 0, with a healthcheck on all three services. Live, at 18:40:39, 23 s after the deploy, crates, worker and navidrome all show `(healthy)`. Health logs: "worker: healthy: heartbeat 5 s old (limit 90 s)", "crates: healthy: …/api/status: 200". A dry run of the Check showed it recreates nothing, and the Check after the deploy passed.
- **Review (Opus, `/tmp/…/h1-03.diff`):** 0 Critical. Important (fixed): the runbooks' `run` and `up -d worker` from `/srv/docker` would still recreate Navidrome and the worker from main's file. Minor (fixed in the docs): a rollback to `dj-crates:b2df730b1d` reads `(unhealthy)` for good, because that image has no `healthcheck.py` (checked); after a reboot, `depends_on` does not apply; a long tick can read unhealthy; the wget test now pins `--spider` and `-T`. Not done: the `compose.yml` header still says `up -d navidrome`, which is fine once main has this.
- **Live (verbatim, all outside 03:15–04:30):** restic `ExecMainStatus=0` at 03:41:34, inactive. Running before: `dj-crates:b2df730b1d`, which is the rollback. `cd /srv/docker && flock -n /srv/docker/crates/live.lock docker compose run --rm --no-deps worker sh -c '…export && …check'` → exit 0, "ok: every playlist file matches Navidrome and every entry exists". `flock -n /srv/docker/crates/live.lock scripts/snapshot-crates-db.sh --suffix pre-dj-2026-10-17-h1-03` → exit 0, integrity ok ×2 (`/srv/docker/crates/crates.db.pre-dj-2026-10-17-h1-03.snap`, `/srv/docker/navidrome/navidrome.db.pre-dj-2026-10-17-h1-03.snap`, `pragma integrity_check` ok on both). `flock -n /srv/docker/crates/live.lock scripts/deploy.sh` (18:39:57–18:40:16) → exit 0, `dj-crates:caef38ce9b`. Navidrome was recreated too (its config changed), about 10 s down. Then the same Check → exit 0, ok.
- **Next session (H1-04):** until main has this commit and `~/projects/dj-crate-streaming` is pulled, any `docker compose up` from `/srv/docker` (the docs' `up -d --build crates worker` after a policy edit) recreates navidrome, crates and worker without healthchecks. Deploy with `scripts/deploy.sh` from this worktree. Also: during the first suite run I stopped it with `pkill -f 'pytest -q -x -p no:cacheprovider'`. That pattern would also have matched another session's pytest at that moment. None was running afterwards, and next time I would kill by PID.
- **Questions for Michael:** none new (D38 is still open). Please confirm the `--no-deps` I added to CLAUDE.md's Check, or revert it.
- **Proposed changes:** after the merge, `git -C ~/projects/dj-crate-streaming pull` (yours) so `/srv/docker/compose.yml` carries the healthchecks.

### 2026-10-17 19:05 · H1-02 · passes
- **Changed:** `sourcing/worker.py`: `Worker(heartbeat_path=…)` touches the file when a tick ends and at each poll while fetch waits on a download or a scan (new `sleep` hook on `sourcing/fetch.py`). A tick that raises does not beat. `run` removes an earlier heartbeat before its first tick, so a new container is healthy only after it has ticked. A failed write is logged once until it works again. `sourcing/cli.py` passes `<dirname(CRATES_DB)>/worker.heartbeat`. New `scripts/healthcheck.py crates|worker` (stdlib, runs as a plain file): crates means `/api/status` answers 200 within 5 s on `127.0.0.1:$CRATES_PORT`, never through a proxy; worker means the heartbeat is younger than max(90, 3 × `WORKER_POLL_S`) s. Every failure, a usage error included, exits 1 (Docker reserves 2). `docs/worker.md` → "Is it alive?". Tests 1,250 → 1,271 (`tests/test_healthcheck.py` 15, `test_worker.py` +5, `test_fetch.py` +1).
- **Verified:** `lib/check.sh` green, 1,271 tests (482 s). `worker --once` with `CRATES_DB=tmp/c.db` leaves `tmp/worker.heartbeat` less than 10 s old. By hand: a fresh heartbeat gives "healthy: heartbeat 0 s old (limit 90 s)", exit 0. A 100 s old one gives exit 1, a missing one "no heartbeat at …" exit 1, and `CRATES_PORT=1` "Connection refused" exit 1 in 0.07 s. In the tests a server that never answers gives "timed out" and exit 1 in under 6 s, and a 502 (Navidrome down) gives 1. Mutations: without the fetch hook, the scan-wait test goes red. Without the end-of-tick beat, 3 tests go red.
- **Review (Opus, `/tmp/…/h1-02.diff`):** 0 Critical. Fixed test-first: Important 1 (the first version also beat at the start of a tick, so a worker failing every tick stayed healthy). Also fixed (Minor): an untested download-wait beat (new fetch test); a weak failed-tick test; the log-once warning coming back after a recovery; two flaky age assertions; `http_proxy` in the environment (new test); the old container's heartbeat after a redeploy (it is now removed at start).
- **Next session (H1-03):** the compose healthchecks are `["CMD", "python", "scripts/healthcheck.py", "worker"]` and `["CMD", "python", "scripts/healthcheck.py", "crates"]` (WORKDIR /app). Give the worker a `start_period` longer than its first tick (it reconciles and exports; 120 s is a guess). Set a Docker `timeout` of about 10 s: the script's 5 s is per socket operation. Crates reads unhealthy while Navidrome is down (502). `/api/status` also walks `/srv/_trash` (`trash.summary`), so after a big duplicate cleanup a cold walk could exceed 5 s. Watch for that before H3 alerts on it.
- **Live:** none.
- **Questions for Michael:** none new (D38 from H1-01 is still open).
- **Proposed changes:** none.

### 2026-10-17 18:06 · H1-01 · passes
- **Changed:** `scripts/snapshot-crates-db.sh` now snapshots crates.db **and** navidrome.db (`NAVIDROME_DB`, default `/srv/docker/navidrome/navidrome.db`) with `sqlite3 .backup` → `pragma journal_mode=delete` (one self-contained file, no `-wal`/`-shm` beside it) → `integrity_check`. `--suffix <name>` (letters, digits, `.`, `_`, `-`) writes `<db>.<name>.snap`; no arguments still writes `<db>.snap`. A missing navidrome.db: a stderr note, crates.db only, exit 0. A missing, unreadable or corrupt source: exit 1, and no snapshot is replaced (copies go to `<snap>.new` and are renamed only once both pass; a trap removes them). Bad arguments: exit 2. New `tests/test_snapshot_script.py` (23 tests); `docs/worker.md` step 1 and `docs/hard-won-facts.md` describe the new script. Tests 1,227 → 1,250.
- **Verified:** `check.sh` green, 1,250 tests (465 s). The tests cover: WAL rows that sat only in `-wal` reach both snapshots, and the sources stay in WAL mode. `--suffix pre-x` leaves both `.snap` files byte-identical. Each source spoiled 3 ways (garbage, mode 000, a zeroed mid page that `.backup` copies and `integrity_check` catches) × nightly/suffix gives exit 1 with both earlier snapshots unchanged and no `.new` left. By hand: "integrity_check said: Error: stepping, database disk image is malformed…", ".backup failed: … unable to open database file".
- **Review (Opus, `/tmp/…/h1-01.diff`):** 0 Critical. Fixed: the docs claimed the nightly job already copies navidrome.db (it runs `~/projects/dj-crate-streaming`'s copy, so `navidrome.db.snap` appears only once that checkout has this version); a `'` in `--suffix` broke `.backup` and left a stray file in the cwd (suffix whitelist, test); the skip note now goes to stderr; a test that the source keeps WAL mode. Kept on purpose (Important 1 → D38 *default*): all or nothing, so a broken navidrome.db also keeps the nightly `crates.db.snap` at its last good copy. Not done (Minor): a `'` in `CRATES_DB`/`NAVIDROME_DB` paths; an unset `NAVIDROME_DB` whose default path is missing is skipped, not an error.
- **Next session (H1-02):** nothing live was touched. A live run's restore point is now `scripts/snapshot-crates-db.sh --suffix pre-<run-id>` (as mh550, from the worktree).
- **Live:** none.
- **Questions for Michael:** D38: should one failing database still let the other's nightly snapshot refresh (each on its own, exit 1)? Today's default keeps both at the last good pair.
- **Proposed changes:** CLAUDE.md → Snapshots, replace the two bullets with: "`scripts/snapshot-crates-db.sh --suffix pre-<run-id>` (from the worktree) writes `/srv/docker/crates/crates.db.pre-<run-id>.snap` and `/srv/docker/navidrome/navidrome.db.pre-<run-id>.snap`, each checked with `integrity_check`; the nightly backup's no-argument call writes the `.snap` files and never these. Pass: exit 0 and one "integrity ok" line per database." H1-04 should also update `docs/backup-plan.md` item 4 (it still suggests a one-line `.backup` of crates.db only).

### 2026-10-17 17:43 · verify N1F

| Feature | Step | What you ran or read | What you saw | Holds |
|---|---|---|---|---|
| N1F-01 | 1 | read `test_trash_refuses_unless_a_scan_finished_after_the_newest_repoint_log` (tests/test_duplicate_cleanup.py:1012) + `test_main_trash_exits_1_naming_the_scan` | asserts CleanupRefused 'no Navidrome scan finished after the newest repoint log', nothing moved/forgot/scanned; CLI exits 1 with that text | yes |
| N1F-01 | 2 | read `test_a_scan_after_the_newest_repoint_log_lets_trash_proceed` + the tail of the test above; ran the file (101 pass) | lastScan newer: s3 'moved to'; existing trash tests unchanged and green | yes |
| N1F-01 | 3 | read `test_an_extra_whose_file_on_disk_is_not_the_planned_file_is_refused` (:1077) | s3 refused with path and both sizes ('38 bytes on disk, navidrome.db says N, the plan says N'); s4 moved | yes |
| N1F-01 | 4 | read docs/worker.md lines 420-436, 469 | trash section states the no-scan refusal and the size refusal with wording matching the code | yes |
| N1F-01 | 5 | `/home/mh550/projects/agent-harness/lib/check.sh`; `.harness/check.sh tests/test_duplicate_cleanup.py` | green, cached for tree, 1227 tests; subset 101 passed | yes |
| N1F-02 | 1 | read `test_a_scan_that_starts_mid_trash_is_waited_for_then_one_more_and_a_file_a_playlist_took_goes_back` (:1118) | scan starts after first move; seen==[False,False], 2 startScan; put-back line (restored True) in trash log; 2 cleanup events; other extra untouched | yes |
| N1F-02 | 2 | read `test_a_dry_run_repoint_previews_every_playlist_the_real_run_would_refuse` (:1174) | smart, other-owner, hidden row each 'would refuse' with reason; spy on playlist_edit.checked_entries sees all 4; no updates/scans/log/db change; CLI exits 1 | yes |
| N1F-02 | 3 | check.sh as above | green, 1227 tests | yes |
| N1F-03 | 1 | read the N1F-03 and N1F-02 progress entries | lists review 1 findings I-A, I-B and review 2 fixes, each with test-first evidence | yes |
| N1F-03 | 2 | read docs/worker.md 454-479 (error table) and grep refusals in scripts/duplicate_cleanup.py | table names lock, scan, unmount, no-scan, size, same-file, still in, in use, added/put back, failed rows; no refusal found missing | yes |
| N1F-03 | 3 | check.sh as above | green, 1227 tests | yes |

All 11 steps hold; no `passes` changed.

### 2026-10-17 23:20 · N1F-03 · passes
- **Changed:** `scripts/duplicate_cleanup.py` `_trash`: the closing scan, and the scan after a put-back, now wait out a scan that is already running before starting ours (`fresh_scan` = `wait_for_scan` or `scan_and_wait`). The refusal path and the normal path share one `closing_scan()`. Every file that stays moved gets its trash-log line (try/finally), also when its put-back during the move failed or `references()` raised, and it stays in `moved`, so the recheck after the scan retries. Put-back messages now say "beets no longer lists it" only when beets did forget it, otherwise "beets still lists it". `docs/worker.md` trash has a table of every line trash can print and what to do. The plan §trash and the module docstring are updated. Tests 1,223 → 1,227.
- **Review 1 (Opus, whole N1F diff `/tmp/…/n1f.diff`):** 0 Critical. **I-A** (a scan starting during the *last* move was never waited for, so `scan_and_wait` returned when that pre-move scan ended) and **I-B** (a move whose put-back failed got no trash line, so the next run said "failed: gone from the library" instead of putting the file back from the log) are both fixed test-first. Minor M-b (the beets wording) is fixed. Not done: M-a (no repoint log beside `--plan` skips I1 silently), M-c (a changed trash root makes the earlier-run put-back a generic `failed: ValueError`), M-d (a disk error in the refusal-path recheck replaces the refusal with a traceback), M-e (the I3 test does not pin the request order).
- **Review 2 (Opus, the fix diff `/tmp/…/n1f-03.diff`):** both fixes correct, and all new tests fail on the old code (I checked this myself too). Fixed: the scan after a put-back had the same gap as I-A (new test), the doc advice for `FileExistsError`, the missing stderr and `trash log:` rows, the `moved` annotation. Rejected: "an `_event` raising after a successful restore leaves a stale line". `_event` catches its own errors (`duplicate_cleanup.py:267`), so it cannot raise there. Not done (Minor): a put-back that failed "during the move" is reported as "after the move" once the recheck runs. No tests yet for `references()` raising inside the move, or for a failed put-back that succeeds at the recheck.
- **Verified:** `check.sh` green, 1,227 tests (466 s). Each of the 4 new tests failed before its fix: `seen == [True]`, no trash line, "beets no longer lists it", `seen == [False, True]`.
- **Next session (H1-…):** N1F is done. CLAUDE.md's gate on `trash` beyond `--dry-run` (I1, I2) is now met in code, but `lastScan` on live Navidrome is still unconfirmed (N1F-01's command), and only Michael can lift the gate.
- **Live:** none.
- **Questions for Michael:** none new (D35 and D36 are still open; the `lastScan` command from N1F-01 is still open).
- **Proposed changes:** none.

### 2026-10-17 22:10 · N1F-02 · passes
- **Changed:** `scripts/duplicate_cleanup.py` `trash`: a scan found mid-run with files moved is waited for (new `subsonic.client.wait_for_scan`), then one more scan runs and is waited for, then every moved file is re-read and put back if a playlist holds it (`restored` trash line, `cleanup` event, one more scan) before `CleanupRefused` (I3). A playlist row on an extra that an earlier run trashed (its scan did not finish) now puts the file back from the trash log's `trash_path` instead of only `failed` (review I-1). `repoint --dry-run` goes through `playlist_edit.repoint_everywhere(dry_run=True)`, the same read-only `checked_entries` checks with no hooks and no write: "dry run: would refuse <playlist>: <why>; …; would repoint <names>", exit 1 like the real run (I4). Fake: `state.scan_polls` lets a running scan end by itself. Docs: module docstring, `docs/worker.md` repoint + trash bullets, N1 plan §trash and safety table. Tests 1,216 → 1,223, check green (462 s).
- **Verified:** with the hourly scan starting after the first move, both of ours start only once it is over (`seen == [False, False]`, 2 `startScan`), and the moved song Amperfy added meanwhile is back on disk with a `restored` line and both events, while the other extra was never moved. With no playlist taking it, the file stays trashed after 1 scan. A scan that never ends gives `(scan): failed: … still running`, and the file is still re-checked. The dry run with a smart playlist, another owner's playlist and a hidden row in Disco Edits lists all three under "would refuse" and "would repoint Fine". `checked_entries` is called for pl-1/2/8/9, with no `updatePlaylist`, no scan, no log, navidrome.db bytes unchanged and `main` exit 1. Mutation: without the wait, the I3 test goes red.
- **Review (Opus, `/tmp/…/n1f-02.diff`):** 0 Critical. Fixed: Important I-1 (the fix held only when the waits succeeded), test-first. Also fixed, Minor: M-2 (the dry run keeps the real run's wording: `skipped: smart playlist`, `failed: …`), M-3 (the repoint docstring), M-5 (tests for the dry-run hooks and `wait_for_scan` errors), M-6 (runbook: a mid-run scan can hold the lock about 30 min, so start trash well before 03:15) and M-7 (the fake syncs when its scan ends). Not done: M-1 (a put-back *during* the move together with a scan found right after gets no scan of ours, a very narrow window; the row stays hidden until the hourly scan) and M-4 (the refusal still reads "a scan is running" after we waited it out).
- **Next session (N1F-03):** review the whole N1F diff (`git diff 9d5ad9f..HEAD -- scripts subsonic crates docs tests`). M-1 and M-4 above are candidates. `docs/worker.md`'s trash section now names: lock, scan running, unmounted, no scan after the newest repoint log, size mismatch, still in playlists, in use, put back (during / after the move / after an earlier run), and the mid-run scan.
- **Live:** none. `lastScan` on live Navidrome is still unconfirmed: Michael, see N1F-01's command.
- **Questions for Michael:** none new (D35 and D36 are still open).
- **Proposed changes:** none.

### 2026-10-17 21:05 · N1F-01 · passes
- **Changed:** `scripts/duplicate_cleanup.py` `trash` (dry run too) refuses to start unless `getScanStatus`' `lastScan` (parsed as Go RFC 3339 with nanoseconds, `Z` or an offset) is later than the newest `repoint-*.jsonl` beside the plan was last written (its mtime). An absent or odd `lastScan` also refuses; with no repoint log, nothing is needed (I1). Per extra, it refuses a file whose size on disk is not navidrome.db's `media_file.size` or the plan's new `size` field, naming the path and the sizes; the other extras still move (I2). The fake's `lastScan` is now a real Go-style time, set by `startScan`. The test fixture's `media_file.size` now matches the files on disk, and `tr` writes its repoint log as `cleanup/repoint-1.jsonl` (assertions unchanged). Docs: `docs/worker.md` trash bullets, plan-file schema and safety table. Tests 1,199 → 1,216, check green (460 s).
- **Verified:** new tests cover a refusal naming `repoint-2.jsonl` and `lastScan` (nothing moved, no scan, no trash log), a dry run that refuses the same way, `main` exit 1, the run that proceeds after a later scan, missing `lastScan`, no repoint log, and parse cases. On size: s3 is refused with "38 bytes on disk, navidrome.db says N, the plan says N" while s4 moves; a new file that a scan has since recorded is refused by the plan's size alone; an N1 plan without sizes still works. Mutation checks: disabling either check turns its tests red.
- **Review (Opus, `/tmp/…/n1f-01.diff`):** 0 Critical. One Important, fixed test-first: a scan after a new download makes `media_file.size` agree with the new file, so the plan now records `size`. Minor, not done: (a) "finished after" is not "started after", since a scan already running during the last write passes (Navidrome exposes no start time); (b) the fake sets `lastScan` at `startScan` even while a test keeps `scanning=True`; (c) a `repoint-*.jsonl` removed between glob and stat gives a traceback (fails safe). Minor (d), the doc wording, is fixed.
- **Next session (N1F-02):** `tr` now uses `cleanup/repoint-1.jsonl`; a test that needs "repoint after the last scan" uses `newer_repoint_log(tr, seconds)` (an mtime relative to `srv.state.last_scan`). Plans written before this commit have no `size` (only the db check applies): re-run `plan` before any trash.
- **Live:** none. A read-only `getScanStatus` from the worker container, to confirm `lastScan` live (CLAUDE.md's last gate before trash), was denied by the session's permission classifier. Michael, please run it and paste the output in INBOX: `cd /srv/docker && docker compose exec -T worker python3 -c "from crates.service import Config; from subsonic.client import SubsonicClient; c=Config.from_env(); print(SubsonicClient(c.subsonic_url,c.username,c.password).scan_status())"`. PASS: `lastScan` looks like `2026-10-17T…Z` (or `+hh:mm`) and moves after a scan to the "Scan completed" time in Navidrome's log.
- **Questions for Michael:** none new (D35 and D36 are still open).
- **Proposed changes:** N1F-01 step 2 should say "existing trash tests' assertions unchanged": the shared fixture had to change (sizes, repoint log location).

### 2026-10-17 verify N1
- N1-01 · holds
- N1-02 · holds
- N1-03 · holds
- N1-04 · holds
- N1-05 · holds
- check.sh green (1199 passed), imports ok.

### 2026-10-17 06:20 · N1-05 · passes
- **Changed:** `scripts/duplicate_cleanup.py`: `main()` shares its args across subcommands, takes SUBSONIC_* via `Config.from_env` and needs `CRATES_DB` *set* and existing for repoint and trash (exit 2). It writes crates.db events (kind `cleanup`): `repointed <playlist> to <keeper>` (new `repoint_everywhere(after_write=…)`), `trashed to <day>/<path>`, `put back from …` (trash-relative). Also a second waited scan after a post-scan put-back, and `build_plan` reads one snapshot. Docs: `docs/worker.md` "Duplicate cleanup" runbook + undo, `docs/architecture.md` §7 row + §8 row, `docs/next-todos.md` item 1 "built (N1), not run live", plan file wording (§repoint as built, events, second scan, step 3 runs in `worker`). Tests 1,188 → 1,199, `.harness/check.sh` green (454 s).
- **Verified:** end-to-end on the fake with env only (`main(["plan"])`, `["repoint"]`, `["trash"]`): s3 and s4 go to `trash/<today>/…`, pl-1 = `[s1,s2,s9]`, pl-2 = `[s9,s8,s5]`, 5 cleanup events, and `export_playlists` export + check give `[]` before and after. Mutation checks: undoing the CRATES_DB guard or the second scan turns their tests red.
- **Review (Opus, `/tmp/…/n1.diff`):** 0 Critical. **Important**, both fixed test-first: (1) an event write that fails (crates.db locked) must never fail a repoint or a move: it is now a stderr note, committed per event; (2) `Config.from_env` falls back to `./data/crates.db`, so `CRATES_DB` must now be set explicitly. **Minor**, fixed: no scan after a post-scan put-back; a dry-run repoint opened (migrated) crates.db; `build_plan` read `playlist_tracks` 115+1 times; `made_at` duplicated `_now`; per-subcommand args. **Minor, not done:** a dry-run trash still opens crates.db read-write (for `song_in_use`); repoint does not check the keeper *on disk*, so clearing a "keeper missing on disk" hold by hand is unsafe (the runbook says leave those); trash does not itself check that a scan ran after repoint (`references()` makes it safe anyway); `_forgotten` re-reads the logs per extra; repoint has no lock of its own (one writer, per the runbook); a startup error is still a traceback.
- **Next session (N2-01):** N1 is done. Live, the runbook runs every command in the `worker` container (`exec` for plan/repoint, `run --rm` for trash and check).
- **Questions for Michael:** none new (D35 and D36 are still open).
- **Proposed changes:** none.

### 2026-10-17 05:05 · N1-04 · passes
- **Changed:** `scripts/duplicate_cleanup.py` gains `trash()`, `CleanupRefused` (carrying `.results`) and a `trash` subcommand (`--plan --navidrome-db --music-root --trash-root --limit --dry-run`; needs an existing `CRATES_DB`, whose folder holds `worker.lock`; forget = `BeetsFiler.forget` only when `DJ_WORKER=1`). `_reverse` now shares `_append` (fsynced JSON line). New `CrateStore.song_in_use(song_id)`: an unfinished `ext-N` filed as the song, an approval in progress, or an open replacement. Tests: 1,154 → 1,188, `.harness/check.sh` green (447 s).
- **Verified (fake):** after repoint, s3's file goes to `trash/<today>/Marshall Jefferson/…/01 - Move Your Body.mp3`. MOVES.txt reads back `mv <quoted trash> <quoted library>`. forget gets the old absolute path, the keeper s9 is untouched, there is one trash line and one waited scan. Before repoint: `refused: still in 2 playlist entries`, nothing moves. Also tested: another user's playlist alone blocks; a running scan, a held lock, or an unmounted library or trash raises before anything happens; a scan that starts mid-run stops before the next move (results attached); `--dry-run` writes nothing; a re-run gives `already gone` and forget is not called twice; a crash between move and forget heals; a row added during the move or before the scan ends → the file is put back; keeper == extra file (hard link) is refused; keeper deleted, missing or off disk; retag; extra moved since the plan; held group; `--limit`; crates.db in-use ×3; `main` with dry run, lock and scan refusals.
- **Review:** an Opus reviewer found 0 Critical, 2 Important and 8 Minor issues. Both Important ones are fixed test-first, plus Minor 3–7, 9 and 10. (1) `already gone` while a playlist row (hidden) still names the song is now `failed`, not a success. (2) A refusal mid-run still re-checks the files it already moved. Minor: a failed forget is retried; a put-back is logged `restored`; library and trash must be mounted (an absent trash would have been created inside the `run --rm` container); crates.db is opened only under the lock; the scan check comes before the playlist read. Not done (Minor 8): a startup error (navidrome.db unreadable, Subsonic down) gives a traceback, not a clean exit 1.
- **Next session (N1-05):** `trash(..., crates_db=Path)` opens the store itself after the lock. Events (kind `cleanup`) are not written yet. `main` reads `SUBSONIC_*` and `CRATES_DB` directly, so move them to `Config.from_env`. The runbook must use `docker compose run --rm worker` with `DJ_WORKER=1`, or beets is not told.
- **Questions for Michael:** none new (D35 and D36 are still open).
- **Proposed changes:** N1-04's last test should read "a copy put back while the first stays in the trash gets '(2)'", because `restore` empties the trash slot, so a restored file goes back to its own name. The "hidden missing row in a third playlist" case can only arise for an extra Navidrome already marks missing, which is the `already gone` path; that is now tested there, with another user's playlist standing in for the third playlist.

### 2026-10-17 04:10 · N1-03 · passes
- **Changed:** `scripts/duplicate_cleanup.py` gains `repoint()`, `failed()` and a `repoint` subcommand (`--plan`, `--navidrome-db`, `--limit`, `--dry-run`; it reads `SUBSONIC_*` directly, and N1-05 moves that to `Config.from_env`). `crates/playlist_edit.repoint_everywhere` gains `before_write(pid, name, before, after)`. The scan wait moved from `identity_backfill._scan` into `subsonic.client.scan_and_wait`, which identity_backfill now calls, with the same messages. The fake's `getScanStatus` now returns `lastScan`, which each `startScan` moves. Tests: 1,134 → 1,154, `.harness/check.sh` green (427 s).
- **Verified (fake):** pl-1 → `[s1,s2,s9]` and pl-2 → `[s9,s4,s5]`, with 2 reverse lines whose `before` is the fixture order. Replaying the log newest first restores every playlist. With a hidden s2, pl-1 is refused and unwritten, pl-2 is repointed, and `main` exits 1. Also tested: an edit made after the plan; keeper deleted or missing → `skipped: keeper missing`; a retag → `skipped: no longer a duplicate of s9`; a held group is never touched; `--limit 1`; `--dry-run` sends no `updatePlaylist` or `startScan` and writes no log; smart and other-owner playlists are reported; a scan that never ends → exit 1.
- **Review:** an Opus reviewer found 0 Critical, 2 Important and 6 Minor issues; the 2 Important and 4 of the Minor are fixed, test-first. (1) The reverse line is now written by `before_write`, after the playlist passes its checks and right before its own write. That means `before` is exactly what the write replaces, even if Amperfy edits the playlist meanwhile, and a refused playlist gets no line. (2) Every run that isn't a dry run and reaches a playlist check scans, so a re-run after a scan timeout cannot exit 0 unscanned. The fixed Minor ones: a keeper equal to its extra is skipped; an exception on one extra is `failed` and the run continues; the `lastScan` string; the spy test. Not done (Minor): the dry run also names smart and other-owner playlists, which the real run will refuse.
- **Next session (N1-04):** `repoint`'s result dict has one key per extra plus `"(scan)"`. Reuse `failed()`, `_recheck(rows, group_of, keeper, extra)`, `_in_scope(plan, limit)` and `scan_and_wait`. Note that `_recheck` checks the keeper by row only; trash must also check the file on disk.
- **Questions for Michael:** none new (D35 and D36 are still open).
- **Proposed changes:** in N1-03, step 4 should read "one line per playlist, written right before *its* write (`before_write`), refused playlists get none", and step 5 should read "scan whenever an extra reached `repoint_everywhere`, not only when a playlist was repointed". The plan file's §repoint says the same; N1-05 should update its wording there.

### 2026-10-17 03:20 · N1-02 · passes
- **Changed:** new `scripts/duplicate_cleanup.py` (`build_plan`, `write_plan`, `render`, `main` with `plan` only; `--limit` ≥ 0, `--out` defaults to `$CLEANUP_DIR` or `/data/duplicate-cleanup`); `bit_rate` in the fake's `NAVIDROME_SCHEMA` and its INSERT; `duplicate_report.load` now closes its connection and orders by `artist, title, id` so the keeper is deterministic. New `tests/test_duplicate_cleanup.py` (13) and 1 fake test: 1,120 → 1,134, `.harness/check.sh` green (413 s).
- **Verified:** the s3/s9 group gives keeper s9 and extra s3 held by Disco Edits and Chicago 86; pl-1 → `[s1,s2,s9]`, pl-2 → `[s9,s4,s5]`. Also tested: both lossless and keeper missing on disk are held with no playlists entry; `--limit 1` through the CLI; two runs equal apart from `made_at`. The db bytes, the db directory listing, the fake's playlists, the music tree and Subsonic requests (none) are unchanged. A spy shows every sqlite connect is `mode=ro`; a read-write `open_ro` fails that test. An Opus review found 0 Critical, 2 Important (the read-only test proved nothing; reads from separate connections could raise `KeyError`) and 7 Minor issues; all are fixed.
- **Next session (N1-03):** s9 is added in the test fixture (`add_song`), not in `SAMPLE_SONGS`, so other tests are unaffected; reuse `lib`, `add_song` and `second_group`. `plan` never sets `keeper missing in Navidrome`, because `load()` returns present rows only (as the plan file says); repoint/trash must re-check it themselves. The fake's `getScanStatus` still needs `lastScan`.
- **New behaviour (safety):** re-running `plan` copies an existing `plan.json` to `plan-<its made_at>.json` (never overwritten, via `free_path`) before writing the new one atomically, so a hold you cleared by hand is not lost silently. Held groups are always listed; `--limit` counts only groups to act on.
- **Questions for Michael:** none new (D35 and D36 from N1-01 are still open).
- **Proposed changes:** N1-02 step 1 "add … a flac copy s9" should say "in the test fixture" (adding it to `SAMPLE_SONGS` would change every fake-based test).

### 2026-10-17 02:49 · N1-01 · passes
- **Changed:** new `docs/plans/2026-10-17-n1-duplicate-cleanup.md` (plan → repoint → trash design, plan JSON schema, holds, recompute rule, reverse logs, lock rule, safety-test table, tasks N1-02..05, staged live runbook); ledger rows `D35 *default*` and `D36 *default*` in `docs/specs/2026-10-17-amperfy-pivot.md`. Docs only; tests 1,120 → 1,120 (`.harness/check.sh` green, 406 s).
- **Verified:** facts recounted from `docs/duplicates-report.md` (102 groups, 115 extras, 59 in a playlist, 9 lossless beside a lossless keeper; the 9 held groups hold **14** extras, so the end state is 730 songs, not 716). An Opus reviewer checked the plan against the code: 1 Critical and 5 Important findings, all folded in. The Critical one: re-check `references()` right after each move and restore the file on a late reference, as `replace._trash` does. The Important ones: run check via `docker compose run --rm worker`, since the crates container has no `/srv/music`; export before each check; `repoint` waits for its scan (reuses `identity_backfill._scan`, `lastScan` must move); one-line reverse log per playlist; 730.
- **Next session (N1-02):** the plan's §plan says what `plan` writes. The fake needs `bit_rate` in `NAVIDROME_SCHEMA`; N1-03 also needs `lastScan` in the fake's `getScanStatus`.
- **Questions for Michael:** (1) **D35:** groups with two lossless copies (9 groups, 14 extras) are held, listed only, until you set `"hold": null` in `plan.json`. OK, or trash them too, as D31 literally says? (2) **D36:** `trash` runs only with the worker stopped (`docker compose stop worker`, it takes `worker.lock`); `plan` and `repoint` run beside it. OK?
- **Proposed changes:** N1-03 step "reverse log … the after list is the one read back" → `after` = expected `_remap`, written before the call (`rewrite`'s readback already guarantees equality); add "waits for its scan (`lastScan` moves)". N1-04 add: re-check `references()` after the move and `restore` on a hit; scan check before every move; already-gone checked before the recompute; `forget` on already-gone only when no trash-log line names it; keeper ≠ extra (`samefile`); refuse an extra in use by an unfinished approval. N1-05 runbook: "check" = export + check in the worker image.

---

## 2026-10-17 initializer (Fable) — feature list written

**Features per milestone:** N1 duplicate cleanup 5 · N2 imported marker 4 · N3 vanished playlist 3 · N4 placement 5 ·
N5 docs + whole-run review 2 = **19 features**. Nothing is built yet. Suite at start: 1,120 passed in 410 s
(`.harness/check.sh`, cached per code tree by `.harness/init.sh`).

### What a worker must know about the code

**Where things live**
- `crates/store.py` (881 lines): `SCHEMA` string at the top creates every table with `CREATE TABLE IF NOT EXISTS`;
  `_migrate()` adds columns to old DBs. New tables go into `SCHEMA` (tests open `CrateStore()` in memory and
  `CrateStore(tmp_path/...)` on disk). `store.log(playlist_id, song_id, kind, detail)` is the events table; call
  `store.commit()` after writes. `imported_entries` (D13) and `external_wanted.playlist_id/position` are the hooks
  N2 and N4 build on. `in_flight(status, reason)` says which rows reconcile must not touch.
- `crates/playlist_edit.py` (187 lines): the only index editor. `checked_entries`, `rewrite(before, after)`,
  `repoint_everywhere(client, db, old, new) -> {name: result}`, `references(db, song_id)` (hidden rows included).
  Refusals are `EditRefused` subclasses: `PlaylistSkew`, `PlaylistChanged`, `NotEditable`, `NotOwned`, `StaleSlot`.
  `EditNotKept` means the write was sent and the readback differs. Reuse these; do not write `updatePlaylist` anywhere else.
- `crates/trash.py`: `move_to_trash(rel, music_root, trash_root, before=None) -> Path` writes the reverse `mv` line to
  `<trash>/<day>/MOVES.txt` *before* moving, never overwrites (`free_path`). `restore` puts a file back.
- `sourcing/replace.py`: the M8 resumable copy replacement. Read its docstring for the licence and step order; the
  cleanup (N1) does **not** reuse its jobs (they need a fingerprint `replaceable` licence that tag-based duplicate
  groups do not have), but it copies the step order and the "references empty before any move" rule.
- `scripts/dedupe_copies.py`: the M3 plan → repoint → trash pattern; its `remap(entries, replace)` is what the plan's
  `after` lists use; its `trash` refuses while `playlist_tracks` still holds a copy. Its `repoint` is pre-M8 (raw
  `update_playlist`); N1 must use `playlist_edit` instead.
- `scripts/duplicate_report.py`: `load(db) -> (rows, held)`, `duplicate_groups(rows)` (each group sorted best first
  by `keep_rank`: lossless, then bit rate, then `library_map._copy_rank`), `LOSSLESS` set. It SELECTs `bit_rate` from
  `media_file`.
- `crates/reconcile.py`: `Reconciler._run` is where N3 goes; the current branch `rep.errors.append(f"{c.name}: playlist
  no longer exists in Navidrome")` is the one to replace. `_untier` shows how in-flight rows are spared.
  `write_comment(client, pl, new)` is the one comment writer (readback, `CommentNotKept`).
- `sourcing/import_playlist.py`: `MARKER`, `is_imported`, `NameCollision`, `_rerun_comment`, `_write_comment_and_cache`
  are N2's targets; `import_playlist()` computes `matches`, `ordered`, `new_ids`, `pending` (rows that become wanted
  rows) and calls `store.mark_imported` — N4-02 records `import_order` right after the `pending` loop.
- `sourcing/fetch.py` `finish()` (inside `fetch`, around lines 176–260): the two sites where an external row becomes
  `ok` (`set_library_song` + `set_status("ok", done)`), and the provisional (play-now) branch. `sourcing/replace.py`
  `_settle` is the third `ok` site. N4's placement is state-driven so none of them needs a new call.
- `sourcing/worker.py` `Worker.tick`: play-now approvals → reconcile_due → re-checks → approvals → `advance_replacements`
  → `export_due`. N4-04 adds placement after replacements. `self.common` carries `navidrome_db`, `music_root`,
  `trash_root`, `filer`.
- `sourcing/worker.py` `hold_lock(path)` is the worker.lock flock (raises `WorkerRunning`); N1's trash step reuses it.
- `sourcing/filer.py` `BeetsFiler.forget(path)` runs `beet remove -f path:<abs>` and refuses while the file exists.
- `crates/cli.py` and `sourcing/cli.py`: argparse subcommands; `crates.service.Config.from_env()` resolves
  `SUBSONIC_URL/USER/PASS`, `CRATES_DB`, `NAVIDROME_DB`; `sourcing/cli.py:_fetch_env()` resolves `MUSIC_ROOT`,
  `TRASH_ROOT`, `NAVIDROME_DB`, the filer (only with `DJ_WORKER=1`).
- `deploy/compose.yml`: the worker container has `/srv/music` rw, `/srv/_trash` rw, `navidrome.db` ro, Navidrome
  credentials and `DJ_WORKER=1`; the crates container has no library mount. So `plan` and `repoint` can run in either,
  `trash` only in the worker image (`docker compose run --rm worker …` with the daemon stopped).

**Test fixtures and fakes**
- `subsonic/fake_server.py`: `FakeSubsonicServer(db_path=tmp_path/"navidrome.db")` mirrors its state into a
  navidrome.db (`FakeState.sync()`); `state.missing` hides songs (the hidden-row trap), `state.smart` marks smart
  playlists, `state.requests` logs every call. Sample data: songs s1–s5 (s3 = Marshall Jefferson "Move Your Body" mp3
  192 kbps, s4 = Mr. Fingers mp3 128 kbps), playlists pl-1 "Disco Edits" [s1,s2,s3], pl-2 "Chicago 86" [s3,s4,s5],
  pl-3 "Sunday Listening" [s2], owner "demo". tests/test_playlist_edit.py adds s9 (a flac copy of s3) — the natural
  duplicate group for N1 tests.
- **Gotcha:** the mirror's `media_file` has **no `bit_rate` column** (`NAVIDROME_SCHEMA` has id, path, title, artist,
  album, duration, suffix, size, missing, mbz_recording_id, album_artist, year). `duplicate_report.load` SELECTs
  `bit_rate`, so N1-02 must add it to the schema and the INSERT (from the song dict's `bitRate`).
- `tests/test_fetch.py::world` builds fake Navidrome + store + reconciler + fake beets filer + music/trash dirs under
  tmp_path; `tests/test_worker.py::worker(world, srv)` builds a Worker on it; `tests/test_replace.py` shows how to
  drive fetch → replacement → trash on the fakes. `tests/test_dedupe_copies.py` shows real ffmpeg-made files under
  tmp_path. `tests/helpers.py` has `make_audio`, `beets_items_db`, `fake_beet`.
- `tests/conftest.py` sets `CRATES_OWNER=comment` and a legacy four-tier policy for the whole suite; app-owner tests
  live in `tests/test_app_owner.py` (its `env` fixture sets owner app). Under the legacy policy `low` is lenient, so a
  play-now copy stays provisional in tests; under the live policy all tiers are one strict rule and a play-now copy
  ends `ok`.
- `.harness/check.sh` runs pytest with `-x` (stops at the first failure) and every path in scratch. Pass test files
  to it while iterating; the full suite is about 7 minutes, run it once before flipping `passes`.

**Gotchas**
- `git add` files by name; never `-A` (scratch files sweep in). Check `git show --stat HEAD` before pushing.
- Soulseek peer names and absolute library paths stay out of events the web client shows (`store.public`).
- `docs/duplicates-report.md` is a snapshot (102 groups, 115 extras, 59 extras in a playlist, 92 lossless keepers,
  9 extras lossless beside a lossless keeper); the tool must recompute from `navidrome.db` every run.
- Michael deleted 35 playlists on 2026-10-17 (D32), so "playlist no longer exists" rows exist live ("sockseek /
  clouds"): N3 will delete them on the first live reconcile after deploy. That is intended.
- Nothing tonight writes to the live box. Deploy, the `imported migrate --apply` comment write and the cleanup stages
  are morning steps for Michael (N5-01 writes the checklist).

### Decisions taken by default (Michael: answer in INBOX.md to change any)

1. **D35 — groups where two copies are lossless** (9 extras of 115): D31 says "ties: the properly filed path", but two
   lossless files are often different masters, so the plan **holds** them (listed in the report, not repointed or
   trashed) until you clear the hold in `plan.json`. Say "trash them too" to follow D31 literally.
2. **D36 — the trash step runs with the worker stopped**: it takes `worker.lock` so `beet remove` has one writer.
   `plan` and `repoint` run beside the daemon. Say "no, make the worker do it" for a replacement-job design instead.
3. **D37 — the import flag is a new table** `imported_playlists` in crates.db (not a column on `crates`); the
   `#imported` token is stripped from "Tea tent" and "shakori (Spotify)" by `crates.cli imported migrate --apply`,
   which is **a live comment write you run in the morning** (dry run first). OK?
4. **D38 — a vanished playlist's rows are deleted** (crate_tracks, crates, imported_entries, import_order), in-flight
   rows wait until finished, wanted rows keep their `playlist_id` as history. Say so if you would rather keep a
   tombstone.
5. **D39 — placement**: M9 Q1/Q2 defaults applied (insert after the nearest earlier Spotify neighbour still in the
   playlist, else before the next, else append; earlier appends are never moved); imported playlists only; worker
   step, 12 attempts then an event. Existing playlists get an `import_order` only when you re-run their import
   (item 5), so the first placements will happen after that re-run.

### Questions that are not decisions
- Item 1's live run needs `/srv/docker/crates/duplicate-cleanup/` (uid 1000, inside the existing `/data` mount): no
  new mount, nothing for root.
- Do you want the cleanup report also copied into `docs/` for review in the GitHub app? Default: it is written beside
  the plan under `/data/duplicate-cleanup/report.md`; copy it by hand.
