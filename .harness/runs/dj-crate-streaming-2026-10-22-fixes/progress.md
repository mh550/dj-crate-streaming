# Progress log — run `dj-crate-streaming-2026-10-22-fixes` (branch `harness/dj-crate-streaming-2026-10-22-fixes`)

What this file is: the shared memory of the agent harness for this run. Each session appends one entry **at the top**
(newest first) when it finishes a feature: what it built, what it learned, what it asks. Nobody edits older entries.

How to read the run: `feature_list.json` in this directory is the build list, in priority and dependency order; a
session takes the first feature with `passes: false` whose `after` features pass, and may flip only its own `passes`.
Michael steers from `INBOX.md` on this branch (status line `run | pause | stop`; answers under `## Answers`); every
session reads it at startup. Policy: **build-only** (`.harness/config.sh`) and the brief in `brief.md`: nothing live,
no docker, no `/srv`, no network, no client UI, PRs only.

### 2026-10-22 18:05 · S1-04 · passes

- **Changed:** `sourcing/fake_slskd.py`: a transfer DELETE acts as slskd 0.26.1 does. Without `?remove=true` it cancels an `InProgress` record (`Completed, Cancelled`) and keeps every record; with `?remove=true` the record goes; both answer 204 with no body; an unknown id is 404. `seed_transfer(..., transfer_id=)`, and a user's transfers are listed sorted by id (the real order isn't captured). `sourcing/slskd_client.py` `remove_download` sends `?remove=true`, and a 404 means already gone. `sourcing/fetch.py` records the ids of this file's transfers right before the enqueue and follows only a new id; it no longer uses `mine[-1]` or the enqueue response. `docs/hard-won-facts.md` gets the slskd fact.
- **Tests:** 1801 → 1806. `tests/test_fake_slskd.py` +3: plain DELETE keeps, unknown id 404, order by id; the remove case now asserts the record is gone. `tests/test_fetch.py` +2: a `~stale` `Errored` retry ends `ok`, one enqueue, stale record forgotten; this failed first with `download ended: Completed, Errored`. Two surviving stale `Succeeded` records (`!stale`, `~stale`) with `complete=False` end `download timed out`.
- **Verified:** mutation checks. Without the new-id filter, the `Succeeded` test fails whether fetch reads `mine[0]` or `mine[-1]`. `test_fetch.py`, `test_fake_slskd.py` and `test_worker.py`: 90 passed. Full `check.sh`: green in 661 s, 1806 tests.
- **Opus review:** no blocking bugs. **Proposed change (S1-06 or S2-05):** the forget loop forgets only `Completed*` records. A still-running transfer of the same file from a timed-out or killed attempt goes into `before`. If slskd refuses the duplicate enqueue, the retry ends `download timed out`; it never files a wrong file. Fix: cancel and forget non-terminal records of the file too (`remove=true`), once slskd's handling of a duplicate enqueue is known. Low: with two new records for one enqueue, fetch reads the lowest id.
- **Next:** S1-05. No questions for Michael.

### 2026-10-22 20:05 · S1-03 · passes

- **Changed:** `sourcing/fetch.py` `finish`: when Navidrome lists the filed file under a title that can't be the asked song (`asked_title or title`), the row becomes `review` "filed <X> as <rel>, asked for <Y>". It keeps its names and `library_song_id` (None), gets a `wrong_song` event (path + song id), no rename, no proposals, no placement. This applies to the first filing, the `verify` re-check, play-now and crate copy upgrades (no replacement starts). `RETRYABLE_REVIEW` (`crates/store.py`, `web/app.js`) accepts the reason; `filed_path` is None for it.
- **Deviation from step 2 ("compare `loose` bases"):** the comparison is the new `identity.can_be_song`: one `loose` base contains the other. This is S1-02's rule, now shared by `verify` and `fetch`. An Opus review showed that equality sends real same-song pairs to `review`: an old copy titled `02 Can You Feel It`, an unbracketed `feat. Bob`, `- From "Movie"`. ext-74 is still caught.
- **Tests:** 1781 → 1801 (`tests/test_fetch.py` +7: ext-74, same song ×3 (spelling, `(Live)`, `feat.`), re-check, play-now, crate copy; `tests/test_identity.py` +10; `tests/test_m8_followup.py` +3). The ext-74 test failed first (`'ok' != 'review'`). Full `check.sh`: green in 657 s, 1801 tests.
- **Decision D48 *default*** (pivot spec): a wrong-song review is retryable. Approving downloads again; the wrong file stays as its own song. **Michael:** keep it retryable, or require `wanted reopen` first? **S1-08 takes D49.**
- **Known limits / proposed changes:** (1) The retry doesn't remember the rejected file. If AcoustID isn't confident, the same peer's mislabelled file can be downloaded and filed again, each time as an extra copy. Proposed: a later feature (S1-R1 or S1-08) rejects the `wrong_song` pick in `rank`. (2) `play_now` refuses this review row with "pick a version first", which is the wrong wording (Minor; for S1-R1). (3) Containment is lenient: asked `Love` vs filed `Lovely Day` still renames (today's behaviour).
- **Next:** S1-04.

