# The worker

The worker is a second container (`worker` in `deploy/compose.yml`) running `python -m sourcing.cli worker`. It is the
only process that downloads from Soulseek or runs beets (D18). The `crates` container keeps serving the web client
and never touches `/srv/music` or `/srv/incoming`.

## What it does each tick

A tick runs every `WORKER_POLL_S` seconds (30 by default), in this order:

1. **Re-check.** Every row that was filed but not yet seen by Navidrome (status `verify`) is asked again whether the
   song has appeared, at most once every `WORKER_RECHECK_S` seconds per row (300 by default), because each re-check
   starts a Navidrome scan. It searches by the filed file's own artist and title tags (what Navidrome indexes), not
   the wanted row's names. Nothing is downloaded for these. Each miss is counted in the reason (`(check N)`); after 12
   the row fails with "Navidrome never indexed <path>; file is in the library", so you see it. Approving that row
   again downloads nothing: it re-checks the same file (counting from 1 again), and the approval reads
   `recheck: already filed as <path>`. If Navidrome still misses it, look at the file's tags.
2. **Approvals.** Each unused approval is claimed, then fetched: search slskd, prefer the exact file you saw in
   Preview while it is still offered (otherwise the top-ranked one), download it, verify it, file it, ask
   Navidrome to rescan, and swap it into the crates. The outcome is written back on the approval.

One bad row never stops the tick, and a tick that fails (slskd or Navidrome down, database locked) never stops the
worker; the next tick tries again. `python -m sourcing.cli worker --once` runs a single tick and exits.

Only one worker runs at a time: it holds an exclusive lock on `worker.lock` next to `crates.db` (`/data/worker.lock`
in the container) for its whole life. A second one, e.g. `docker compose exec -T worker python -m sourcing.cli worker
--once` while the service is running, exits with "worker already running" and touches nothing. Outside the worker
container (`DJ_WORKER=1` unset) `sourcing.cli worker` refuses to start.

Once beets has filed a download, the row never goes back to `failed` on an error: it becomes `verify` with the filed
path in its reason, so the re-check picks it up and nothing downloads a second copy. Rows in progress (`sourcing`,
`verify`) stay in the Wanted tab with their status and reason, without Preview or Approve.

## Approvals

1. In the web client's Wanted tab, press **Preview**. It searches and scores but downloads nothing, and shows the
   pick (file name, format, bit rate, score) and a "why" panel.
2. Press **Approve**. The row reads "approved · waiting for worker" until the next tick takes it, then
   "worker: <outcome>".

Every download carries an approval record (D23): who approved, the candidate, the tier and the time. Today the only
`approved_by` value is `michael` (the Approve button, and `sourcing.cli fetch --approve`). Later values are
`policy:<name>` and `agent:<id>`: new approvers, not a redesign.

`sourcing.cli fetch --wanted <id> --approve` only records the approval, with the same rules as the Approve button
(the previewed pick if there is one; refused for a row that is `sourcing` or `verify`), and prints "approved; the
worker picks it up on its next tick". Add `--wait` to wait (up to 600 s) for the worker's outcome. Run it in the
worker container, which has the real `CRATES_DB`; the command refuses to run without `CRATES_DB` in its environment
(its default path is relative to the working directory, so a host run would approve in a stray database). The worker
daemon is the only process that downloads, files with beets, and holds the worker lock, so a manual run can never be
a second beets writer or leave an approval `started`.

```
cd /srv/docker && docker compose exec -T worker python -m sourcing.cli fetch --wanted <id> --approve [--wait]
```

A row that failed as "Navidrome never indexed <path>" shows **Re-check** instead of Preview/Approve: it approves with
no candidate, and the worker re-checks the filed file without downloading.

A Preview of a row that is already filed (`verify`, or failed as "Navidrome never indexed …") searches nothing and
changes nothing: it answers "already filed as <path>; the worker re-checks it". The web service answers 409 to
Preview or Approve of a row that is `sourcing` or `verify`.

Approvals are claimed atomically. A second approval for the same row supersedes the first; a superseded or already
taken approval is skipped, with a `skipped <id>: approval #N already used` line in the log.

## Filing

The verified download is never imported from slskd's folder. It moves to its own
`/srv/incoming/soulseek/.staging/<id>-<timestamp>/` folder and beets imports it from there
(`beet import -q -s -m -W`: quiet, as a singleton, moved into the library, no write during import).

