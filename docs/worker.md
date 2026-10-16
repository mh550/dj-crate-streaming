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
   again would download a second copy: look in Navidrome first (a rescan, or the file's tags).
2. **Approvals.** Each unused approval is claimed, then fetched: search slskd, prefer the exact file you saw in
   Preview while it is still offered (otherwise the top-ranked one), download it, verify it, file it, ask
   Navidrome to rescan, and swap it into the crates. The outcome is written back on the approval.

One bad row never stops the tick, and a tick that fails (slskd or Navidrome down, database locked) never stops the
worker; the next tick tries again. `python -m sourcing.cli worker --once` runs a single tick and exits.

Once beets has filed a download, the row never goes back to `failed` on an error: it becomes `verify` with the filed
path in its reason, so the re-check picks it up and nothing downloads a second copy. Rows in progress (`sourcing`,
`verify`) stay in the Wanted tab with their status and reason, without Preview or Approve.

## Approvals

1. In the web client's Wanted tab, press **Preview**. It searches and scores but downloads nothing, and shows the
   pick (file name, format, bit rate, score) and a "why" panel.
2. Press **Approve**. The row reads "approved · waiting for worker" until the next tick takes it, then
   "worker: <outcome>".

Every download carries an approval record (D23): who approved, the candidate, the tier and the time. Today the only
`approved_by` value is `michael` (the Approve button, and `sourcing.cli fetch --approve`, which records and claims
its own approval so the worker cannot fetch the same row at the same time). Later values are `policy:<name>` and
`agent:<id>`: new approvers, not a redesign.

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
  tags are untouched. `beet update -M` in M7 refreshes the index from the tags.
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

With `ACOUSTID_KEY` set, an AcoustID lookup also checks the new file against the recording id Navidrome holds. Without
the key there is no lookup. To enable it, add `ACOUSTID_KEY=<your key>` to `/srv/docker/.env`; the compose file passes
it through (empty means off). The key travels in a request body, never in a URL or a log.

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
