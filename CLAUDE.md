# dj-crate-streaming

The parts of Michael's music server we write ourselves (crates app, worker, sourcing, playlist tools) around adopted
Navidrome, slskd and beets. It runs live on this box (compose project `dj`, from `/srv/docker`), beta, one user.

## Code rules
- Simple beats clever: stdlib Python 3.10+. Adopt beets, Navidrome and slskd; don't re-implement them.
- Use what exists: `crates/playlist_edit.py` (guarded index edits), `sourcing/replace.py`, `crates/trash.py` (trash +
  `MOVES.txt`), `scripts/dedupe_copies.py` (the plan → repoint → trash pattern), `scripts/duplicate_report.py`
  (`keep_rank`), `crates/store.py`, `crates/reconcile.py`.
- Safety invariants, each with a test: never trash while any playlist (hidden entries included) still holds the file;
  scan between repoint and trash; recompute groups right before acting; every destructive step has a logged reverse.
- Read `docs/hard-won-facts.md` before touching beets, Navidrome scans or playlists.

## How to verify
- Suite: `.harness/check.sh` (pytest, paths in scratch, live credentials unset), **about 12 minutes**. Subset:
  `.harness/check.sh tests/test_trash.py`. Run the files you touch while iterating, the full suite once at the end.
- Needs python3 ≥ 3.10 and `~/.local/bin/pytest` (`pipx install pytest`); without ffmpeg, flac, fpcalc, beet or
  sqlite3 their tests skip. No dev server: tests use the fake Navidrome/slskd in `tests/`; follow those fakes.

## Decisions and plans
- Design: `docs/specs/2026-10-17-amperfy-pivot.md` (wins on conflict), `docs/specs/2026-10-17-m9-remaining-ownership.md`,
  `docs/specs/2026-10-16-ownership-and-identity.md`, `docs/architecture.md`, build list `docs/next-todos.md`.
- Decisions: `docs/decisions.md`, the current rule set (D1 on). A new one that is Michael's gets the simplest
  reversible default, recorded there as `D<n> *default*`.
- Plans: `docs/plans/<date>-<milestone>-<topic>.md`; a flow that trashes files or writes tags needs a reviewed plan.
  Dated checklists for Michael's live steps: `docs/runbooks/`.

## Where things go
- What happened, was tried or failed → your session's `entry.json` (interactive sessions: the PR description).
- A decision → `docs/decisions.md`, next free number; an overturned one is rewritten in place with one
  `Updated in place <date>: …` line, never a new entry beside a dead one.
- A fact a fresh session would otherwise rediscover → one line in `## Gotchas`, edited in place; beets, Navidrome,
  slskd and tool facts → `docs/hard-won-facts.md`.
- Tonight's scope → the run brief, never this file. How to work here → Michael's: propose it (`proposed_changes`).
- Anything the code, git or the suite can tell (test counts, file lists, constants) → nowhere.

## Gotchas
- `git add` files by name, never `-A`: scratch files sweep in. `git show --stat HEAD` before pushing. (dj-2026-10-17 2026-10-17)
- `.harness/check.sh` runs pytest with `-x`: it stops at the first failure and hides any later ones. (dj-crate-streaming-2026-10-21 2026-10-21)
- `tests/conftest.py` sets `CRATES_OWNER=comment` and the legacy policy; app-owner tests: `tests/test_app_owner.py`. (dj-crate-streaming-2026-10-21 2026-10-21)
- Peer names, library paths and API keys never reach a reason, event, payload or doc (`store.public`). (dj-crate-streaming-2026-10-22-fixes 2026-10-22)
- A script SELECTing a new navidrome.db column: add it to `NAVIDROME_SCHEMA` and the fake's INSERT in `subsonic/fake_server.py`. (dj-2026-10-17 2026-10-19)
- `docs/duplicates-report.md` is a snapshot; the cleanup tools recompute from `navidrome.db` every run. (dj-2026-10-17 2026-10-17)
- Before numbering a decision, `git fetch -q`: take the next free D across `origin/main` and open run branches. (dj-crate-streaming-2026-10-22-build 2026-10-22)

## Off-limits
- The `amperfy` account and Soulseek transfers (D7). `/srv/incoming/**` and the secrets (`/srv/docker/.env`,
  `/etc/restic/env`) are user-level denies.