- **Matched.** beets found the recording on MusicBrainz. The worker runs `beet write` on that one new file, and only
  when `sourcing/musicbrainz.py` confirms that the recording's length agrees with the file (within 4 s). beets 1.6
  applies a match on artist and title alone when MusicBrainz has no length for the recording; for a DJ library
  (radio edit or 12"?) that is a guess, so it does not count as confident (D22). The `filed` event reads
  `beets matched: <path>` and, when relevant, the reason.
- **As-is.** No match, or a match that was not confirmed. The file keeps its own tags, byte for byte. The `filed` event
  reads `beets as-is: <path>` and says why. An unconfirmed match has one side effect: beets' `library.db` (a
  disposable index) holds the matched metadata and the file sits under the matched artist/title path, while the file's
  tags are untouched. `beet update -M` refreshes the index from the tags.
- **Missing tags.** An empty artist or title tag is filled from the wanted row before import, and a `tagged` event
  says so.
- **`duplicate_action: keep`.** Copies and versions of one song coexist in this library. `skip` would silently drop
  every copy upgrade, so beets keeps both and the new file lands next to the old one.
- **Names copied back.** Once Navidrome has indexed the new file, its artist and title go back onto the wanted row
  (a `renamed:` event), because they are what the library now calls the song.
- If beets imports nothing, the row fails and the file stays in `.staging/<id>-<timestamp>/` for you to look at.

beets 1.6 configures MusicBrainz before it reads the `-c` file, so MusicBrainz settings for the worker go in
`$BEETSDIR/config.yaml` (`/srv/docker/beets/config.yaml`), not in `deploy/beets.yaml`. That file does not exist today and
the worker needs none. beets' state (`library.db`, `import.log`) is in `/srv/docker/beets`.

## Copy upgrades

When the wanted row is a song already in Navidrome that is not good enough, the old copy is the reference. The
worker reads its path from Navidrome's database (read-only) and fingerprints both files with `fpcalc`; a bit-error
rate under 0.20 means the same recording. If the reference cannot be found, a `reference` event says why and the
download is verified without one.

The comparison runs over the full length of both files. verify then reports `replaceable`: true only when the bit-error
rate is 0.20 or less, the durations agree, the files differ and the verdict is `ok` (`docs/identity.md`). Without a
reference it is false. M8's replacement will trash the old copy only when it is true. A download of another version
of the song (the row's file name shows a different label) is not compared with the old copy: it is verified as a new
version and added.

With `ACOUSTID_KEY` set, an AcoustID lookup also checks the new file against the recording id Navidrome holds. Without
the key there is no lookup. To enable it, add `ACOUSTID_KEY=<your key>` to `/srv/docker/.env`; the compose file passes
it through (empty means off). The key travels in a request body, never in a URL or a log.

## Identity backfill (runs in the worker)

Only 98 of 831 library files carry a MusicBrainz recording id. Navidrome uses it to keep a song's id after a retag
plus a move, and M8 will trust it to tell copies from versions. The backfill fills the ids in, in three steps:
propose, review, apply. It runs in the worker because that container holds `/srv/music` read-write, `fpcalc` and
the Navidrome credentials, so every library writer stays in one place. See `docs/identity.md` for what the classes
mean. beets is not used.

All commands run from `/srv/docker`. Output lands in `/data/identity/` in the container, which is
`/srv/docker/crates/identity/` on the host.

**1. Propose (reads the library, writes nothing to it).**

```
cd /srv/docker
docker compose exec -T worker python -m scripts.identity_backfill propose            # the whole library
docker compose exec -T worker python -m scripts.identity_backfill propose --limit 40 # a trial
```

- It makes `identity-proposal.json`, `identity-backfill-report.md` and `mb-cache.jsonl` in the output folder.
  `--out` and `--music` change the folders. `--out` inside the library is refused.
- MusicBrainz allows about one request per second, and about one in ten gets a 503, which the client retries. Expect
  roughly 45 to 70 minutes for the whole library. A progress line every 50 files shows the time left.
- If the run is killed, run the same command again. Answers already fetched come from `mb-cache.jsonl`.
- With `ACOUSTID_KEY` set in `/srv/docker/.env` it also uses AcoustID. Without it, that step is skipped.

**2. Review.** Open `identity-backfill-report.md` (`/srv/docker/crates/identity/`). It lists each class with the files in
it and a MusicBrainz link for each pick. Then, in `identity-proposal.json`:
- set `"skip": true` on any row you do not want written;
- on an `ambiguous` row (or a `none` row with candidates), set `"choose": "<recording id>"` to one of its listed
  candidates. Any other id is refused;

By default `apply` writes only the accepted rows of the `confirmed`, `isrc` and `acoustid` classes, plus rows with a
`choose`. Rows of another class (`search`, for example) are written only when you name the class with `--classes`
(below).

**3. Apply.** Look first, then write.

```
docker compose exec -T worker python -m scripts.identity_backfill apply /data/identity/identity-proposal.json --dry-run
docker compose exec -T worker python -m scripts.identity_backfill apply /data/identity/identity-proposal.json --yes
```

- `--dry-run` prints each file and the ids it would write, and every skip with its reason. It writes nothing and
  does not touch Navidrome. Without `--dry-run` or `--yes`, `apply` refuses to run.
- Narrow it with `--classes isrc,acoustid`, `--limit N` (at most N files) and `--only 'GLOB'` (repeatable, matched on
  the path). Start with `--limit 5`.
- What it writes: `mb_trackid`, `mb_workid` and `acoustid_id`, through `write_minimal`, and only where the file's own
  field is empty. A file that already has a different id, or that changed since `propose` (size, time or tags), is
  skipped with a reason. Every other tag must come back unchanged, or the run stops.
- Each write is logged first to `/data/identity/apply-<time>.jsonl`, with the values it replaced (`--log` changes the
  file).
- After the writes it asks Navidrome to scan and checks that every written file kept its song id, that Navidrome
  reads the recording id, and that the exported playlists still resolve. Run
  `python3 scripts/export_playlists.py check` first: a playlist that was already stale shows up as a problem.
  `--no-navidrome` skips this.
- It exits 1 when any check reports a problem. The first failed write stops the run.

**Undo.**

```
docker compose exec -T worker python -m scripts.identity_backfill revert /data/identity/apply-<time>.jsonl
```

It removes the fields that apply wrote, newest first, and only where a file still holds exactly that value. A field
you changed by hand is left alone, and the run says so. Running it twice is harmless.
To apply again after an undo, run `propose` first: the undo changes each file's modification time, so `apply`
skips those files as "changed since the proposal".

## Editing the policy

`deploy/policy.toml` holds Michael's settings: the four quality tiers (what each accepts, its floors and speed
weight) and the version preferences. The worker and the crates service read it once at start-up, from the image
(`Dockerfile` copies it). To change it:

