# Morning checklist v2: the live steps after run dj-crate-streaming-2026-10-21

For Michael. It replaces `docs/plans/2026-10-17-morning-checklist.md`. Everything of runs `dj-2026-10-17` (N1–N5,
H3-05) and `dj-crate-streaming-2026-10-21` (R1–R7) is merged into `main` and tested against the fakes; **none of it
has run live**. Live today: `crates` and `worker` on `dj-crates:f4882ab85b` (N1, N1F, H1, H2, H3-01..04), the H3-03
timer not enabled. Do the steps in order and stop at the first surprise: undo that step, run **check**, and ask.
The detail behind each step is in `docs/worker.md` and the plans named below.

## Conventions

- `docker compose` commands run from `/srv/docker`. `scripts/…` commands run from a checkout of this repo on `main`
  (the deploy worktree of step 4 once it exists; before that `~/projects/dj-crate-streaming` after step 1).
- **Lock.** Wrap each live write and each deploy in `flock -n /srv/docker/crates/live.lock <command>`. If the lock
  is taken, someone else (or the nightly backup) is working: wait.
- **Window.** No live write and no deploy from 03:15 to 04:30, or while `systemctl is-active restic-backup.service`
  prints `active`.
- **Snapshots first.** Before the first live write (step 4), and again on every later day with a live write (the
  held trash of step 6, the identity writes of step 9), all three must pass:
  1. The last backup is good: `systemctl show restic-backup.service -p ExecMainExitTimestamp -p ExecMainStatus`
     shows `ExecMainStatus=0`, less than 26 h old. Otherwise no live write today.
  2. **check** is green.
  3. Snapshots named for the day: `scripts/snapshot-crates-db.sh --suffix pre-2026-10-22` (a new suffix each day: a
     re-run with the same suffix replaces that restore point). It writes
     `/srv/docker/crates/crates.db.pre-2026-10-22.snap` and `/srv/docker/navidrome/navidrome.db.pre-2026-10-22.snap`,
     each checked with `integrity_check` (one line per database, exit 0). The nightly `.snap` never overwrites them.
     *Undo of a bad database:* stop `crates` and `worker` (Navidrome too for its file), move the database's
     `-wal` and `-shm` files aside (SQLite would replay a leftover WAL onto the copy), copy the snapshot over it,
     start them again.
- **check** = `scripts/live-check.sh` (`--print` shows the command, runs nothing). It runs
  `python3 -m scripts.export_playlists export && python3 -m scripts.export_playlists check` in the deployed image
  through `scripts/live-run.sh`. Pass: exit 0 and "ok: every playlist file matches Navidrome…".
- **One-off worker commands** go through `scripts/live-run.sh <command…>` (D45): it reads the revision label of
  `dj-worker-1` (running or stopped), prints `live-run: image dj-crates:<rev>` and runs
  `GIT_SHA=<rev> docker compose --project-directory /srv/docker run --rm --no-deps worker <command…>`. It refuses
  (exit 1, one line) when the container is missing, the label is empty, `dev` or not a sha, or `dj-crates:<rev>` is
  gone. `--print` shows the command only. Commands for the `crates` container use `docker compose exec -T crates`.

## 1. Pull the main checkout

`/srv/docker/compose.yml` follows `~/projects/dj-crate-streaming`, so that checkout must match what you deploy. Until
it does, don't pass `--remove-orphans` to any `docker compose` command (it would delete Gatus).

```
cd ~/projects/dj-crate-streaming
git status
git rev-parse --abbrev-ref HEAD; git rev-parse HEAD  # note both: the undo
```

If `git status` still shows `.harness/runs/dj-2026-10-17/INBOX.md` modified, keep a copy of the change and drop it:

```
git diff .harness/runs/dj-2026-10-17/INBOX.md > ~/inbox-dj-2026-10-17.diff
git checkout -- .harness/runs/dj-2026-10-17/INBOX.md
```

Then `git checkout main && git pull --ff-only`.

Check: `git status` is clean and `git log -1 --oneline` is `origin/main`'s commit. **check** is still green (it runs
the live image `f4882ab85b`, which has the revision label).
Undo: `git checkout <the noted branch> && git reset --hard <the noted sha>` (only if that branch moved); the INBOX change comes back with `git apply ~/inbox-dj-2026-10-17.diff`.

## 2. The H3-03 disk and backup timer

`docs/monitoring.md` → "Michael's one-time steps", step 3: as mh550, no sudo, from `~/projects/dj-crate-streaming`
on `main` (step 1):

