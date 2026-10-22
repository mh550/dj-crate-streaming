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
- Suite: `.harness/check.sh` (pytest, paths in scratch, live credentials unset): ~1,523 tests, **about 9-10 minutes** (570 s measured). Subset:
  `.harness/check.sh tests/test_trash.py`. Run the files you touch while iterating, the full suite once at the end.
- Needs python3 ≥ 3.10 and `~/.local/bin/pytest` (`pipx install pytest`); without ffmpeg, flac, fpcalc, beet or
  sqlite3 their tests skip. No dev server: tests use the fake Navidrome/slskd in `tests/`; follow those fakes.

## Decisions and plans
- Design: `docs/specs/2026-10-17-amperfy-pivot.md` (wins on conflict), `docs/specs/2026-10-17-m9-remaining-ownership.md`,
  `docs/specs/2026-10-16-ownership-and-identity.md`, `docs/architecture.md`, build list `docs/next-todos.md`.
- Decisions: D1–D23 in `docs/specs/2026-10-13-next-session-design.md`, D24 on in the pivot spec; all settled. A new
  one that is Michael's gets the simplest reversible default, recorded in the pivot spec as `D<n> *default*`.
- Plans: `docs/plans/<date>-<milestone>-<topic>.md`; a flow that trashes files or writes tags needs a reviewed plan.

## Off-limits
- `/srv/incoming/**`, the `amperfy` account, Soulseek transfers (D7); secrets (`/srv/docker/.env`, `/etc/restic/env`).
- Other checkouts: `~/projects` and `~/projects/dj-crate-streaming` belong to other sessions.

## Live system
Live: Navidrome, the `crates` and `worker` containers, `/srv/music`, `/srv/_trash`. Run `docker compose` from `/srv/docker`.

### Check
`scripts/live-check.sh` (from the worktree). It runs, through `scripts/live-run.sh` (one-off worker commands in the
deployed image `dj-crates:<rev>`, from `dj-worker-1`'s revision label, D45), the long form
`docker compose run --rm --no-deps worker sh -c 'python3 -m scripts.export_playlists export && python3 -m scripts.export_playlists check'`
with `GIT_SHA=<rev>`; `--print` shows it without running. Pass: exit 0 and "ok: every playlist file matches Navidrome…". `--no-deps`: `/srv/docker/compose.yml` follows
`~/projects/dj-crate-streaming`, and a `run` with dependencies recreates Navidrome whenever that file differs from what runs. Export first: the worker exports only every 300 s
(never while stopped), so a bare `check` reports "stale".

### Snapshots
- `scripts/snapshot-crates-db.sh` (from the worktree), then copy its output to a run-named file:
  `cp /srv/docker/crates/crates.db.snap /srv/docker/crates/crates.db.pre-<run-id>.snap`. The script's own file is
  the nightly backup's and is overwritten at 03:30. Pass: exit 0 and "integrity ok".
- `sqlite3 /srv/docker/navidrome/navidrome.db ".backup /srv/docker/navidrome/navidrome.db.pre-<run-id>.snap"`.
  Pass: exit 0, and `sqlite3 <snap> 'pragma integrity_check'` prints `ok`. This is the only consistent copy of
  navidrome.db: the nightly backup copies its files raw while Navidrome writes.

### Backups
Nightly restic (`restic-backup.timer` → `restic-backup.service`): 03:30 + up to 15 min random delay, about 2 min
long (2026-10-17: 03:39–03:41, snapshot `da26a815` of /srv/music, /srv/docker, /srv/crates).
- **Status:** `systemctl show restic-backup.service -p ExecMainExitTimestamp -p ExecMainStatus`. Pass:
  `ExecMainStatus=0` and less than 26 h old; otherwise no live writes this session. A skipped backup (HDD not
  mounted) exits 1, so status 0 means a snapshot was saved (`/usr/local/sbin/restic-backup`, checked 2026-10-17).
- **Window:** no live write and no deploy from 03:15 to 04:30, or while `systemctl is-active restic-backup.service`
  prints `active`.
- **Lock:** the live-writer lock is `/srv/docker/crates/live.lock` (`LIVE_LOCK` in `.harness/config.sh`), so the
  backup job can hold the same lock while it snapshots and backs up.

### Deploy and rollback
- First record what runs: `docker compose ps` (the `dj-crates:<sha>` image of `crates` and `worker`) and
  `docker image ls dj-crates`. That tag is the rollback.
- Deploy: `scripts/deploy.sh` from the run's worktree, on a pushed commit. It refuses a dirty tree, builds
  `crates` + `worker` and tags `dj-crates:<10-char sha>`.
- After: `docker compose ps` shows `crates` and `worker` up (healthy, once healthchecks exist), then **Check** green.
- Rollback (the `deploy.sh` header's form; old image gone → `scripts/deploy.sh` from a worktree at the old commit):
  `GIT_SHA=<old> CRATES_SRC=$PWD docker compose --project-directory /srv/docker -f deploy/compose.yml up -d --no-build crates worker`

### Staged runbooks
- Duplicate cleanup: `docs/worker.md` → "Duplicate cleanup" (merged into `main` with N1, PR #5).
  Reverse logs in `/srv/docker/crates/duplicate-cleanup/` (`repoint-<time>.jsonl`, `trash-<time>.jsonl`) and
  `/srv/_trash/<day>/MOVES.txt`. `plan` and every `repoint` stage may run.
- **`duplicate_cleanup trash`:** review findings I1 and I2 are fixed in `scripts/duplicate_cleanup.py`: I1 is
  `_scanned_since_repoint` (trash refuses unless a Navidrome scan finished after the newest repoint log), I2 is the
  size check in `trash` (the size on disk vs `media_file.size` and the plan's `planned_size`). It stays at `--dry-run` until a live
  `trash --dry-run` has confirmed `lastScan` on Navidrome and Michael lifts it. See
  `~/projects/agent-harness/journal/runs/dj-2026-10-17.md`.

### Never
- Soulseek transfers (`fetch --approve`, D7); writes under `/srv/incoming` (not backed up); the `amperfy` account and its playlists.
- Reading `/srv/docker/.env` or `/etc/restic/env`; `sudo`; restic `restore`, `forget` or `prune`.
- Editing `/srv/docker/compose*`; deploying from `~/projects/dj-crate-streaming`.
