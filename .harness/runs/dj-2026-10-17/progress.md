# Progress log — run `dj-2026-10-17` (branch `harness/dj-2026-10-17`)

What this file is: the shared memory of the agent harness for this run. Each session appends one entry **at the top**
(newest first) when it finishes a feature: what it built, what it learned, what it asks. Nobody edits older entries.

How to read the feature list: `.harness/runs/dj-2026-10-17/feature_list.json`. Array order is priority and dependency
order; the harness hands a session the first feature whose `passes` is false. A session may flip only its own
feature's `passes`, and only after `.harness/check.sh` is green on the committed tree. Milestones `N1`…`N5` map to
`docs/next-todos.md` items 1–4 plus docs; each milestone starts with a plan feature and ends with a review feature.

How Michael steers: edit `.harness/runs/dj-2026-10-17/INBOX.md` on this branch. First line `status: run | pause |
stop`; answers to the questions below go under `## Answers`. Every session reads it at startup.

---

### 2026-10-17 03:20 · N1-02 · passes
- **Changed:** new `scripts/duplicate_cleanup.py` (`build_plan`, `write_plan`, `render`, `main` with `plan` only; `--limit` ≥ 0, `--out` defaults to `$CLEANUP_DIR` or `/data/duplicate-cleanup`); `bit_rate` in the fake's `NAVIDROME_SCHEMA` and its INSERT; `duplicate_report.load` now closes its connection and orders by `artist, title, id` so the keeper is deterministic. New `tests/test_duplicate_cleanup.py` (13) and 1 fake test: 1,120 → 1,134, `.harness/check.sh` green (413 s).
- **Verified:** the s3/s9 group gives keeper s9 and extra s3 held by Disco Edits and Chicago 86; pl-1 → `[s1,s2,s9]`, pl-2 → `[s9,s4,s5]`. Also tested: both lossless and keeper missing on disk are held with no playlists entry; `--limit 1` through the CLI; two runs equal apart from `made_at`. The db bytes, the db directory listing, the fake's playlists, the music tree and Subsonic requests (none) are unchanged. A spy shows every sqlite connect is `mode=ro`; a read-write `open_ro` fails that test. An Opus review found 0 Critical, 2 Important (the read-only test proved nothing; reads from separate connections could raise `KeyError`) and 7 Minor issues; all are fixed.
- **Next session (N1-03):** s9 is added in the test fixture (`add_song`), not in `SAMPLE_SONGS`, so other tests are unaffected; reuse `lib`, `add_song` and `second_group`. `plan` never sets `keeper missing in Navidrome`, because `load()` returns present rows only (as the plan file says); repoint/trash must re-check it themselves. The fake's `getScanStatus` still needs `lastScan`.
- **New behaviour (safety):** re-running `plan` copies an existing `plan.json` to `plan-<its made_at>.json` (never overwritten, via `free_path`) before writing the new one atomically, so a hold you cleared by hand is not lost silently. Held groups are always listed; `--limit` counts only groups to act on.
- **Questions for Michael:** none new (D35 and D36 from N1-01 are still open).
- **Proposed changes:** N1-02 step 1 "add … a flac copy s9" should say "in the test fixture" (adding it to `SAMPLE_SONGS` would change every fake-based test).

