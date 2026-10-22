# R7: the identity picker (M9 §5a) — Implementation Plan

> REQUIRED SUB-SKILL: superpowers:executing-plans (inline) with superpowers:test-driven-development.
> **Nothing in R7 writes a library file.** The crates service writes one file, `identity-choices.json` in its own
> identity dir, and logs an event in crates.db. `identity_backfill apply --choices` is built and tested on fixtures,
> dry run only. The live apply stays Michael's (`docs/next-todos.md` item 6); its staged steps are below and go into
> the R8 morning checklist.

**Goal:** M9 §5a (`docs/specs/2026-10-17-m9-remaining-ownership.md`), R7 of `docs/specs/2026-10-21-guards-and-checks.md`.
Today a `search` row is written only when its whole class is named (`--classes search`), and an `ambiguous` or
`none` row only when someone types `"choose": "<mbid>"` into a 4,300-line JSON. After R7, Michael opens an
**Identity** tab on his phone. It has one row per file, with the file's tags, length and ▶, and the candidates with
length, release, disambiguation and a MusicBrainz link. He taps **Accept**, **Choose** or **Skip**. The taps land
in `identity-choices.json`. `apply --choices` merges them into the proposal rows, behind the same checks a hand
edit gets today.

**Decisions.** Q7 and Q8 take their defaults, recorded as **D47 *default*** in the pivot spec. Q7: `search` rows are
accepted one by one, and the class stays out of `--classes`' default. Q8: the only candidate on the file's own
album is pre-selected, and is written only after a click. Q9 (AcoustID key) has nothing to decide here: the picker
works with or without a key.

## Today (checked against `b261971`)

- `scripts/identity_backfill.py propose` writes `<out>/identity-proposal.json` (`PROPOSAL`) atomically
  (`_write_atomic`: tmp + `os.replace`). Live, `<out>` is `/data/identity` in the worker, which is
  `/srv/docker/crates/identity` on the host. The file is `{"created", "music_root", "counts": {cls: n},
  "proposals": [asdict(Proposal)]}`. Each row has:
  - `path`: relative to the music root, posix. It is also Navidrome's `media_file.path`.
  - `cls`: one of `CLASSES`.
  - `write`: `{mb_trackid?, mb_workid?, acoustid_id?}`.
  - `recording`, `title`, `length_s`: the pick, on `search`/`isrc`/`acoustid`/`confirmed` rows.
  - `why`.
  - `candidates`: mbids, on `ambiguous` rows and on `none` rows with "near" recordings.
  - `accept`, `size`, `mtime_ns`, `skip`.
  - `file`: `FileFacts.tags()`, i.e. artist, title, album, length_s, isrc, version_tag, mb_trackid, mb_workid,
    acoustid_id.
  - `candidate_details`: `_detail` = `{id, title, length_s, artist, release (the first release only),
    disambiguation}`.

  A `search` row has **no** `candidates` and no `candidate_details`. Its one recording is `recording`/`title`/
  `length_s`/`write.mb_trackid`.
- `apply` (line 878): `_selected(row, classes, only)`. A JSON `skip` is final. A row needs `write` or `choose`.
  With `--classes`, the class decides. Without it, a `choose` or an `accept` on an `ACCEPT` class decides. Then
  `_check`: first `_intended`, then `_check_file`.
  - `_intended` refuses classes outside `APPLY_CLASSES | CHOOSABLE` ("a {cls} row is never applied; refused").
  - A `choose` counts only on `CHOOSABLE = {search, ambiguous, none}` and must be among the row's non-empty
    `candidates` ("choose '<x>' is not one of the row's candidates; refused"). So a `search` row cannot be chosen:
    its candidates are empty.
  - `_check_file` refuses a file whose size or mtime differs from the row's ("changed since the proposal"), whose
    tags differ, or whose target field is no longer empty.
  - Each write is logged first in `apply-<time>.jsonl`. `revert <log>` undoes it.
