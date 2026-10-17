# Backups: `/srv/music` + `/srv/docker` (restic)

_Written 2026-10-13 overnight. Nothing here was initialised or changed; the job below already exists._

## What already runs (verified from the journal, not from `/etc/restic`, which is root-only)

| | |
|---|---|
| Unit | `restic-backup.timer` → `restic-backup.service` → `/usr/local/sbin/restic-backup` |
| When | nightly 03:30 (+ up to 15 min jitter), `Persistent=true` so a missed night runs at next boot |
| Repo | `/mnt/backup/restic` on the 1 TB HDD (`sda1`, 890 GB free); skips cleanly if the HDD isn't mounted |
| Includes | `/etc`, `/home/mh550`, `/mnt/games/isos`, `/srv/crates`, `/srv/docker`, `/srv/music` |
| Retention | `forget --prune --keep-daily 7 --keep-weekly 4 --keep-monthly 6` |
| Integrity | `restic check --read-data-subset=5%` every run (last run: "no errors were found") |
| Last run | 2026-10-13 03:39, snapshot `ef5494a0`, 39 GiB processed, 3.2 GiB new, 1:27 |

So the plan phase0-options §5 asked for ("nightly `restic` to an external drive before anything else")
is **done**, and `/srv/music` + `/srv/docker` are in it.

## Gaps and follow-ups

1. **Last night's snapshot predates the library.** The import filled `/srv/music` 04:14–05:05, after the
   03:39 run, so `ef5494a0` has an empty music dir. **Tonight's 03:30 run is the first real backup of
   the 22 GB library.** Until then the only copy is the laptop + `/srv/incoming/library-import/`.
   Check tomorrow: `sudo restic -r /mnt/backup/restic snapshots --path /srv/music` (needs the repo
   password from `/etc/restic/env`) and expect "processed … ~22 GiB".
2. **`/srv/incoming` is not backed up — correct.** It's the import mirror (24 GB, original on the laptop)
   plus slskd downloads in flight. Leave it out; verified downloads move into `/srv/music`.
3. **Exclude the transcoding cache.** `/srv/docker/navidrome/cache/` is rebuilt on demand and is allowed
   to grow to 3 GB (`ND_TRANSCODINGCACHESIZE`). If it isn't already in `/etc/restic/excludes`, add
   `/srv/docker/navidrome/cache` and `/srv/docker/slskd/logs`. (Can't read the excludes file without root.)
4. **Live SQLite files are in the set, so the job snapshots them first.** `navidrome.db` and `crates.db` run in WAL
   mode and are copied while the services run, so a plain file copy can miss recent writes (crates.db holds
   approvals, which are not rebuildable). The nightly job's first step is
   `sudo -u mh550 /home/mh550/projects/dj-crate-streaming/scripts/snapshot-crates-db.sh || true` (no arguments;
   with `|| true` a failed snapshot neither stops the backup nor says so, and restic saves the previous `.snap`).
   Since H1 that script writes **both** `/srv/docker/crates/crates.db.snap` and `/srv/docker/navidrome/navidrome.db.snap`
   (`sqlite3 .backup`, one self-contained file each, `integrity_check`, all or nothing: D38 *default*), and restic
   picks them up with the rest of `/srv/docker`. Restore from the `.snap` files, not the live `.db` copies.
   **The job runs the script from `~/projects/dj-crate-streaming`, so it runs whatever that checkout has: `main`
   must be checked out there** (and pulled: until that checkout has H1, the nightly run writes `crates.db.snap`
   only). H2 replaces this with an installed copy (`/usr/local/lib/dj-crates/snapshot-crates-db.sh`, see
   `docs/specs/2026-10-17-backup-lock-and-monitoring.md`). A run's own restore point is
   `scripts/snapshot-crates-db.sh --suffix pre-<run>`, which the nightly call never overwrites.
5. **`.env` secrets are in the set.** `/srv/docker/.env` is inside the (encrypted) repo. That's desirable
   for recovery; just remember the repo password is the key to everything.
6. **Off-site is the remaining hole.** The HDD sits next to the NVMe. The cheapest step is a second
   restic repo on Backblaze B2 (~$6/TB/mo, ≈ $0.15/mo at today's size) fed by the same script:
   `restic -r b2:<bucket>:dj backup --files-from /etc/restic/includes …` with `B2_ACCOUNT_ID/KEY` in
   `/etc/restic/env`, and `restic copy` nightly from the local repo is even simpler. Michael's call.

## Restore drill (do once, so the first real restore isn't the first time)

```bash
sudo -i
set -a; . /etc/restic/env; set +a              # RESTIC_REPOSITORY + RESTIC_PASSWORD
restic snapshots --path /srv/music              # pick an ID
restic restore <id> --target /tmp/restore-test --include "/srv/music/Chic"
ls /tmp/restore-test/srv/music/Chic && rm -rf /tmp/restore-test
restic mount /mnt/restic-browse &               # or browse it like a filesystem (needs fuse)
```

Full-box recovery order: reinstall Pop → mount HDD → restore `/etc/restic`, `/srv/docker` (brings `.env`,
compose symlink target is the git checkout), `/srv/music`, `/home/mh550` → put the snapshots in place: copy
`navidrome.db.snap` over `navidrome.db` and `crates.db.snap` over `crates.db`, and delete any `-wal`/`-shm` beside
them → `docker compose up -d` → Navidrome rescans → playlists come back from `navidrome.db` (or rebuild from
`docs/library-map.csv` with `scripts/folders_to_playlists.py`).