### 2026-10-17 02:49 · N1-01 · passes
- **Changed:** new `docs/plans/2026-10-17-n1-duplicate-cleanup.md` (plan → repoint → trash design, plan JSON schema, holds, recompute rule, reverse logs, lock rule, safety-test table, tasks N1-02..05, staged live runbook); ledger rows `D35 *default*` and `D36 *default*` in `docs/specs/2026-10-17-amperfy-pivot.md`. Docs only; tests 1,120 → 1,120 (`.harness/check.sh` green, 406 s).
- **Verified:** facts recounted from `docs/duplicates-report.md` (102 groups, 115 extras, 59 in a playlist, 9 lossless beside a lossless keeper; the 9 held groups hold **14** extras, so the end state is 730 songs, not 716). An Opus reviewer checked the plan against the code: 1 Critical and 5 Important findings, all folded in. The Critical one: re-check `references()` right after each move and restore the file on a late reference, as `replace._trash` does. The Important ones: run check via `docker compose run --rm worker`, since the crates container has no `/srv/music`; export before each check; `repoint` waits for its scan (reuses `identity_backfill._scan`, `lastScan` must move); one-line reverse log per playlist; 730.
- **Next session (N1-02):** the plan's §plan says what `plan` writes. The fake needs `bit_rate` in `NAVIDROME_SCHEMA`; N1-03 also needs `lastScan` in the fake's `getScanStatus`.
- **Questions for Michael:** (1) **D35:** groups with two lossless copies (9 groups, 14 extras) are held, listed only, until you set `"hold": null` in `plan.json`. OK, or trash them too, as D31 literally says? (2) **D36:** `trash` runs only with the worker stopped (`docker compose stop worker`, it takes `worker.lock`); `plan` and `repoint` run beside it. OK?
- **Proposed changes:** N1-03 step "reverse log … the after list is the one read back" → `after` = expected `_remap`, written before the call (`rewrite`'s readback already guarantees equality); add "waits for its scan (`lastScan` moves)". N1-04 add: re-check `references()` after the move and `restore` on a hit; scan check before every move; already-gone checked before the recompute; `forget` on already-gone only when no trash-log line names it; keeper ≠ extra (`samefile`); refuse an extra in use by an unfinished approval. N1-05 runbook: "check" = export + check in the worker image.

---

## 2026-10-17 initializer (Fable) — feature list written

**Features per milestone:** N1 duplicate cleanup 5 · N2 imported marker 4 · N3 vanished playlist 3 · N4 placement 5 ·
N5 docs + whole-run review 2 = **19 features**. Nothing is built yet. Suite at start: 1,120 passed in 410 s
(`.harness/check.sh`, cached per code tree by `.harness/init.sh`).

### What a worker must know about the code

**Where things live**
- `crates/store.py` (881 lines): `SCHEMA` string at the top creates every table with `CREATE TABLE IF NOT EXISTS`;
  `_migrate()` adds columns to old DBs. New tables go into `SCHEMA` (tests open `CrateStore()` in memory and
  `CrateStore(tmp_path/...)` on disk). `store.log(playlist_id, song_id, kind, detail)` is the events table; call
  `store.commit()` after writes. `imported_entries` (D13) and `external_wanted.playlist_id/position` are the hooks
  N2 and N4 build on. `in_flight(status, reason)` says which rows reconcile must not touch.
- `crates/playlist_edit.py` (187 lines): the only index editor. `checked_entries`, `rewrite(before, after)`,
  `repoint_everywhere(client, db, old, new) -> {name: result}`, `references(db, song_id)` (hidden rows included).
  Refusals are `EditRefused` subclasses: `PlaylistSkew`, `PlaylistChanged`, `NotEditable`, `NotOwned`, `StaleSlot`.
  `EditNotKept` means the write was sent and the readback differs. Reuse these; do not write `updatePlaylist` anywhere else.
- `crates/trash.py`: `move_to_trash(rel, music_root, trash_root, before=None) -> Path` writes the reverse `mv` line to
  `<trash>/<day>/MOVES.txt` *before* moving, never overwrites (`free_path`). `restore` puts a file back.
- `sourcing/replace.py`: the M8 resumable copy replacement. Read its docstring for the licence and step order; the
  cleanup (N1) does **not** reuse its jobs (they need a fingerprint `replaceable` licence that tag-based duplicate
  groups do not have), but it copies the step order and the "references empty before any move" rule.
- `scripts/dedupe_copies.py`: the M3 plan → repoint → trash pattern; its `remap(entries, replace)` is what the plan's
  `after` lists use; its `trash` refuses while `playlist_tracks` still holds a copy. Its `repoint` is pre-M8 (raw
  `update_playlist`); N1 must use `playlist_edit` instead.
- `scripts/duplicate_report.py`: `load(db) -> (rows, held)`, `duplicate_groups(rows)` (each group sorted best first
  by `keep_rank`: lossless, then bit rate, then `library_map._copy_rank`), `LOSSLESS` set. It SELECTs `bit_rate` from
  `media_file`.
- `crates/reconcile.py`: `Reconciler._run` is where N3 goes; the current branch `rep.errors.append(f"{c.name}: playlist
  no longer exists in Navidrome")` is the one to replace. `_untier` shows how in-flight rows are spared.
  `write_comment(client, pl, new)` is the one comment writer (readback, `CommentNotKept`).
- `sourcing/import_playlist.py`: `MARKER`, `is_imported`, `NameCollision`, `_rerun_comment`, `_write_comment_and_cache`
  are N2's targets; `import_playlist()` computes `matches`, `ordered`, `new_ids`, `pending` (rows that become wanted
  rows) and calls `store.mark_imported` — N4-02 records `import_order` right after the `pending` loop.
