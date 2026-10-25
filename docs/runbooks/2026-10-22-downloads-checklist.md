# Downloads checklist: the S1–S3 live steps after runs dj-crate-streaming-2026-10-22-fixes and -build

For Michael. Milestone S1 of `docs/specs/2026-10-22-downloads-and-requests.md` (S1-01..S1-08, the download fixes
from the Al Green attempts) was built on branch `harness/dj-crate-streaming-2026-10-22-fixes`; S2 (album requests) and
S3 (the request API and CLI) on branch `harness/dj-crate-streaming-2026-10-22-build`, which contains S1. All of it was
tested against the fakes only; **none of it has run live**. This file is the spec's "Morning checklist addition" steps
1–7, in that order, then the slskd captures; the numbers below are the spec's. Live today (per the spec): `crates` and
`worker` on `dj-crates:41fcc5bc01`, the 10-22 hotfix. Stop at the first surprise: undo that step, run **check**, and
ask.

## Conventions

The same as `docs/runbooks/2026-10-22-morning-checklist.md` → "Conventions", in short:

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

Then `docs/runbooks/2026-10-22-morning-checklist.md` section 4 ("Deploy `main` from a fresh worktree"), with this one
change: the image running before the deploy, and so the rollback, is **`dj-crates:41fcc5bc01`** (the hotfix), not
`f4882ab85b`. Confirm it with `docker compose ps` and `docker image ls dj-crates` before you deploy.

Check: as in section 4: `crates` and `worker` up and healthy on the new tag, `scripts/live-run.sh --print python3 -m sourcing.cli --help` names
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

## 4. Album request through the request API

**After S2/S3 are merged and deployed.** This run's PR (`gh pr list --head harness/dj-crate-streaming-2026-10-22-build`
gives its number) merges after step 1's two, from `~/projects/dj-crate-streaming`: `gh pr ready <that #> && gh pr merge
<that #> --merge`. Two cases:
- **Merged before step 2:** step 2 deployed S1–S3 at once. The rollback stays `dj-crates:41fcc5bc01`, and step 3 ran on
  this image.
- **Merged after step 2:** deploy again, after `git -C ~/projects/dj-crate-streaming pull --ff-only`, as in step 2 with
  three changes. Skip the morning checklist's sections 1–3 (done) and its snapshot (the same day's suffix would replace
  that restore point). Take this step's snapshot **before** the deploy: the new image migrates crates.db when it
  starts (new `requests` columns). The rollback is **`dj-crates:<the sha step 2 deployed>`** (the S1 image).

Snapshot, before the deploy (or, in the first case, before the first write below):
`scripts/snapshot-crates-db.sh --suffix pre-<date>-s2`, "integrity ok" twice. Check after the deploy as in step 2:
the new tag up and healthy, `scripts/live-run.sh --print python3 -m sourcing.cli --help` names it, **check** green.
The worker stays up: it downloads what you approve.

1. **The album path is in the image.** The image is built from the deploy worktree, so look there:
   `git -C <the deploy worktree> grep -n 'dj_album:1:' deploy/beets.yaml`.
   Check: one line, `dj_album:1: $albumartist/%if{$year,$album ($year),$album}/$track - $title`. Undo: none needed.
2. **Make the request.** First the MusicBrainz release, so the album's rows carry their recording ids and verify
   checks each file against its own track (the check that would have caught ext-74). `request add` asks MusicBrainz
   too (S4-02), but silently and best effort; the seed prints what it found. Then `request add` finds the same request
   and asks the library:

   ```
   flock -n /srv/docker/crates/live.lock scripts/live-run.sh python3 -m sourcing.cli seed-spotify https://open.spotify.com/album/2nTlIPIQ7fHOnNN7BRch0Z --musicbrainz
   flock -n /srv/docker/crates/live.lock scripts/live-run.sh python3 -m sourcing.cli request add https://open.spotify.com/album/2nTlIPIQ7fHOnNN7BRch0Z
   ```

   Check: each first line is `live-run: image dj-crates:<the sha this deploy made>`. The seed prints
   `request <id>: Al Green – I'm Still in Love With You (9 rows)`, then one of these:
   - `musicbrainz release <mbid>`: the ids are stored.
   - "no MusicBrainz release matches its 9 rows one to one; the request goes on without ids".
   - On stderr, `<error>; the request goes on without MusicBrainz ids` (MusicBrainz unreachable, exit 0).

   In the last two cases verify runs without the recording check. The add prints
   `request <id>: Al Green – I'm Still in Love With You (album, 9 rows, <n> in library); already requested` (the same
   `<id>`), then one line per row (`  01 ext-…  I'm Still In Love With You  ok`). The rows step 3 filed are `ok`
   already. A row that was still open and that Navidrome has turns `ok` with a `matched` event
   (`curl -s 'http://127.0.0.1:4580/api/events?limit=200'`); nothing is downloaded for it.