- Suggestion: `_tie_break` already breaks a tie by the file's album (over **all** of a recording's releases). So an
  `ambiguous` row has exactly one candidate on the file's album only when the ISRC test narrowed the tie away from
  it. The picker sees only `candidate_details[].release`, the first release. Measured on the checked-in
  `docs/identity-backfill-proposal.json` (before R6) by that field:

  | Rows | No candidate on the album | Exactly one (a suggestion) | Two or more |
  |---|---|---|---|
  | `ambiguous` | 84 | 5 | 27 |
  | `none` with candidates | 29 | 4 | — |

  So the suggestion is rare. To make it exactly Q8's rule (any release, as `_same_album`), R7-02 adds
  `"releases": r.releases` to `_detail`. This is additive: new proposals only, and `apply` never reads it. The view
  uses `releases` when a row has it, and otherwise the first `release`. The live proposal predates the field, so it
  gets the narrower rule until the next `propose`.
- Live state (`docs/next-todos.md` "State at hand-off", the proposal of 2026-10-17 with the AcoustID key):
  - confirmed 77, isrc 172, acoustid 236, search 16, ambiguous 89, conflict 38, none 203.
  - The 16 `search` rows were already applied as a trial, so an Accept on them shows "already written" at apply.
  - The 485 default-class rows are **not** applied yet.
  - So the live picking is mostly the 89 ambiguous rows, the `none` rows with candidates, and Skip on the 38
    conflict rows.
- The crates container has no `/srv/music`, and mounts `/srv/docker/crates:/data` (rw) and `/srv/docker/navidrome`
  (ro) with `NAVIDROME_DB` set. `/data/identity` is therefore already the worker's output dir: no compose change.
  `scripts.export_playlists._path_ids(db)` maps `media_file.path` (relative) → song id. `crates/` already imports
  `scripts.export_playlists`.
- Events: `store.log(playlist_id, song_id, kind, detail)`. It does **not** commit: every caller runs
  `store.commit()` after it. The `events` table has no `decided_by` column, so a pick records it in `detail`, as
  `proposals` does ("#n accept by michael"). `CrateApp._lock` (service.py:104) already serializes writes.
- Error handling in `_route` (service.py:384-407): `ApiError(status, msg)` → that status. Any other `OSError` →
  502 "cannot reach Navidrome". `KeyError`/`ValueError` (a `JSONDecodeError` included) → 400. So every identity
  error that should be a 503 must be raised as an `ApiError` explicitly.
- `identity_backfill._navidrome_ids(db)` maps `media_file.path` → id for `NOT missing` rows. Use it for ▶, not
  `export_playlists._path_ids`, which also returns missing rows.
- Web: tabs are `<button data-tab=…>` + `<section id="tab-…">`; ▶ uses `streamUrl(id)` → `/api/stream/<id>` and the
  existing player. `changeError(e)` is playlist-specific (409 → "This playlist is a crate by its name…"), so the
  Identity rows show `e.message`, the server's text. `grep -c apply web/app.js` prints 0 today.

## Design

### Where it lives

- `crates/service.py` `Config.identity_dir` comes from `CRATES_IDENTITY_DIR`, default `/data/identity`. Tests point
  it at `tmp_path`.
- `crates/identity_view.py` (new, stdlib) does four things:
  - It reads the proposal (`<identity_dir>/identity-proposal.json`).
  - It builds the rows.
  - It reads and writes `<identity_dir>/identity-choices.json`. The write is atomic: tmp + `os.replace`, with
    `_write_atomic` made public in `identity_backfill` as `write_atomic` and imported, not copied.
  - It never opens any other path for writing.

  `PROPOSAL`, `CHOOSABLE`, `_canon`, `_navidrome_ids` and a new `choice_problem(row, choice) -> str` come from
  `scripts.identity_backfill`, so the file name, the classes, the id check and the staleness rule have one source.
  `choice_problem` returns "" when a choice still fits its row, else the reason. The service and `apply` both call
  it.
- The picker rows are the proposal rows whose class is `search`, `ambiguous`, `conflict` or `error`, plus `none`
  rows that have candidates. `confirmed`/`isrc`/`acoustid` rows are applied by default and are not in the picker.
  A `none` row without candidates offers nothing to pick.