## Live system
Live: Navidrome, the `crates` and `worker` containers, `/srv/music`, `/srv/_trash`. Run `docker compose` from `/srv/docker`.
`.claude/settings.json` allows `scripts/deploy.sh`, the snapshot script and `flock -n <LIVE_LOCK>`-wrapped `deploy.sh`
and `docker compose`; every other live command, `scripts/live-run.sh` included, goes past auto mode's classifier.

### Check
`scripts/live-check.sh` (from the worktree). It runs, through `scripts/live-run.sh` (one-off worker commands in the
deployed image `dj-crates:<rev>`, from `dj-worker-1`'s revision label, D45), the long form
`docker compose run --rm --no-deps worker sh -c 'python3 -m scripts.export_playlists export && python3 -m scripts.export_playlists check'`
with `GIT_SHA=<rev>`; `--print` shows it without running. Pass: exit 0 and "ok: every playlist file matches Navidrome…". `--no-deps`: `/srv/docker/compose.yml` follows
`~/projects/dj-crate-streaming`, and a `run` with dependencies recreates Navidrome whenever that file differs from what runs. Export first: the worker exports only every 300 s
(never while stopped), so a bare `check` reports "stale".

### Snapshots
- `scripts/snapshot-crates-db.sh --suffix pre-<run-id>` (from the worktree): `sqlite3 .backup` of both databases to
  `crates.db.pre-<run-id>.snap` and `navidrome.db.pre-<run-id>.snap` beside them. Pass: exit 0 and "integrity ok" for
  each. Without `--suffix` it writes the nightly backup's `*.snap`, replaced at 03:30. The
  `.snap` files are the consistent copies; the live database files restic also copies are not.

### Backups
Nightly restic (`restic-backup.timer` → `restic-backup.service`): 03:30 + up to 15 min random delay, about 2 min
long, of /srv/music, /srv/docker and /srv/crates.
- **Status:** `systemctl show restic-backup.service -p ExecMainExitTimestamp -p ExecMainStatus`. Pass:
  `ExecMainStatus=0` and less than 26 h old; otherwise no live writes this session. A skipped backup (HDD not
  mounted) exits 1, so status 0 means a snapshot was saved (`/usr/local/sbin/restic-backup`, checked 2026-10-17).
  After a reboot the timestamp is empty: `journalctl -u restic-backup.service -n 3 -o short-iso` then gives the last
  run (pass: "Finished restic-backup.service", less than 26 h old).
- **Window:** no live write and no deploy from 03:15 to 04:30, or while `systemctl is-active restic-backup.service`
  prints `active`.
- **Lock:** the live-writer lock is `/srv/docker/crates/live.lock` (`LIVE_LOCK` in `.harness/config.sh`), so the
  backup job can hold the same lock while it snapshots and backs up.

### Deploy and rollback
- First record what runs: `docker compose ps` (the `dj-crates:<sha>` image of `crates` and `worker`) and
  `docker image ls dj-crates`. That tag is the rollback.
- Deploy: `scripts/deploy.sh` from the run's worktree, on a pushed commit. It refuses a dirty tree, builds
  `crates` + `worker` and tags `dj-crates:<10-char sha>`.
- After: `docker compose ps` shows `crates` and `worker` up and healthy, then **Check** green.
- Rollback (the `deploy.sh` header's form; old image gone → `scripts/deploy.sh` from a worktree at the old commit):
  `GIT_SHA=<old> CRATES_SRC=$PWD docker compose --project-directory /srv/docker -f deploy/compose.yml up -d --no-build crates worker`

### Staged runbooks
- Duplicate cleanup: `docs/worker.md` → "Duplicate cleanup".
  Reverse logs in `/srv/docker/crates/duplicate-cleanup/` (`repoint-<time>.jsonl`, `trash-<time>.jsonl`) and
  `/srv/_trash/<day>/MOVES.txt`. `plan` and every `repoint` stage may run.
- **`duplicate_cleanup trash` stays at `--dry-run`** until a live `trash --dry-run` has confirmed `lastScan` on
  Navidrome and Michael lifts it. Its guards are in `scripts/duplicate_cleanup.py`: `_scanned_since_repoint` (no
  trash unless a scan finished after the newest repoint log) and the size check (disk vs `media_file.size` and the
  plan's `planned_size`).

### Never
- Soulseek transfers (D7); the `amperfy` account and its playlists.
- `restic` (`restore`, `forget` and `prune` can't be undone) and editing `/srv/docker/compose*`: denied in
  `.claude/settings.json`.
- Deploying from `~/projects/dj-crate-streaming`.