```
install -D -m 0755 deploy/health-push.sh ~/.local/lib/dj-crates/health-push.sh
install -m 0600 /dev/null ~/.config/dj-health-push.env
printf 'GATUS_BACKUP_URL=http://127.0.0.1:4590\nGATUS_BACKUP_TOKEN=<same token as /srv/docker/.env>\n' >> ~/.config/dj-health-push.env
install -D -m 0644 -t ~/.config/systemd/user deploy/systemd/dj-health-push.service deploy/systemd/dj-health-push.timer
systemctl --user daemon-reload
systemctl --user enable --now dj-health-push.timer
systemctl --user start dj-health-push.service; journalctl --user -u dj-health-push -n 5
loginctl enable-linger mh550
```

Check: `systemctl --user list-timers dj-health-push.timer` shows a next run; the journal has no `WARNING` line (a
successful push prints nothing; a missing token warns and still exits 0); the Gatus dashboard (port 4590) shows
both `disk` and `backup` green.
Undo: `systemctl --user disable --now dj-health-push.timer` (and `loginctl disable-linger mh550`).

## 3. No pinned `GIT_SHA` in `/srv/docker/.env`

```
grep -c '^GIT_SHA=' /srv/docker/.env
```

Check: it prints `0`. Compose then takes `GIT_SHA` only from the command's own environment: `scripts/deploy.sh`,
`scripts/live-run.sh` and `scripts/live-check.sh` set it themselves. A bare `docker compose run|up` of `crates` or
`worker` falls back to `dj-crates:dev` (an old unlabelled image, or a build), and a `run` without `--no-deps` can
recreate Navidrome: never run those bare; use `deploy.sh` and `live-run.sh` only.

If it prints `1`, look at that line yourself (`grep '^GIT_SHA=' /srv/docker/.env`; the agent never reads the file).
A variable set in the shell wins over `.env`, so the three scripts still use the sha they chose. But every bare
`docker compose run|up` from `/srv/docker` then uses the pinned image, which goes stale with each deploy, and a bare
`up -d` would quietly put `crates` and `worker` back on it. Unless you pinned it on purpose, remove the line:
`cp -p /srv/docker/.env /srv/docker/.env.pre-2026-10-22`, then delete the `GIT_SHA=` line in an editor.
Undo: `cp -p /srv/docker/.env.pre-2026-10-22 /srv/docker/.env`.

## 4. Deploy `main` from a fresh worktree

Do the "Snapshots first" checks of the conventions now. Then:

```
docker compose ps                                    # crates and worker on dj-crates:f4882ab85b
docker image ls dj-crates                            # dj-crates:f4882ab85b is the rollback
git -C ~/projects/dj-crate-streaming fetch origin
git -C ~/projects/dj-crate-streaming worktree add ~/worktrees/dj-crate-streaming/deploy-2026-10-22 origin/main
cd ~/worktrees/dj-crate-streaming/deploy-2026-10-22
flock -n /srv/docker/crates/live.lock scripts/deploy.sh
```

`deploy.sh` refuses a dirty tree, builds `crates` + `worker` and tags `dj-crates:<10-char sha>`.

Check: `docker compose ps` shows `crates` and `worker` up and healthy on the new tag;
`scripts/live-run.sh --print true` names `GIT_SHA=<the new sha>`; **check** green.
Undo (CLAUDE.md, from the deploy worktree):

```
GIT_SHA=f4882ab85b CRATES_SRC=$PWD docker compose --project-directory /srv/docker -f deploy/compose.yml up -d --no-build crates worker
```

If that image is gone: `scripts/deploy.sh` from a worktree at commit `f4882ab85b`. Then **check**.

## 5. Imported marker (N2, `docs/plans/2026-10-17-n2-imported-marker.md` "Live runbook")

```
docker compose exec -T crates python3 -m crates.cli imported migrate
```

Check: exactly "Tea tent" and "shakori (Spotify)" as `would record + strip`. Anything else: stop.

```
flock -n /srv/docker/crates/live.lock docker compose exec -T crates python3 -m crates.cli imported migrate --apply
docker compose exec -T crates python3 -m crates.cli imported list
docker compose exec -T crates python3 -m crates.cli imported migrate
```

Check: `imported list` shows both rows (source `migrated`); in Navidrome neither comment says `#imported`; the last
dry run says `nothing to migrate`; **check** green. A `CommentNotKept` means Navidrome ignores `comment=`: stop and
log it.
Undo: the `imported` events (Log tab) hold each old comment: set it back in Navidrome (or from the navidrome.db
snapshot) and delete the row: `DELETE FROM imported_playlists WHERE playlist_id=…` (worker stopped).

## 6. Duplicate cleanup (N1, D35; `docs/worker.md` → "Duplicate cleanup")

Output lands in `/srv/docker/crates/duplicate-cleanup/`. Read every refusal before the next stage; exit 1 means a
playlist was refused or a scan failed.

**Plan (read-only):**

```
scripts/live-run.sh python3 -m scripts.duplicate_cleanup plan
```

