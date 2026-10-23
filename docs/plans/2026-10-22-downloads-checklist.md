# Downloads checklist: the S1 live steps after run dj-crate-streaming-2026-10-22-fixes

For Michael. Milestone S1 of `docs/specs/2026-10-22-downloads-and-requests.md` (S1-01..S1-08, the download fixes
from the Al Green attempts) was built on branch `harness/dj-crate-streaming-2026-10-22-fixes` and tested against the
fakes only; **none of it has run live**. This file is the spec's "Morning checklist addition" steps 1–3, 5 and 7, in
that order; the numbers below are the spec's. Live today (per the spec): `crates` and `worker` on
`dj-crates:41fcc5bc01`, the 10-22 hotfix. Stop at the first surprise: undo that step, run **check**, and ask.

## Conventions

The same as `docs/plans/2026-10-22-morning-checklist.md` → "Conventions", in short:

- **Lock.** Wrap each live write and each deploy in `flock -n /srv/docker/crates/live.lock <command>`.
- **Window.** No live write and no deploy from 03:15 to 04:30, or while `systemctl is-active restic-backup.service`
  prints `active`.
- **Snapshots first.** Before the first live write of the day: backup status (`ExecMainStatus=0`, under 26 h old),
  **check** green, then `scripts/snapshot-crates-db.sh --suffix pre-<date>-s1` ("integrity ok" for both databases).
  The `-s1` keeps the morning checklist's `pre-<date>` restore point of the same day: the same suffix replaces it.
- **check** = `scripts/live-check.sh`. Pass: exit 0 and "ok: every playlist file matches Navidrome…".
- **One-off worker commands** go through `scripts/live-run.sh <command…>` (the deployed image, D45). Its first output
  line is `live-run: image dj-crates:<rev>`.

## 1. PR #16 on main, before any deploy from main

```
git -C ~/projects/dj-crate-streaming fetch -q && git -C ~/projects/dj-crate-streaming merge-base --is-ancestor 59c6f6a origin/main && echo ok
```

If it prints nothing, from `~/projects/dj-crate-streaming` (so `gh` knows the repo): `gh pr ready 16 && gh pr merge 16 --merge` (a merge commit, not a squash, so the commits match
this run's base), then the command again. Then merge this run's S1 PR after it:
`gh pr list --head harness/dj-crate-streaming-2026-10-22-fixes` gives its number, then `gh pr merge <that #> --merge`.

Check: the command prints `ok`; `git -C ~/projects/dj-crate-streaming fetch -q && git -C ~/projects/dj-crate-streaming log --oneline -3 origin/main`
shows the S1 merge on top.
Undo: nothing is live yet. A wrong merge on main is reverted with `git revert -m 1 <merge sha>` in a PR (never a
force-push to main).

## 2. Deploy main

First the morning checklist's sections 1–3 (main checkout pulled, `/srv/docker/compose.yml` follows it; no pinned
`GIT_SHA`). If you did them before step 1's merges, pull again: `git -C ~/projects/dj-crate-streaming pull --ff-only`.

Then `docs/plans/2026-10-22-morning-checklist.md` section 4 ("Deploy `main` from a fresh worktree"), with this one
change: the image running before the deploy, and so the rollback, is **`dj-crates:41fcc5bc01`** (the hotfix), not
`f4882ab85b`. Confirm it with `docker compose ps` and `docker image ls dj-crates` before you deploy.

Check: as in section 4: `crates` and `worker` up and healthy on the new tag, `scripts/live-run.sh --print true` names
the new sha, **check** green.
Undo (from the deploy worktree):

```
GIT_SHA=41fcc5bc01 CRATES_SRC=$PWD docker compose --project-directory /srv/docker -f deploy/compose.yml up -d --no-build crates worker
```

If that image is gone: `scripts/deploy.sh` from a worktree at commit `41fcc5bc01`. Then **check**.

## 3. Re-test the Al Green album

**Only after step 2 has deployed S1**, not before: without S1-01..S1-03 the same-named folder can bring the wrong song
again. Snapshots first (a crates.db write).

Reopen ext-74 (filed as "One of These Good Old Days"; `docs/worker.md` → "Reopen a row filed as the wrong song"):

```
scripts/live-run.sh python3 -m crates.cli wanted reopen ext-74
flock -n /srv/docker/crates/live.lock scripts/live-run.sh python3 -m crates.cli wanted reopen ext-74 --apply
```

Check: the first line is `live-run: image dj-crates:<the sha step 2 deployed>` (any other sha: stop, S1 isn't
live). The next is `ext-74: Al Green – One of These Good Old Days → Al Green – I'm Still In Love With You`; the
`placed when the right file arrives:` line names the album's playlist `6CqtHuurS3iah9VrrfrVam`; the last is
`dry run: add --apply to write this`. A refusal (`wanted reopen: …`, exit 1) is a surprise: stop. `--apply` prints
the same plan and ``reopened ext-74; the `reopened` event holds the old values``.

