# S2 plan: album requests, sourced album-first

Milestone S2 of `docs/specs/2026-10-22-downloads-and-requests.md` (run `dj-crate-streaming-2026-10-22-build`).
Written by S2-01, which builds the schema below; the album-job design is fixed here so S2-02..S2-07 build on one
shape. The spec and the pivot spec win on conflict; D7 (no transfer without Michael's approval) and D26 (source the
exact track) bind every step. Nothing here trashes a file; tags are S2-06a's own reviewed plan
(`docs/plans/2026-10-22-S2-album-tags.md`).

## Schema

In `crates/store.py`, additive (the `SCHEMA` string for a new db, `_migrate` for an old one; tested in
`tests/test_crates.py::test_store_migrates_old_db_to_requests`).

- `requests`: `id INTEGER PRIMARY KEY`, `kind TEXT` (`album | playlist | track`, a CHECK), `source TEXT` (the URL
  asked for, or `search`), `artist`, `album`, `year INTEGER` (None until known: Spotify's album embed has
  `releaseDate: null`, MusicBrainz gives it), `mb_release_id TEXT` (S2-03), `created_at REAL`. No `status` column.
- `external_wanted` gains `request_id INTEGER`, `track_no INTEGER`, `mb_recording_id TEXT`.
- A request's rows are the `external_wanted` rows naming it. **A row belongs to the first request that asked for
  it**: `add_external_wanted(..., request_id=, track_no=)` returns the existing row for the same artist/title (so a
  re-run adds nothing) and records the request only on a row that has none. A later request asking the same song
  does not take the row out of an album job under way; S3-01 shows such a song as already asked (or in the library,
  S1-07) rather than as one of its rows. A `removed` (superseded) row is never attached: the request gets a fresh
  row. Known gap: an import's `_reask` may supersede a failed row another request holds, and that request then
  loses the row (it counts for nothing); S2-07/S3-01 decide whether a request re-links it.
- API (`CrateStore`): `add_request(kind=, source=, artist=, album=, year=) -> int`, `set_release_id(request_id,
  mbid)`, `set_recording_id(ext_id, mbid)`, `request(id) -> dict | None` (the row's columns, `rows` = `wanted_row`
  dicts ordered by `track_no`, then playlist `position`, rows without a track number last, and `status`), `requests()` newest first. Every payload
  that leaves the server goes through `store.public` (no peer name, no absolute path; tested).
- From a Spotify URL (S2-02, `sourcing/requests.py` `add_spotify`): `source` is the canonical URL (no `?si=`, no
  `/intl-xx/`), so a share link finds its request again (`CrateStore.find_request(source)`). `track_no` is the
  position in the album embed's list: the embed has no disc number, so a second disc runs on (disc 2 track 1 of a
  12-track first disc is 13). S2-03 matches MusicBrainz tracks by their order across all media, not by
  `position` within one medium. A request whose every row already belongs to another request is not made: that
  request answers (a track already in an album request gives the album request).
- MusicBrainz release (S2-03, `sourcing/musicbrainz.py` `match_release`, `sourcing/requests.py`
  `match_request_release`): one release search (`artist:"…" AND release:"…"`, limit 25), then `release/<id>?inc=recordings`
  for each release listing exactly as many tracks as the request has live rows, in tie order (Digital Media, CD,
  other; then the earliest date, no date last), stopping at the first whose tracks, in order across all media, have
  their rows' title keys (`identity.loose(parse_title(title, artist).base)` plus the version key, so a live or
  remixed track is no match; the row's `asked_title`). Live rows: not `removed`, per track number the newest (a
  re-seed queues a new row beside a failed one); they must be numbered 1..n. Recordings (to every non-removed row of
  that track number, `updated_at` untouched) and `mb_release_id` are one transaction, with a `release` event
  `#<request> musicbrainz release <id> (<format> <date>)`. A matched request is not searched again; a row added
  since gets its recording from the stored release. No match, a MusicBrainz error or an unusable cache → no ids,
  the request goes on. `seed-spotify` asks only with `--musicbrainz` or `$MUSICBRAINZ_CACHE` (the client's
  resumable cache file). fetch verifies with the row's `mb_recording_id`; a copy upgrade uses the old copy's
  recording id from Navidrome first. Known gap: an album track that already belongs to another request is not this
  request's row, so the album has a missing track number and gets no ids (soft title check, as before S2-03).

## Request status

