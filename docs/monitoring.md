# Monitoring: Gatus dashboard and ntfy alerts

_Written 2026-10-19 (H3-05). Design: `docs/specs/2026-10-17-backup-lock-and-monitoring.md` §H3. The checks
themselves are `deploy/gatus/config.yaml`; this page follows it, and `tests/test_monitoring_doc.py` fails when the
table's endpoints, URLs, intervals or thresholds drift from it._

Gatus (`gatus` in `deploy/compose.yml`, image `twinproduction/gatus:v5.37.0`) watches the stack from outside the
containers, keeps its history in `/srv/docker/gatus/data.db`, shows a dashboard and sends alerts by ntfy.
Dashboard: http://127.0.0.1:4590 on the box (bound to 127.0.0.1 only). The raw results:
`curl -s http://127.0.0.1:4590/api/v1/endpoints/statuses`.

## What is checked, and how often

| Endpoint | How | Every | Green when | Alerts after |
|---|---|---|---|---|
| navidrome | Gatus GETs `http://navidrome:4533/ping` | 60 s | status 200 | 3 failures in a row |
| crates | Gatus GETs `http://crates:4580/api/status` | 60 s | status 200, and `workerHeartbeatAge` is present and < 180 s (the worker ticked in the last 3 min) | 3 failures in a row |
| slskd | Gatus GETs `http://gluetun:5030/` (slskd lives in gluetun's network) | 60 s | connected, status < 500 | 3 failures in a row |
| backup | pushed: `deploy/restic-backup` after each nightly backup that fully succeeded, and `deploy/health-push.sh` every 10 min from `systemctl show restic-backup.service` (D42) | heartbeat 26 h | the last nightly backup succeeded and ended less than 26 h ago | 1 failure, or no push for 26 h |
| disk | pushed: `deploy/health-push.sh` every 10 min (user timer `dj-health-push.timer`) | heartbeat 30 min | `/srv` < 85 % used, and `/mnt/backup` mounted and < 90 % used | 1 failure, or no push for 30 min (D40) |

Three failures before an alert means a deploy's restart (about a minute) never pages. The pushed endpoints alert on
the first failure, because each push is already a considered result. A failed push carries its reason (`error=` in
the push, shown on the dashboard), for example `/srv is 91% used (limit 85%)` or `last backup exited 1 (exit-code)`.
The ntfy message itself carries the endpoint's alert `description` (pushed results have no conditions to quote).

How `health-push.sh` reads the backup from systemd: a run that failed (any exit status but 0, a kill or a timeout),
one that ended 26 h ago or more, or a box up 26 h without a run since boot is a failure; otherwise success. A failing
`systemctl`, or a unit systemd doesn't know, is a failure too. It pushes nothing while a run is in progress (systemd clears the last result when a run
starts) or before the first run after a recent boot. Gatus keeps the last 100 results per endpoint, so with
a push every 10 min the dashboard shows about 16 h of `backup` and `disk` history, not a month of nightly runs.

What a heartbeat means: Gatus marks a pushed endpoint failed when no push arrived within its interval. Gatus checks
this on a ticker that starts with Gatus, so a lapse is noticed between one and two intervals after the last push,
and a Gatus restart starts the clock again. That is why `health-push.sh` also reports the backup from systemd every
10 min: a failed nightly backup alerts within 10 min, and a missed one within 10 min of turning 26 h old, whatever
Gatus did meanwhile. One exception: systemd forgets runs from before a boot, so after a reboot a missed backup alerts
only once the box has been up 26 h. The backup's own 26 h heartbeat is the fallback for when the timer isn't running.

## How alerts reach Michael

Gatus posts to ntfy.sh, topic `${GATUS_NTFY_TOPIC}` (set in `/srv/docker/.env`, never in git). Michael subscribes to
that topic in the ntfy phone app. Every alert is sent once when the endpoint turns red and once more when it turns
green again (`send-on-resolved`); a check that stays red doesn't repeat.

The pushed endpoints need the token `${GATUS_BACKUP_TOKEN}` (`Authorization: Bearer …`). The same token is in
`/srv/docker/.env` (Gatus), `/etc/restic/env` (the nightly backup) and `~/.config/dj-health-push.env` (the disk
timer). Scripts pass it to curl on stdin, so it never shows in `ps`.