The wrong "One of These Good Old Days" entry stays at ext-74's place in `6CqtHuurS3iah9VrrfrVam` (D49; ext-81's
copy is in it too). Remove that one entry by hand in the playlist, so the title is there once.

Then in the web client, Preview and Approve **ext-74** and **ext-78** (ext-78 still shows the 21:46 404; it was never
approved again). The worker downloads them on its next ticks.

Check:
- ext-74 is track 01 "I'm Still In Love With You" and ext-78 is "Oh, Pretty Woman", both `ok`
  (`curl -s http://127.0.0.1:4580/api/wanted/ext-74`, the same for ext-78). Length can't tell track 01 from track 09
  (195.7 s vs 195.6 s): look at the filed path in the `filed` event or the reason, and play the start in Navidrome.
- `curl -s 'http://127.0.0.1:4580/api/events?limit=200'` shows, for each row, `pick`, `filed`, a `status` event
  `ok` and a `placed` event into `6CqtHuurS3iah9VrrfrVam`, and **no** `renamed` to another title and **no**
  `wrong_song`. A `retry` event (S1-06, another peer after a transfer error) is fine. A `matched` event
  `same recording: …` or `same version: …` (S1-07) means the library already had it and nothing was downloaded;
  `matched` `library not asked: …` means Navidrome didn't answer and the download went ahead.
- Navidrome lists all 9 titles of *I'm Still in Love With You* under the artist Al Green (as singletons they need not
  share one album: the album path is S2/S3). **check** green.

Undo:
- The reopen: the `reopened` event's old values (`docs/worker.md` → "Reopen a row filed as the wrong song": the
  `SELECT detail …` and the `UPDATE`/`INSERT` it gives, worker stopped). The removed playlist entry comes back from
  `/srv/music/_playlists/.history/<date>/` or by adding it again in Navidrome.
- A new download that is wrong after all: `wanted reopen` it again (the row goes back to `needs_source`). The file
  stays as its own song, and its playlist entry stays (D49). A second copy of a recording goes with the N1 duplicate
  cleanup (step 5). Don't move a file to the trash by hand: anything else, stop and ask.

## 5. Duplicate cleanup plan for the `.1.flac` copy

ext-81 filed `One of These Good Old Days.1.flac`, a second copy of the file ext-74 brought. The N1 cleanup handles it
(`docs/worker.md` → "Duplicate cleanup"). **Plan only**:

```
scripts/live-run.sh python3 -m scripts.duplicate_cleanup plan
```

Check: `/srv/docker/crates/duplicate-cleanup/report.md`, section "Lossless pairs, will be trashed" (both copies are
FLAC), has the pair of `One of These Good Old Days` paths, one as keeper and one as extra (`keep_rank` picks which; a
`.1.flac` keeper is fine if it ranks higher).
Undo: nothing is written to the library; a re-run keeps the old `plan.json` as `plan-<made_at>.json`. Repoint and the
held trash follow the morning checklist's section 6, not this step. This `plan` replaces `plan.json`: if section 6's
repoint stages already ran, run them again on this plan before any trash.

## 7. gluetun's port forwarding

The VPN drops every 5–15 min because gluetun's NAT-PMP refresh times out, and slskd logs out of Soulseek for about
10 s. It's yours (compose); look at why:

```
docker logs dj-gluetun-1 2>&1 | grep 'port forwarding'
```

Check: the `refreshing port mapping … connection failed` lines and how often they come. Since S1-06 a drop costs one
retry: if another peer offers the file, the row gets a `retry` event and that peer after a 20 s pause; otherwise, or
on a second drop, it fails as before.
Undo: a setting you change lives in `deploy/compose.yml` of `~/projects/dj-crate-streaming` (which
`/srv/docker/compose.yml` follows): revert it there with git, then `docker compose up -d gluetun slskd` with no
download in flight and outside the window. slskd uses gluetun's network (`network_mode: "service:gluetun"`), so
recreating gluetun alone leaves slskd without a network.

While you are in slskd's UI during steps 3 and 7, three things are worth noting for the fixtures (the S1-R1 review
asked; no code depends on them yet): whether a running transfer disappears after our cancel (`DELETE ?remove=true`),
what slskd answers to a duplicate enqueue, and whether a transfer caught in a logout survives the 20 s pause.

Steps 4 (the album request through `sourcing.cli request`) and 6 (the Spotify app and capture) of the spec's
addition belong to the S2–S4 run (`dj-crate-streaming-2026-10-22-build`).
