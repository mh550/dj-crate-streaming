# Progress log — run `dj-crate-streaming-2026-10-22-build` (branch `harness/dj-crate-streaming-2026-10-22-build`)

What this file is: the shared memory of the agent harness for this run. Each session appends one entry **at the top**
(newest first) when it finishes a feature: what it built, what it learned, what it asks. Nobody edits older entries.

How to read the run: `feature_list.json` in this directory is the build list, in priority and dependency order; a
session takes the first feature with `passes: false` whose `after` features pass, and may flip only its own `passes`.
Michael steers from `INBOX.md` on this branch (status line `run | pause | stop`; answers under `## Answers`); every
session reads it at startup. Policy: **build-only** (`.harness/config.sh`) and the brief in `brief.md`: nothing live,
no docker, no `/srv`, no network, no client UI, PRs only (open, never merge).

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
