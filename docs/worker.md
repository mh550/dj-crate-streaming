# The worker

The worker is a second container (`worker` in `deploy/compose.yml`) running `python -m sourcing.cli worker`. It is the
only process that downloads from Soulseek or runs beets (D18). The `crates` container keeps serving the web client
and never touches `/srv/music` or `/srv/incoming`.

## What it does each tick

A tick runs every `WORKER_POLL_S` seconds (30 by default), in this order. The wait between ticks is slept in steps
of at most one second and ends early when a play-now approval is waiting (see "Play-now").

1. **Play-now approvals.** Any unused play-now approval is claimed and fetched first, because you are waiting to
   hear the track.
2. **Reconcile.** At most once every `WORKER_RECONCILE_S` seconds (600 by default; 0 turns it off; the first tick
   always runs it). It reads the crate switches in `crates.db`, refreshes playlist names, derives each song's tier
   and re-judges the tracks. (Under the retired `CRATES_OWNER=comment` it re-read every playlist comment, which is how
   a `#crate` or `#tier:` edited in Amperfy took effect.) If
   the crates service is reconciling at that moment, the worker logs "reconcile skipped" and tries next interval.
3. **Re-check.** Every row that was filed but not yet seen by Navidrome (status `verify`) is asked again whether the
   song has appeared, at most once every `WORKER_RECHECK_S` seconds per row (300 by default), because each re-check
   starts a Navidrome scan. It searches by the filed file's own artist and title tags (what Navidrome indexes), not
   the wanted row's names. Nothing is downloaded for these. Each miss is counted in the reason (`(check N)`); after 12
   the row fails with "Navidrome never indexed <path>; file is in the library", so you see it. Approving that row
   again downloads nothing: it re-checks the same file (counting from 1 again), and the approval reads
   `recheck: already filed as <path>`. If Navidrome still misses it, look at the file's tags.
4. **Approvals.** Each remaining unused approval is claimed, then fetched: search slskd, prefer the exact file you
   saw in Preview while it is still offered (otherwise the top-ranked one), download it, verify it, file it, ask
   Navidrome to rescan, and then either finish the row or start a copy replacement (below). The outcome is written
   back on the approval.
5. **Replacements.** Every copy replacement that was left unfinished when the tick began is advanced one more time
   (a playlist that could not be repointed yet, Navidrome not yet showing the old copy gone, a crash in between).
6. **Placement.** Every filed track an imported playlist still waits for is inserted at its Spotify position (see
   "Placement"): one guarded edit per playlist and track; a refused one is retried later, less often each time.