- `sourcing/fetch.py` `finish()` (inside `fetch`, around lines 176–260): the two sites where an external row becomes
  `ok` (`set_library_song` + `set_status("ok", done)`), and the provisional (play-now) branch. `sourcing/replace.py`
  `_settle` is the third `ok` site. N4's placement is state-driven so none of them needs a new call.
- `sourcing/worker.py` `Worker.tick`: play-now approvals → reconcile_due → re-checks → approvals → `advance_replacements`
  → `export_due`. N4-04 adds placement after replacements. `self.common` carries `navidrome_db`, `music_root`,
  `trash_root`, `filer`.
- `sourcing/worker.py` `hold_lock(path)` is the worker.lock flock (raises `WorkerRunning`); N1's trash step reuses it.
- `sourcing/filer.py` `BeetsFiler.forget(path)` runs `beet remove -f path:<abs>` and refuses while the file exists.
- `crates/cli.py` and `sourcing/cli.py`: argparse subcommands; `crates.service.Config.from_env()` resolves
  `SUBSONIC_URL/USER/PASS`, `CRATES_DB`, `NAVIDROME_DB`; `sourcing/cli.py:_fetch_env()` resolves `MUSIC_ROOT`,
  `TRASH_ROOT`, `NAVIDROME_DB`, the filer (only with `DJ_WORKER=1`).
- `deploy/compose.yml`: the worker container has `/srv/music` rw, `/srv/_trash` rw, `navidrome.db` ro, Navidrome
  credentials and `DJ_WORKER=1`; the crates container has no library mount. So `plan` and `repoint` can run in either,
  `trash` only in the worker image (`docker compose run --rm worker …` with the daemon stopped).

**Test fixtures and fakes**
- `subsonic/fake_server.py`: `FakeSubsonicServer(db_path=tmp_path/"navidrome.db")` mirrors its state into a
  navidrome.db (`FakeState.sync()`); `state.missing` hides songs (the hidden-row trap), `state.smart` marks smart
  playlists, `state.requests` logs every call. Sample data: songs s1–s5 (s3 = Marshall Jefferson "Move Your Body" mp3
  192 kbps, s4 = Mr. Fingers mp3 128 kbps), playlists pl-1 "Disco Edits" [s1,s2,s3], pl-2 "Chicago 86" [s3,s4,s5],
  pl-3 "Sunday Listening" [s2], owner "demo". tests/test_playlist_edit.py adds s9 (a flac copy of s3) — the natural
  duplicate group for N1 tests.