Derived on read by `crates.store.request_status(rows)`, a pure function; nothing is stored twice. The rows are
`wanted_row` dicts (`status`, `reason`, `approval`). A `removed` row (superseded) counts for nothing. A row is
*going* when it is `sourcing` or `verify`, is `failed` with its file in the library (`filed_path`: Navidrome never
indexed it), or has an approval waiting or being fetched (unused, or `started`). A row is *ok* when its status is
`ok`, *open* when it is not ok and not a `failed` row that isn't going (so a failed row approved again is open).
The first rule that applies:

1. `done`: every row ok.
2. `failed`: no row ok and none open (every row failed).
3. `partly`: some row ok (the rest failed or still open).
4. `approved`: some row is going.
5. `open`: anything else, including a request with no rows yet. A `review` row (a question for Michael) is open:
   no status of its own; the row's own status and reason say what is asked.

## Album job

The spec's S2-04..S2-07, as the features build them:

- **`sourcing/album.py`** (S2-04): the planner, pure, no I/O. Input: one slskd search response list for
  `"<artist> <album>"` and the request's rows. Groups files by (peer, directory) and maps rows to files with the
  scorer's per-file rules (`sourcing.scorer`, S1-01, D24). Output: the primary folder (most rows covered, then summed
  score, then free slot and speed), at most one secondary for what the primary lacks (preferring the same release:
  lengths within 2 s of the primary's, or the S2-03 MusicBrainz release, and the same format family; a one-row
  folder is not a folder source), the per-track
  rows, and the other folders ranked for a later switch. Folders are labelled `folder 1`, `folder 2`; no peer name
  reaches a reason, an event or a payload.
- **As built (S2-04)**: `plan_album(responses, rows, *, policy, listed_lengths=None) -> AlbumPlan` (`primary`,
  `secondary`: `FolderPick(username, directory, rows=[(row, Candidate)])` with `score` = the summed candidate scores;
  `per_track` rows; `alternates`; `assignments()` = primary rows, then secondary rows). Rows are the caller's dicts
  and are kept by position (`FolderPick.at`); S2-05 should tell them apart by `row["id"]`. A folder source covers at
  least 2 rows (`MIN_FOLDER_ROWS`), so a one-row request is all per-track. Folders are (peer, directory), the
  directory `""` for files at a share root; each folder's `fileCount` is its own file count. Ties after free slot and
  speed: the summed bitrate (the scorer gives a lossless file's bitrate no points, so two copies of one rip differ
  only there), then peer and directory. Secondary order: most rows the primary lacks, then no sign of another
  release (a format family the primary lacks, or a length more than 2 s off the primary's file of a shared row or
  `listed_lengths[track_no]`; a file without a length shows nothing), then the primary's order over those rows.
  `listed_lengths` is `{track_no: seconds}`: S2-03's `ReleaseTrack` has no length yet, so S2-05 adds
  `length` (MusicBrainz `track.length`, ms → s) to pass it, or passes None. `describe(plan, peers=False)` labels
  folders `folder 1..n` in plan order and prints no directory. For S2-05: the dataclasses' `repr` and
  `Candidate.as_dict()` carry the peer name, so a cached plan goes out only through `store.public`; the secondary
  may be the primary's own peer (another directory), so a start timeout on that peer switches both.
- **The plan is cached** with `CrateStore.set_preview(f"req-<id>", plan)` (the `previews` table, keyed by text, so
  it never collides with a song id or `ext-N`). S3-03's preview reads it back through `store.public`.
- **Approvals get purpose `album`** (added to `APPROVAL_PURPOSES` by S2-05a): one approval of a request writes one
  `approvals` row per open row, purpose `album`, the planned file as the candidate. Michael's click (HTTP or CLI) is
  the only trigger (D7); a preview may search slskd but never POSTs a transfer.
- **`sourcing/album_job.py`** (S2-05a..c): the worker side. `Worker._spend` groups `album` approvals by their rows'
  `request_id` and hands each group to `album_job.run`: claim them together, run one search, plan, enqueue all
  planned files of a folder to its peer in one `POST /transfers/downloads/{peer}`, then run each row through
  `sourcing.fetch.fetch` in planned mode.
- **fetch's planned mode**: `planned=True` + `prefer=<planned candidate>` means no search and no enqueue of its own;
  fetch polls for the transfer the job enqueued (S1-04's record poll, given the ids that existed before the job's
  enqueue), then verifies with the row's `mb_recording_id` as the recording id (S2-03), files, finishes and places
  as today. A row already in the library (S1-07) is linked, not downloaded.