7. **Export.** At most once every `WORKER_EXPORT_S` seconds (300 by default; 0 turns it off) the playlists are
   written as `.m3u8` into `/srv/music/_playlists`, changed files only, so repoints, swaps and your own edits reach
   the backup files. Before a changed file is rewritten, its previous version goes to
   `_playlists/.history/<YYYY-MM-DD>/` (the first one of the day; later rewrites that day keep it), and day folders
   older than 30 days are pruned (only date-named folders under `.history/`; links are not followed). The date is
   the container's (UTC, no `TZ` is set). A history problem is logged as `export: history: …` and never stops the
   export. After an export that worked, it counts per playlist the entries on a missing or unknown song (the ones
   Navidrome hides; read-only `navidrome.db`), in its own user's playlists only, smart playlists left out (D46). When that list changes it is stored for `/api/status`
   (`playlistHealth`) and one `playlist_health` event says so ("2 entries in Tea tent point at missing files; 1 in
   Chicago 86", or "no playlist entry points at a missing file" once they are gone). An unchanged list logs nothing.
   Healing a hidden entry stays manual (M9 §7).

One bad row never stops the tick, and a tick that fails (slskd or Navidrome down, database locked) never stops the
worker; the next tick tries again. `python -m sourcing.cli worker --once` runs a single tick and exits.

Only one worker runs at a time: it holds an exclusive lock on `worker.lock` next to `crates.db` (`/data/worker.lock`
in the container) for its whole life. A second one, e.g. `docker compose exec -T worker python -m sourcing.cli worker
--once` while the service is running, exits with "worker already running" and touches nothing. Outside the worker
container (`DJ_WORKER=1` unset) `sourcing.cli worker` refuses to start.

Reconcile has two callers (the crates service when you toggle or tap reconcile, and this worker), so each takes an
exclusive lock on `reconcile.lock` next to `crates.db` and waits up to 60 s for it. If the wait runs out, the web
client answers 503 "busy, try again" and the worker skips that run; nothing is written either way.
`worker --once --no-reconcile` skips the reconcile step (useful for a one-off tick while you are migrating).

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

The web service answers 409 to Preview or Approve of a row whose approval the worker has already claimed (it is
searching or downloading), and 404 for an unknown id. Preview picks come with an opaque `token` and no peer name:
Approve posts the token back and the service finds the full candidate in the stored preview (409 "preview again"
if the preview changed since). No wanted, approval or preview response shows a Soulseek peer name or an absolute
path; library paths are relative to `/srv/music`.

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
reference it is false. M8's replacement trashes the old copy only when it is true. A download of another version
of the song (the row's file name shows a different label) is not compared with the old copy: it is verified as a new
version and added.

With `ACOUSTID_KEY` set, an AcoustID lookup also checks the new file against the recording id Navidrome holds. Without
the key there is no lookup. To enable it, add `ACOUSTID_KEY=<your key>` to `/srv/docker/.env`; the compose file passes
it through (empty means off). The key travels in a request body, never in a URL or a log.

## Copy replacement and the trash

This is the one place the project removes a file from the library, so every step refuses on doubt.

**When it starts.** You approve a download for a playlist row whose song is already in Navidrome but below its tier,
and the new file arrives. A replacement starts only if all of these hold:
- the stored verification says `replaceable` is true and names the old file it compared;
- that old file is still exactly what was compared (same path in Navidrome's database, same size and modified time);
- `identity.same_version` calls the two one version, and the new file is not the old file;
- Navidrome lists the new file, and it is on disk.

If any fails, nothing is replaced. Both copies stay, no playlist is touched, and the row becomes `review` with
"kept beside <old>: not proven the same recording (<why>)". That also asks you a question per playlist slot (see
"Proposals"). A request that was withdrawn while the file downloaded (no tiered playlist holds the old song any more)
also ends in `review`: "filed beside <old>; request withdrawn, both copies kept".

**The steps.** Each is saved in `crates.db` before the next starts, so a crash or restart resumes where it was.
1. *repoint.* The new song takes the old song's place, in the same position, in every playlist that holds the old
   one, not only crates. Each edit is checked against `navidrome.db` first (the hidden-song trap: a playlist with a
   missing file would delete the wrong row), and written in one call that is read back.
2. *trash.* Only when no playlist entry anywhere, hidden ones included, still holds the old song: the old file
   moves to the trash and beets drops it from its index (`beet remove`, index only; the file is not touched).
3. *scan.* The worker asks Navidrome to rescan, at most once per `WORKER_RECHECK_S`, until Navidrome stops listing
   the old copy. Then the job is `done`. Reconcile gives the new song its own row (judged `ok` if it meets the tier)
   and drops the old song's. The new copy is indexed before anything is repointed and the old one is moved after,
   so Navidrome never merges two files into one song id.

**What makes it wait (not blocked).** A smart playlist, a playlist owned by another Navidrome user (Amperfy's
account: we never edit those) or a hidden row keeps a reference to the old song. The job stays in *repoint*, the row
is `review` and says why ("replacement #N repoint: old song still in N playlist entries (<name>: refused: owned by
…)"), and the old file does not move.
Remove the old song from that playlist yourself and the next tick carries on. If a playlist gets the old song back
while the file is moving or in the trash, the worker restores the file and repoints again.

**Where the old file goes.** `/srv/_trash/<YYYY-MM-DD>/<its library path>`, for example
`/srv/_trash/2026-10-17/Chic/Risque (1979)/03 - Good Times.flac`. A name already in the trash gets
`(2)`, `(3)`. Nothing deletes from the trash; you empty it. `crates.cli status` shows its size and oldest day.
The worker mounts it read-write at that path; the crates container sees it read-only.

**How to undo it.** Each dated folder has a `MOVES.txt` with one reverse `mv` line per file, written before the move:

```
mv '/srv/_trash/2026-10-17/Chic/Risque (1979)/03 - Good Times.flac' '/srv/music/Chic/Risque (1979)/03 - Good Times.flac'
```

Run the line on the host (the paths are the same inside and outside the containers; `mkdir -p` the target folder if
it is gone). A line followed by `# not moved (<error>)` means the move failed and the file never left the library.
`# restored …` means the worker put the file back itself. After you restore a file, Navidrome lists it again at its
next scan (`ND_SCANSCHEDULE` is 1 h); the playlists keep pointing at the new copy, so put the old song back in
by hand if you want it there.

**What `blocked` means.** The worker stopped on purpose and will not retry. Nothing is deleted, and the row reads
`review` "replacement #N blocked: <why>". Blocked is final; there is no button, so read the reason. The causes:
- the old copy moved or changed since it was compared (path, size or modified time differ), or it is not the file
  verify compared;
- identity says the two are another version;
- the new copy is missing in Navidrome, is somewhere else than it was filed, is not on disk, or is the old file;
- the library is not reachable (an unmounted `/srv/music` also says "no such file", and is never read as "the old
  copy is gone");
- the file would have to be restored from the trash but its place is taken by another file, or it is not in the
  trash any more.

Playlists may already point at the new copy when it blocks later; the old file is then still in the library, in no
playlist. The reason says which.

## Proposals

A new version never replaces anything by itself, even when the tier prefers it (D23). It asks instead. There are two
questions, one per playlist slot, only for playlists that have a tier:
- **New version.** A filed song is another version of a song a tiered playlist holds, and that tier prefers it
  (`[versions.<tier>] prefer` in `deploy/policy.toml`, for example a 12" at crate). It stays silent for the same
  version, a version the tier does not prefer, a playlist that has the new song already, or a version that would
  drop what the slot specifically is (an instrumental, a credited mix).
- **Better copy, not proven the same recording.** The copy-replacement licence failed, so both files stayed. The
  row is `review` until every slot is answered.

Answer in the Wanted tab (a box at the top: **Swap** or **Keep**), or in the crates container:

```
cd /srv/docker
docker compose exec -T crates python -m crates.cli proposals [--all]      # open questions; --all adds answered ones
docker compose exec -T crates python -m crates.cli proposals accept <id>  # swap that one slot
docker compose exec -T crates python -m crates.cli proposals decline <id> # keep the playlist as it is
```

Swap edits that one slot only, with the same checks as a repoint. If the slot no longer holds the old song, the
playlist changed, or the edit was not confirmed, the answer is `stale` with the reason and nothing is written
(`accept` needs `NAVIDROME_DB` in the crates container). Swap never trashes: a version is a different recording, and
an unproven copy is not proven redundant. Keep is final; the same question is not asked again. Questions whose slot
or playlist has gone are marked stale the next time the list is read (`decided_by` `policy:slot-check`).

When all slots of an unproven copy are answered: if every one was swapped, an external row becomes `ok`; otherwise
the row stays `review`, "declined replacement #N; approve a different candidate to retry (the new copy stays in the
library as <path>)". Rows like "kept beside …", "declined replacement …", "replacement #N not made …" and "filed
beside …" show Preview and Approve again, so a retry is one tap. Import's "ambiguous …" review rows still need a pick
and offer nothing.

## Play-now

Pressing the play button on a track that is queued but not in the library is your approval (D20) for **one fast
copy**. The Wanted tab says so on the button ("downloads a quick copy to play now") and shows where the copy is:
queued, downloading, checking, filed, playing.

- It is an approval with `purpose` `play-now`, `approved_by` `michael`. The worker takes it first in the tick, and
  wakes within a second instead of waiting out `WORKER_POLL_S`.
- The download is ranked and verified at tier `low`; the row keeps its own tier. The file is filed as a
  **provisional** copy. Once Navidrome lists it the web client plays it (autoplay) and labels it provisional.
- The row then goes back to `needs_source` as the **upgrade**: "provisional low copy filed as <path>; upgrade at
  <tier> waits for approval". Approve it like any download. It is an ordinary copy replacement of the provisional
  file: with proof the provisional file goes to the trash, otherwise both stay and you are asked.
- **One exception.** If the fast copy was verified at least as strictly as the row's tier, and passes that tier's
  judge, it is the row's file ("provisional copy already meets <tier>"): the row is `ok` and no upgrade is queued.
  A copy verified at `low` is never final for `crate`, whose checks are stricter, and reconcile will not mark a
  provisional song `ok` at a crate tier either ("provisional copy (verified at low only); crate needs its own
  download").
- **One open request per song.** If a tiered playlist later holds the same song, its row takes over the upgrade,
  unless the upgrade is already in flight; then the playlist row waits ("upgrade in flight as ext-N") and Preview
  and Approve answer 409 for it.
- Refused with 409, recording nothing: a playlist row (its song is in Navidrome, play that), a row that has a
  library song, an `ok` row, a row in progress (`sourcing`, `verify`, filed but not indexed), a `review` row (pick a
  version first), and a row with an approval waiting or already claimed (a double tap, a second device). Preview and
  Approve of a row whose play-now approval is claimed also answer 409.
- **Placed only once final.** A provisional file is in the library but not in the playlist that wanted it. When the
  row ends `ok` (the exception above, or its upgrade filed), the worker places the final song like any other
  ("Placement").
- **iOS.** A phone lets a page start audio only from a tap, and the file lands seconds later. The tap itself primes
  the audio player, then the page starts it when the file is listed. If the browser still blocks it the row says
  "tap play". This has not been tried on a real phone yet.

## Placement

A track you queued from an imported playlist goes into that playlist **where Spotify had it**, not at the end (N4,
D44, M9 §1). The code is `crates/placement.py`; the plan is `docs/plans/2026-10-17-n4-placement.md`.

- **What is due** is read from state each tick (`CrateStore.due_placements`), so filing, a copy replacement and
  play-now need no extra step: an external row that is `ok` with its library song (not provisional), named by the
  playlist's `import_order`, not yet in `imported_entries` for that playlist, with no finished placement. A track
  wanted by two imported playlists is placed in each.
- **Where it goes.** `import_order` is the playlist's last real import, row by row. The track goes right after the
  nearest earlier Spotify neighbour still in the playlist (its last occurrence), else right before the nearest later
  one (its first occurrence), else at the end. A neighbour you removed, or one still wanted, is skipped and the next
  one used. A neighbour that was itself filed and placed counts.
- **What it never does.** It edits only playlists import-playlist made or adopted (`imported_playlists`), owned by
  our user (`NotOwned` otherwise), never a smart playlist. It only inserts: no entry moves or goes, so a track an
  earlier re-run appended at the end stays there. One placement per track and playlist, ever: a track you remove
  afterwards stays removed (it is in `imported_entries`, D13). Every edit is one `playlist_edit.rewrite`, which
  refuses on hidden missing rows or a concurrent edit, and reads the result back.
- **States** (`placements` in crates.db): `open` (refused, retried), `writing` (the edit was sent, not yet
  confirmed), `done` (placed, or skipped: already there, playlist gone, not imported), `given_up`.
- **Events.** `placed`: "<playlist>: <artist> – <title> at <n> (after <song>|before <song>|append)", or "(confirmed
  after an unconfirmed edit)". `not_placed`: "<playlist>: not placed after 12 tries: <why>; re-run the import to
  append it", or "edit not confirmed, look at the playlist; re-run the import to append it".
- **Retries.** A refusal (hidden missing rows, a concurrent edit, another owner, the song no longer in the library)
  is counted and tried again after `WORKER_RECHECK_S`, then each wait doubles up to a day (5 min, 5, 10, 20 min…
  ~21 h, a day), so the 12 tries span about four days: long enough for a scan or a cleanup to clear a hidden row.
  The 12th gives up with `not_placed`. Navidrome
  unreachable or crates.db locked is not counted, so an outage never gives a placement up.
- **An edit not confirmed** (Navidrome did not show it on read-back, or the worker stopped mid-write) is never sent
  again. The next tick only looks: the song there → `done`, absent → `given_up` with `not_placed`. That way an entry
  is never doubled, and a track you removed in that moment is never put back.
- **Fallback: re-run the import.** A track that was not placed is not in `imported_entries`, so the next real run of
  `import-playlist` for that playlist appends it at the end (and records a fresh `import_order`).
- **Older imports.** A playlist imported before N4 has no `import_order`, so nothing is placed into it until its next
  real re-run of `import-playlist` records one.
- **A repointed song.** When a copy replacement or the duplicate cleanup's `repoint` has moved every playlist from
  an old copy to its new one, crates.db follows (`CrateStore.repoint_song`): import orders and filed rows name the
  new song, and a playlist that ever had the old one added counts the new one as added too. The duplicate cleanup
  does it after `repoint` and again right before `trash` moves a file, and logs a `cleanup` event "crates.db now
  names <keeper>: …". Each repoint that changed rows appends one line `{ts, old, new, rows}` to
  `songs-repointed.jsonl` beside crates.db (a finished copy replacement too); `CrateStore.unrepoint_song(line)`
  undoes it (lines newest first). A file trash puts back stays repointed in crates.db until the next `repoint` run.
- **Deleted playlist.** The reconcile that drops a deleted playlist's rows (N3) drops its `import_order` and
  `placements` too, so nothing stays due for it.

## Settings the worker reads

All set in `deploy/compose.yml` (the worker service); change them there, commit, push and run `scripts/deploy.sh worker`
from that clean checkout (see "Deploying, and what healthy means"; not `docker compose up` from `/srv/docker`).

| Variable | Default | What it does |
|---|---|---|
| `WORKER_POLL_S` | 30 | seconds between ticks (a waiting play-now ends the wait early) |
| `WORKER_RECHECK_S` | 300 | a `verify` row is re-checked (one Navidrome scan) at most this often; also the scan interval of a replacement and the first retry wait of a placement (it doubles after each refusal, up to a day) |
| `WORKER_RECONCILE_S` | 600 | playlist comments re-read and tiers re-derived; 0 = never |
| `WORKER_EXPORT_S` | 300 | `.m3u8` export into `/srv/music/_playlists`; 0 = never |
| `TRASH_ROOT` | `/srv/_trash` | where a replaced copy goes (mounted read-write in the worker) |
| `NAVIDROME_DB` | `/srv/docker/navidrome/navidrome.db` | read-only; copy replacement and playlist edits cross-check it |
| `MUSIC_ROOT`, `DOWNLOADS_ROOT` | `/srv/music`, `/srv/incoming/soulseek` | as before |
| `DJ_WORKER`, `ACOUSTID_KEY`, `BEETSDIR`, `CRATES_DB` | | as before |

Host scripts that write beets' `library.db` take the same lock, so they run only with the worker stopped:
`scripts/tag_cleanup.py retag|move` and `scripts/dedupe_copies.py repoint|trash` hold `<dirname(CRATES_DB)>/worker.lock`
for the whole command (on the host `CRATES_DB=/srv/docker/crates/crates.db`) and otherwise exit 1 with
`refused: stop the worker first (docker compose stop worker): it holds …/worker.lock`; with `CRATES_DB` unset they
exit 1 and ask for it. `plan` and `refresh-map` stay free; `identity_backfill apply` stays outside the lock. Only the
worker downloads: `sourcing.cli rank` no longer has `--download` (it exits 2 and names Preview + Approve).

The crates container reads `CRATES_TRASH` (`/trash`, read-only: status shows its size) and `NAVIDROME_DB` (the same
file, mounted read-only: playlist edits and proposal answers need it). Navidrome's database is opened with
`mode=ro`; if it cannot be opened, those calls answer 503 or refuse, and nothing is written. It also reads `CRATES_IDENTITY_DIR`
(default `/data/identity`, the worker's identity output on the same mount): the Identity picker's `GET /api/identity`
serves `identity-proposal.json` from there, and `POST /api/identity/choice` writes `identity-choices.json` there, the
only file it writes (R7).

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

- It makes `identity-proposal.json`, `identity-backfill-report.md`, `mb-cache.jsonl` and (with a key)
  `acoustid-cache.jsonl` in the output folder.
  `--out` and `--music` change the folders. `--out` inside the library is refused.
- MusicBrainz allows about one request per second, and about one in ten gets a 503, which the client retries. Expect
  roughly 45 to 70 minutes for the whole library. A progress line every 50 files shows the time left.
- If the run is killed, run the same command again. Answers already fetched come from `mb-cache.jsonl`.
- With `ACOUSTID_KEY` set in `/srv/docker/.env` it also uses AcoustID (at most 3 requests a second). Without it, that
  step is skipped. AcoustID answers are kept in `acoustid-cache.jsonl` in the output folder, keyed on path, size and
  modification time, so a second propose asks only about changed files. Delete it to ask again for every file (an
  answer of "not in AcoustID" is kept too). The key is never written to it. `apply` and `revert` do not read it.

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

**Apply the picker's choices.** The Identity tab of the crates app records each Accept, Choose and Skip in
`/data/identity/identity-choices.json` (nothing is written to a file then). `--choices` applies them:

```
docker compose exec -T worker python -m scripts.identity_backfill apply /data/identity/identity-proposal.json --choices /data/identity/identity-choices.json --dry-run
```

- Without `--classes` it selects **only** the rows you accepted or chose. With `--classes` it adds those classes' rows.
  `--limit` and `--only` apply to all of them alike. The live run is yours: the staged steps (dry run, `--limit 5`,
  all, scan and check after each) are in `docs/plans/2026-10-21-r7-identity-picker.md` "Live steps".
- Accept takes a `search` row's proposed recording, Choose sets the row's `choose` to the tapped candidate, Skip
  drops the row, whatever its class. The choices file wins over a hand-typed `"choose"`, for an Accept too (the run
  says so); a `"skip": true` in the proposal still wins over everything. A path the proposal holds twice is refused.
- A choice is refused, and its row is not written by its class either, when it no longer fits the row: the row's
  class, size or modification time changed since the tap (a new `propose`), the accepted recording is no longer the
  row's pick, or the chosen id is not one of the candidates (the same message as a hand-typed `choose`). Accept or
  Choose on a `conflict` or `error` row is refused. Each refusal is printed as `choices: <path> …`, and a choice for
  a path the proposal lacks as `… is not in the proposal; ignored`. Pick again in the tab after a new `propose`.
  A row that a new `propose` moved out of the picker (a `search` row that became `acoustid`, say) is no longer in
  the tab, so its old choice stays refused (or, for a skip, keeps dropping the row): apply such rows without
  `--choices`, or delete their entries from the choices file first.
- The dry run marks those rows `(choice: accept, decided_by michael)`. A real run adds `"choice"` and
  `"decided_by": "michael"` to their lines in the apply log; `revert` works as before.
- A missing or unreadable choices file stops the command (exit 2) before any library file is read.

**Undo.**

```
docker compose exec -T worker python -m scripts.identity_backfill revert /data/identity/apply-<time>.jsonl
```

It removes the fields that apply wrote, newest first, and only where a file still holds exactly that value. A field
you changed by hand is left alone, and the run says so. Running it twice is harmless.
To apply again after an undo, run `propose` first: the undo changes each file's modification time, so `apply`
skips those files as "changed since the proposal".

## Duplicate cleanup (built in N1, not yet run live)

Navidrome lists some recordings more than once (102 groups, 115 extra files in `docs/duplicates-report.md`). The
cleanup keeps the best copy of each (lossless first, then bit rate, then the properly filed path: `keep_rank`),
repoints every playlist from the other copies to it, and moves the other files to `/srv/_trash/<day>/` (D31). It runs
in three commands: `plan` (read-only), `repoint`, `trash`. All of them take their paths from the worker's environment,
so no path flags are needed. The design, with every check, is in `docs/plans/2026-10-17-n1-duplicate-cleanup.md`.

`docker compose` commands run from `/srv/docker`, `scripts/live-run.sh` and `scripts/live-check.sh` from a checkout of
this repo. Output goes to `/data/duplicate-cleanup/` in the container, which is
`/srv/docker/crates/duplicate-cleanup/` on the host. Stop at the first surprise and undo from the logs (below).

**check** below means `scripts/live-check.sh` (from a checkout of this repo), which runs
`docker compose run --rm --no-deps worker sh -c 'python3 -m scripts.export_playlists export && python3 -m scripts.export_playlists check'`
in the deployed image. `scripts/live-run.sh <command…>` runs any one-off worker command that way (D45): it reads the
revision label of `dj-worker-1` (running or stopped), refuses when it is missing, `dev`, not a hex sha or its
`dj-crates:<rev>` image is gone, and passes `GIT_SHA=<rev>`, so the one-off never runs `dj-crates:dev`. `--print` shows the command only.
Only the worker image mounts `/srv/music`. The worker exports only every 300 s, and not at all while it is stopped, so
a check without a fresh export reports "stale".

**1. Before.** Deploy the image with `scripts/deploy.sh` and note the previous image tag for a rollback. Then take the
snapshots: `scripts/snapshot-crates-db.sh --suffix pre-<run>` writes `crates.db.pre-<run>.snap` and
`navidrome.db.pre-<run>.snap` beside the databases (each checked with `pragma integrity_check`), which the nightly
`.snap` copies never overwrite. Note when restic last ran. **check** must be green.

**2. Plan (read-only).**

```
docker compose exec -T worker python3 -m scripts.duplicate_cleanup plan
```

Read `duplicate-cleanup/report.md`. Its section "Lossless pairs, will be trashed" lists the groups with two lossless
copies: Michael chose on 2026-10-19 to trash those extras too (D35), so `repoint` and `trash` act on them. To keep
them instead, run `plan --hold-lossless`: they are then held as "both lossless" and listed only. Groups whose keeper
file is not on disk are always held; leave them alone. A re-run of `plan` keeps the old `plan.json` as `plan-<made_at>.json`.

**3. Repoint (the worker may keep running).**

```
docker compose exec -T worker python3 -m scripts.duplicate_cleanup repoint --dry-run
docker compose exec -T worker python3 -m scripts.duplicate_cleanup repoint --limit 5     # then check
docker compose exec -T worker python3 -m scripts.duplicate_cleanup repoint --limit 50    # then check
docker compose exec -T worker python3 -m scripts.duplicate_cleanup repoint               # then check
docker compose exec -T crates python3 -m crates.cli reconcile
```

- Each run reads every playlist's current entries and edits it only through `crates/playlist_edit.py`. A hidden
  row, a smart playlist, another user's playlist or an edit made meanwhile refuses that playlist, and it stays as it
  was.
- Before each write, one reverse line goes to `repoint-<time>.jsonl`. Each written playlist is also a `cleanup`
  event in crates.db.
- Each run ends with a Navidrome scan and waits for it (the scan between repoint and trash). A scan already
  running is waited out first: it may have started before the last write and not see it.
- `--dry-run` runs the same checks without writing and names every playlist the real run would refuse, with why:
  "dry run: would refuse Chicago 86: skipped: smart playlist; Theirs: owned by other; would repoint Disco
  Edits". It
  exits 1 then, like the real run. A hidden row reads "'<name>': position N holds <id>, a song whose file is
  missing…".
- Exit 1 means a playlist was refused or failed, or the scan did not finish. Read it before going on.
- `--limit N` counts groups in plan order. A re-run does not write the done ones again.

**4. Trash (the worker stopped).**

```
docker compose stop worker
scripts/live-run.sh python3 -m scripts.duplicate_cleanup trash --dry-run
scripts/live-run.sh python3 -m scripts.duplicate_cleanup trash --limit 5      # then check
scripts/live-run.sh python3 -m scripts.duplicate_cleanup trash --limit 50     # then check
scripts/live-run.sh python3 -m scripts.duplicate_cleanup trash                # then check
docker compose start worker
```

- `docker compose` from `/srv/docker`, `scripts/live-run.sh` from a checkout. `live-run.sh` is
  `run --rm --no-deps worker` in the deployed image (its first line names it). Use `run --rm worker`, not `exec`. Only that container has `DJ_WORKER=1`, which tells beets to forget each trashed
  path, and `/srv/music` and `/srv/_trash` mounted.
- It refuses to start while the worker holds `/data/worker.lock`, while a Navidrome scan runs (checked again before
  every move), or when the library or the trash is not mounted.
- It also refuses to start unless a Navidrome scan *finished* after the newest `repoint-<time>.jsonl` was last
  written (Navidrome's `lastScan` against the log's modification time): "no Navidrome scan finished after the newest
  repoint log …". That happens when repoint's scan timed out or failed, or repoint ran again after the last scan.
  Start a scan in Navidrome, wait for it to end, then run trash again. Without any repoint log there is nothing to
  wait for. `--dry-run` refuses the same way, so the dry run shows it first.
- Per file, it moves nothing unless all of these hold:
  - no playlist row names the extra in navidrome.db (hidden rows and other users' playlists included);
  - nothing in crates.db is still working with it, and crates.db's rows were repointed to the keeper just before
    (a busy crates.db leaves the file: "refused: crates.db not repointed (…); run again");
  - the keeper is on disk and still one recording with it;
  - the file on disk is still the planned file: its size equals navidrome.db's `media_file.size` and the size in
    `plan.json`. A file filed at that path since the plan is refused with its path and the sizes that differ
    ("refused: <path> is N bytes on disk, navidrome.db says M, the plan says P: not the planned file"); the other
    extras still move. Look at that file before anything else; a new `plan` then treats it as a new copy.
- Each move goes through `crates.trash.move_to_trash`, so its `mv` back is in `/srv/_trash/<day>/MOVES.txt` before
  the file moves. Then there is a line in `trash-<time>.jsonl` and a `cleanup` event.
- If a playlist takes the song during the move, or before the closing scan ends, the file is put back.
- The closing scan, and the one after a put-back, first wait out a scan that is already running (Navidrome's hourly
  one may start during the last move and not see it), then start their own and wait for it.
- A scan that starts mid-run, or a repoint log written mid-run with no scan since, stops the run before the next
  move ("refused: a Navidrome scan is running" / "no Navidrome scan finished after …"), exit 1.
  If files had moved, it first waits for that scan to end, starts one more and waits for it, then puts back any
  moved file a playlist took meanwhile (a `restored` line in `trash-<time>.jsonl`, a `cleanup` event). Run trash
  again for the rest. Each wait lasts up to 10 minutes, so such a run can hold the live lock for about 30: start
  trash well before the 03:15 backup window.
- When no scan of ours finished (it timed out or failed), Navidrome still lists a trashed song, and Amperfy can add
  it. The next run then puts the file back from the trash log ("refused: still in 1 playlist entry; put back from
  <day>/<path>", a `restored` line, a `cleanup` event) and scans, so the row shows again. Without a trash log line
  for it, that is "failed: gone from the library but still in …": put it back with its `MOVES.txt` line, then scan.
- A re-run reports the moved files as `already gone`.
- Exit 1 means something was refused or failed. Read every refusal before the next stage.

Every line trash can print, and what to do (N is "1 playlist entry" or "N playlist entries"):

| Line | Meaning, and what to do |
|---|---|
| `refused: stop the worker first (docker compose stop worker): it holds …/worker.lock` | Nothing ran. Stop the worker. |
| `refused: a Navidrome scan is running: …` | At the start: nothing ran; wait for the scan. Mid-run: see above. |
| `refused: the library is not mounted: …` / `refused: the trash is not mounted: …` | Nothing ran. Fix the mount. |
| `refused: no Navidrome scan finished after the newest repoint log …` | Nothing ran. Scan, wait, run again. |
| `set CRATES_DB to the crate service's database …` (exit 2) | Nothing ran. Use `run --rm worker`. |
| `moved to <trash path>` | Done. `(beets still lists it)` after it: beets' forget failed; the next run retries it. |
| `dry run: would move` | The real run would move it. |
| `already gone` | An earlier run moved it, or it is gone otherwise; no playlist holds it. |
| `skipped: held (<why>)` | The plan holds the group: keeper missing on disk, or "both lossless" from `plan --hold-lossless` (D35). |
| `skipped: moved since the plan (now <path>)` | navidrome.db lists the extra elsewhere now. Re-run `plan`. |
| `skipped: keeper missing` | The keeper is not a present row or not a file on disk. Leave it; re-run `plan`. |
| `skipped: no longer a duplicate of <keeper>` | A retag since the plan. Re-run `plan`. |
| `refused: the same file as the keeper <keeper>` | A hard link (or one file listed twice): moving it would lose the keeper. Leave it. |
| `refused: <path> is N bytes on disk, … says M: not the planned file` | A new file at that path. Look at it first. |
| `refused: still in N` | A playlist (any user's, hidden rows included) holds it: repoint again, or leave it. |
| `refused: in use by <ext-N \| approval of <id> \| replacement #N>` | crates.db is still working with it. Run again when that is done. |
| `refused: crates.db not repointed (<error>); run again` | crates.db was busy; the file stays. Run trash again. |
| `refused: added to N during the move; put back` / `… after the move; put back; …` | A playlist took it; the file is back. |
| `refused: still in N; put back from <day>/<path>; …` (dry run: `would put back from`) | An earlier run's scan did not finish and a playlist took it; the file is back. |
| `failed: added to N during/after the move, not put back (<error>); the file is at <trash path>` | A playlist holds it and it is in the trash. `FileExistsError`: a new file is at its library path, so neither `mv -n` nor a re-run puts it back: compare the two files first. Any other error: run its `MOVES.txt` line with `mv -n` and scan, or run trash again (it puts it back from the trash log). |
| `failed: gone from the library but still in N` | No trash log line to put it back from: find it in `MOVES.txt`, `mv -n` it back, scan. |
| `failed: re-checking its playlists after the move: <error>` | navidrome.db could not be read; run trash again (it re-checks from the trash log). |
| `failed: <error>` | That extra failed; the others went on. Its file is moved only if `MOVES.txt` and the trash log say so. |
| `(scan): done` / `(scan): failed: Navidrome scan still running after 600 s` / `failed: Navidrome scan failed (…)` | The closing scan. On a failure, scan in Navidrome and run trash again (see the bullet on an unfinished scan). |
| `trash log: <path>`, or ` (trash log: <path>)` after a closing `refused:` line | Where this run's `trash-<time>.jsonl` is. |
| `no beets here (DJ_WORKER is not 1): …` (stderr) | Not run in `run --rm worker`: beets keeps rows for the trashed paths. |
| `event not logged (…): …` (stderr) | crates.db was busy; the jsonl logs stay the record. |

Expected end state: 716 songs listed (730 after `plan --hold-lossless`, the 9 "both lossless" groups held), 0 playlist rows on a missing file,
**check** green. Do not purge missing files in Navidrome until you are sure: the purge is what makes a restored file
come back under a new id.

**Undo.**
- **A trashed file:** run its `MOVES.txt` line with `mv -n` (it never overwrites), or use `crates.trash.restore`.
  Then scan. It comes back under its old id only while Navidrome still has its missing row, that is, before a purge.
- **crates.db's rows of a repointed song:** replay its lines of `/srv/docker/crates/songs-repointed.jsonl` newest
  first, each as `store.unrepoint_song(line)` then `store.commit()` (worker stopped, crates.db snapshot first).
- **A repointed playlist:** first get its files back and scanned. Then replay its lines of `repoint-<time>.jsonl`
  **newest first**, each as `playlist_edit.rewrite(client, db, playlist_id, after, before)`. The oldest line's
  `before` is the playlist as it was.
- **A playlist that lost entries:** `/srv/music/_playlists/.history/<YYYY-MM-DD>/<name>.m3u8` is the playlist as it
  was before that day's first rewrite (30 days kept; hidden entries keep their old paths). Its entries are relative to
  `_playlists/`, so copy it there under another name (`cp -n`) to open it in a player or compare it (the export then
  lists it as stale until you delete it). The live `.m3u8` files themselves are not an undo source: every export
  rewrites them to match Navidrome.

## Editing the policy

`deploy/policy.toml` holds Michael's settings: the four quality tiers (what each accepts, its floors and speed
weight) and the version preferences. The worker and the crates service read it once at start-up, from the image
(`Dockerfile` copies it). To change it:

```
$EDITOR deploy/policy.toml            # in a checkout of the branch you deploy; commit and push it
scripts/deploy.sh                     # from that clean checkout: builds and recreates crates + worker
cd /srv/docker && docker compose logs --tail 5 worker
```

A typo (an unknown key, a version word that does not exist, a wrong type) stops the start with a message naming the
key, so check the log afterwards. `scripts/deploy.sh`, not `docker compose up` from `/srv/docker`: see "Deploying, and
what healthy means".

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

As it stands (D26, 2026-10-17): **no `[versions.*]` table at all.** We source the exact track a playlist names, no
version is preferred, and none stands in for another. The mechanism above still exists (a policy that lists words
behaves as described), but the live file lists none. So an import row for "Good Times" matches only a library
"Good Times" of the same version and length; a "Good Times (12" Version)" in the library is a different version and the
row stays wanted (or goes to review if several candidates fit). A crate upgrade only looks for better copies of the
version the library already holds.

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
- Events the worker writes (crates.db `events`, the web client's log tab): `status`, `attrs`, `reconcile`,
  `playlist_gone` (reconcile); `pick`, `tagged`, `filed`, `renamed`, `reference`, `kept_both`, `upgrade_queued`,
  `proposal`, `replace` (approvals and copy replacement); `interrupted` (an approval cut off by a restart); `placed`,
  `not_placed` (placement); `playlist_health` (the export step: which playlists have entries on a missing song, logged
  only when that list changes); `reasked` (import-playlist: a re-import put a failed, unfiled row back to
  `needs_source` with its own id instead of queuing a second one, M9 §8h; the detail keeps the old reason) and
  `superseded` (an older failed duplicate of that row, queued before §8h, set to `removed`; detail: the old reason;
  one holding an approval is kept). A `removed` row (its playlist deleted) never answers an import: the import queues
  a fresh row.

```
cd /srv/docker
docker compose logs -f worker      # watch it work
docker compose stop worker         # stop (queued approvals wait; a stop mid-download marks that approval
                                   # "interrupted: worker restarted" and the row failed at the next start: approve again)
docker compose start worker        # resume (never recreates; `up -d worker` would re-read compose.yml)
```

**Is it alive?** The worker touches `/srv/docker/crates/worker.heartbeat` (beside `crates.db`) when a tick ends, and
at each poll while it waits on a download or a Navidrome scan. A tick that fails as a whole (`tick failed:` in the
log) does not, and a starting worker removes the old file, so it reads unhealthy until its first tick ends.
`scripts/healthcheck.py` (stdlib, exit 0 healthy, 1 not, one line saying why) reads it:

```
docker compose exec worker python scripts/healthcheck.py worker   # heartbeat younger than 3 × WORKER_POLL_S, at least 90 s
docker compose exec crates python scripts/healthcheck.py crates   # /api/status answers 200 within 5 s
```

`crates` is unhealthy while Navidrome is down too, because `/api/status` asks it (502). A stale heartbeat while the
container runs means the loop is stuck, every tick fails (`tick failed:`), or the file cannot be written
(`heartbeat failed:`).

**Deploying, and what healthy means.** `scripts/deploy.sh` (from a clean checkout of the commit to run; its header has
the rollback) builds `crates` + `worker`, tags `dj-crates:<10-char sha>` and recreates both. Note the running tag
from `docker compose ps` first: it is the rollback. `docker compose up` starts `crates` and `worker` only once
Navidrome is healthy (after a reboot Docker's restart policy starts all three at once). The healthchecks in `deploy/compose.yml` run every 30 s with a 10 s timeout. Three failures in a row make a
container unhealthy. During its start period a container is checked every 5 s, and its first pass makes it healthy.

| Container | Healthy means | Start period |
|---|---|---|
| navidrome | `/ping` answers (the busybox `wget` in its image) | 60 s |
| crates | `scripts/healthcheck.py crates`: `/api/status` answers 200 within 5 s (not while Navidrome is down) | 30 s |
| worker | `scripts/healthcheck.py worker`: the heartbeat is younger than max(90 s, 3 × `WORKER_POLL_S`) | 120 s |

```
docker compose ps                                          # STATUS "Up 2 minutes (healthy)", "(health: starting)", "(unhealthy)"
docker inspect --format '{{json .State.Health}}' dj-worker-1 | python3 -m json.tool   # the last 5 checks and the line each printed
```

After a deploy, all three should read `(healthy)` within 2 minutes; then run the Check (`CLAUDE.md`). Docker only
labels a container: it neither restarts nor alerts on unhealthy. A worker inside one long step that does not beat
(a reconcile, a Soulseek search, a beets import, a hanging Navidrome) can read unhealthy for a while and still be working: read its log.
An image built before H1-03 (`dj-crates:b2df730b1d` and older) has no `scripts/healthcheck.py`, so a rollback to it
reads `(unhealthy)` for good while it works normally. `/srv/docker/compose.yml` is a symlink to
`~/projects/dj-crate-streaming/deploy/compose.yml`. Compose recreates a running dependency whose settings differ from
the file it reads. So while that checkout's file has no healthchecks, a `docker compose up` there recreates what it touches without
them (and Navidrome with it). This page's `run` commands use `--no-deps` and resume with `start` for that reason; a
code or policy change goes out with `scripts/deploy.sh` from a checkout that has them.

The worker mounts `/srv/music`, `/srv/docker/beets` and `/srv/incoming/soulseek` at the same paths as on the host,
because beets stores absolute paths in `library.db`. It also mounts `/srv/_trash` read-write at the same path
(copy replacement moves old files there). Navidrome's database is mounted read-only, in the worker and in the crates
container.
