# Backup lock and monitoring (milestones H2, H3)

2026-10-17. Written by the evaluating session at Michael's request; builds on H1 (navidrome.db snapshots,
run-named restore points, worker heartbeat, `scripts/healthcheck.py`, compose healthchecks).

## Why

- **H2, the lock.** Live writes and the nightly restic backup must not overlap (journal D-H21). Agent sessions
  already wrap live writes in `flock -n /srv/docker/crates/live.lock`, but the backup script doesn't take the
  lock, so today only the 03:15–04:30 time rule protects the backup. The script also lives only in
  `/usr/local/sbin` (not in git) and runs the snapshot script from whatever branch `~/projects/dj-crate-streaming`
  has checked out.
- **H3, monitoring.** Healthchecks (H1) are labels: Docker doesn't restart or alert on "unhealthy". Michael wants
  a dashboard he can look at, plus alerts on a sensible schedule, including one when the nightly backup *didn't*
  run.

## H2: the backup script in git, with the lock

`deploy/restic-backup` becomes the source of truth for `/usr/local/sbin/restic-backup`. Agents write and test it;
**only Michael installs it** (sudo).

Behaviour (keep everything the current script does, in this order):
1. Load `${RESTIC_ENV_FILE:-/etc/restic/env}`.
2. Take the live-writer lock: `exec 9>>"${LIVE_LOCK:-/srv/docker/crates/live.lock}"`, then `flock -w 1800 9`. If
   the 30 minutes pass, log `live.lock held for 30 min; backing up anyway` and carry on: a missed backup is worse
   than one taken between stages. If the script creates the lock file, it must stay usable by uid 1000 (chown it,
   or create it with `install -o mh550`), because agent sessions run as mh550.
3. Snapshot crates.db and navidrome.db with the **installed** copy of the snapshot script
   (`/usr/local/lib/dj-crates/snapshot-crates-db.sh`), never from a checkout. A failed snapshot logs
   `WARNING: DB snapshot failed` and the backup continues (today `|| true` hides it).
4. `mountpoint -q /mnt/backup` or exit 1 (unchanged; a skipped backup must not report success).
5. `restic backup …` (unchanged includes, excludes and tag), then **release the lock** (`flock -u 9`) before
   `forget --prune` and `check`. Those only touch the repository, and they're the slow part.
6. On success only: if `GATUS_BACKUP_URL` and `GATUS_BACKUP_TOKEN` are set in the env file, POST success to Gatus'
   external endpoint `backup` (H3). This is the "backup ran" heartbeat. A failed POST logs a warning and doesn't
   fail the backup.

`deploy/install-backup.sh` (run by Michael: `sudo deploy/install-backup.sh`):
- shows `diff` of each target against what's installed, then installs `deploy/restic-backup` →
  `/usr/local/sbin/restic-backup` (0755 root) and `scripts/snapshot-crates-db.sh` →
  `/usr/local/lib/dj-crates/snapshot-crates-db.sh`;
- refuses to run from a dirty tree, or from anything but a commit on `main`, and prints the installed commit.

**Tests** (stdlib + bash, with stub `restic`, `mountpoint`, `curl` and `sudo` first on PATH, and the env file, lock
and installed paths overridable by env vars):
- the order is lock → snapshot → mount check → backup → unlock → forget/check;
- an unmounted drive exits 1 with no heartbeat;
- a restic failure gives no heartbeat;
- a held lock (a background `flock` on the test lock) makes the script wait, and with a short override timeout
  it logs the "backing up anyway" line and proceeds;
- a failed snapshot logs the warning and still backs up;
- a lock file created by the script isn't root-only.

**Never in H2:** sudo, installing anything, running the real backup, or reading `/etc/restic/env`. The session
writes the install command into its progress entry and INBOX for Michael.

## H3: Gatus, a dashboard and alerts

Gatus (one container; its config is YAML in this repo, so a new check is a reviewed diff) watches from outside the
containers, keeps history, shows a dashboard and alerts by ntfy.

**Service** in `deploy/compose.yml`:
- `gatus`, image pinned to a released v5 tag at least two weeks old, with a comment like navidrome's;
- `127.0.0.1:4590:8080`;
- config mounted read-only from the repo (`deploy/gatus/config.yaml`), history in `/srv/docker/gatus`;
- `restart: unless-stopped`, on the default compose network so it reaches services by name.

**Checks** (`deploy/gatus/config.yaml`). Every HTTP check runs at a 60 s interval, alerts after 3 failures in a
row (so a deploy doesn't page) and sends on resolved:

| Endpoint | Check | Pass |
|---|---|---|
| navidrome | `http://navidrome:4533/ping` | status 200 |
| crates | `http://crates:4580/api/status` | status 200, and the worker heartbeat age it reports < 180 s (H3-01) |
| slskd (via gluetun) | `http://gluetun:5030/` | connected, status < 500 |
| backup | external endpoint, pushed by `restic-backup` (H2) | a success within 26 h (use Gatus' external-endpoint heartbeat; check the pinned version supports it, and if it doesn't, say so in INBOX instead of improvising) |
| disk | external endpoint, pushed every 10 min by `deploy/health-push.sh` | `/srv` < 85 % used and `/mnt/backup` mounted and < 90 %; alert at once |

**Alerts:** ntfy, with the topic from `${GATUS_NTFY_TOPIC}` and the external-endpoint token from
`${GATUS_BACKUP_TOKEN}`, both set by Michael in `/srv/docker/.env`. Agents never read that file; `.env.example`
lists the names.

**`deploy/health-push.sh`** and `deploy/systemd/dj-health-push.{service,timer}` (user units, every 10 min) push
the disk result. Michael enables them; agents only write and test them.

**Deploy** under the live-staged protocol. Gatus writes no data, so the stages are:
1. `scripts/deploy.sh gatus`, inside `flock -n` on the live lock;
2. check `http://127.0.0.1:4590/api/v1/endpoints/statuses`: navidrome, crates and slskd green;
3. backup and disk may stay grey until Michael's steps below.

Rollback: `docker compose … stop gatus && docker compose … rm -f gatus`. Note it in the progress entry.

`docs/monitoring.md`: what's checked and how often, how alerts reach Michael, how to add a check, and Michael's
one-time steps.

## Michael's one-time steps (agents write these into INBOX when the code merges; they never do them)

1. Pick a private ntfy topic. Put `GATUS_NTFY_TOPIC=<topic>` and a random `GATUS_BACKUP_TOKEN=<token>` in
   `/srv/docker/.env`. Put `GATUS_BACKUP_URL=http://127.0.0.1:4590` and the same token in `/etc/restic/env`.
2. After H2 merges: `cd ~/projects/dj-crate-streaming && git pull && sudo deploy/install-backup.sh`.
3. After H3 merges: enable the disk timer (`systemctl --user link …` and `enable --now`, the exact lines in
   docs/monitoring.md), and optionally `tailscale serve` port 4590 to see the dashboard on the phone.