### `GET /api/identity[?class=<cls>]`

`404 {"error": "no identity proposal yet: run identity_backfill propose"}` when the proposal file is missing.
`503` when it cannot be parsed. `400` for an unknown `class`. Otherwise `200`:

```json
{"created": "2026-10-17T…", "counts": {"search": 239, "ambiguous": 116, "none": 33, "conflict": 24, "error": 0},
 "rows": [{
   "path": "Artist/Album/02 - Title.flac",
   "cls": "ambiguous",
   "why": "search: 3 of 10 results fit at 3:13, 3:14, 3:15",
   "file": {"artist": "…", "title": "…", "album": "…", "length_s": 194.0, "isrc": "…", "version_tag": "",
            "mb_trackid": "", "mb_workid": "", "acoustid_id": ""},
   "songId": "nd-song-id-or-null",
   "proposed": null,
   "candidates": [{"id": "<mbid>", "title": "…", "artist": "…", "length_s": 194.0, "release": "…",
                   "disambiguation": "…", "url": "https://musicbrainz.org/recording/<mbid>"}],
   "suggested": "<mbid> or null",
   "choice": {"action": "choose", "mbid": "<mbid>", "at": "…", "decided_by": "michael", "stale": false}
 }]}
```

- `counts` counts the picker rows per class, before the filter.
- The rows come in class order (`search`, `ambiguous`, `none`, `conflict`, `error`), then by path.
- `proposed` is set only on `search` rows: `{"id", "title", "length_s", "url"}`, from `recording`/`title`/
  `length_s`. It is what Accept writes, and the row shows it as its one recording.
- `candidates` come from `candidate_details`, in the proposal's order, each with its MusicBrainz link.
- `suggested` is the one candidate with a release (`releases`, else `release`) that loosely equals the file's album
  (`sourcing.identity.loose`, as `_same_album`). It is `null` when none or several match, and always `null` on
  `search`, `conflict` and `error` rows.
- `why` is shown with the proposal's `music_root` prefix removed (`<music_root>/` → ""). An `error` row's
  `unreadable: …` text comes from an exception and can hold the absolute path.
- `songId` is `_navidrome_ids(NAVIDROME_DB).get(path)`, read once per request. It is `null` when `NAVIDROME_DB` is
  unset, or the path is not in Navidrome or is missing there. A `sqlite3.Error` gives the existing 503.
- `choice` is the recorded choice for the path, or `null`. `stale` is true when it no longer fits the row (see the
  choices file). A stale choice is shown so Michael can see it and pick again. `apply` refuses it.
- The payload never contains `music_root`, an absolute path or anything from the environment. The AcoustID key is
  never in the proposal (R6-01).

### `POST /api/identity/choice`

The body is `{"path": "<proposal path>", "action": "accept"|"choose"|"skip", "mbid": "<mbid>"?}`. `mbid` is
required for `choose` (the chosen candidate) **and for `accept`**: the client sends the `proposed.id` it showed, so
an Accept can never bind to a recording that a `propose` finished in the meantime put on the row. `path` is only
looked up as a key among the picker rows; it is never joined to a directory or opened.

The service answers each case as follows:

| Case | Answer |
|---|---|
| no proposal file | 404 (as GET) |
| proposal or choices file unreadable or not valid JSON | 503 `ApiError`; the choices file is **never** overwritten then |
| body not a JSON object | 400 `body must be a JSON object` |
| `path` missing, not a string, or not a picker row | 400 `not in the identity proposal: <path>` |
| `action` not one of the three | 400 `action must be accept, choose or skip` |
| `accept`/`choose` on a `conflict`/`error` row | **409** `<cls> rows can only be skipped` |
| `accept` on a row that is not `search` | 400 `accept is for search rows; choose a candidate` |
| `accept` whose `mbid` is not the row's `write.mb_trackid` | **409** `the proposal changed since the page loaded; reload` |
| `choose` on a `search` row | 400 `a search row is accepted or skipped (it has no candidates)` |
| `choose` with `mbid` missing, not canonical, or not among the row's `candidates` (canonical compare) | 400 `<mbid> is not one of the row's candidates` |
| otherwise | 200 `{"path", "choice": {…}}` |

On a 200, the service first writes the choices file, then runs `store.log(...)` and `store.commit()`. It does all
three under `CrateApp._lock`, which serializes the read-modify-write; the service is one process. A failed write
(`OSError`) is raised as `ApiError(503, "could not save the choice: …")`, and no event is logged.

### The choices file `<identity_dir>/identity-choices.json`

```json
{"created": "<first write, UTC iso>",
 "choices": {"Artist/Album/02 - Title.flac": {
   "action": "choose", "mbid": "<mbid>", "cls": "ambiguous", "size": 25521726, "mtime_ns": 1792039245660081385,
   "at": "2026-10-22T08:01:02+00:00", "decided_by": "michael"}}}
