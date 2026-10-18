status: run
<!-- Steer this run from the GitHub app: edit this file on branch harness/dj-2026-10-17.
     Change the first line to "status: pause" or "status: stop"; write answers to questions under "### H3-03 (2026-10-18): enable the disk health timer (after H3-04 deploys Gatus and the vars are set)
Written and tested, not enabled. As mh550, from a checkout of main (no sudo):

    install -D -m 0755 deploy/health-push.sh ~/.local/lib/dj-crates/health-push.sh
    install -m 0600 /dev/null ~/.config/dj-health-push.env
    printf 'GATUS_BACKUP_URL=http://127.0.0.1:4590\nGATUS_BACKUP_TOKEN=<same token as /srv/docker/.env>\n' >> ~/.config/dj-health-push.env
    systemctl --user link $PWD/deploy/systemd/dj-health-push.service $PWD/deploy/systemd/dj-health-push.timer
    systemctl --user enable --now dj-health-push.timer
    systemctl --user start dj-health-push.service; journalctl --user -u dj-health-push -n 5

Rollback: `systemctl --user disable --now dj-health-push.timer`.

## Answers".
     The harness pulls before every session; every session reads this file at startup. -->

## For Michael: one-time steps (sessions write these; only you run them)

### H2-01 (2026-10-17): install the nightly backup from git, after H2 is merged into main
Only after H2 (H2-01 + its review H2-02) is merged. The installer refuses a dirty tree and any commit that isn't on
origin/main. It shows a diff of both files against what is installed and asks `[y/N]` before writing:

    cd ~/projects/dj-crate-streaming && git checkout main && git pull && sudo deploy/install-backup.sh

Optional, outside 03:15–04:30, to see it work once (this runs a real backup, about 2 min):

    sudo systemctl start restic-backup.service; journalctl -u restic-backup.service -n 20 --no-pager

Rollback: `git checkout <older main commit>` in that checkout, then the same `sudo deploy/install-backup.sh`.

Before the `sudo`, check the installer itself is main's (sudo runs the working-tree copy; this prints nothing):

    git -C ~/projects/dj-crate-streaming diff origin/main -- deploy/install-backup.sh

### H2-02 (2026-10-17): give the backup unit a start timeout (optional, any time outside 03:15–04:30)
`restic-backup.service` has `TimeoutStartUSec=infinity`, so a hang (e.g. a stuck mount) leaves it "activating"
for good: no backup, no failure, and the timer never fires again. A 3 h limit makes a hang fail visibly:

    sudo mkdir -p /etc/systemd/system/restic-backup.service.d
    printf '[Service]\nTimeoutStartSec=3h\n' | sudo tee /etc/systemd/system/restic-backup.service.d/timeout.conf
    sudo systemctl daemon-reload
    systemctl show restic-backup.service -p TimeoutStartUSec     # expect 3h

Rollback: `sudo rm /etc/systemd/system/restic-backup.service.d/timeout.conf && sudo systemctl daemon-reload`.

### H3-02 (2026-10-17): before Gatus can be deployed (H3-04), set its two values
Gatus exits at start while either is empty, and agents can't check `/srv/docker/.env`, so H3-04 waits for this.
From the spec (step 1 of your one-time steps): pick a private ntfy topic. Put `GATUS_NTFY_TOPIC=<topic>` and a random
`GATUS_BACKUP_TOKEN=<token>` in `/srv/docker/.env`. Put `GATUS_BACKUP_URL=http://127.0.0.1:4590` and the same token in
`/etc/restic/env`. For example (`openssl rand -hex 24` makes a token; `deploy/.env.example` lists both names):

    nano /srv/docker/.env            # add GATUS_NTFY_TOPIC=… and GATUS_BACKUP_TOKEN=…
    sudoedit /etc/restic/env         # add GATUS_BACKUP_URL=http://127.0.0.1:4590 and GATUS_BACKUP_TOKEN=… (same token)

Then subscribe to the topic in the ntfy phone app. Write "gatus vars set" under Answers so H3-04 knows.

## Answers
