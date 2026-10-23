# Progress log — run `dj-crate-streaming-2026-10-22-build` (branch `harness/dj-crate-streaming-2026-10-22-build`)

What this file is: the shared memory of the agent harness for this run. Each session appends one entry **at the top**
(newest first) when it finishes a feature: what it built, what it learned, what it asks. Nobody edits older entries.

How to read the run: `feature_list.json` in this directory is the build list, in priority and dependency order; a
session takes the first feature with `passes: false` whose `after` features pass, and may flip only its own `passes`.
Michael steers from `INBOX.md` on this branch (status line `run | pause | stop`; answers under `## Answers`); every
session reads it at startup. Policy: **build-only** (`.harness/config.sh`) and the brief in `brief.md`: nothing live,
no docker, no `/srv`, no network, no client UI, PRs only (open, never merge).

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
