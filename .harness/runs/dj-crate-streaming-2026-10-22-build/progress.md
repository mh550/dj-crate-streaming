# Progress log — run `dj-crate-streaming-2026-10-22-build` (branch `harness/dj-crate-streaming-2026-10-22-build`)

What this file is: the shared memory of the agent harness for this run. Each session appends one entry **at the top**
(newest first) when it finishes a feature: what it built, what it learned, what it asks. Nobody edits older entries.

How to read the run: `feature_list.json` in this directory is the build list, in priority and dependency order; a
session takes the first feature with `passes: false` whose `after` features pass, and may flip only its own `passes`.
Michael steers from `INBOX.md` on this branch (status line `run | pause | stop`; answers under `## Answers`); every
session reads it at startup. Policy: **build-only** (`.harness/config.sh`) and the brief in `brief.md`: nothing live,
no docker, no `/srv`, no network, no client UI, PRs only (open, never merge).

### 2026-10-23 05:10 · S2-06b · passes

- **Changed.** `sourcing/filer.py`: `AlbumIdentity`, `album_changes` (only differing fields; unknown year clears
  year/month/day, D51; no release clears `mb_albumid`/`mb_albumartistid`; `comp` only when true; a stray album-artist
  key or ID3 alias counts), `BeetsFiler.file(…, album=, on_tagged=)` records first, then `write_minimal`, then
  `beet import … --set dj_album=1`; `album=` without `on_tagged` is refused. `sourcing/fetch.py`: `album_identity`
  (kind `album` only) and a committed `tagged {json}` event. `deploy/beets.yaml`: `dj_album:1:` before `singleton:`.
  `scripts/tag_cleanup.restore_fields` (the reverse). New `requests.tracktotal` (migrated, set by `add_spotify`).
  `docs/worker.md` Filing, plan as-built. `fake_beet(fail_import=)`. Tests 2064 → 2093.