```
cd /srv/docker
$EDITOR /home/mh550/projects/dj-crate-streaming/deploy/policy.toml
docker compose up -d --build crates worker
```

A typo (an unknown key, a version word that does not exist, a wrong type) stops the start with a message naming the
key, so check `docker compose logs --tail 5 worker` afterwards.

The tier numbers are the same as before M7. D17 (raising the medium and high bitrate floors) is still open, and it is
one number per tier in this file.

Each tier may have a `[versions.<tier>]` block with two lists:
- **`prefer`**: versions we favour when choosing a download, best first. A candidate whose file name shows one gets
  a few extra points. It is a nudge, not a rule: a much better file still wins.
- **`accept`**: other versions that may stand in for the one a playlist row asked for, when an import looks for the
  song in the library. A playlist's own choice always wins, and a stand-in is logged as "matched with another
  version". A version counts only when **every** version word in it is on the list.

The words are `edit extended club dub instrumental acappella live remix reedit demo alt original`. A 12" is
`extended`.

D16 as it stands today:

```
[versions.crate]
prefer = ["extended", "club", "original"]   # at crate quality, take the 12" or club mix when we choose
accept = ["extended", "club"]

[versions.high]                              # same for medium and low
prefer = []
accept = ["extended"]                        # a 12" may stand in for a radio-version row
```

So an import row for "Good Times" can match a "Good Times (12" Version)" in the library at `high`. A "Good Times
(12" Dub)" cannot, because `dub` is not accepted: that row goes to review. A crate upgrade never swaps in another
version at all; it only looks for better copies of the version the library already holds.

## Streaming default

The web client's stream quality menu has a "server" entry (D19): the client sends no format, so Navidrome's player
profile for `dj-crates-web` decides. It is the default only for a database that has never stored a choice. A
`crates.db` that already stores a tier keeps it, so choose "server" once in the player menu.

## Where things are, and how to watch it

- Library: `/srv/music` (beets files under its path template: artist, album, track and title; singletons under
  `<artist>/Singles/`).
- slskd's downloads: `/srv/incoming/soulseek` (slskd sees only this folder; `/srv/incoming/library-import` is not
  exposed to it). Staging is `.staging/` inside it.
- Before the first `docker compose up`, create `/srv/incoming/soulseek` and `/srv/incoming/soulseek/.incomplete`
  as uid 1000 (`mkdir -p /srv/incoming/soulseek/.incomplete`, no sudo). Otherwise compose creates the mount source as
  root, and slskd checks for the incomplete folder but does not create it: it refuses to start and restarts in a loop.
- Soulseek peer names never appear in events, logs or the web client: file basenames only.

```
cd /srv/docker
docker compose logs -f worker      # watch it work
docker compose stop worker         # stop (queued approvals wait; a stop mid-download marks that approval
                                   # "interrupted: worker restarted" and the row failed at the next start: approve again)
docker compose up -d worker        # start / resume
```

The worker mounts `/srv/music`, `/srv/docker/beets` and `/srv/incoming/soulseek` at the same paths as on the host,
because beets stores absolute paths in `library.db`. Navidrome's database is mounted read-only.