- **Gotcha:** the mirror's `media_file` has **no `bit_rate` column** (`NAVIDROME_SCHEMA` has id, path, title, artist,
  album, duration, suffix, size, missing, mbz_recording_id, album_artist, year). `duplicate_report.load` SELECTs
  `bit_rate`, so N1-02 must add it to the schema and the INSERT (from the song dict's `bitRate`).
- `tests/test_fetch.py::world` builds fake Navidrome + store + reconciler + fake beets filer + music/trash dirs under
  tmp_path; `tests/test_worker.py::worker(world, srv)` builds a Worker on it; `tests/test_replace.py` shows how to
  drive fetch → replacement → trash on the fakes. `tests/test_dedupe_copies.py` shows real ffmpeg-made files under
  tmp_path. `tests/helpers.py` has `make_audio`, `beets_items_db`, `fake_beet`.
- `tests/conftest.py` sets `CRATES_OWNER=comment` and a legacy four-tier policy for the whole suite; app-owner tests
  live in `tests/test_app_owner.py` (its `env` fixture sets owner app). Under the legacy policy `low` is lenient, so a
  play-now copy stays provisional in tests; under the live policy all tiers are one strict rule and a play-now copy
  ends `ok`.
- `.harness/check.sh` runs pytest with `-x` (stops at the first failure) and every path in scratch. Pass test files
  to it while iterating; the full suite is about 7 minutes, run it once before flipping `passes`.

**Gotchas**
- `git add` files by name; never `-A` (scratch files sweep in). Check `git show --stat HEAD` before pushing.
- Soulseek peer names and absolute library paths stay out of events the web client shows (`store.public`).
- `docs/duplicates-report.md` is a snapshot (102 groups, 115 extras, 59 extras in a playlist, 92 lossless keepers,
  9 extras lossless beside a lossless keeper); the tool must recompute from `navidrome.db` every run.
- Michael deleted 35 playlists on 2026-10-17 (D32), so "playlist no longer exists" rows exist live ("sockseek /
  clouds"): N3 will delete them on the first live reconcile after deploy. That is intended.
- Nothing tonight writes to the live box. Deploy, the `imported migrate --apply` comment write and the cleanup stages
  are morning steps for Michael (N5-01 writes the checklist).

### Decisions taken by default (Michael: answer in INBOX.md to change any)

1. **D35 — groups where two copies are lossless** (9 extras of 115): D31 says "ties: the properly filed path", but two
   lossless files are often different masters, so the plan **holds** them (listed in the report, not repointed or
   trashed) until you clear the hold in `plan.json`. Say "trash them too" to follow D31 literally.
2. **D36 — the trash step runs with the worker stopped**: it takes `worker.lock` so `beet remove` has one writer.
   `plan` and `repoint` run beside the daemon. Say "no, make the worker do it" for a replacement-job design instead.
3. **D37 — the import flag is a new table** `imported_playlists` in crates.db (not a column on `crates`); the
   `#imported` token is stripped from "Tea tent" and "shakori (Spotify)" by `crates.cli imported migrate --apply`,
   which is **a live comment write you run in the morning** (dry run first). OK?
4. **D38 — a vanished playlist's rows are deleted** (crate_tracks, crates, imported_entries, import_order), in-flight
   rows wait until finished, wanted rows keep their `playlist_id` as history. Say so if you would rather keep a
   tombstone.
5. **D39 — placement**: M9 Q1/Q2 defaults applied (insert after the nearest earlier Spotify neighbour still in the
   playlist, else before the next, else append; earlier appends are never moved); imported playlists only; worker
   step, 12 attempts then an event. Existing playlists get an `import_order` only when you re-run their import
   (item 5), so the first placements will happen after that re-run.

### Questions that are not decisions
- Item 1's live run needs `/srv/docker/crates/duplicate-cleanup/` (uid 1000, inside the existing `/data` mount): no
  new mount, nothing for root.
- Do you want the cleanup report also copied into `docs/` for review in the GitHub app? Default: it is written beside
  the plan under `/data/duplicate-cleanup/report.md`; copy it by hand.