Check: read `duplicate-cleanup/report.md`. Its section **"Lossless pairs, will be trashed"** is new (R3): the groups
whose extra is lossless beside a lossless keeper (9 on 2026-10-17). You said on 2026-10-19 to trash those extras too
(D35), so a plain `plan` acts on them and nothing needs editing. To keep them after all, run `plan --hold-lossless`
instead: they are then listed as "both lossless" and held. A pair whose keeper file is missing is always held.
Undo: nothing is written to the library; a re-run keeps the old `plan.json` as `plan-<made_at>.json`.

**Repoint** (the worker may keep running), each stage followed by **check**:

```
scripts/live-run.sh python3 -m scripts.duplicate_cleanup repoint --dry-run
flock -n /srv/docker/crates/live.lock scripts/live-run.sh python3 -m scripts.duplicate_cleanup repoint --limit 5
flock -n /srv/docker/crates/live.lock scripts/live-run.sh python3 -m scripts.duplicate_cleanup repoint --limit 50
flock -n /srv/docker/crates/live.lock scripts/live-run.sh python3 -m scripts.duplicate_cleanup repoint
flock -n /srv/docker/crates/live.lock docker compose exec -T crates python3 -m crates.cli reconcile
```

(`docker compose exec -T worker python3 -m scripts.duplicate_cleanup …`, as `docs/worker.md` writes it, is the same
code once step 4 has deployed.) Each real run ends with a Navidrome scan and waits for it; the dry run does not scan.
Check: every refusal understood; **check** green after each stage.
Undo (`docs/worker.md` → "Undo"): get any trashed files back and scanned first; replay
`duplicate-cleanup/repoint-<time>.jsonl` newest first; and replay `/srv/docker/crates/songs-repointed.jsonl` newest
first, each line as `store.unrepoint_song(line)` then `store.commit()` (worker stopped, crates.db snapshot first),
because repoint also points crates.db's rows at the keeper. The previous
`.m3u8` of each rewritten playlist is in `/srv/music/_playlists/.history/<date>/` (step 9).

**Trash dry run** (the worker stopped, D36):

```
docker compose stop worker
scripts/live-run.sh python3 -m scripts.duplicate_cleanup trash --dry-run
docker compose start worker
```

Check: the first line is `live-run: image dj-crates:<the new sha>`. If it refuses with "no Navidrome scan finished
after the newest repoint log", start a scan in Navidrome, wait for it to end, run the dry run again: that is the
`lastScan` confirmation the hold waits for. Read every `would move` and `skipped` line.
Undo: `docker compose start worker` (the dry run writes nothing).

**Stop here.** The real trash stays held until you have understood the `lastScan` refusal (or its absence) and lift
the hold. After that, with the worker stopped and each stage followed by **check**:
`flock -n /srv/docker/crates/live.lock scripts/live-run.sh python3 -m scripts.duplicate_cleanup trash --limit 5`,
then `--limit 50`, then without `--limit`, then `docker compose start worker`. Undo: each file's reverse `mv -n` line
in `/srv/_trash/<day>/MOVES.txt`, then a scan. End state (`docs/worker.md`): 0 playlist rows on a missing file,
**check** green.

## 7. Reconcile (N3)

The deployed worker reconciles every 10 minutes by itself, so this may already have happened: look for a
`playlist_gone` event in the Log tab first. Otherwise:

```
flock -n /srv/docker/crates/live.lock docker compose exec -T crates python3 -m crates.cli reconcile
```

Check: the JSON's `errors` list is empty and `playlists_gone` names "sockseek / clouds" ("playlist no longer exists
in Navidrome; N rows dropped" is the success line there); one `playlist_gone` event and a line in
`/srv/docker/crates/playlists-gone.jsonl`; **check** green.
Undo: replay `playlists-gone.jsonl` newest first (`docs/architecture.md` §9).

## 8. Re-run the imports (next-todos item 5)

Only after step 6's repoint stages (better: after its trash stages, once the hold is lifted): with fewer duplicates,
the 13 `review` rows and "shakori (Spotify)"'s 2 ambiguous rows can match. For each imported playlist
(`imported list`), with the source you imported it from: a Spotify URL, or an Exportify CSV copied into
`/srv/docker/crates/` and passed as `/data/<file>.csv` (the `crates` container sees only that folder):

```
docker compose exec -T crates python3 -m sourcing.cli import-playlist <source> --dry-run
flock -n /srv/docker/crates/live.lock docker compose exec -T crates python3 -m sourcing.cli import-playlist <source>
```