- **Verified.** Tests red first. Real beet 1.6.0 (offline, tmp library): album rows land at `Al Green/I'm Still in Love
  With You (1972)/01 - …` and `…/I'm Still in Love With You/09 - …`, plain row in `Singles`, `dj_album=1` in
  `item_attributes`. FLAC plus mp3/m4a/ogg (ffmpeg) tag tests; kill test: event committed when beets starts and
  survives a rollback. 10 mutations, each turns a test red. Opus review: 1 Important (tracktotal fell when the last
  track belonged to another request → `requests.tracktotal`) + 4 Minor (2 fixed test-first, 2 in the plan's "Not
  restored"). Subset 163 passed; full suite green, 2093 tests, 766 s.
- **Next session must know.** The filed file's record is the row's last `tagged` event starting with `{` before
  `filed`. Old requests have `tracktotal` NULL (falls back to the highest row track number).
- **Proposed change (S2-06b step 2).** It said "the request's row count" for tracktotal; built as the plan says
  (highest listed track number), since a count can fall below a track number.
- **Question for Michael.** Still D51 (from S2-06a): clear an unknown year, or take the first filed file's year?

### 2026-10-23 03:40 · S2-06a · passes

- **Changed.** New `docs/plans/2026-10-22-S2-album-tags.md` (Fields, Writer, When, Reverse, beets measurement, Out,
  Live steps, Review) and `tests/test_album_tags_plan_doc.py` (3 tests); pivot spec gains **D50** (the album path,
  your answer, not default) and **D51 *default*** (an album request without a year clears year/month/day on its
  files so they share one folder). No code. Tests 2061 → 2064.
- **Verified.** Doc test red first. Measured in scratch (no /srv; MusicBrainz pointed at a closed local port, so
  offline) on /usr/bin/beet 1.6.0: `import -q -s -m -W --set dj_album=1` with `dj_album:1:` before `singleton:` files
  at `Al Green/I'm Still in Love With You (1972)/01 - …`; `beet ls dj_album:1` lists exactly the flagged files; the
  import leaves them byte-identical; a plain import still goes to `Singles`. Also measured: the reverse (delattr,
  `modify -W -M … dj_album!`, `move -p` → Singles). Opus review: 1 Critical (event not committed before the write), 4
  Important, 8 Minor, all fixed in the plan text (`## Review`). Subset (plan doc + tag_cleanup) 26 passed; full suite
  green, 2064 tests, 761 s.
- **Next session (S2-06b) must know.** Follow the plan's `## Writer` order: compute old → log **and commit** the
  `tagged` event → `write_minimal` → `beet import --set dj_album=1`. The reverse needs a new
  `scripts.tag_cleanup.restore_fields` (one save, year before month/day, `null` → delattr).
- **Proposed changes (S2-06b steps).** `tracktotal` = highest `track_no` of all the request's rows, not the row count;
  a missing `mb_release_id` also clears `mb_albumid` and `mb_albumartistid`; `restore_fields` is the reverse, not
  `write_minimal(path, old)` (that leaves `ALBUM=`, `TRACKNUMBER=0`); m4a/ogg tag tests.
- **Question for Michael.** D51: OK to clear an unknown year (one folder), or should the first filed file's year
  become the request's year?

### 2026-10-23 02:45 · S2-05c · passes

- **Changed.** `sourcing/fetch.py`: `exclude=<usernames>` drops those peers' candidates right after `rank` (S1-06's
  retry too); "no acceptable candidate from another peer" when it removed one; pick event `per track: <basename>`.
  `sourcing/album_job.py`: attempts per row in order (own failure `folder 1: transcode (<basename>)` / `folder 2:
  <fetch reason>`, or the folder's cause when moved along); per-track fetches pass every failed folder's peer as
  `exclude`; a row with attempts that files nothing fails with `<attempts>; per track: <why>`, outcome `failed: …`.
  `docs/worker.md` `## Album jobs` + `album` purpose under Approvals; plan as-built. Tests 2049 → 2061.
- **Verified.** New tests red first (pick, then reason); 6 mutations (no exclude filter, no pick, no moved-along
  attempt, no rewrite, job passes no exclude, rejected switched row not per track) each turn 1–4 red; one survivor
  showed `| stalled` redundant (removed). Opus review: 2 important (a per-track fetch raising before fetch's `try`
  kept a stale reason; a row held in its switched folder lost its first attempt) + 3 minor, all fixed test-first.
  Full suite green, 2061, 753 s.
- **Next session must know.** A row failing an ordinary check in its switched folder ends there (no per-track fetch),
  both folders in its reason. Still open from S2-05b: a `_forget` that fails (slskd away) is not retried.
- **Questions for Michael.** None. Proposed changes: none.

### 2026-10-23 01:15 · S2-05b · passes

- **Changed.** `sourcing/album_job.py` `run` switches folders: triggers `FetchResult.again` (fetch no longer retries
  in planned mode), `start_timeout_s` (`ALBUM_START_TIMEOUT_S`=600; worker `album_start_timeout_s`, CLI env), a
  `DISTRUST` kind, or 2 failed rows per folder; the folder's unfiled records forgotten (remove=true), moved rows
  re-planned over the cached first search (`responses` now in the `req-<id>` cache, server side) + one fresh search
  with `plan_album(exclude=, like=, min_rows=1)`; one `switch` event per failed folder. `Verdict.kinds` →
  `FetchResult.kinds`; `album.folder_of`; fake slskd `stalled_peers`, `deleted`. Tests 2032 → 2049.
- **Verified.** New tests red first; 8 mutations (no distrust, failures 99, no start check, no forget, no exclude,
  held not moved, no planned `again`, no kinds) each turn 1–5 red. Opus review: 3 important fixed test-first (switch
  ignored same release → `like`; one row could never switch → `min_rows=1`, weak "never the failed folder" test
  rewritten; a refused fresh search aborted every row → falls back to the cached responses), 1 minor fixed (a held
  row now moves on a stall too). Full suite green, 2049, 759 s.
- **Next session (S2-05c) must know.** A row switches once; then (or with no folder found) it goes per track as an
  ordinary fetch with `prefer=None` and **no exclude yet**, so it may pick the distrusted peer again: 05c adds
  `exclude` and the attempt list in the reason (today the reason is the last attempt's). Known gap: a `_forget` that
  fails (slskd away) is not retried. The switch event is `#<id> folder 1 distrusted: transcode (<basename>); 8 rows →
  folder 2` (with `#<id>`, as `plan` has).
- **Proposed changes.** S2-05b step 1 case 2 says "A's first file" and "8 rows": the failed row switches too (the spec
  and S2-05c's cap test need that), so with the first file it is 9 rows; the test puts the transcode on A's second
  file (track 1 filed, untouched: 8 rows), which also gives step 3 a filed row to check. Questions: none.

### 2026-10-23 01:20 · S2-05a · passes

- **Changed.** New `sourcing/album_job.py`: `plan_request` (one `"<artist> <album>"` search, plan cached as preview
  `req-<id>` with `at` + `assign`, returns a `public` view, one `plan` event `#<id> folder 1: 9 of 9`),
  `approve_request` (one `album` approval per open row, planned file or None; ValueError while a row is
  sourcing/verify or an approval is `started`), `run` (claim, `fetch.in_library` per row, re-plan past
  `ALBUM_PLAN_MAX_AGE_S`=3600 (CLI env), one enqueue per peer, each row `fetch(planned=True, prefer=, enqueued=)`).
  `fetch.py`: planned mode (no search, no library ask, no enqueue), `in_library` lifted to module level.
  `Worker._spend` groups `album` approvals by `request_id`. Fake slskd gains `posts`/`searched`; `fake_beet`
  takes a per-file target. New `tests/test_album_job.py` (23). Tests 2009 → 2032.
- **Verified.** First red at import, then mutation checks (no grouping, planned search, planned enqueue, no
  library first, no re-plan, approve every row, no busy refusal): each turns 1–7 tests red. Opus review: 3
  important fixed test-first (5 tests seen red): don't enqueue rows that are ok, in flight or rejected at their own
  tier; forget a planned file its fetch didn't file and a refused POST's records; refuse re-approval while claimed.
  Subset (album_job, worker, fetch, approvals, fake_slskd, fetch_filing) 189 passed; full suite green, 2032, 716 s.
- **Next sessions must know.** The happy-path FLACs are per-length (`flac_bytes`, not `good_flac_bytes`: header_only
  checks each row's own duration). The restart case leaves rows the job hadn't reached `needs_source` (request
  `open`), as `recover_interrupted` does for one row; their queued transfers stay in slskd (gap noted in the plan,
  for S2-05b/c). Per-track rows already go through an ordinary fetch; S2-05c adds the caps and `exclude`.
- **Questions for Michael.** None. Proposed change: none.

### 2026-10-23 00:30 · S2-04 · passes

- **Changed.** New `sourcing/album.py` (pure): `plan_album(responses, rows, *, policy, listed_lengths)` → `AlbumPlan`
  (`primary`, `secondary`, `per_track`, `alternates`, `assignments()`), `FolderPick(username, directory, rows, score)`,
  `describe(plan, peers=False)` (`folder N`, `7 of 9`, row → basename; no peer, no directory). Folders are
  (peer, directory); rows map via `scorer.rank` per folder, greedy by score, one file per row. New
  `tests/test_album_plan.py` (23 tests: the 5 spec cases + review fixes). Plan: "As built (S2-04)" in the S2 plan.
  Tests 1986 → 2009.
- **Verified.** Tests seen red first (no module; then 5 review-fix tests red); mutation checks (no bitrate tie-break,
  MIN_FOLDER_ROWS=1, no release rule, file reuse, rejected files used) each turn a test red. `check.sh
  tests/test_album_plan.py tests/test_scorer.py` 56 passed; full suite green, 2009 tests, 704 s. Opus review: 0
  critical, 1 important (the secondary ranked same release over coverage, against the spec: fixed, coverage first),
  lows fixed: share-root files (`directory ""`), per-folder `fileCount`, peer/directory final tie-break, rows kept by
  position (not `id()`).
- **Next session (S2-05) must know.** Spec case 3 ("bitRate 1000 vs 900") is decided by a summed-bitrate tie-break
  after slot and speed: the scorer gives a lossless file's bitrate no points, so the scores tie. `listed_lengths` is
  `{track_no: seconds}`, but S2-03's `ReleaseTrack` has no length: add it (MB `track.length` ms → s) or pass None.
  `repr`/`as_dict` carry peer names, so a cached plan goes out only through `store.public`. The secondary can be the
  primary's own peer in another directory, so a start timeout must switch both.
- **Questions for Michael.** None. Proposed change: none to the feature list.

### 2026-10-22 23:40 · S2-03 · passes

- **Changed.** `sourcing/musicbrainz.py`: `MusicBrainz.release_search` / `release` (shared limiter + cache) and pure
  `match_release` → `ReleaseMatch(id, format, date, tracks)` (track count, then titles in order across media by
  `loose(base)` + version key, `asked_title` first; tie order Digital Media, CD, earliest date, no date last).
  `sourcing/requests.py` `match_request_release` (live rows only: not removed, newest per track_no; a matched
  request refills a re-seeded row from its stored release); `CrateStore.set_request_release` writes rows + release in
  one commit, `updated_at` untouched. `fetch.py`: verify gets the row's `mb_recording_id` (a copy upgrade: Navidrome's
  id first). `seed-spotify --musicbrainz` / `$MUSICBRAINZ_CACHE`. Plan notes under `## Schema`. Tests 1954 → 1986.
- **Verified.** Each new test seen red first; the step's subset (client, musicbrainz, fetch_filing, fetch, requests,
  sourcing_cli) 155 passed before the review fixes; full suite green, 1986 tests, 698 s. Opus review: 2 medium
  (a re-seeded row got no recording id / blocked any later match; the hard check vs digital-only recordings, see
  below) and 6 low; fixed test-first: live rows, one transaction, version key, OSError from the cache, asked_title,
  the copy-upgrade fallback test.
- **Next sessions must know.** An album track already owned by another request leaves a gap in track numbers, so
  that album gets no ids (soft check, documented in the plan). The rate limit is per process (worker + seed-spotify
  at once are not spaced against each other). S4-01's checklist: first live `seed-spotify <album> --musicbrainz`
  with `MUSICBRAINZ_CACHE` set, and check the `release` event.
- **Questions for Michael.** None blocking. Proposed change: the spec's tie order picks Digital Media first; if a
  digital release has recordings of its own with few AcoustID submissions, a correct CD rip would fail verify's hard
  check. MusicBrainz usually shares recordings across remasters, so I kept the spec; S2-05 could accept the recording
  of any release that matched one to one (or treat a mismatch with the same title key as a warning).

### 2026-10-22 23:50 · S2-02 · passes

- **Changed.** `sourcing/playlist_sources.py`: `Row.track_no`/`Row.year`; `rows_from_spotify` fills album, track_no,
  year (`releaseDate[:4]`, null → None) for an album entity, reads a track entity as one row; `load` refuses a track
  URL. New `sourcing/requests.py` `add_spotify(store, url, *, fetch, tier, default_tier)` + `canonical(url)` (no
  `?si=`, no `/intl-xx/`). `crates/store.py` `find_request(source)`; a queued row joining a request also gets album/year
  (COALESCE). `spotify_csv.URL` matches `track` too. `seed-spotify` prints `request <id>: Al Green – I'm Still in Love
  With You (9 rows)` for an album or track; playlists unchanged. Plan: S2-02 notes under `## Schema`. Tests 1933 → 1954.
- **Verified.** New tests seen red first (the review-fix batch: check.sh stops at the first failure, so one of those
  was seen red); subset of the 4 touched test files 108 passed; full suite green, 1954 tests, 693 s. Opus review: 2
  important (track URL made a 1-track playlist via import-playlist; a track already in another request made an empty
  request that stays `open`) + 5 minor, fixed test-first; kept the `sourcing/requests.py` name (the spec's).
- **Next sessions must know.** `track_no` is embed order across discs (no disc number): S2-03 must compare against
  MusicBrainz tracks in order across all media, not `position` within one medium. A request whose rows all belong to
  another request is not made; that request is returned. The **track embed shape is not captured**: code assumes
  `name`, `artists[{name}]`, `duration`, `uri` (as `track_lead` reads); `releaseDate` as a string or `{isoString}`.
  S4-01 should add "capture one track embed to `fixtures/`" to the checklist.
- **Questions for Michael.** None.

### 2026-10-22 23:05 · S2-01 · passes

- **Changed.** `crates/store.py`: `requests` table (kind CHECK album|playlist|track, no status column) and
  `external_wanted.request_id/track_no/mb_recording_id`, additive in `SCHEMA` + `_migrate`; `add_request`,
  `set_release_id`, `set_recording_id`, `request(id)` (rows = `wanted_row` dicts by track_no), `requests()` newest
  first, pure `request_status(rows)` + `REQUEST_STATUSES`; `add_external_wanted(..., request_id=, track_no=)`.
  Plan `docs/plans/2026-10-22-s2-album-requests.md` (Schema, Request status, Album job, Live steps). Tests 1906 → 1933
  (`tests/test_crates.py` +25, new `tests/test_s2_plan_doc.py` +2). Fixed a garbled comment on `REPLACEMENT_OPEN`.
- **Verified.** Each test seen red first; `check.sh tests/test_crates.py tests/test_s2_plan_doc.py` 65 passed; full
  suite green, 1933 tests, 690 s. Opus review of the diff: 3 medium findings fixed test-first (a failed row approved
  again or filed-but-unindexed counts as going → `approved`; a request never attaches a `removed` row), plan wording
  ("prefer" the same release) and the rollback caveat added.
- **Next sessions must know.** A row belongs to the **first** request that asks for it (`request_id` set only when
  NULL). Known gap in the plan: an import's `_reask` can supersede a failed row another request holds; S2-07/S3-01
  decide whether to re-link. `review` rows count as open (no status of their own). S4-01's rollback step must first
  spend unused `album` approvals (an older worker would run them per track). Migration race on two containers
  starting at once (existing pattern) is unchanged.
- **Questions for Michael.** None new (status words = initializer question 2).

### 2026-10-22 22:10 · initializer

**Scope.** Milestones S2 (album requests), S3 (request API) and S4 (checklist, whole-run review) of
`docs/specs/2026-10-22-downloads-and-requests.md`, as the brief says; S1 is in the base and is not redone.
**21 features**: S2 = 11 (S2-01 plan+table, S2-02, S2-03, S2-04, S2-05a/b/c, S2-06a plan, S2-06b, S2-07, S2-R1),
S3 = 8 (S3-01, S3-01b, S3-02, S3-03, S3-04, S3-05 docs, S3-06, S3-R1), S4 = 2 (S4-01 docs, S4-02 review).
Splits against the spec: S2-05 is three sessions (happy path, switching, caps and last resort: seven fake-slskd tests
would not fit one session); S2-06 is plan+measurement (S2-06a, reviewed before any tag code, as CLAUDE.md requires)
then code (S2-06b); S3-01's MusicBrainz-id bodies and the library marking are S3-01b. The spec's S3-03..S3-06 keep
their numbers. S1 ran 16–35 min per feature at $1.6–4.5 on Opus; these are sized the same (S2-05b is the risky one).

**`after`.** S2-01 `[]`; S3-01 `[S2-01]` (the brief's words; array order still puts every S2 feature first, so S3-01
runs only once S2 is done or stuck); S4-01 after every S2 and S3 feature; S2-06b after S2-06a and S2-05a; S2-07 after
S2-05c and S2-02; the reviews after their milestone. S2-R1 is Opus; S3-05 is Sonnet (docs only). S4-01 is Opus on
purpose: it is a live runbook with undo steps (S1-09's checklist needed 13 review fixes on Opus).

**Base.** `1eb4259` = `origin/harness/dj-crate-streaming-2026-10-22-fixes` (S1-01..S1-09, S1-R1, D48, D49) which
contains `origin/main` at `e4e806e` (`git merge-base --is-ancestor origin/main HEAD` → yes). Suite on the base: green,
1906 tests, 710 s. S1's PR (#27 per its retro) is open, not merged; PR #16 is not on main either (checklist step 1).
Reviews diff from `1eb4259`.

**Where things live (what S2–S4 touch)**
- `crates/store.py` (1222 lines): schema string at line ~36 (`external_wanted` ~63, `approvals` ~105 with `purpose`
  download|play-now, `previews` keyed by song_id ~109); additive `_migrate` at ~292 (the pattern for the `requests`
  table and the new columns; test model `tests/test_crates.py::test_store_migrates_old_external_wanted_table` ~174);
  `APPROVAL_PURPOSES` ~131 (add `album`); `approve(wanted_id, by, candidate, tier, purpose)` ~562 supersedes an
  earlier unused approval of the same row; `add_external_wanted` ~670 returns the existing id for a same artist/title
  row (so a re-run of a request adds no row) and `_insert_external` ~719 is the INSERT to extend; `set_preview` /
  `preview` ~545; `recover_interrupted` ~617; `external_for_playlist` ~912; `public(v)` ~224 strips what must not
  leave (apply it to every new payload); `log(playlist_id, song_id, kind, detail)` ~1197; `events(limit)` ~1218.
- `sourcing/fetch.py` (609 lines; read the module docstring first): `fetch(wanted_id, *, store, slskd, navidrome,
  reconciler, music_root, downloads_root, approve, tier, policy, download_timeout_s, poll_s, scan_timeout_s,
  verifier, filer, navidrome_db, lookup, prefer, trash_root, score_tier, provisional, sleep, retry_pause_s)`.
  Closures: `in_library()` ~386 (S1-07), `intent_for` ~462, `attempt(cand)` ~475 with inner `records()`/`download()`
  (forget completed records → `before` set → `slskd.enqueue(username, [{filename, size}])` → poll for the record
  whose id is new, S1-04), the S1-06 retry ~534, `rid`/`extra`/`asked_title` for the verifier ~550–560 (S2-03 sets
  `rid = row.get('mb_recording_id')` for non-copies), `finish` ~239. `TRANSFER_ERRORS` line 97. Planned mode
  (S2-05a) adds `planned=True` + `enqueued=<ids before the job's enqueue>` and skips search and enqueue.
- `sourcing/worker.py` (363 lines): `Worker(store, slskd, navidrome, reconciler, fetch_kwargs, fetcher=fetch, log)`,
  `self.common` = the fetch kwargs; `_spend(approvals, results)` ~267 claims each approval and calls
  `self.fetcher(wanted_id, approve=True, prefer=candidate, **extra, **self.common)`; `_tick` ~297 order: play-now,
  reconcile, rechecks, the rest of the approvals, replacements, placement, export. Album approvals (purpose `album`)
  are grouped by the rows' `request_id` and handed to `album_job.run` from `_spend`. Env for the CLI's `worker`
  (`WORKER_RECHECK_S`) is read in `sourcing/cli.py`; add `ALBUM_START_TIMEOUT_S`, `ALBUM_PLAN_MAX_AGE_S` there.
- `sourcing/slskd_client.py` (142 lines): `search`, `downloads(username=None)` (404 → none), `enqueue(username,
  files)` takes a list (one POST for a whole folder works already), `remove_download(username, id)` sends
  `?remove=true` (S1-04), `transfer_files` flattens the per-user shape; `SlskdError.status`.
- `sourcing/fake_slskd.py` (170 lines): `FakeSlskdServer(responses, downloads_dir, files, api_key='k', complete=True,
  fail_enqueue=False|set)`; `do_POST` on `/transfers/downloads/<user>` answers one record per file in the body;
  `seed_transfer(username, filename, state)` plants an old record; `transfers` is the list to inspect; `complete`
  is global (S2-05b's "one peer never starts" needs a per-peer form: extend the fake first, as S1-04 did).
- `sourcing/scorer.py`: `Wanted(artist, title, album, duration_s, year, …)`, `Candidate(username, filename, size,
  …, basename, extension, score, rejected, reasons)`, `parse_responses`, `score_candidate`, `rank(responses, wanted,
  policy)` sorts rejected last, `explain(cands, peers=False)`. `sourcing/album.py` (S2-04) ranks per folder with it.
- `sourcing/identity.py`: `parse_title(title, artist).base`, `loose(s)` (the "same song" fold), `lead_artist`.
  Title keys for the 1:1 release match (S2-03) and the planner are `loose(parse_title(...).base)`.
- `sourcing/verify.py`: `HARD_EVERY_TIER` line 233 (`recording` is a hard finding), `HARD_WHEN_STRICT` 234
  (`transcode`, `fake_24bit`, `fake_hires`, …); `Verdict.problems` entries carry the kind. S2-05b's distrust set.
- `sourcing/musicbrainz.py` (233 lines): `MusicBrainz(opener, sleep, clock, min_interval_s, retries, timeout,
  cache)`, `get(path, **query)` (cache, 404 → None, 503 backoff), `recording`, `isrc`, `search(artist, title)`
  (recordings). S2-03 adds `release_search` and `release`. The shared limiter is process-wide (`reset_shared_limiter`
  in tests). `tests/test_musicbrainz_client.py` has the stub-opener pattern.
- `sourcing/playlist_sources.py`: `Row(position, title, artist, duration_s, spotify_id, album, note, sep, isrc)`;
  `rows_from_spotify(entity)` reads `trackList[].title/subtitle/duration/uri`; `load(src, fetch=fetch_entity)`.
  `sourcing/spotify_csv.py`: `fetch_entity(url)` is the one network call (tests `monkeypatch.setattr(cli,
  'fetch_entity', …)`), `rows(entity)`, `track_lead`.
- `sourcing/import_playlist.py`: `match(client, Row, accept)`, `choose`, `import_playlist(name, rows, client,
  store, source, dry_run, merge, resolve, tier) -> Report`; `--merge` adopts a same-named playlist.
- `sourcing/filer.py` (178 lines): `BeetsFiler(config, library, beet)`, `file(folder, log, *, names=…)` runs
  `beet import -q -s -m -W -l <log> <folder>` and `fill_missing_tags` (artist/title only); `scripts/tag_cleanup.py`
  `write_minimal(path, changes)` line 73 is the only tag writer allowed (M2 trap). `deploy/beets.yaml` `paths:`
  has `default`, `comp`, `singleton: $artist/Singles/$title`; a query key (`dj_album:1:`) must come before
  `singleton:` (beets takes the first matching query). `tests/helpers.py::fake_beet` is the stand-in `beet`;
  `tests/test_filer.py` drives it. `/usr/bin/beet` is beets 1.6.0 on this box (python 3.12): S2-06a measures with a
  scratch `BEETSDIR` and `directory:`, never `/srv`.
- `crates/service.py` (539 lines): `Config.from_env`, `CrateApp(cfg, policy, store, …)`, the HTTP router `_route`
  ~404 (error mapping) and `_api(method, parts, query)` ~431 (add routes beside `wanted`); `preview` ~216 and
  `approve` ~233 for one row (the `_lock`, `pick_token`, `_not_in_progress` 404/409 wording to reuse). Tests:
  `tests/test_service.py` `svc` fixture (`Config(subsonic_url=fake.url, username='demo', password='demo',
  db_path=':memory:', port=0)`, `CrateApp(cfg, store=CrateStore())`, `get`/`post` helpers).
- `sourcing/cli.py` (333 lines): argparse subcommands at ~113 (`rank`, `verify`, `fetch`, `worker`, `seed-spotify`
  ~151/~226, `import-playlist`, `retier`); `add_slskd_args`, `_fetch_env`. `tests/test_sourcing_cli.py` `_env`.
- `crates/cli.py`: `wanted reopen` (S1-08) is the dry-run-by-default model.
- Tests to copy from: `tests/test_fetch.py` (`world`, `run`, `header_only`, `new_song`, `not_in_library`,
  `good_flac_bytes`, `RESPONSES`), `tests/test_worker.py` (`worker(world, srv)`), `tests/test_fetch_filing.py`
  (`fetched(...)` captures verifier kwargs), `tests/test_fake_slskd.py`, `tests/test_playlist_sources.py`,
  `tests/test_crates.py`, `tests/test_approvals.py`, `tests/test_monitoring_doc.py` (a doc test).
- Fixtures (never invent a shape; copy a dict and change values): `search_responses.sample.json` (slskd responses,
  8 peers), `spotify_embed_album_al-green-still-in-love.json` (`type: album`, `name`, `subtitle: Al Green`,
  **`releaseDate: null`** — the year must be allowed to be None; MusicBrainz gives it), `spotify_embed_tea-tent-1.json`
  (playlist), `musicbrainz_release_search_al-green.json` (10 releases: 9-track CD `3c9a52ee…` 1993, CD `15e4ea1a`
  2009, digital `095b1ca3…` 2019-12-20 and `5ee0b926…` undated, vinyls 1972/2009/2022, an 11-track CD and an 18-track
  one), `musicbrainz_release_al-green-still-in-love.json` (the CD `3c9a52ee…`, 9 tracks with `recording.id`, track
  `length` ms; track 1 `cdac1a50-8ba6-4edd-8137-618928580d38` 195733, track 9 `83f06455…`),
  `musicbrainz_search.sample.json`, `musicbrainz_recording.docs-example.json`, `acoustid_lookup.docs-example.json`.
  Not captured (don't depend on it): the enqueue response body, `/users/*`, slskd's transfer listing order.

**Gotchas**
- Every feature starts with a failing test on the current tree; run the touched test files while iterating
  (`.harness/check.sh tests/test_album_job.py`), the full suite once before `passes` (1906 tests, ~11–12 min; `-x`
  stops at the first failure). `git add` files by name, never `-A`; `git show --stat HEAD` before pushing.
- Peer names (`username`), absolute library paths and API keys never reach a reason, an event, a plan, an API
  payload or a doc: label folders `folder 1`, `folder 2`; `store.public` on every response; a test per payload.
- D7: nothing is enqueued without an approval; `album` approvals are Michael's `approve` (HTTP or CLI). A preview or
  `plan_request` may *search* slskd (as today's preview does) but never POSTs a transfer.
- Nothing live: no `docker`, `scripts/live-run.sh`, `scripts/deploy.sh`, `scripts/live-check.sh`, no `/srv`, no
  network (`.harness/check.sh` unsets the live credentials and points every path into scratch; keep new env reads
  defaulting that way). `scripts/capture_spotify.py` (S3-06) is tested with a stub and never run.
- Decisions: D49 is the highest taken (this branch); `origin/main` and the SoulSync branch stop at D47. A new
  decision that is Michael's → `D<n> *default*` at the **end** of the table in
  `docs/specs/2026-10-17-amperfy-pivot.md`, after `git fetch -q` and a grep of `origin/main`,
  `origin/harness/dj-soulsync-review-2026-10-22` and this branch for the highest `| D`. The album path (S2-06a) is
  Michael's answer of 2026-10-22, recorded as `D<n>` **without** *default*.
- The SoulSync review (`origin/harness/dj-soulsync-review-2026-10-22`, `docs/research/2026-10-22-soulsync/`,
  not on this branch) is context only: its spec deltas (pair S1-07 on the MB id, maximum matching, measured speed,
  poll the global transfer list, reuse an existing album folder's identity, request status words, 429 stop, capture
  list) are **not** adopted unless the spec or an INBOX answer says so. Two cheap ones are in the steps because they
  cost nothing: `spotify:<kind>:<id>` URIs (S3-01) and the 429 stop (S3-06); the status words (S2-01) are ours too.
- Sessions are sequential, but `sourcing/fetch.py`, `sourcing/album_job.py`, `crates/store.py` and
  `sourcing/requests.py` are edited by several features: read them fresh each session.
- `tests/conftest.py` sets `CRATES_OWNER=comment`; the `world` fixture's library already holds Chic — Good Times,
  so album tests use `not_in_library` or the Al Green titles.
- beets measurement (S2-06a): `beet -c <scratch yaml>` with `BEETSDIR` in scratch; `--set dj_album=1` on `import -s`
  sets a flexible field on the items; the path-format query `dj_album:1:` is matched in yaml order, so it goes
  before `singleton:`. If it does not take, keep `Singles`, say so in the plan and the checklist, don't force it.

**Docs the run touches**: `docs/plans/2026-10-22-s2-album-requests.md` (new, S2-01), `docs/plans/2026-10-22-S2-album-tags.md`
(new, S2-06a), `docs/api.md` (new, S3-05), `docs/worker.md` (`## Album jobs`, `## Filing`, `## Approvals`),
`docs/architecture.md` §2 §3 §4(e), `docs/hard-won-facts.md`, `docs/next-todos.md` State, the spec's S2/S3/S4
headers, the pivot spec (D50+), `docs/plans/2026-10-22-downloads-checklist.md` sections 4, 6 and the captures (S4-01),
`docs/plans/2026-10-22-morning-checklist.md` (a link; its "PR #16" line is S1-09's, don't duplicate).

**Questions for Michael (defaults taken; answer in INBOX.md to change any)**
1. **Each album row is filed as it lands** (today's behaviour), so Navidrome may show a half album for a while;
   the alternative (hold verified files in `.staging` until the job ends) is not built. Recorded by S2-05a as a
   `D<n> *default*` only if a session finds it changes code; otherwise it stays this note.
2. **Request status words** `open | approved | partly | done | failed`, derived from the rows (S2-01's plan).
3. **A folder is distrusted on one `transcode`/`fake_24bit`/`fake_hires`/`recording` finding or on 2 failures of any
   kind**; an ordinary finding (`duration`, `truncated`) fails that row only (spec S2-05, taken literally).
4. **The album path** is built as you answered (`$albumartist/$album ($year)/$track - $title`, D<n>, not a default)
   **only if** beets 1.6.0 honours the `--set` field and the query path for `-s` imports in S2-06a's scratch
   measurement; otherwise the tags are written and the path stays `Singles` until you say otherwise.
5. **Question B (client UI)** stays open: S3 is server-only; `docs/api.md` is what a client would use.
6. **Spotify as a catalog provider** waits for the S3-06 capture you run (checklist section 6); where the client
   secret lives for good is not decided.
