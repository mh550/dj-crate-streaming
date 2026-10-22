# Morning checklist: the live steps for the dj-2026-10-17 run

> **R8 replaces this checklist** (`docs/plans/2026-10-22-morning-checklist.md`, run dj-crate-streaming-2026-10-21).
> Until then: **check** and the trash step below run in the deployed image through `scripts/live-check.sh` and
> `scripts/live-run.sh` (R2, D45).

For Michael. Everything below is built on branch `harness/dj-2026-10-17` and tested against fakes; **none of it has run
live**. Do the steps in order and stop at the first surprise: undo with that step's undo, run **check**, and ask.
The full detail of each stage is in `docs/worker.md` ("Duplicate cleanup", "Placement") and the plans named below.

**Conventions.** All commands from `/srv/docker`. Wrap each live write and each deploy in
`flock -n /srv/docker/crates/live.lock <command>`; if the lock is taken, someone else is working, so wait. Make no
live write from 03:15 to 04:30 or while `systemctl is-active restic-backup.service` says `active`.

**check** = `scripts/live-check.sh` (from a checkout of this repo; `--print` shows the command). It runs
`docker compose run --rm --no-deps worker sh -c 'python3 -m scripts.export_playlists export && python3 -m scripts.export_playlists check'`
in the deployed image `dj-crates:<rev>` (the `dj-worker-1` container's revision label), not `dj-crates:dev`.
Pass: exit 0 and "ok: every playlist file matches Navidrome…".

## 0. Before anything

1. Last backup succeeded in the last 26 h:
   `systemctl show restic-backup.service -p ExecMainExitTimestamp -p ExecMainStatus` (`ExecMainStatus=0`).
2. **check** is green.
3. Snapshots, named for the day (run `scripts/snapshot-crates-db.sh --suffix pre-morning` from the worktree; it writes
   `/srv/docker/crates/crates.db.pre-morning.snap` and `/srv/docker/navidrome/navidrome.db.pre-morning.snap`, each
   checked with `integrity_check`).
   *Undo:* restore a database by stopping `crates`/`worker` (Navidrome for its file) and copying the snapshot over it.
4. N1–N4 are merged into `main` (PRs #5–#12); merge the N5 PR too, then pull `~/projects/dj-crate-streaming`, so the checkout that
   `/srv/docker/compose.yml` follows matches what you deploy. Don't pass `--remove-orphans` before that (it would
   delete Gatus).

## 1. Deploy

1. Note what runs now: `docker compose ps` and `docker image ls dj-crates`. The current `dj-crates:<sha>` tag is the rollback.
2. From a worktree on the pushed commit: `flock -n /srv/docker/crates/live.lock scripts/deploy.sh`.
3. `docker compose ps`: `crates` and `worker` up (healthy). **check** green.

*Undo:* `GIT_SHA=<old> CRATES_SRC=$PWD docker compose --project-directory /srv/docker -f deploy/compose.yml up -d --no-build crates worker`
(old image gone: run `scripts/deploy.sh` from a worktree at the old commit). Then **check**.

## 2. Imported marker (N2, `docs/plans/2026-10-17-n2-imported-marker.md`)

1. Dry run: `docker compose exec -T crates python -m crates.cli imported migrate`. Expect exactly "Tea tent" and
   "shakori (Spotify)" as `would record + strip`. Anything else: stop.
2. `docker compose exec -T crates python -m crates.cli imported migrate --apply`, then `… imported list` (both rows,
   source `migrated`). A `CommentNotKept` means Navidrome ignores `comment=`: stop and log it.
3. `… imported migrate` again says `nothing to migrate`. **check**.

*Undo:* the `imported` events hold each old comment: set it back in Navidrome (or from the `navidrome.db` snapshot) and
`DELETE FROM imported_playlists WHERE playlist_id=…`.

## 3. Duplicate cleanup (N1, `docs/worker.md` → "Duplicate cleanup")

The trash step stays at `--dry-run` until you lift that: review findings I1 and I2 are fixed in this branch, but
`lastScan` still has to be confirmed on live Navidrome, which the `trash --dry-run` does.

1. Plan: `docker compose exec -T worker python3 -m scripts.duplicate_cleanup plan`; read
   `/srv/docker/crates/duplicate-cleanup/report.md`. Its section "Lossless pairs, will be trashed" lists the
   groups with two lossless copies (9 on 2026-10-17; one whose keeper file is missing is held instead): you said
   2026-10-19 to trash those extras too (D35), so nothing needs editing. To keep them after all, run
   `plan --hold-lossless` instead.
   *Undo:* nothing is written; `plan` keeps the old file as `plan-<made_at>.json`.
2. Repoint, each stage followed by **check**:
   ```
   docker compose exec -T worker python3 -m scripts.duplicate_cleanup repoint --dry-run
   docker compose exec -T worker python3 -m scripts.duplicate_cleanup repoint --limit 5
   docker compose exec -T worker python3 -m scripts.duplicate_cleanup repoint --limit 50
   docker compose exec -T worker python3 -m scripts.duplicate_cleanup repoint
   ```
   Read every refusal before the next stage. Exit 1 means a playlist was refused or a scan failed.
   *Undo:* replay `repoint-<time>.jsonl` newest first (`docs/worker.md` → "Undo").
3. Trash (needs the worker stopped, D36):
   ```
   docker compose stop worker
   scripts/live-run.sh python3 -m scripts.duplicate_cleanup trash --dry-run    # from a checkout of this repo
   ```
   `live-run.sh` prints `live-run: image dj-crates:<rev>` first and refuses (exit 1, one line) when the stopped
   `dj-worker-1` has no revision label, was built as `dev`, or `dj-crates:<rev>` is gone; `--print` shows the command.
   Every trash stage below runs the same way (`scripts/live-run.sh python3 -m scripts.duplicate_cleanup trash --limit 5`).
   If the dry run refuses ("no Navidrome scan finished after the newest repoint log"), scan in Navidrome, wait, run it
   again. When it is clean, `docker compose start worker` and **stop here until the trash is cleared to run**. Then
   the stages `--limit 5`, `--limit 50`, all, each followed by **check**, and `docker compose start worker` at the end.
   *Undo:* each file's reverse `mv -n` line in `/srv/_trash/<day>/MOVES.txt`, then a scan.
4. Expected end state (`docs/worker.md`): 0 playlist rows on a missing file, **check** green.

## 4. Reconcile

`docker compose exec -T crates python -m crates.cli reconcile`. With N3 deployed this drops a deleted playlist's rows
(the dead "sockseek / clouds" crate) with a `playlist_gone` event and a reverse log.
*Undo:* the reverse log it names (`docs/architecture.md` §9).

## 5. Re-run the imports (next-todos item 5)

Only after step 3 has run its stages: the library no longer has duplicates, so the 13 `review` rows and
"shakori (Spotify)"'s 2 ambiguous rows can match. For each imported playlist's source:
`docker compose exec -T crates python -m sourcing.cli import-playlist <source> --dry-run`, read it, then without
`--dry-run`. A real re-run also records `import_order`, which switches placement on (N4, D44): the worker then puts
each downloaded track at its Spotify position. It downloads nothing by itself (every download still needs your approval, D7).
*Undo:* a re-run only appends and records; remove an appended entry by hand in the playlist. To stop placement,
`DELETE FROM placements WHERE playlist_id=…` (a refused one retries up to 12 times over about four days).

## 6. Monitoring (H3), if not done

`docs/monitoring.md` → "Michael's one-time steps" (the disk timer, optional `tailscale serve` of port 4590).
