# Download fixes, album requests and a request API (2026-10-22 run, milestones S1–S4)

Written 2026-10-22 00:50–01:05 from a read-only look at the live system (crates `/api/events`, `/api/wanted/<id>`,
`docker logs` of `dj-crates-1`, `dj-worker-1`, `dj-slskd-1`, `dj-gluetun-1`) and offline repros on the hotfix code.
**Build-only:** nothing here runs live. Every live step goes into the downloads checklist (S4) for Michael. The pivot
spec wins on conflict. Identity follows `docs/identity.md` and M9. D26 (source the exact track) and D7 (Soulseek
transfers only after Michael's approval) bind every milestone.

**Base.** This run starts from branch `spec/2026-10-22-downloads`: `origin/main` at `5b3e370` (R1–R5 of the 10-21 run)
plus PR #16's branch `worktree-fix-slskd-downloads-404` (merged, same commits). The live hotfix's four patches are
therefore in the base: the per-peer downloads 404, the ffmpeg 7.1 verify panic, the empty first read of responses, and
the scorer title slot. Each verify merges `origin/main` in first, so R6–R8 of the 10-21 run arrive as they land.
**Decision numbers.** The 10-21 run may add decisions while this one is queued. Take the next free `D<n>` when you
write one, and refer to this spec's decisions by name ("album path", …).

## What was found for the Al Green errors (concern E)

Request: Spotify album `2nTlIPIQ7fHOnNN7BRch0Z` (*I'm Still in Love With You*, 9 tracks). It was imported as playlist
`6CqtHuurS3iah9VrrfrVam`, wanted rows `ext-74`…`ext-81`; "Simply Beautiful" was already in the library. Images by time
(EDT): `f4882ab85b` until 22:12; `6238ee5d69` (404 fix) 22:12; `243b9d7199` (+ verify panic fix) 22:36;
`41fcc5bc01` (all four) from 22:57.

| When | Rows | What failed | Endpoint / code path | Covered by the hotfix? |
|---|---|---|---|---|
| 21:46 | all 8 | `HTTPError: HTTP Error 404: Not Found`, before any enqueue | `GET /api/v0/transfers/downloads/{peer}` in fetch's "forget earlier attempts" loop; slskd 0.26.1 answers 404 for a peer with no transfers | yes, `6238ee5` (`SlskdClient.downloads`) |
| 22:27–22:28 | ext-74, ext-75 | downloaded, then `failed` in verify | ffmpeg 7.1 band filter panic | yes, `243b9d7` |
| 22:38 | ext-74 | **wrong song filed as ok**: asked "I'm Still In Love With You", got track 09 "One of These Good Old Days" from the folder `I'm Still in Love With You (1972)`; the row was then renamed to the other song | scorer: the asked title matched the album name in the path (98.0, a tie with the right track); verify: AcoustID said "One of These Good Old Days" (0.958), but the check fails only when a recording id is known; `finish` copied the library's name onto the row | ranking yes (`41fcc5b`, deployed 22:57); **rejection no, verify no, rename no** |
| 22:59–23:07 | ext-76, 77, 79, 80, 81 | all `ok` | — | — |
| 23:00 | ext-81 | filed `One of These Good Old Days.1.flac`, a second copy of the file ext-74 brought | `duplicate_action: keep`; nothing asks the library before downloading | no |
| still now | ext-78 | shows `failed` with the 21:46 404; never approved again | stale reason | (fixed code, row never retried) |

The "4xx errors after the hotfix" are the 21:46 404s. They stay visible on rows that were not approved again (ext-78
still shows one). **No row failed after 22:57.** But 4 bugs the hotfix doesn't cover showed up:

- **Wrong song accepted.** Repro on `41fcc5b` (offline, `scorer.rank`): a peer that offers only track 09 of the
  same-named album is still `ok` at 84.5 for "I'm Still In Love With You". `verify._acoustid_check(…, recording_id=None)`
  with AcoustID answering "One of These Good Old Days" returns no finding. Spotify's 196 s and the file's 195 s agree,
  so duration can't catch it: MusicBrainz has track 1 at 195.7 s and track 9 at 195.6 s.
- **Transfers are never forgotten.** `SlskdClient.remove_download` sends `DELETE /transfers/downloads/{peer}/{id}` without
  `?remove=true`. slskd's `TransfersController.CancelDownloadAsync` (`[FromQuery] bool remove = false`) then cancels and
  answers 204, and the record stays. fetch then reads `mine[-1]` by filename, so a retry of the same file from the same
  peer can take an old `Completed, …` record as its own. `sourcing/fake_slskd.py` deletes on any DELETE, so no test can
  see this. It didn't bite on 10-21: the 22:38 retry of ext-74's file came back fine.
- **The VPN drops every 5–15 min.** gluetun's NAT-PMP refresh times out (`refreshing port mapping … connection failed`).
  It clears the forwarded-port file, and slskd logs out of Soulseek for about 10 s (13 drops between 21:30 and 00:50).
  A transfer caught in one ends `Completed, Errored`, and the row fails with no second source tried. Fixing gluetun is
  Michael's (compose); the code must survive it.
- **Album placement.** Spotify album rows carry `album: null`: the embed has the album name but `playlist_sources`
  doesn't copy it. The filer imports singletons (`-s`, path `$artist/Singles/$title`), so the album's tracks came from 5
  peers and 4 different releases into `Al Green/Singles/`.

## Order and rules

S1 (the fixes for E) comes first; S2 (albums) and S3 (requests) build on it; S4 last. Every feature starts with a failing
test that shows the problem, then the fix. Tests use the fakes and the fixtures only; no network. Never invent a
response shape: use `fixtures/search_responses.sample.json`, `fixtures/spotify_embed_album_al-green-still-in-love.json`,
`fixtures/musicbrainz_release_search_al-green.json`, `fixtures/musicbrainz_release_al-green-still-in-love.json`
(captured 2026-10-22) and the existing `fixtures/musicbrainz_search.sample.json`. Where a real slskd shape isn't captured
(the enqueue response, `/users/*`), don't depend on it. A shape you'd need goes into the checklist as a capture step.

## S1: download fixes from the Al Green attempts (after: [])
**Built 2026-10-22** (run `dj-crate-streaming-2026-10-22-fixes`, commits `0493bc2`…S1-R1 on branch
`harness/dj-crate-streaming-2026-10-22-fixes`, base `307d62b`): against the fakes only, not deployed, PR open. Decisions
D48 and D49 (*default*) in the pivot spec.
1. **S1-01 Reject a file whose title slot names another song** (`sourcing/scorer.py`). After the hotfix's title-slot
   rule, a candidate whose title slot parses (`identity.parse_filename`) to a different song key than the wanted title
   (`parse_title(...).key`, labels and case ignored; D26 versions stay as they are) is `rejected` ("title slot is <X>"),
   not just ranked lower. Failing test first: the ext-74 shape (folder `Al Green\I’m Still in Love With You (1972)`, only
   track `09 - One of These Good Old Days` offered) must give no acceptable candidate. Keep every existing scorer test
   green, `strip_trackno` cases (R6 8b) included.
2. **S1-02 AcoustID disagreement without a recording id is a hard finding** (`sourcing/verify.py` `_acoustid_check`).
   When no recording id is known, a confident result (top score ≥ 0.8, `docs/identity.md`) with **no** returned
   recording whose title key matches the asked title is a `recording` finding: "AcoustID says this is <title>, not
   <asked>". The asked title is the row's `asked_title`, else `title`. A lookup error and "not in AcoustID" stay warnings.
   fetch passes the asked title in. Failing test first: ext-74's lookup (fixture-shaped, ids from the 10-21 row) fails.
3. **S1-03 Never rename a row onto another song** (`sourcing/fetch.py` `finish`). If the filed song's title key differs
   from the asked title's key, the row becomes `review` ("filed <X>, asked for <Y>"), keeps its names, and is not placed.
   Same key, other spelling (`Love And Happiness` → `Love and Happiness`): renamed as today.
4. **S1-04 slskd transfer hygiene** (`sourcing/slskd_client.py`, `sourcing/fetch.py`, `sourcing/fake_slskd.py`).
   - `remove_download` sends `?remove=true`, and reads a 404 there as already gone.
   - The fake keeps the record on a DELETE without `remove=true`, as slskd 0.26.1 does. Change the fake first, so the
     failing test is the retry case.
   - fetch identifies its own transfer as a record for its filename whose id wasn't there before the enqueue. It doesn't
     use `mine[-1]` or the enqueue response.
5. **S1-05 A reason names the step and the endpoint.** An `HTTPError` from slskd becomes e.g. `slskd GET
   /transfers/downloads/<peer>: HTTP 404`, never the peer's name (fetch header rule), never an API key. Tests on the
   reason strings.
6. **S1-06 One more source on a transfer error** (`sourcing/fetch.py`). A transfer ending `Completed, Errored`,
   `TimedOut`, `Rejected` or `Cancelled`, or a connection error or 5xx from slskd during the download, tries the next
   acceptable candidate from another peer, once per approval. That covers a VPN drop. A second failure fails the row as
   today, and both attempts appear in the reason. A verify failure is not retried here (S2 covers album fallbacks).
7. **S1-07 Ask the library before downloading.** Before searching for an external row, fetch asks Navidrome as the
   import does (`import_playlist.match`/`choose`, same rules). On a same-recording or same-version hit, the row becomes
   `ok` with that `library_song_id`, gets a `matched` event, and nothing is downloaded. Placement then works as for any
   filed row. Test: ext-81's case, a song filed by another row, makes no second download.
8. **S1-08 `crates.cli wanted reopen <id> [--apply]`** for a row filed as the wrong song (ext-74). It puts the asked
   names back, clears `library_song_id`, sets `needs_source` with a `reopened` event, and touches no file and no
   playlist. Dry run by default; the reverse is in the event. Tests on a fake store.

## S2: album requests, sourced album-first (after: [S1-01, S1-02])
**Built 2026-10-23** (run `dj-crate-streaming-2026-10-22-build`, commits `88eba88`…S2-R1 on branch
`harness/dj-crate-streaming-2026-10-22-build`, base `1eb4259`): against the fakes only, not deployed. Plans
`docs/plans/2026-10-22-s2-album-requests.md` and `docs/plans/2026-10-22-S2-album-tags.md`; decisions D50 and D51
(*default*) in the pivot spec. Approving a request from a client is S3's.
The need (Michael, 2026-10-22): one album in one go. Ideally one source (one peer's folder) has every track and all
come from it. On any trouble, switch, and ideally to **one other folder for the rest**, not track by track. Per-track
sourcing is the last resort, for what no folder has. Why this order: one folder is one master (the same lengths,
sample rate and loudness), one peer queue and one failure point. Per-track picks the best copy of each track but mixes
releases, as the 10-21 Al Green album did (5 peers, 4 releases, a 393 s best-of take of "For the Good Times").
1. **S2-01 Requests in crates.db** (`crates/store.py`, additive migration in the existing style).
   - A `requests` table: id, kind `album|playlist|track`, source (URL or `search`), artist, album, year,
     `mb_release_id`, created_at.
   - `external_wanted` gains `request_id`, `track_no` and `mb_recording_id`.
   - A request's status is derived from its rows; nothing is stored twice.
   - Tests: migration on an old db; round trip.
2. **S2-02 An album URL fills the album** (`sourcing/playlist_sources.py`, `spotify_csv.py`). A Spotify album entity
   gives every row `album` = the entity name, `track_no` = its position, and `year` from `releaseDate`. Fixture: the
   captured Al Green embed (9 tracks, "Oh ,Pretty Woman" spelled as Spotify spells it). Playlist rows are unchanged.
3. **S2-03 MusicBrainz release match** (`sourcing/musicbrainz.py` client, cache and limiter). For an album request:
   - Search releases by artist and album. Take the one whose track count matches and whose titles match the rows' one to
     one by key.
   - Ties: digital, then CD, then the earliest date.
   - Store `mb_release_id` and each row's `mb_recording_id`. No 1:1 match → no ids, and the request goes on without them.
   - fetch passes the row's `mb_recording_id` to verify as the recording id, so the existing hard AcoustID check applies.
     That would have caught ext-74: track 1 is `cdac1a50…`, the file AcoustID'd as track 9's `83f06455…`.
   - Tests on the two captured fixtures.
4. **S2-04 Album-first plan** (new `sourcing/album.py`, pure, no I/O).
   - Input: one search response list for `"<artist> <album>"` (Soulseek matches the whole path, so it returns whole
     folders) and the request's rows.
   - Group files by (peer, directory). In each folder, map rows to files with the scorer's per-file rules (S1-01
     included, policy D24).
   - The **primary** folder: the most rows covered (all of them wins outright), then the summed quality score, then free
     slot and speed.
   - The **secondary** folder: the one covering the most of the rows the primary lacks. Prefer the same release: track
     lengths within 2 s of the primary's listing (or the S2-03 MusicBrainz release), same format family. A folder
     covering only one row isn't a folder source; that row goes per-track.
   - At most two folders, then per-track for what is left.
   - Output: an ordered plan (primary rows, secondary rows, per-track rows), plus the remaining candidate folders
     ranked for a later switch (S2-05).
   - Tests on synthetic responses in the sample's shape:
     - full coverage in one folder;
     - 7 of 9 plus a folder with the other 2;
     - two same-named folders;
     - a folder of a different release with other track lengths (loses to a same-release secondary);
     - nothing better than one track per folder (all per-track).
5. **S2-05 Album job in the worker** (`sourcing/fetch.py`, `sourcing/worker.py`).
   - One approval of a request approves its rows: one `approvals` row each, purpose `album`, the planned file as the
     candidate. Michael's click is the only trigger (D7).
   - The worker claims a request's approvals together. It runs one search, plans (S2-04), and enqueues all planned files
     to that peer in one `POST /transfers/downloads/{peer}`.
   - It then runs each row through the existing pipeline in a planned mode: no re-search; poll that file's transfer
     (S1-04); verify with the recording id; file; finish; placement.
   - **Switching.** Trouble with a planned file switches the rest of that folder's rows, not only the failed one:
     - Triggers: a transfer error or timeout (S1-04/S1-06), a peer that hasn't started any file
       `ALBUM_START_TIMEOUT_S` (default 600 s) after the enqueue, or a verify finding.
     - A single verify finding of the "not what it claims" kind (a lossy source in a lossless file, a wrong recording)
       distrusts the whole folder, because fakes come as folders. Any 2 failures in one folder do the same.
     - On a switch: cancel and forget (`?remove=true`) that folder's queued transfers for rows not yet filed, so they
       don't land later as duplicates. Re-plan the remaining rows over the first search's folders plus one fresh album
       search, without the failed folder, preferring the same release (S2-04's secondary rule).
     - Rows already verified or filed from the first folder stay.
   - Each row gets at most: its planned folder, one switched folder, and one per-track fetch (excluding every failed
     peer and file). Then it fails, and every attempt is in the reason.
   - A row already in the library (S1-07) is linked, not downloaded.
   - Tests with the fake slskd:
     - whole-album happy path;
     - one track fails verify (ordinary finding), and the rest of the album stays on the primary;
     - a transcode finding, so the remaining rows switch to the secondary and their primary transfers are removed;
     - a peer that never starts (start timeout);
     - a transfer error mid-album;
     - the per-track last resort;
     - the restart case (`recover_interrupted`).
6. **S2-06 Album path** (`deploy/beets.yaml`, `sourcing/filer.py`; Michael's answer 2026-10-22, recorded as a `D<n>`
   in the pivot spec, not a default: "album path").
   - A track filed for an album request goes to `$albumartist/$album ($year)/$track - $title`, still as a singleton
     import. Mark it with beets' `--set` (e.g. `dj_album=1`) and a query-keyed path. Every other singleton stays at
     `$artist/Singles/$title`.
   - An album request's tracks carry the request's album identity: album, albumartist, track, year and, with S2-03,
     the MusicBrainz release id. So tracks from the primary, the secondary and per-track fallbacks file into one folder,
     and Navidrome shows them as one album. That writes tags, so first write `docs/plans/2026-10-22-S2-album-tags.md`:
     - which fields;
     - through `scripts.tag_cleanup.write_minimal` only (the one field-by-field writer, never a full beets write: the
       M2 trap);
     - on our fresh download in `.staging` only, before beets sees it;
     - the reverse (the old values in the event).
     Have it reviewed (an Opus review subagent) before the code. Plain rows keep `fill_missing_tags` as today.
   - Measure on beets 1.6.0 (on this box, scratch config and library) that the `--set` field and the path key work for
     `-s` imports. If they don't, keep Singles, record the finding, and leave it as a checklist question.
   - The live library changes only after a deploy.
7. **S2-07 A playlist in one go.**
   - A playlist request is the import as today, plus one approval for all its open rows.
   - Rows sharing artist and album (3 or more) are sourced as an album job (S2-05), the rest per track.
   - Tests: a mixed playlist.

## S3: request API, client-agnostic (after: [S2-01])
**Built 2026-10-23** (run `dj-crate-streaming-2026-10-22-build`, commits `ea4823a`…S3-R1 on branch
`harness/dj-crate-streaming-2026-10-22-build`): against the fakes only, not deployed, no client UI. The endpoints are
in `docs/api.md`, the CLI in `docs/worker.md` ("The morning path, without a client"), both in `docs/architecture.md`
§4 (e); decision D52 (*default*) in the pivot spec. `scripts/capture_spotify.py` is written and never run.
Server side only. Any client (the current web client, Amperfy's successor, a phone shortcut) can drive it. **No UI in
this run** (concern B is open).
1. **S3-01 `POST /api/requests`** `{"url": …}`:
   - a Spotify track → one row;
   - a Spotify album → an album request (S2-02, S2-03);
   - a Spotify playlist → the playlist import with `--merge` semantics and a playlist request (S2-07).
   `{"mbReleaseId": …}` or `{"mbRecordingId": …}` comes from a catalog pick (S3-02). It answers with the request and its
   rows, already-in-library rows marked (S1-07). Errors are 400 with a reason; an unknown URL kind is 400 too.
2. **S3-02 `GET /api/catalog/search?q=&kind=album|track`.**
   - MusicBrainz release and recording search through the existing client: limiter, cache, 503 backoff.
   - Each hit carries title, artist, year, track count or length, mbids and `inLibrary`.
   - Search goes through a small provider interface (`sourcing/catalog.py`: `search(q, kind) -> [hit]`, each hit
     with `provider` and that provider's ids), so a second provider is a new class, not a new endpoint. MusicBrainz is
     the one provider in this run.
   - **Spotify is the next provider**, using Michael's own developer app (his answer to C, 2026-10-22). Not in this
     run: no real Web API response has been captured, and the February 2026 changes removed fields from track and
     album objects. So don't build it against documentation examples. S3-06 builds the capture.
   - Tests on fixtures only.
3. **S3-03 `GET /api/requests`, `GET /api/requests/<id>`, `POST /api/requests/<id>/preview|approve`.**
   - Preview = the album plan (folder, coverage, row → file, per-track rows), cached like `previews`, peer names never
     shown.
   - Approve = S2-05. 409 while a row is `sourcing`/`verify`.
   - Same auth and exposure as today's `/api/*`.
4. **S3-04 CLI for the same** (`python -m sourcing.cli request add <url> | preview <id> | approve <id> | show <id>`).
   It's what Michael uses in the morning without a client; approve and the downloads are his.
5. **S3-05 `docs/api.md`**: the request endpoints with example bodies, written for a future client.
6. **S3-06 `scripts/capture_spotify.py`** (written and tested against a stub, **never run in this run**). It's for
   Michael's morning: Client Credentials flow (`POST https://accounts.spotify.com/api/token`) with `SPOTIFY_CLIENT_ID` and
   `SPOTIFY_CLIENT_SECRET` from the environment, then one `GET /v1/search?type=album,track&limit=10&q=…` and one
   `GET /v1/albums/{id}`. It writes `fixtures/spotify_search.captured.json` and `fixtures/spotify_album.captured.json`.
   - The token and the secret never reach stdout, a file or an exception message (tested with a stub opener).
   - It refuses when either variable is unset.
   - Usage in its docstring.

## S4: checklist and whole-run review (after: [S1-01, S1-02, S1-03, S1-04, S1-05, S1-06, S1-07, S1-08, S2-01, S2-02, S2-03, S2-04, S2-05, S2-06, S2-07, S3-01, S3-02, S3-03, S3-04, S3-05, S3-06])
**Built 2026-10-23** (run `dj-crate-streaming-2026-10-22-build`, S4-01 `b3658c9` and S4-02 on branch
`harness/dj-crate-streaming-2026-10-22-build`): the checklist (§4, §6, Captures) and the whole-run review, its
Important findings fixed test-first; not deployed, PRs open. Decision D53 (*default*) in the pivot spec.
1. **S4-01** `docs/runbooks/2026-10-22-downloads-checklist.md`, each step with its check and undo, from "Morning checklist
   addition" below. Link it from `docs/runbooks/2026-10-22-morning-checklist.md` (the 10-21 run's R8) when that file is on
   main. Add a line before that checklist's deploy step: "PR #16 must be on main first". Update `docs/architecture.md`
   §4 (requests, album jobs) and `docs/next-todos.md` State.
2. **S4-02** A whole-run review (Opus) of the diff since the base. Fix Critical and Important findings; the suite stays
   green.

## Out on purpose
- **Client UI** (a search bar, a request screen, album progress) until Michael answers B. The API (S3) is what any client uses.
- Other platforms' links (Apple Music, YouTube, Deezer): ask first. Spotify search: the next run, after S3-06's capture.
- Credentials embedded in other projects (SpotiFLAC's): never. Only Michael's own app.
- slskd peer browse (`/users/{peer}/directory`): not needed while folder search covers albums; no captured shape.
- gluetun / VPN settings (Michael's compose); live re-tests and downloads (Michael's, D7).
- Cleaning the live library (the `.1.flac` copy): the N1 duplicate cleanup does it.

## Morning checklist addition (S4 writes it into the checklist)
1. **Before any deploy from main**, PR #16 is on main: `git -C ~/projects/dj-crate-streaming fetch -q && git -C
   ~/projects/dj-crate-streaming merge-base --is-ancestor 59c6f6a origin/main && echo ok`. If not: `gh pr ready 16 &&
   gh pr merge 16 --merge`. Use a merge commit, not a squash, so the commits match this run's base.
2. Then the 10-21 checklist's deploy step. Rollback tag: `dj-crates:41fcc5bc01` (the hotfix).
3. **After this run's S1 is merged and deployed** (not before: without S1-01..03 a same-named folder can bring the wrong
   song again), re-test the album:
   - Reopen the wrong row: `scripts/live-run.sh python3 -m crates.cli wanted reopen ext-74`, then the same with `--apply`.
   - Approve ext-74 and ext-78 in the web client. Expect ext-74 = track 01 (191–196 s), ext-78 = "Oh, Pretty Woman";
     `/api/events` shows `pick`/`filed`/`ok` and no `renamed` to another title.
   - Check: Navidrome album "Al Green" has all 9 titles.
4. **After S2/S3 are deployed**: `scripts/live-run.sh python3 -m sourcing.cli request add
   https://open.spotify.com/album/2nTlIPIQ7fHOnNN7BRch0Z` → `preview` shows one folder with ≥ 8 of 9 tracks → `approve`
   (Michael). Expect one peer for most tracks, files under `Al Green/I'm Still in Love With You (1972)/` (if the album
   path holds). Capture one real enqueue response for the fixtures (S4 notes the command).
5. Run the duplicate cleanup's `plan` for the `.1.flac` copy (N1 runbook).
6. Spotify (for the next provider): on developer.spotify.com, create an app (Web API; needs Premium on the owning
   account). From a checkout of the run's branch, on the host (no container needed), run `read -rs
   SPOTIFY_CLIENT_SECRET; export SPOTIFY_CLIENT_SECRET SPOTIFY_CLIENT_ID=<id>; python3 -m scripts.capture_spotify
   "Al Green I'm Still in Love With You"`, then commit the two captured fixtures (catalog data only). Where the secret
   lives for good (`/srv/docker/.env` plus the compose environment) is decided when the provider is built.
7. gluetun: look at why the NAT-PMP refresh fails (`docker logs dj-gluetun-1 | grep 'port forwarding'`). It's yours; the
   code now survives a drop (S1-06).