Check: the dry run says `updated existing playlist`, not `NameCollision`, and its matches look right; after the real
run, the playlist in Navidrome and **check** green. A real re-run records `import_order`, which switches placement on
(N4, D44); since R6-03 a failed, unfiled wanted row is reused (back to `needs_source`, same `ext-N`) instead of a new
one. Nothing downloads without your approval (D7).
Undo: a re-run only appends and records; remove an appended entry by hand in the playlist. To stop placement into a
playlist: `DELETE FROM import_order WHERE playlist_id=…` (worker stopped, crates.db snapshot first). Leave
`placements` alone: deleting its `done`/`given_up` rows makes those tracks due again.

## 9. What R4–R7 change live, and how to look at it

All of it arrives with step 4.

- **`rank --download` is gone (R4).**
  `scripts/live-run.sh python3 -m sourcing.cli rank --download` exits 2 with "rank no longer downloads: use Preview +
  Approve in the web client (the worker downloads, D23)". It contacts nothing. Undo: none needed.
- **Host writers refuse beside the worker (R4).** `tag_cleanup retag|move` and `dedupe_copies repoint|trash` hold
  the worker's lock (`/srv/docker/crates/worker.lock`, `/data/worker.lock` inside a container) for the whole command. To see the refusal without running any of them, with the worker up
  (`docker compose ps worker`):

  ```
  scripts/live-run.sh python3 -c 'from sourcing.worker import with_worker_lock; raise SystemExit(with_worker_lock(lambda: 0))'
  ```

  Check: exit 1 and "refused: stop the worker first (docker compose stop worker): it holds /data/worker.lock". The
  probe only tries the lock (with the worker stopped it takes it and exits 0). Undo: none needed.
- **Playlist health (R5).** After each export the worker counts the entries of the app user's playlists (D46) that
  point at a missing file. The web client shows a banner ("2 entries in Tea tent point at missing files") from
  `/api/status` `playlistHealth`: `curl -s http://127.0.0.1:4580/api/status`. When the set changes, the Log tab gets
  one `playlist_health` event. Expect the counts to fall during step 6. Healing stays manual. Undo: none needed.
- **`.m3u8` history (R5).** Before an export rewrites a changed `.m3u8`, it keeps the old text in
  `/srv/music/_playlists/.history/<YYYY-MM-DD>/` (the day's first version; 30 days kept). After the first changed
  export (step 6's repoint at the latest): `ls /srv/music/_playlists/.history/`. That folder is the restore source for
  a playlist that lost entries (`docs/worker.md` → "Undo"). Undo: none needed.
- **AcoustID cache (R6).** The next `identity_backfill propose` with `ACOUSTID_KEY` set writes
  `/srv/docker/crates/identity/acoustid-cache.jsonl` beside `mb-cache.jsonl` and skips unchanged files' lookups.
- **The Identity tab (R7, `docs/plans/2026-10-21-r7-identity-picker.md` "Live steps").**
  1. `ls -ld /srv/docker/crates/identity`: it must be writable by uid 1000 (the crates container). If root owns it,
     `sudo chown 1000:1000 /srv/docker/crates/identity`. **check** green.
  2. Open the Identity tab and pick (Accept on `search` rows, Choose or Skip on `ambiguous`/`none`, Skip only on
     `conflict`/`error`). Check: `cat /srv/docker/crates/identity/identity-choices.json` holds your picks with
     `decided_by: michael`; the Log tab shows one `identity_pick` event per tap. Undo: tap again, or delete the
     entry from the file (nothing is written to the library yet).
  3. Dry run:

     ```
     scripts/live-run.sh python3 -m scripts.identity_backfill apply /data/identity/identity-proposal.json --choices /data/identity/identity-choices.json --dry-run
     ```

     Check: **every** `would write` line carries `(choice: …)` and is a pick you made; every `choices:` line (a refused,
     skipped or ignored pick) is one you understand. Undo: none (writes nothing).
  4. Five files:

     ```
     flock -n /srv/docker/crates/live.lock scripts/live-run.sh python3 -m scripts.identity_backfill apply /data/identity/identity-proposal.json --choices /data/identity/identity-choices.json --yes --limit 5
     ```

     It scans Navidrome and checks song ids, recording ids and playlists itself (exit 0). Check: **check** green.
     Undo:

     ```
     flock -n /srv/docker/crates/live.lock scripts/live-run.sh python3 -m scripts.identity_backfill revert /data/identity/apply-<time>.jsonl
     ```

     (the run prints the log path). `revert` does not scan: wait for Navidrome's hourly scan or start one, then
     **check**. Re-run `propose` before applying again (a revert changes the files' mtime).
  5. All: the same command without `--limit`, then **check**. Undo as in 4, with this run's log.

  The default classes of next-todos item 6 (`confirmed`, `isrc`, `acoustid`) are a separate apply without
  `--choices`, staged the same way (`docs/worker.md` → "Identity backfill"); their order relative to the picks does
  not matter.