```

- One entry per path. The latest click replaces the earlier one, and is the only way to change a choice.
- `mbid` depends on the action:
  - `choose`: the chosen candidate.
  - `accept`: the row's `write.mb_trackid` at the time of the click, so a later `propose` that picks another
    recording cannot borrow the Accept.
  - `skip`: `null`.
- `cls`, `size` and `mtime_ns` are the row's at the time of the click. If any of them differs from the current
  row, the choice is **stale**. So is an accepted `mbid` that is no longer the row's `write.mb_trackid`, or a chosen
  one no longer among its `candidates`. Michael picks again. `choice_problem` is the one definition of stale. It
  also rejects a malformed entry: an unknown action, a non-canonical `mbid`, or `accept` on a row that is not
  `search`.
- `decided_by` is always `michael`: the picker has one user, and nothing else writes the file.
- Written as one whole file by tmp + replace, so `apply` reading it while the service writes sees one version or
  the other.

### The event

`store.log(None, songId, "identity_pick", "<cls> <path>: accept <mbid> | choose <mbid> | skip; decided_by=michael")`
then `store.commit()`, once per accepted POST, after the file write. It shows in the Log tab and in `/api/events`.

### `identity_backfill apply <proposal> --choices <file>`

The new argument is `apply(..., choices: Path | None = None)`, and the CLI flag is
`--choices /data/identity/identity-choices.json`. Without `--choices`, nothing changes: the existing tests stay as
they are and stay green.

**Reading the file.** A missing or unparsable choices file, or one without a `choices` object, is an error. The CLI
says so and exits 2 before reading any library file.

**Which rows are selected.**
- `--choices` without `--classes` selects **only the rows with an `accept` or `choose` choice**. A staged run then
  writes Michael's picks and nothing else, even while the 485 default-class rows are still unapplied. The JSON
  `choose` rows of the default run are left out too.
- `--choices` with `--classes` selects those picks plus the named classes' rows.
- `--only` and `--limit` apply to all selected rows alike.

This narrows R7-03's wording, which only said that an accept is selected outside `--classes`. Both readings agree
on that; this one also keeps a `--limit 5` run to the picks.

**Each proposal row that has a choice**, in proposal order:
1. If the row's own JSON has `skip: true`, that is final, as today. The choice is ignored, and the run reports
   `choices: <path> is skipped in the proposal`.
2. If the choice is `skip`, the row is dropped, whatever its class, and even when the choice is stale. A skip
   never turns into a write.
3. If the row is `conflict` or `error`, an `accept` or `choose` is refused with `choices: <path> is <cls>; refused`.
4. Otherwise `choice_problem(row, choice)` runs. A stale or malformed choice is refused with
   `choices: <path> <reason>; pick again`. This covers a changed size, mtime or class, an accepted mbid that is no
   longer the row's pick, a chosen one no longer among its candidates, `accept` on a non-`search` row, an unknown
   action, and a malformed mbid.
5. `accept` (a `search` row): the row is selected. R7-03 allowed `accept` on `ambiguous`/`none` too, but such rows
   have no `write`, so an accept there could only end in "nothing to write". It is refused by step 4 instead.
6. `choose`: a copy of the row gets `choose = mbid`, and that copy is selected. The choices file wins over a
   hand-typed JSON `choose`; when the two differ, the run reports `choices: <path> overrides the proposal's choose
   <x>`. `_intended` then runs its unchanged check ("not one of the row's candidates; refused"), so a choice is
   checked against the candidates twice: when it is recorded, and when it is applied.

**What a refused choice does.** The row is **never** selected by its class instead. It goes into `rep.skipped` with
its reason, like any other skip. Skips do not change the exit code. That is today's rule: only `problems` make
`apply` exit 1.

**Paths the proposal lacks.** A choice whose `path` is not in the proposal is reported as
`choices: <path> is not in the proposal; ignored`, and goes into `rep.skipped` too.

**The checks that follow.** The existing `_check`/`_check_file` runs on every selected row: file unchanged since the
proposal, tags equal, target fields empty.

**What gets printed and logged.**
- The dry run marks each row from a choice: `would write <path>: mb_trackid=<id> (choice: accept, decided_by
  michael)`.
- `ApplyReport` gets `chosen: dict[path, action]`.
- A real run's `write` lines in `apply-<time>.jsonl` gain `"choice": "<action>", "decided_by": "michael"` (from the
  file's entry). `revert` ignores the extra keys.

### The Identity tab (R7-04)

- `web/index.html` gets two things:
  - `<button data-tab="identity">Identity <span id="identity-count" class="pill"></span></button>`.
  - `<section id="tab-identity" class="tab">`, holding a class filter `<select id="identity-class">` (all, `search`,
    `ambiguous`, `none`, `conflict`, `error`) and `<ul id="identity">`.
- `web/app.js` gets `loadIdentity()`, which renders one `<li>` per row:
  - The row text: artist – title, album, length (m:ss), the class, `why`, and a ▶ when `songId` is set (the
    existing player via `streamUrl`).
  - `search` rows: the proposed recording as text, with its MusicBrainz link, and the buttons **Accept** and
    **Skip**. Accept sends `mbid` = the shown `proposed.id`.
  - `ambiguous`/`none` rows: one radio per candidate (title, length, release, disambiguation, MusicBrainz link),
    with `suggested` pre-checked. **Choose** is disabled until a radio is checked; **Skip** is always there.
  - `conflict`/`error` rows: the evidence (`why`, the file's existing ids) and **Skip** only.
- A click POSTs `/api/identity/choice` and paints the answer on that row only: `accepted`, `chosen: <mbid>` or
  `skipped`, or `stale: pick again`. An error shows `e.message` (the server's text) in the row; it does not go
  through `changeError`, whose 409 and 503 texts are about playlists. Nothing else reloads.
- Phone-first: no fixed width over 375 px, and long titles wrap.
- `app.js` never says `apply`. A `#identity` hash opens the tab (for the R7-05 screenshots).

