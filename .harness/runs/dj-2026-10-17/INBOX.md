status: run
<!-- Steer this run from the GitHub app: edit this file on branch harness/dj-2026-10-17.
     Change the first line to "status: pause" or "status: stop"; write answers to questions under "## Answers".
     The harness pulls before every session; every session reads this file at startup. -->

## For Michael: one-time steps (sessions write these; only you run them)

### H2-01 (2026-10-17): install the nightly backup from git, after H2 is merged into main
Only after H2 (H2-01 + its review H2-02) is merged. The installer refuses a dirty tree and any commit that isn't on
origin/main. It shows a diff of both files against what is installed and asks `[y/N]` before writing:

    cd ~/projects/dj-crate-streaming && git checkout main && git pull && sudo deploy/install-backup.sh

Optional, outside 03:15–04:30, to see it work once (this runs a real backup, about 2 min):

    sudo systemctl start restic-backup.service; journalctl -u restic-backup.service -n 20 --no-pager

Rollback: `git checkout <older main commit>` in that checkout, then the same `sudo deploy/install-backup.sh`.

## Answers