3. **Preview** (one slskd search, nothing enqueued; it caches the plan in crates.db):

   ```
   flock -n /srv/docker/crates/live.lock scripts/live-run.sh python3 -m sourcing.cli request preview <id>
   ```

   Check:
   - The first line is `folder 1: <k> of <m>, score …`, with `<k>` at least all but one of the `<m>` open rows (8 of
     9 when none is in the library).
   - Then one line per row, `  <track>. <title> → <basename>`.
   - Then `secondary folder 2: …` if the plan has one, `per track: …` for the rest, and `alternate folder <n>: …`
     lines (the folders kept for a switch).
   - Folders appear only as labels: no peer name anywhere.

   If step 3 left every row `ok`, it prints `nothing to plan` on stderr (exit 1). The Al Green request then has
   nothing left to download: do 3–5 with the next album you want (6 below).
4. **One row first** (it writes tags: the album-tags plan's "Live steps"). In the web client, Preview and Approve
   **one** of the request's open rows, as in step 3: your click (D7). It goes per track but is filed with the
   request's album tags.
   Check:
   - `/api/events` shows, for that row, `pick`, a `tagged` event `{…}` (the old tag values), then
     `filed beets …: Al Green/I'm Still in Love With You/<nn> - <title>.<ext>`. `<title>` is the file's title tag,
     or MusicBrainz's if beets matched (`beets matched:`).
   - The folder is `… (<year>)` with the release group's first-release year when step 2 printed `musicbrainz release
     <mbid>` (D53 *default*; `request show <id>` names the release), else it has no year: the Spotify embed has none
     and D51 clears it. S2-06b's album path holds (measured on beets 1.6.0).
   - Navidrome shows the album "I'm Still in Love With You" by Al Green with that track. **check** green.

   Undo: `docs/plans/2026-10-22-S2-album-tags.md` → "Reverse" for that file (the `tagged` event's values; worker
   stopped).
5. **Approve the rest:** your click (D7), the only step here that leads to transfers. The worker downloads on its next
   tick (`WORKER_POLL_S`, 30 s):

   ```
   flock -n /srv/docker/crates/live.lock scripts/live-run.sh python3 -m sourcing.cli request approve <id>
   ```

   Check: it prints `approved <n> rows of request <id>; the worker downloads them on its next tick`. A row in progress
   is refused with the API's 409 text (exit 1): wait for the worker, then approve again. Over the next minutes,
   `/api/events` shows:
   - per row: `pick` (`planned file: <basename>`, or `per track: …`), `tagged {…}`, `filed`, and a `status` event
     `ok`;
   - a `placed` event for a row a playlist holds (step 3's `6CqtHuurS3iah9VrrfrVam`);
   - **at most one** `switch` (`#<id> folder 1 distrusted: …`);
   - a second `plan` event only if the preview's plan was over an hour old (`ALBUM_PLAN_MAX_AGE_S`).

   Then:

   ```
   scripts/live-run.sh python3 -m sourcing.cli request show <id>
   ```

   (no lock: it only reads). It lists each row `ok` or `failed`, every attempt in a failed row's reason. To see that
   the new files form one album, take a fresh snapshot (`scripts/snapshot-crates-db.sh --suffix post-<date>-s2`), then:

   ```
   sqlite3 -readonly /srv/docker/navidrome/navidrome.db.post-<date>-s2.snap "SELECT count(DISTINCT album_id) FROM media_file WHERE path LIKE '%Al Green/I''m Still in Love With You/%'"
   ```

   It prints `1`. Step 3's singles under `Al Green/Singles/` keep their own album tags (not retagged), so Navidrome
   may also list them as a second entry of that name. That is expected. **check** green.
6. **Another album** (when Al Green had nothing left to plan): the same four commands of 2, 3 and 5 with its Spotify
   album link and its new `<id>`, and one row first as in 4.
   Check: the seed and the add print its artist, title and track count; preview covers all but at most one open row
   in `folder 1` or it says why. The files land under `<album artist>/<album> (<year>)/` when MusicBrainz matched the
   release (D53 *default*), else `<album artist>/<album>/`. A MusicBrainz release link (`request add https://musicbrainz.org/release/<id>`) carries the release's year
   (`<album> (<year>)/`), but only for an album not requested yet: for one requested before, the add answers with
   that request.

Undo:
- A wrong row: `wanted reopen <ext-id>` as in step 3 (dry run, then `--apply` under the lock); its file stays as its
  own song. To give that file its old tags back: the album-tags plan's "Reverse", as in 4. Nothing is trashed by
  hand: a second copy goes with the N1 duplicate cleanup.
- The request stays as history (no delete). An approval can't be withdrawn: if the preview looks wrong, don't approve.
- The deploy: the rollback command of step 2, with `GIT_SHA=` the rollback of this step's case. Roll back only once
  the album job has ended: `request show <id>` has no row `sourcing` or `verify`, and in `request show <id> --json`
  every approval has a `usedAt`. The older worker would
  spend leftover `album` approvals as per-track downloads without album tags. Then **check**. Files already filed
  stay in their album folders.

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

## 6. Spotify developer app and the capture

For the next catalog provider (S3-02: the Spotify provider is built against real replies only). Nothing here touches the server: it runs on
the host, as you; no container, no lock, no snapshot. **After this run's PR is on `main`** (section 4's merge), so the
capture's own PR holds the two fixtures and nothing else.