## How to add a check

1. Add an endpoint to `deploy/gatus/config.yaml`: for an HTTP check copy the `navidrome` block (`interval: 60s`, an
   ntfy alert with `failure-threshold: 3` and `send-on-resolved: true`); for something pushed from outside copy
   the `disk` block under `external-endpoints` and push to `/api/v1/endpoints/_<name>/external?success=true|false`.
   Containers are reached by their compose service name on the default network.
2. Never write a secret into the file: only `${NAME}` references, passed into the container by `deploy/compose.yml`
   and listed in `deploy/.env.example`. Gatus expands every `$` in the file, comments included.
3. Add the endpoint to the table above, and to `tests/test_gatus.py`'s expectations. `.harness/check.sh` green.
4. Deploy it (live-staged, outside 03:15–04:30): `flock -n /srv/docker/crates/live.lock scripts/deploy.sh gatus`
   from a clean, pushed checkout. It copies that commit's config to `/srv/docker/gatus/config/` (D41; the file it
   replaces stays as `config.yaml.prev`), recreates only Gatus, so the new file is loaded now, and waits for its
   API: a broken config makes Gatus exit, and the deploy fails with the rollback. Then
   `curl -s http://127.0.0.1:4590/api/v1/endpoints/statuses`. (`skip-invalid-config-update` only covers an edit
   made in place while Gatus runs; it keeps the old checks and logs the error.)

Start Gatus only through `scripts/deploy.sh gatus`, never with a plain `docker compose up` from `/srv/docker`:
deploy.sh creates `/srv/docker/gatus` as mh550, Docker would create it as root.

Rollback, to the last config: `mv /srv/docker/gatus/config/config.yaml.prev /srv/docker/gatus/config/config.yaml &&
docker compose --project-directory /srv/docker -f deploy/compose.yml up -d --force-recreate gatus`. To remove Gatus:
`docker compose --project-directory /srv/docker -f deploy/compose.yml stop gatus && docker compose
--project-directory /srv/docker -f deploy/compose.yml rm -f gatus`.

## Michael's one-time steps

1. **Done 2026-10-19.** Pick a private ntfy topic. Put `GATUS_NTFY_TOPIC=<topic>` and a random
   `GATUS_BACKUP_TOKEN=<token>` in `/srv/docker/.env`. Put `GATUS_BACKUP_URL=http://127.0.0.1:4590` and the same
   token in `/etc/restic/env`. Subscribe to the topic in the ntfy app.
2. After H2 merges, install the backup script (it pushes the backup heartbeat):

       cd ~/projects/dj-crate-streaming && git checkout main && git pull && sudo deploy/install-backup.sh

3. After H3 merges, enable the disk and backup timer (as mh550, from that checkout of main, no sudo; copies, so a
   later checkout of another branch can't take the units away):

       install -D -m 0755 deploy/health-push.sh ~/.local/lib/dj-crates/health-push.sh
       install -m 0600 /dev/null ~/.config/dj-health-push.env
       printf 'GATUS_BACKUP_URL=http://127.0.0.1:4590\nGATUS_BACKUP_TOKEN=<same token as /srv/docker/.env>\n' >> ~/.config/dj-health-push.env
       install -D -m 0644 -t ~/.config/systemd/user deploy/systemd/dj-health-push.service deploy/systemd/dj-health-push.timer
       systemctl --user daemon-reload
       systemctl --user enable --now dj-health-push.timer
       systemctl --user start dj-health-push.service; journalctl --user -u dj-health-push -n 5
       loginctl enable-linger mh550     # user timers otherwise stop when mh550 has no session (Linger=no on 2026-10-19)

   Rollback: `systemctl --user disable --now dj-health-push.timer` (and `loginctl disable-linger mh550`). After a
   later change to `health-push.sh` or the units, rerun the first and fourth lines (`install … health-push.sh`, `install
   … ~/.config/systemd/user …`) and `daemon-reload`; not the second, which would empty the env file.

   Optional, to see the dashboard on the phone: `tailscale serve` port 4590.