## Tasks and tests

Each task is TDD: the test first, seen red, then the code.

**R7-02, the API.** `tests/test_identity_api.py` runs `CrateServer` on the fake Navidrome and its `navidrome.db`
mirror. `CRATES_IDENTITY_DIR` is a tmp dir holding a proposal in the real schema. That proposal is made by
`identity_backfill.propose` on the suite's audio fixtures with a scripted MusicBrainz client (the
`tests/test_identity_backfill.py` helpers), then trimmed or extended with rows built by `asdict(Proposal(...))` so
that every class occurs. Tests:
- `test_rows_have_the_plan_shape`: the keys above, `url`s, no `music_root`, and no absolute path anywhere in the
  JSON.
- `test_an_error_rows_why_loses_the_music_root`: a real `propose` over an unreadable fixture file, so the text is a
  real exception's.
- `test_confirmed_isrc_acoustid_and_bare_none_rows_are_not_listed`.
- `test_class_filter` (an unknown class gives 400).
- `test_no_proposal_is_404`.
- `test_suggested_is_the_only_candidate_on_the_files_album` (one → its id; two → null; none → null; never on
  search/conflict).
- `test_song_id_from_navidrome_db_by_path` (null without `NAVIDROME_DB`, and null for a `missing` media_file).
- `test_suggested_uses_every_release_when_the_row_has_them` (`_detail` now carries `releases`).
- `test_conflict_and_error_rows_refuse_accept_and_choose_with_409`.
- `test_choose_outside_the_candidates_is_400`.
- `test_accept_outside_search_is_400`.
- `test_accept_of_another_recording_is_409` (the proposal was re-made between load and tap).
- `test_a_body_that_is_not_an_object_is_400`.
- `test_a_corrupt_choices_file_is_503_and_kept`: the bytes are unchanged after the POST.
- `test_choose_on_a_search_row_is_400`.
- `test_unknown_path_is_400` (including `../../etc/passwd`, and an absolute path).
- `test_second_click_replaces_the_first`: the file has one entry, the second action, and `decided_by: michael`.
- `test_each_pick_logs_identity_pick_with_decided_by_michael` (read through a second `CrateStore` on the same
  file, which proves the commit).