1. On developer.spotify.com (logged in with the account that owns the app; the Web API needs Premium on it): Dashboard
   → Create app, API "Web API", any redirect URI (the capture uses none). Keep the Client ID; the Client secret stays
   in the dashboard until step 3 reads it.
2. A checkout of `main` (it has `scripts/capture_spotify.py` once the run's PR is merged), on a branch of its own:

   ```
   git -C ~/projects/dj-crate-streaming fetch -q origin
   git -C ~/projects/dj-crate-streaming worktree add -b spotify-capture ~/worktrees/dj-crate-streaming/spotify-capture origin/main
   cd ~/worktrees/dj-crate-streaming/spotify-capture
   ```

3. The capture, exactly as `scripts/capture_spotify.py`'s docstring has it (`read -rs` prompts for the secret without
   echoing it; paste it and press Enter):

   ```
   read -rs SPOTIFY_CLIENT_SECRET; export SPOTIFY_CLIENT_SECRET SPOTIFY_CLIENT_ID=<id>; python3 -m scripts.capture_spotify "Al Green I'm Still in Love With You"
   ```

   It makes three requests (one token, one search, one album) and stops. Exit 2: a variable is unset, nothing was
   asked. Exit 3: rate limited; it prints `Retry-After` and does not retry: wait that long, then run it again. Exit 1:
   one line on stderr, nothing written.

Check: in the same shell (the secret is still in its environment),
- exit 0 and two files, `fixtures/spotify_search.captured.json` and `fixtures/spotify_album.captured.json`;
- `grep -cFf <(printf '%s\n' "$SPOTIFY_CLIENT_SECRET") fixtures/spotify_*.captured.json` prints `0` for each (the
  secret is read from a pipe, not put on grep's command line; if it prints the line counts instead, the variable is
  empty: this is not the shell of step 3);