- **As built (S2-05a)**: `sourcing/album_job.py`. `plan_request(store, slskd, id, policy=None, *, poll_s)` plans
  the request's open rows (not `ok`/`removed`, nothing filed) and caches `{folders, per_track, text, at, assign}`
  under `req-<id>`, `assign` = ext id → `{folder: "folder N", candidate: Candidate.as_dict()}` (server side, so it
  holds the peer); it returns the cache without `at`/`assign`, through `public`; one `plan` event
  `#<id> folder 1: 8 of 9; 1 row per track`. `approve_request(store, id, approved_by)` → approval ids (a candidate
  from `assign`, None without a cached plan: the job plans first). `run(id, approvals, *, fetcher, plan_max_age_s,
  **fetch kwargs)` → `[(approval, outcome)]`: claims, `fetch.in_library` per row (outcome `ok: in library (<song>)`),
  re-plan when the cache is missing or older than `ALBUM_PLAN_MAX_AGE_S` (3600; the CLI's worker reads the env),
  one `enqueue` per peer (its earlier `Completed` records of those files forgotten first, as fetch does), each
  planned row `fetch(..., planned=True, prefer=<candidate>, enqueued=<the peer's record ids before>)`, then the rows
  without a planned file as an ordinary fetch. An error after the claim is the outcome of every approval not yet
  marked. In planned mode fetch neither asks the library nor searches (the one candidate is `prefer` scored again:
  `fetch.planned_candidate`; rejected → `needs_source`, nothing downloaded) and logs `pick` `planned file: <basename>`.
  The secondary's files go in the same POST when it is the primary's peer. `listed_lengths` is still None (S2-03's
  tracks have no length). Review fixes: only a row fetch would download (needs_source, failed, a retryable review;
  nothing filed) whose planned file passes at its own tier is enqueued; a planned file not filed afterwards (fetch
  raised or failed) and a refused POST's records are forgotten (remove=true); `approve_request` also refuses while an
  approval of the request is `started` (the job has not reached that row yet). Known gap for S2-05b/c: a worker
  restart mid-album leaves the transfers of rows the job had not reached in slskd (`recover_interrupted` fails no
  `needs_source` row and forgets no transfer); a later approval's planned fetch takes only a record newer than its
  own enqueue, so it cannot mistake one, but the file may land unfiled in downloads.
- **Switch triggers** (the rest of that folder's rows switch, not only the failed one): a transfer error or timeout
  (S1-04/S1-06); a peer that has started no file `ALBUM_START_TIMEOUT_S` (default 600 s) after the enqueue; a verify
  finding. One finding of the "not what it claims" kind (`transcode`, `fake_24bit`, `fake_hires`, `recording`)
  distrusts the whole folder at once; any 2 failures in one folder do the same; an ordinary finding (`duration`,
  `truncated`) fails that row only. On a switch: cancel and forget (`?remove=true`) the folder's queued transfers for
  rows not yet filed, re-plan the remaining rows over the first search's folders plus one fresh album search without
  the failed folder (S2-04's same-release rule); rows already verified or filed stay.
- **As built (S2-05b)**: `album_job.run(..., start_timeout_s=ALBUM_START_TIMEOUT_S)` (600; the worker's
  `album_start_timeout_s`, the CLI's `$ALBUM_START_TIMEOUT_S`). After each peer's POST the job waits until one of its
  records is past `Requested`/`Queued`/`Initializing`; none by the timeout → every folder of that peer in the POST
  fails (its records forgotten, the peer's other folders left out of the re-plan). In planned mode fetch does not
  retry another peer: a transfer error S1-06 would retry returns `FetchResult.again`, and the job switches. A failed
  verification's `FetchResult.kinds` are verify's check names (`Verdict.kinds`, also in the stored verification);
  `DISTRUST = {transcode, fake_24bit, fake_hires, recording}` switches at once (`implied_kbps`, the size guess, is
  an ordinary finding), any `MAX_FOLDER_FAILURES` = 2 failed rows do too; an exception (Navidrome down) is no
  folder's failure. A row failed by an ordinary finding keeps its approval open until the job ends, so a later
  switch of its folder takes it along. On a switch: the folder's records of unfiled rows go (remove=true), the
  moved rows (the failed one included) are planned again by `plan_album(..., exclude=failed folders, like=the
  planned files' lengths by track number, min_rows=1)` over the cached first search's `responses` (the cache keeps
  them server side, beside `assign`) merged with one fresh album search (a peer's fresh response replaces its old
  one; a refused search plans over the cached ones alone), and run in the next round (one POST per peer again).
  `like` ranks a folder of the release being filed first after coverage (a switch never trades it for a better
  scored remaster); `min_rows=1` lets a single row switch to a folder. A folder new to the job gets the next label. One `switch` event per failed folder: `#<id> folder 1
  distrusted: transcode (<basename>); 8 rows → folder 2` (or `folder 1: download ended: Completed, Errored (…)`,
  `folder 1: 2 failures (…, …)`, `folder 1: no transfer started within 600 s`; destinations `7 rows → folder 2,
  1 row → folder 3; 1 row per track`). A row switches once; one with no folder left goes per track as an ordinary
  fetch with no preferred file (S2-05c adds `exclude` and the cap's reason). Its approval gets its last fetch's
  outcome; the row's reason is the last attempt's (S2-05c lists every attempt).
- **Per-row attempt cap**: its planned folder, one switched folder, one per-track fetch (excluding every failed peer
  and file). Then the row fails, and every attempt is in its reason.
- **As built (S2-05c)**: `fetch(..., exclude=<usernames>)` drops those peers' candidates right after `rank` (the
  S1-06 retry picks from what is left), answers `needs_source` "no acceptable candidate from another peer" when none
  is left, and logs the pick as `per track: <basename>`. The job passes every failed folder's peer and every stalled
  peer as `exclude` to each per-track fetch (rows no folder covers included). It keeps each row's attempts in order:
  its own failure in a folder is `folder N: <kind> (<basename>)` for a distrust finding, else `folder N: <fetch's
  reason>`; a row moved along with its folder gets the folder's cause (`folder 1: no transfer started within 600 s`,
  `folder 1: 2 failures (…)`, `folder 1: download ended: … (<basename>)`). A row with attempts whose per-track fetch
  ends `failed` or `needs_source` (nothing filed) is failed with `<attempts>; per track: <its reason>`, and its
  approval's outcome is `failed: <that reason>`; a per-track fetch that raises (its search, before fetch's own
  `try`) is `per track: error: …`. A row that failed with an ordinary finding in a folder that stayed trusted keeps
  fetch's reason when that was its planned folder, and lists both folders when it was its switched one (no per-track
  fetch: an ordinary finding fails its row only). A switched row whose new file its own tier now rejects goes per
  track. "from another peer" only when `exclude` removed an acceptable candidate. Opus review: 2 important (the
  raising per-track fetch, the held switched row) and 3 minor fixed, test-first.
- **Filing** (S2-06): album rows go to `$albumartist/$album ($year)/$track - $title` only if S2-06a's scratch
  measurement shows beets 1.6.0 honours `--set dj_album=1` and the query-keyed path for `-s` imports; otherwise
  `Singles`, as today. Each row is filed as it lands (today's behaviour), so Navidrome may show a half album for a
  while.
- **Playlists** (S2-07): the import as today plus one approval for its open rows; rows sharing artist and album
  (3 or more) go as an album job, the rest per track. As built: `sourcing.requests.add_playlist(store, playlist_id, source=, name=)` (and
  `add_spotify(..., playlist_id=)` for a Spotify playlist URL; `import-playlist --request`) records a `playlist`
  request whose `album` is the playlist's name and whose rows are the wanted rows of its last `import_order` that no
  other request holds (`CrateStore.attach_request`; `track_no` stays None). `album_job.groups` splits its open rows
  by `identity.loose` artist and album (MIN_GROUP_ROWS = 3); each group is its own job inside `album_job.run`
  (`_run(request_id, group, …)`; cache `req-<id>:<group>`), searching `"<artist> <album>"` with the rows' own
  lengths (no release, so no listed lengths); `per_track` rows get `download` approvals. `plan_request` on a
  playlist returns `{"albums": [...], "per_track": [...]}`. Tests: `tests/test_playlist_request.py`.
  After the Opus review: the playlist's name is the request's identity (`find_playlist_request`; a file path is
  none); `detach_request` releases rows the last import no longer lists (unless going); a playlist holds its rows
  loosely (`CrateStore.takeable`: an album or track request asked for later takes rows with nothing going, so the
  album files as one); ambiguous `review` rows are neither grouped nor approved; an `album` approval whose row lost
  its album is fetched per track without a plan; no empty request. Known limit: a Spotify playlist URL's embed has
  no album, so its rows all go per track (album groups need an Exportify CSV or a SpotiFLAC report).

## Live steps

None in this run (build-only). Every live step of S2 (the migration on the live crates.db at the first deploy, the
first album request, the beets path) goes into `docs/plans/2026-10-22-downloads-checklist.md` with S4-01, with its
snapshot, stages and undo. The migration is additive: an older image ignores the new table and columns, so rolling
back the image is the undo for S2-01. From S2-05a on it is not the whole undo: an older worker would spend unused
`album` approvals as plain per-track downloads (still Michael's approvals, so D7 holds, but outside the album job).
S4-01's rollback step must first mark unused `album` approvals used (or roll back only while none is waiting).