### 2026-10-22 18:45 · S1-02 · passes

- **Changed:** `sourcing/verify.py`. `verify(..., asked_title=)` is passed through to `_acoustid_check`. With no recording id, a confident result (a recording scoring at least `ACOUSTID_CONFIDENT` = 0.8) where no returned recording can be the asked song is the hard `recording` finding "AcoustID says this is <title>, not <asked>". `m["acoustid"]["asked"]` records the asked title. `sourcing/fetch.py` passes `asked_title = row.get("asked_title") or row["title"]` whenever a lookup is configured.
- **Deviation from the step ("equals"):** "can be the asked song" means one `loose(parse_title(t).base)` contains the other, not that they are equal. An Opus review showed that equality hard-rejects the same song in common forms: `Song ft. X`, `Song (Acoustic)` (a label `parse_title` doesn't know), and a Navidrome title such as `Al Green - Love and Happiness` or `01 Love and Happiness`. A hard reject throws a good download away, while a miss only keeps today's behaviour. ext-74 still fails. Any returned recording, at any score, can clear the check (the spec's "no returned recording").
- **Tests:** 1774 → 1781 (6 new in `tests/test_acoustid.py`, 1 new in `tests/test_fetch_filing.py`; two `kw ==` asserts there updated). The ext-74 test failed first with `TypeError: unexpected keyword 'asked_title'`.
- **Verified:** full `check.sh` green in 654 s, 1781 tests.
- **Known limits:** `Song, Pt. 1` vs `Song, Part 1` and a title in another script (Japanese vs romanised) still give the hard finding when AcoustID's titles differ that way.
- **Next:** S1-03. No questions for Michael.

### 2026-10-22 17:50 · S1-01 · passes

- **Changed:** `sourcing/scorer.py`. New helpers `title_slot(basename)` (shared with `name_match`) and `slot_names_another_song`. A candidate whose title slot's song differs from the wanted title's song is rejected as `title slot is <slot>`, score 0. Songs are compared as `loose` base titles, with feat./ft. credits and labels ignored; D26 version rules are unchanged.
- **Review findings fixed:** an Opus review of the first diff found that `- 09. Title`, the en dash `– 09 –` and underscore names bypassed the rule. It also found false rejects for an unbracketed `feat.` and for compilation slots (`Chic - Good Times`, `Good Times - Chic & Nile Rodgers`, `VA_Disco_Hits_07_Chic_Good_Times`). The slot regex now also takes `–` and `NN. `. Any ` - ` part of the slot, or the slot without the lead artist in front, may be the title.
- **Tests:** 1757 → 1774 (17 new in `tests/test_scorer.py`). Every existing scorer, version, fetch and identity test passes unchanged.
- **Verified:** `python3 -m sourcing.cli rank --fixture <scratch>/ext74.json --artist 'Al Green' --title "I'm Still In Love With You" --duration 196` prints `✗ title slot is One of These Good Old Days` and exits 3 (no acceptable pick). Full `check.sh`: green in 651 s, 1774 tests.
- **Known limits (left as they are):** strict key equality still rejects slots like `Lovin' You` for "Loving You" and `Satisfaction` for "(I Can't Get No) Satisfaction". A slot after a bare `- 09 Title` (space only) isn't read as a slot, because that would collide with numeric titles ("Nena - 99 Luftballons").
- **Next:** S1-02 (`verify._acoustid_check`). No questions for Michael.

### 2026-10-22 17:05 · initializer

**Scope.** Milestone S1 of `docs/specs/2026-10-22-downloads-and-requests.md` (the eight download fixes from the Al
Green attempts), a closing review, and the S1 live checklist: **10 features, one milestone**: S1-01…S1-08 (build),
S1-R1 (review + simplify), S1-09 (docs: `docs/plans/2026-10-22-downloads-checklist.md`). S2–S4 are the later run
`dj-crate-streaming-2026-10-22-build`. No plan file: the spec is the plan (nothing in S1 trashes files or writes tags).

**Base.** `307d62b` = the run's start (`94fd950`: `main@5b3e370` + PR #16's four hotfix patches + the spec) **merged
with `origin/main` at `e4e806e`** (R6–R8 of the 10-21 run, D47, the 2026-10-22 morning checklist). The merge was
clean; the suite on the merged tree is in this entry's last line. Why: R6-02 changed `strip_trackno` and
`parse_filename` (now `(basename, artist, wanted)`) and R8-02 touched `fetch.py`, the exact lines S1 edits, and the
milestone verify merges `origin/main` anyway. PR #16 itself is still **not** on `main` (`git merge-base
--is-ancestor 59c6f6a origin/main` → 1); the checklist's step 1 (S1-09) is about that.

**Where things live (what S1 touches)**
- `sourcing/scorer.py`: `name_match` already computes the title slot (`nums`/`slot`, the words after the last
  ` - NN - ` or `_NN_`); `score_candidate` parses versions with `parse_filename(c.basename, w.artist, w.title)` →
  `Title` (`base`, `label`, `kinds`, `key`). `rank` sorts rejected last. `explain(peers=False)` is what reaches events.
- `sourcing/identity.py`: `parse_title`, `parse_filename`, `strip_trackno(s, wanted)`, `loose` (the text fold for
  "same song": accents, punctuation, `&`→`and`), `song_key`. A **song** is `loose(Title.base)`; `Title.key` is the
  **version** (kinds + credits). The spec's "song key" in S1-01/02/03 means the base title, labels ignored.
- `sourcing/verify.py`: `verify(path, expected, tier=, reference=, recording_id=, lookup=, intent=, listed_length_s=)`
  → `Verdict(ok, problems, info, warnings, measurements)`; `_acoustid_check` (line ~387) is the one to extend;
  `HARD_EVERY_TIER` already holds `recording`. `lookup(path) -> [{"id","title","score","acoustid"}]` is
  `sourcing.acoustid.parse`'s shape (best score first). AcoustID "confident" = 0.8 (`docs/identity.md` line 122).
- `sourcing/fetch.py` (504 lines; read the module docstring): status gates → `slskd.search` → `rank` → `prefer` →
  intent → forget/enqueue/poll (`mine[-1]`, the S1-04 bug) → `verifier(...)` → staging → `filer.file` → `finish`
  (`locate_in_navidrome`, `set_wanted_names` = the S1-03 rename, then `ok`/provisional/replacement). Row dicts come
  from `store.find_wanted`: external rows carry `asked_artist`, `asked_title`, `library_song_id`, `provisional`,
  `playlist_id`, `position`, `album`, `duration`, `year`. `copy_of(row)` is None for a plain external row.
- `sourcing/slskd_client.py` (93 lines): `_req` builds every request; `downloads()` already maps a 404 to no
  transfers; `remove_download` is the one missing `?remove=true`. `transfer_files` flattens the per-user shape.
- `sourcing/fake_slskd.py`: `FakeSlskdServer(responses, downloads_dir, files, complete=, fail_enqueue=)`,
  `seed_transfer`, `empty_reads`; **`do_DELETE` matches `self.path` including the query string**, so
  `…/<id>?remove=true` falls through to the search branch today: split the query first (S1-04).
- `sourcing/import_playlist.py`: `match(client, Row, accept=frozenset()) -> Match(status, song_id, how, title, why)`;
  `choose` is the pure part. `Row` is `sourcing.playlist_sources.Row(position, title, artist, duration_s, album=…)`.
  No import cycle with fetch (import_playlist never imports fetch).
- `crates/store.py` (1109 lines): `external_wanted` columns in the `CREATE TABLE` at line ~63 and the additive
  `_migrate` at ~290; `set_wanted_names` (the `renamed` event), `set_library_song`, `set_external_song`,
  `set_wanted_status`, `log(playlist_id, song_id, kind, detail)`, `events`; `RETRYABLE_REVIEW` / `filed_path`
  (reason regexes, mirrored in `web/app.js` ~125); `placements` table (deleting rows re-arms placement, D44).
- `crates/cli.py`: argparse, `wanted` has only `--json` today; `imported migrate [--apply]` is the dry-run pattern.
- `crates/service.py` `preview`/`approve`: the crates container calls `fetch(..., approve=False)`; the worker
  (`sourcing/worker.py` `_spend`) calls `fetch(wanted_id, approve=True, prefer=candidate, **common)` and records
  `r.approval_result or f"{status}: {reason}"`; its `except Exception` writes `TypeName: message` as the outcome.
- Tests: `tests/test_fetch.py` (`world` fixture: fake Navidrome `FakeSubsonicServer`, in-memory `CrateStore`,
  `FakeSlskdServer`, `fake_beet` filer, `header_only` verifier, `new_song` to make Navidrome "find" the filed file),
  `tests/test_fetch_filing.py` (`fetched(...)` captures the verifier's kwargs), `tests/test_fake_slskd.py`,
  `tests/test_scorer.py` (`_named(...)` builds candidates from basenames; the ext-74 test from the hotfix is at
  line 81), `tests/helpers.py` (`load_responses`, `make_flac`, `beets_items_db`, `fake_beet`).
- Fixtures for S1: `fixtures/search_responses.sample.json` (8 peers, slskd response shape: copy it, never invent
  keys), `fixtures/musicbrainz_release_al-green-still-in-love.json` (track 1 `cdac1a50-…` 195.7 s, track 9
  `83f06455-…` 195.6 s), `fixtures/spotify_embed_album_al-green-still-in-love.json` (9 tracks, "Oh ,Pretty Woman"),
  `fixtures/acoustid_lookup.docs-example.json` (raw AcoustID shape; `acoustid.parse` flattens it).

**Gotchas**
- Every feature starts with a failing test on the merged tree; run the touched test files while iterating
  (`.harness/check.sh tests/test_fetch.py`), the full suite once before `passes` (about 1,750 tests, 10–11 min,
  `-x`: it stops at the first failure).
- `git add` files by name; never `-A` (scratch sweeps in). `git show --stat HEAD` before pushing.
- Peer names (`username`), absolute library paths and the API key never reach a reason, an event, an API payload or a
  doc (`store.public`, `explain(peers=False)`, `test_approved_event_never_names_the_peer`). New reason strings:
  write `<peer>` literally.
- Don't depend on an slskd shape that isn't captured: the enqueue response, `/users/*`, the order transfers are
  listed in. S1-04 makes the fake sort by id for that reason.
- `tests/conftest.py` sets `CRATES_OWNER=comment` and the legacy policy file; the suite's env (`.harness/check.sh`)
  points every path into scratch and unsets the live credentials. Keep it that way in new tests.
- Several features edit `sourcing/fetch.py`; sessions are sequential, so no conflicts, but read the file fresh each
  session (S1-04 and S1-06 reshape the download loop; S1-R1 simplifies it).
- A new decision that is Michael's: the simplest reversible default, recorded in
  `docs/specs/2026-10-17-amperfy-pivot.md` as `D<n> *default*` at the **end** of the table. D47 is taken on
  `origin/main` (the identity picker); this branch has it since the merge. Another run (`harness/dj-soulsync-review-2026-10-22`)
  is active in parallel: before numbering, `git fetch -q` and check `origin/main` and that branch for the highest D.
- Nothing in this run writes to the live box. No `docker`, no `scripts/live-run.sh`, no `scripts/deploy.sh`, no
  `/srv`, no network; the fixtures are enough. S1-09 verifies commands with `--help` only.

**Docs the milestone touches** (S1-R1 and S1-09): `docs/worker.md` "Approvals" (+ a "Reopen" paragraph),
`docs/architecture.md` §4 and §7, `docs/hard-won-facts.md` (slskd 0.26.1 DELETE semantics; AcoustID same-length
songs), `docs/next-todos.md` State, the spec's S1 header, the pivot spec (one `D<n> *default*` from S1-08),
`docs/plans/2026-10-22-downloads-checklist.md` (new), `docs/plans/2026-10-22-morning-checklist.md` (one line before
section 4).

**Decisions taken by default (Michael: answer in INBOX.md to change any)**
1. **S1-08 reopen also resets placement** (`D<n> *default*`, recorded by S1-08): `wanted reopen --apply` deletes the
   row's `placements` rows so the right file is placed at its Spotify position when it arrives; the wrong song's
   playlist entry is left where it is (no playlist edit; the N1 cleanup or you remove it). Alternative: leave the
   placement `done`, so the right file is never placed automatically.
2. **S1-03's review row is retryable**: approving a "filed <X> as <rel>, asked for <Y>" row is a fresh download
   attempt (S1-01/02 now refuse the wrong song); the wrong file stays in the library as its own song. Alternative:
   require `wanted reopen` first.
3. **S1-07 runs in previews too**: a `Preview` from the web client that finds the song in the library marks the row
   `ok` without a download (`wanted reopen` reverses it). Alternative: only on approval.
4. **S1-06 retries once, on transfer end states and 5xx/connection errors only**: our own `download timed out`, a
   4xx, and every verify finding keep today's one-attempt behaviour.
5. **S1-05 error text**: `slskd <METHOD> <endpoint with <peer>/<id> placeholders>: HTTP <code>` or `: <reason>`.

**Questions that are not decisions**
- PR #16 (the hotfix) is not on `main`; this branch carries its commits, so the S1 PR will show them too. Merge #16
  first (checklist step 1), then the S1 PR.
- `origin/main` was merged into this branch at the start (`307d62b`); if the harness's milestone verify merges
  again it will be a no-op unless `main` moves.

Suite on the merged base `307d62b`: `.harness/check.sh` green, **1757 passed in 649 s** (10:48). No live command was run by the initializer: no docker, nothing read or written under /srv.