- `test_a_refused_pick_writes_nothing_and_logs_nothing`.
- `test_nothing_is_written_outside_the_identity_dir`: a listing of `tmp_path` before and after, where only
  `identity-choices.json` is new.
- `test_a_choice_goes_stale_when_the_row_changes` (re-written proposal with another `mtime_ns`).

**R7-03, `apply --choices`.** These go in `tests/test_identity_backfill.py`, on the existing fixture library and
dry run only. Tests:
- `test_choices_accept_selects_a_search_row_without_classes`.
- `test_choices_without_classes_selects_only_the_picks`: a default-class row without a choice is absent.
- `test_choices_with_classes_adds_the_picks`.
- `test_choices_choose_sets_the_chosen_id` (the dry-run fields show the mbid).
- `test_choices_skip_drops_a_default_class_row`.
- `test_choices_wrong_mbid_is_refused_with_the_existing_message`.
- `test_choices_on_conflict_are_refused`.
- `test_choices_stale_row_is_refused`: the row goes into skipped and never falls back to its class.
- `test_choices_stale_skip_still_drops_the_row`.
- `test_choices_override_a_json_choose_and_say_so`.
- `test_choices_malformed_entry_is_refused` (unknown action, bad mbid, accept on ambiguous).
- `test_choice_problem_is_shared`: the service and apply call the one `identity_backfill.choice_problem`.
- `test_choices_unknown_path_is_reported`.
- `test_choices_json_skip_is_final`.
- `test_choices_dry_run_changes_nothing_on_disk` (sha256 of every fixture file, and the tags re-read equal).
- `test_choices_cli_dry_run_names_rows_from_choices`.
- `test_choices_file_missing_or_malformed_exits_2`.
- `test_apply_log_carries_decided_by`: a real `--yes` run on the tmp fixture copy, the same harness the existing
  apply tests use, with no live paths.

R7-03 also writes the docs: the `--choices` form in docs/worker.md "Identity backfill", and one paragraph on the
picker in docs/how-ids-work.md.

**R7-04, the tab.** `tests/test_web_identity.py`, in `tests/test_web_m8.py` style (no JS runner):
- The tab button, the section, the filter and the list exist.
- `app.js` calls `/api/identity` and `/api/identity/choice`, contains `Accept`, `Choose`, `Skip` and
  `https://musicbrainz.org/recording/`, and never `/srv`.
- `grep -c apply web/app.js` is 0.
- The CSS has no width over 375 px.
- The `#identity` hash opener exists.

**R7-05** takes 375 px headless screenshots on the fake (or, where Firefox cannot render, tests of the payloads),
and **R7-06** reviews the R7 diff against the rules below and writes the docs.

## Safety rules, each with its test

- **Nothing is applied without a click.** The service has no route that writes a tag or runs `apply`, and the
  client never says `apply` (R7-04 grep). `apply --choices` only reads the choices file.
- **A choice must be one of the row's candidates.** It is checked when recorded (400) and again when applied
  (`_intended`, unchanged message).
- **`conflict`/`error` rows are never accepted or chosen.** The API answers 409, and `apply` refuses with
  `choices: <path> is <cls>; refused`, besides the existing `_intended` refusal.