- `grep -c access_token fixtures/spotify_*.captured.json` and `grep -c tok_ fixtures/spotify_*.captured.json` print
  `0` for each (`tok_` is the tests' stub token: a quick sign the files are the real replies; a real token is not
  `tok_`-prefixed, so the script's own refusal of a reply repeating the token or the secret is the real guard).

Then `unset SPOTIFY_CLIENT_SECRET`. Read both: catalog data only (albums, tracks, artists, images), no account. Then
`git add fixtures/spotify_search.captured.json fixtures/spotify_album.captured.json` and a commit
(`git commit -m "fixtures: Spotify Web API capture for the next provider (S3-06)"`), `git push -u origin
spotify-capture` and a draft PR (`gh pr create --draft --base main`): its diff is the two files only. The next run
builds the Spotify provider on them.

Undo: before the commit, `rm fixtures/spotify_search.captured.json fixtures/spotify_album.captured.json`; after it,
`git revert` the commit (or close the PR unmerged). If the secret was ever printed, written to a file or pasted
anywhere else, rotate it in the dashboard (the app → Settings → rotate the client secret); the old one stops working.
Remove the worktree when done: `git -C ~/projects/dj-crate-streaming worktree remove ~/worktrees/dj-crate-streaming/spotify-capture`.

Where the secret lives for good (for the provider in the crates container: `/srv/docker/.env` plus the compose
environment, or somewhere else) is not decided here; it is a question for when the provider is built.

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

## Captures for the fixtures

slskd shapes that the S1 fixes and the S2 album job depend on but that no fixture holds: the fake slskd
(`sourcing/fake_slskd.py`) answers them as read from slskd 0.26.1's code and the 10-21 logs, not from a capture. Three
captures settle them (the S1-R1 review's three questions among them). No code reads these files yet: a later feature
adds a test to `tests/test_fake_slskd.py` that loads each one and holds the fake to its shape. Only shapes this
run or S1 relies on are listed; the SoulSync review's other open slskd questions
(`docs/research/2026-10-22-soulsync/04-soulseek.md` on branch `origin/harness/dj-soulsync-review-2026-10-22`, e.g.
`GET /transfers/downloads/<transfer id>`) are context only, since nothing here calls them. One shape our code relies
on stays uncaptured: the 404 that the per-peer `GET /transfers/downloads/<peer>` answers for a peer with no transfers
(`sourcing/slskd_client.py` reads it as an empty listing); the UI uses the all-peers listing.

How, without a secret or a command of ours: slskd's web UI with the browser's developer tools open (Network tab,
filter `transfers`). The UI calls the same `/api/v0/…` endpoints; each request's Response tab has the body to copy.
`docker logs dj-worker-1` does not have them (the worker logs no slskd reply bodies). The enqueue is a Soulseek
transfer, so it is yours (D7): do it with files you want anyway, or cancel and remove them in the UI right after
(that gives capture 3 too). **Cancel or remove only records you enqueued in the UI for these captures, never one the
worker enqueued** (section 4's or any approved download): that fails the row or switches a running album job. Copy
response bodies only: never the request headers or "Copy as cURL", which carry slskd's session token.

Before you save a file: replace each peer name with `peer-a`, `peer-b` (in `username` and in any path), each share
root (`@@abcde\`) with `@@share\`, and any personal part of a path (`C:\Users\<name>\`, a real name) with `user`,
so no peer is named in the repo; `grep -c '<the peer name>' <file>` is 0. Save them
in a checkout on a branch of its own (as in section 6), commit, and open a draft PR.

1. **`fixtures/slskd_enqueue.captured.json`: a multi-file enqueue.** In the UI, open one search result's folder,
   select two or more files and Download: one `POST /transfers/downloads/<peer>` (`/api/v0/transfers/downloads/<peer>`)
   with a list of `{filename, size}`, the request the album job sends once per peer (`sourcing/album_job.py`). Save
   `{"status": <its HTTP status>, "request": <the request body>, "reply": <the reply body>}`. Then Download one of the
   same files again while its record is still listed (what slskd answers to a duplicate enqueue): add
   `"again": {"status": …, "reply": …}`. Our code reads no enqueue reply (S1-04: it tells its transfer by the ids
   listed before the POST); the fake answers a list of transfer records, a guess this capture checks.
   Which test reads it: the later `tests/test_fake_slskd.py` test, against `sourcing/fake_slskd.py`'s POST reply.
2. **`fixtures/slskd_transfers.captured.json`: a transfer record per state, and two records of one file.** The UI's
   Downloads page polls `GET /transfers/downloads` (all peers): copy one reply while a file is `Queued, Remotely`
   (or `Queued, Locally`), one `InProgress`, one `Completed, Succeeded`, and one in an error state
   (`Completed, Errored|TimedOut|Rejected|Cancelled`; a cancel in the UI gives `Completed, Cancelled`). Step 4's
   downloads and the enqueue above give most of them. The duplicate enqueue in capture 1 should leave two records of
   one file in one reply (if slskd refused it, note that instead). During a VPN drop (step 7), one more reply shows
   whether a transfer caught in the logout survives the 20 s pause (S1-06). Save
   `{"<state>": <reply>, …, "two_of_one_file": <reply>, "after_logout": <reply or null>}`. What depends on them: the
   states `sourcing/fetch.py` matches (`Completed, Succeeded`; `TRANSFER_ERRORS`), the album job's `NOT_STARTED`
   (`Queued`, `Requested`, `Initializing`) and the record shape `{username, directories: [{directory, files: [{id,
   filename, state, size, …}]}]}`. Which test reads it: the later `tests/test_fake_slskd.py` test, against the fake's
   listing and states.
3. **`fixtures/slskd_remove.captured.json`: `DELETE …?remove=true` on a running and on a finished record.** In the
   Downloads list, Remove (or Cancel, then Remove) a running record, and Remove a finished one: each is a
   `DELETE /transfers/downloads/<peer>/<id>?remove=true`. Note each request's exact URL (with or without
   `?remove=true`: that says what the UI sends) and HTTP status, then the next `GET /transfers/downloads` reply: does
   the running transfer stop and its record go, and does the finished one go? slskd 0.26.1's code keeps the record
   without `?remove=true`, and our cancel and forget (`fetch.forget_new`, `forget_finished`, the album job's switch)
   rely on `?remove=true` removing it. Save `{"running": {"url": …, "status": …, "listing_after": …}, "finished": {…}}`.
   Which test reads it: the later `tests/test_fake_slskd.py` test, against the fake's DELETE (cancel keeps the
   record, remove forgets it, an unknown id is 404).
