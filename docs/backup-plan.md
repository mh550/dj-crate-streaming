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
4. **Live SQLite files are in the set.** `navidrome.db` (WAL) and `crates.db` are copied while the services
   run. Fine in practice — Navidrome's DB is rebuildable from the files + playlists, crates.db is tiny —
   but a consistent copy costs one line: `sqlite3 /srv/docker/crates/crates.db ".backup /srv/docker/crates/crates.db.bak"`
   before the backup, or stop `crates` for the few seconds the snapshot takes. Not worth doing until
   crates.db holds something Michael would miss.
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
compose symlink target is the git checkout), `/srv/music`, `/home/mh550` → `docker compose up -d` →
Navidrome rescans → playlists come back from `navidrome.db` (or rebuild from
`docs/library-map.csv` with `scripts/folders_to_playlists.py`).