- **The service writes only inside `identity_dir`.** The only path it writes is `identity_dir /
  "identity-choices.json"` (and its tmp sibling). `path` from the body is never a filesystem path: it is compared
  with the proposal's paths.
- **Every pick is an `identity_pick` event with `decided_by=michael`.**
- **No absolute path, `music_root` or key in the payload.**
- **A stale choice is never applied.** The row changed since the click: size, mtime, class, or the recording an
  Accept saw. An Accept is bound to the recording the page showed (409 otherwise), and a refused choice never
  falls back to its class.

## Live steps (Michael's; into the R8 checklist, not run by the harness)

Prerequisites:
- R7 is deployed (`scripts/deploy.sh`).
- Before any write (steps 4 and 5, and any revert), two checks from CLAUDE.md must pass:
  - The backup status:
    `systemctl show restic-backup.service -p ExecMainExitTimestamp -p ExecMainStatus` shows `ExecMainStatus=0`,
    under 26 h old.
  - The time: outside 03:15–04:30, and not while `systemctl is-active restic-backup.service` prints `active`.
- Every write runs under the live-writer lock: `flock -n /srv/docker/crates/live.lock <command>`. If the lock is
  taken, someone else is working: wait.
- The order relative to next-todos item 6 (the default classes) does not matter. `--choices` without `--classes`
  writes only the picks.
- A fresh `propose` is optional. Choices made on the old proposal go stale for every row it changes.

Every command runs from the worktree. "Check" means `scripts/live-check.sh`: exit 0 and "ok: every playlist file
matches Navidrome…".

1. **Look.** Run `ls -ld /srv/docker/crates/identity`: it must be writable by uid 1000, which the crates container
   runs as. If it is root-owned, the fix is a sudo step for Michael:
   `sudo chown 1000:1000 /srv/docker/crates/identity`. Then run **Check**. It must be green before any write:
   `apply`'s own check counts an already-stale playlist as a problem.
2. **Pick.** Open the Identity tab and pick. Then look at the result:
   - `cat /srv/docker/crates/identity/identity-choices.json`.
   - The Log tab shows the `identity_pick` events.
3. **Dry run:**

   ```
   scripts/live-run.sh python3 -m scripts.identity_backfill apply /data/identity/identity-proposal.json --choices /data/identity/identity-choices.json --dry-run
   ```

   Check:
   - **Every** `would write` line carries `(choice: …)`, and each one is a pick you made. If a line lacks it, stop.
   - Every `refused` line is one you understand.
4. **Five files:**

   ```
   flock -n /srv/docker/crates/live.lock scripts/live-run.sh python3 -m scripts.identity_backfill apply /data/identity/identity-proposal.json --choices /data/identity/identity-choices.json --yes --limit 5
   ```

   It scans Navidrome and checks song ids, recording ids and playlists itself (exit 0). Then run **Check**.

   **Undo:**

   ```
   flock -n /srv/docker/crates/live.lock scripts/live-run.sh python3 -m scripts.identity_backfill revert /data/identity/apply-<time>.jsonl
   ```

   The log path is printed by the run. `revert` does not scan Navidrome: wait for its next scan
   (`ND_SCANSCHEDULE` 1 h) or start one in Navidrome's UI, then run **Check**. After a revert, re-run `propose`
   before applying again: the revert changed the files' mtime.
5. **All:** the same command without `--limit`, then **Check**. The undo is as in step 4, with this run's log.

## Not built

- Bulk accept: one tap for a whole class, or "accept all suggested".
- A "clear" action. Another tap replaces a choice; an unapplied choice can always be changed to Skip.
- Choose on a `search` row. Its proposal holds one recording and no candidates, so Choose would be a second Accept.
  M9 §5a lists `search` under Choose, which this plan deliberately narrows.
- Accept on an `ambiguous` or `none` row. Such a row has no `write`, so the plan narrows R7-03 here as well: Accept
  is for `search` rows only.
- Applying from the web client. Tag writes stay in the worker, run by Michael.
- The 5b picker for the import `review` rows (M9 §5b), and a re-propose triggered from the web.
