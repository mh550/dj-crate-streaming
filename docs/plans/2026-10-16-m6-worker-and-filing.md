# M6: worker, approvals and beets filing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task, with superpowers:test-driven-development.
> Steps use checkbox (`- [ ]`) syntax for tracking. Code only: **no real Soulseek download anywhere** (D7).

**Goal:** approved downloads are fetched by a long-running worker container, filed by `beet import` (the only
beets writer), named back onto their wanted rows, checked against the old copy and AcoustID, and the web
client gets an Approve button and a "server" stream default.

**Architecture:** `sourcing/filer.py` wraps the `beet` CLI behind an injectable runner and reads beets'
`library.db` read-only to find what it filed. `fetch` swaps `organize.file_into` for the filer, and gains a
copy-upgrade reference, an optional AcoustID lookup (`sourcing/acoustid.py`) and a preferred candidate.
`crates.db` gains `approvals` and `previews` tables. The crates service records approvals and previews.
`sourcing/worker.py` is a poll loop that runs `fetch(approve=True)` only for rows with an unused approval.
`deploy/compose.yml` gains a `worker` service built from the existing Dockerfile, with identical-path mounts.

**Tech Stack:** stdlib Python 3.12, SQLite, beets 1.6.0 (CLI only, as a subprocess), ffmpeg/flac/fpcalc,
Docker Compose, vanilla JS.

**Spec:** `docs/specs/2026-10-16-ownership-and-identity.md` (Part 1 "Who may write what" and "Where beets fits",
Part 3 approvals and streaming, the M6 row). The runbook queue is `~/projects/OVERNIGHT-2.md` § M6.
Beets traps: `docs/hard-won-facts.md`.

## Global Constraints

Every task's requirements include these:

- **No sudo.** Anything root-only goes to "Needs Michael" with the exact command.
- **No real Soulseek downloads** (D7). Tests use `sourcing/fake_slskd.py` and `subsonic/fake_server.py`. No task
  and no live step creates an approval on the live `crates.db`. The first real download is Michael's.
- **Never write to `/srv/incoming/library-import/`.** It is read-only and Michael's. The filer refuses any
  folder that is not a `.staging/<name>` folder.
- **Secrets** live only in `/srv/docker/.env`. They are never printed, logged, committed or put in a URL.
  Do not source `.env` into a shell. Navidrome and slskd calls run inside the containers.
- **stdlib Python only** (plus `mediafile`/`mutagen`, already used by `scripts/tag_cleanup.py`). The beets
  Python package is never imported by new code: `beet` is called as a subprocess.
- **beets never writes to existing files.** `beet write` runs only on the file that the same filer call has
  just imported, and only after beets applied a MusicBrainz match to it. No `beet modify`, `mbsync` or
  `import -L` anywhere.
- **Every tool subprocess** gets `stdin=subprocess.DEVNULL` and reads output with
  `encoding="utf-8", errors="replace"`.
- **Soulseek peer names stay out of events and logs.** Event details name the file's basename, never the
  username.
- **Tests:** `~/.local/bin/pytest -q` (256 passing at the start of M6). Existing tests stay unchanged, apart
  from the edits this plan names explicitly (Tasks 3 and 5). New behaviour gets new tests. Fakes mirror
  captured live responses in `fixtures/`.
- **Commits:** `git add` files by name (never `-A`). Check `git show --stat HEAD` after each commit.

## Measured before writing this plan (2026-10-16, real `/usr/bin/beet` 1.6.0, temp library in the scratchpad)

Each of these changes something the controller's rulings assumed:

1. **Offline fallback works without `-A`.** With MusicBrainz unreachable (the test suite proves this offline
   path with `test_real_beet_tests_are_offline`; the original measurement was taken online),
   `beet -c cfg import -q -s -m -W <dir>` prints `Importing as-is.`, exits 0 in about 3 s, moves the file to
   `$artist/Singles/$title.flac` and leaves the file **byte-identical** (`metaflac --export-tags-to=-` diff
   empty). The test uses the normal autotag path.
2. **A hidden staging folder is fine.** `ignore: ['.*']` applies only to entries *inside* the folder given
   to `import`, so `<downloads>/.staging/<id>-<ts>/` imports normally.
3. **`duplicate_action: skip` breaks copy upgrades.** A second file with the same artist and title is logged
   `duplicate-skip`, beets exits 0, and the file stays in staging with no new `items` row. Every crate row is,
   by definition, a song already in the library. Fix: `duplicate_action: keep` in `deploy/beets.yaml`, which
   is also what Part 2 needs (several versions of a song coexist). The second copy lands as
   `Good Times.1.flac`. The host no longer runs beets imports, so the change is safe.
4. **A non-empty `mb_trackid` does not mean a confident match.** An uploader's file that already carries
   `MUSICBRAINZ_TRACKID` gets imported as-is (offline) with that id in `items.mb_trackid`. With the
   `mb_trackid` signal, the filer would then `beet write` an unmatched file (the M2 trap). The reliable
   signal is beets' import log: `ImportSession.log_choice` writes `asis <path>` for an as-is import and
   nothing for an applied match. The filer passes its own `-l <log>` per call and treats "no line starting
   `asis `" plus a new `items` row as "matched".
5. `items.path` is a **BLOB** (bytes): decode it with `os.fsdecode`.
6. **An untagged download is filed as `/srv/music/_/Singles.flac`** (empty `$artist` → `_`, empty `$title` collapses
   the file name; a second one becomes `_/Singles.1.flac`). See Review Focus 1.
7. PyPI `beets==1.6.0` has no `imp` import (only Debian's *test* patches mention it), so it should install on
   `python:3.12-slim`. The host's working combination is mediafile 0.12.0 and confuse 2.0.1. Pin those two
   and smoke-test in the container (Task 7).
8. **A beets match is "confident" (D22) only when MusicBrainz's recording length agrees with the file (Task 6b).**
   beets 1.6 in quiet mode applies a MusicBrainz recording that has no length on artist + title alone
   (distance 0.0, "strong"), which for a DJ library (radio edit vs 12") is a guess, and `beet write` would
   stamp the wrong recording id and titles. So `BeetsFiler` takes a `confirm` hook and runs `beet write` only
   when it says yes; with none configured, nothing is written. `sourcing/musicbrainz.py` provides
   `confirm_recording_length` (one `recording/<id>?fmt=json` GET per download, descriptive User-Agent,
   tolerance 4 s, never raises: a failed lookup is "unconfirmed"). `FiledItem` gains `length` and `note`; the
   `filed` event carries the note.

## Review Focus

These are the inputs most likely to bite that the rulings do not cover. Each one has a test in the task
that owns the code:

1. **A download with no artist or title tag.** Real beets files it as `/srv/music/_/Singles.flac` (measured), and
   the names-back step would copy the blanks onto the row. Expected: before importing, the filer fills
   *only the empty* artist/title from the wanted row with `scripts.tag_cleanup.write_minimal`. The file is our
   fresh download, not a library file, and nothing else is touched. → Task 2
   `test_real_beet_untagged_download_is_named_from_the_wanted_row`; Task 3 `test_fetch_passes_the_wanted_names_to_the_filer`.
2. **A copy upgrade of a song already in beets' library.** Expected: filed next to the old copy, not
   silently skipped. → Task 2 `test_real_beet_keeps_a_second_copy_of_the_same_song`; Task 3
   `test_nothing_imported_fails_and_keeps_the_file_in_staging`.
3. **An unmatched upload that carries its own MusicBrainz id.** Expected: as-is, no `beet write`, file
   byte-identical. → Task 2 `test_real_beet_as_is_with_uploader_recording_id_is_not_rewritten`.
4. **Re-seeding a Spotify playlist after a row was renamed from Navidrome.** Expected: the renamed row is
   found under its original Spotify names, with no duplicate row. → Task 3
   `test_renamed_external_row_is_still_found_by_its_asked_names`.
5. **A worker fetch that ends in `verify`** (Navidrome had not indexed the file yet). The approval is spent.
   Expected: later ticks re-check it without downloading. → Task 6 `test_tick_rechecks_verify_rows_without_downloading`.

Also checked live in Task 8 rather than by a test: `navidrome.db` opened `mode=ro` on a read-only bind mount
while Navidrome holds it in WAL mode.

---

## File map

| File | Change | Responsibility |
|---|---|---|
| `crates/store.py` | modify | `approvals`, `previews` tables; `asked_artist`/`asked_title` columns; `set_wanted_names`; `verify_ids`; stream default |
| `crates/service.py` | modify | `POST /api/wanted/<id>/preview`, `POST /api/wanted/<id>/approve`; slskd in `Config`/`CrateApp`; stream tier `server` |
| `web/app.js`, `web/index.html` | modify | Preview / Approve on Wanted rows; "server · Navidrome decides" |
| `sourcing/scorer.py` | modify | `Candidate.as_dict()` |
| `sourcing/filer.py` | create | `BeetsFiler`, `FiledItem`, `FilingError` |
| `sourcing/fetch.py` | modify | staging + filer, names back, reference, AcoustID, `prefer` |
| `sourcing/organize.py`, `tests/test_organize.py` | delete | retired |
| `sourcing/acoustid.py` | create | compressed fingerprint + `/v2/lookup` |
| `sourcing/verify.py` | modify | `recording_id`, `lookup` parameters |
| `sourcing/policy.py` | modify | `STREAM["server"]`, `STREAM_DEFAULT`, `check_stream` |
| `sourcing/worker.py` | create | `Worker.tick()`, `Worker.run()` |
| `sourcing/cli.py` | modify | `worker [--once]`; shared env wiring for `fetch` and `worker` |
| `Dockerfile`, `deploy/compose.yml`, `deploy/beets.yaml` | modify | tools + beets in the image; `worker` service; slskd downloads dir; beets header |
| `docs/worker.md`, `README.md` | create / modify | worker, approvals, filing |
| `tests/helpers.py` | modify | `fake_beet(...)` runner, `beets_items_db(...)` |
| `tests/test_approvals.py`, `tests/test_filer.py`, `tests/test_fetch_filing.py`, `tests/test_acoustid.py`, `tests/test_stream_server.py`, `tests/test_worker.py` | create | new behaviour |

---

### Task 1: Approval and preview records, the API and the Wanted tab

No change to `fetch` in this task: preview calls today's `fetch(..., approve=False)`.

**Files:**
- Modify: `crates/store.py` (SCHEMA, new methods, `wanted()`)
- Modify: `crates/service.py` (`Config`, `CrateApp.__init__`, new `preview`/`approve`, `_api` POST routes)
- Modify: `sourcing/scorer.py` (`Candidate.as_dict`)
- Modify: `web/app.js` (`loadWanted`)
- Test: `tests/test_approvals.py`

**Interfaces:**
- Produces (store):
  ```sql
  CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY, wanted_id TEXT NOT NULL, approved_by TEXT NOT NULL,  -- michael | policy:<name> | agent:<id>
    candidate TEXT, tier TEXT NOT NULL, ts REAL NOT NULL, used_at REAL, result TEXT);
  CREATE TABLE IF NOT EXISTS previews (song_id TEXT PRIMARY KEY, result TEXT NOT NULL, ts REAL NOT NULL);
  ```
  - `approve(wanted_id: str, approved_by: str, candidate: dict | None, tier: str) -> int`: inserts and returns
    the new id. Any earlier unused approval for the same `wanted_id` gets `used_at=now`,
    `result="superseded by #<new id>"`, so at most one is pending per row. Logs event kind `approved`, detail
    `"<approved_by> at <tier>"` plus `": <candidate basename>"` when a candidate is given (never the username).
    Commits.
  - `pending_approvals() -> list[dict]`: `used_at IS NULL`, ordered by id.
  - `mark_approval_used(approval_id: int, result: str) -> None`: sets `used_at=now` and `result`. Commits.
  - `approval(wanted_id: str) -> dict | None`: the latest by id.
  - The approval dict shape: `{"id", "wanted_id", "approved_by", "candidate": dict | None, "tier", "ts", "used_at", "result"}`.
  - `set_preview(wanted_id: str, result: dict) -> None` and `preview(wanted_id: str) -> dict | None`. They
    mirror `set_verification`/`verification`.
  - Every `wanted()` row gains `"approval"` (latest or None) and `"preview"` (cached or None).
- Produces (scorer): `Candidate.as_dict() -> dict` = `dataclasses.asdict(self) | {"basename": self.basename}`.
- Produces (service):
  - `Config.slskd_url: str | None` (env `SLSKD_URL`) and `Config.slskd_key: str | None` (env `SLSKD_API_KEY`).
  - `CrateApp(cfg, policy=..., store=None, slskd: SlskdClient | None = None)`. When `slskd` is None and
    `cfg.slskd_url` and `cfg.slskd_key` are set, it builds one.
  - `CrateApp.preview(wanted_id) -> dict` returns `{"status", "reason", "pick": Candidate.as_dict() | None,
    "explain", "ts"}` and caches it with `set_preview`.
  - `CrateApp.approve(wanted_id, candidate: dict | None) -> dict` returns the approval dict.
  - `POST /api/wanted/<id>/preview` returns 200 with the preview, 404 when fetch says `missing`, and 503
    `{"error": "slskd is not configured"}` without slskd.
  - `POST /api/wanted/<id>/approve`, body `{}` or `{"candidate": {...}}`, returns 200 with the approval dict,
    404 for an unknown id, and 400 when a given candidate lacks a string `username` or `filename`. Without a
    body candidate it uses the cached preview's `pick` (which may be None). `approved_by` is always
    `"michael"`. `tier` is the row's tier.

- [ ] **Step 1: Write the failing tests** in `tests/test_approvals.py`. Fixture `svc_slskd`: like `test_service.svc`, plus
  relabel s4 as in `test_fetch.world` (`title="Good Times", artist="Chic", album="Risqué", year=1979, track=3,
  duration=501`), `app.reconciler.set_crate("pl-2", True)`, and a `FakeSlskdServer(load_responses(), tmp/"dl", files={})`
  passed as `CrateApp(..., slskd=SlskdClient(srv.url, "k"))`.
  - `test_approve_records_and_supersedes`: store-level. Call `approve("s4","michael",None,"crate")`, then
    `approve("s4","michael",{"username":"u","filename":"f"},"crate")`. Assert `[a["id"] for a in
    pending_approvals()] == [second]`, `approval("s4")["candidate"] == {"username":"u","filename":"f"}`, and
    the first approval's result is `"superseded by #<second>"`. Assert `mark_approval_used(second, "ok: x")`
    leaves `pending_approvals() == []` and `approval("s4")["result"] == "ok: x"`.
  - `test_approved_event_never_names_the_peer`: approve with candidate `{"username":"vinylhead77","filename":"a\\b\\03 - Good Times.flac","basename":"03 - Good Times.flac"}`.
    Assert `"vinylhead77" not in` any event detail, and `"03 - Good Times.flac" in` the `approved` event's detail.
  - `test_preview_endpoint_returns_and_caches_the_pick`: `POST /api/wanted/s4/preview`. Assert 200,
    `pick["username"] == "vinylhead77"`, `"Good Times" in explain`, `srv.enqueued == []`, and that
    `GET /api/wanted` shows the s4 row's `preview["pick"]["basename"] == "03 - Good Times.flac"`.
  - `test_approve_endpoint_uses_the_previewed_pick`: preview, then `POST /api/wanted/s4/approve` with `{}`.
    Assert 200, `approved_by == "michael"`, `tier == "crate"`, `candidate["filename"] == pick["filename"]`,
    `used_at is None`, and the s4 row in `GET /api/wanted` has `approval["id"]` equal to it.
  - `test_approve_unknown_id_is_404_and_bad_candidate_400`: `/api/wanted/nope/approve` → 404;
    `{"candidate": {"username": 3}}` → 400.
  - `test_preview_without_slskd_is_503`: the plain `test_service.svc`-style app without slskd → 503.
  - `test_web_client_offers_preview_and_approve`: `GET /app.js` body contains `"/preview"`, `"/approve"` and
    `"waiting for worker"`.
- [ ] **Step 2: Run** `~/.local/bin/pytest -q tests/test_approvals.py`. Expected: FAIL (no `approve`, routes return 404).
- [ ] **Step 3: Implement** the store, scorer and service parts per Interfaces. Route matching:
  `head == "wanted" and len(p) == 3 and p[2] in ("preview", "approve")`. `preview` calls
  `sourcing.fetch.fetch(wanted_id, store=, slskd=self.slskd, navidrome=self.api, reconciler=self.reconciler,
  music_root=Path(os.environ.get("MUSIC_ROOT", "/srv/music")), downloads_root=Path(os.environ.get("DOWNLOADS_ROOT",
  "/srv/incoming/soulseek")), approve=False)` under `self._lock`.
- [ ] **Step 4: Implement the Wanted tab** in `web/app.js` `loadWanted`. For each row:
  - With `t.approval` and no `used_at`: a sub line `approved · waiting for worker`.
  - With `t.approval.used_at`: a sub line `worker: ${t.approval.result}`.
  - Otherwise: a `Preview` button that POSTs `/api/wanted/<id>/preview` (label `searching…` while in flight).
  - With a preview pick: a pick line `pick: <basename> · <extension> · <bit_rate>k · score <score.toFixed(2)>`
    (no username), the explain text in a `<details>`, and an `Approve` button that POSTs
    `/api/wanted/<id>/approve` with `{candidate: pick}`, then reloads the tab.
  - With a preview that has no pick: show `no acceptable candidate`.
- [ ] **Step 5: Run** `~/.local/bin/pytest -q tests/test_approvals.py tests/test_service.py tests/test_crates.py`. Expected: PASS.
- [ ] **Step 6: Run the full suite** `~/.local/bin/pytest -q`. Expected: all pass.
- [ ] **Step 7: Commit**
  ```bash
  git add crates/store.py crates/service.py sourcing/scorer.py web/app.js tests/test_approvals.py
  git commit -m "M6: approval and preview records, /api/wanted/<id>/preview|approve, Approve in the Wanted tab (D23)"
  ```

---

### Task 2: `sourcing/filer.py` and the real-beet test

**Files:**
- Create: `sourcing/filer.py`
- Modify: `deploy/beets.yaml` (`duplicate_action: keep` with its reason; the header comes in Task 7)
- Modify: `tests/helpers.py` (`fake_beet`, `beets_items_db`)
- Test: `tests/test_filer.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass
  class FiledItem:
      path: Path          # absolute, as beets filed it (decoded from the items.path BLOB)
      artist: str
      title: str
      mb_trackid: str     # "" when none
      matched: bool       # beets applied a MusicBrainz match (no "asis " line in this call's import log)
      filled: list[str] = field(default_factory=list)   # tag fields filled from the wanted row before import

  class FilingError(Exception): ...

  class BeetsFiler:
      def __init__(self, config: Path, *, library: Path | None = None, beet: str = "beet",
                   runner=subprocess.run, tagger=fill_missing_tags, timeout_s: float = 600): ...
      def file(self, folder: Path, log: Path, *, names: dict[str, str] | None = None) -> FiledItem | None: ...

  def fill_missing_tags(path: Path, names: dict[str, str]) -> list[str]:
      """Write each of `names` (keys "artist", "title") whose tag in `path` is empty, via
      scripts.tag_cleanup.write_minimal (imported lazily); return the fields written. Reads with mediafile.MediaFile."""
  ```
- `library` defaults to the top-level `library:` value read from the config with
  `re.search(r"^library:\s*(\S+)", text, re.M)`. That keeps it stdlib-only and keeps one definition.
- `file()`, in order:
  1. Raise `ValueError` unless `folder.parent.name == ".staging"`. This guard keeps beets away from
     originals and the library.
  2. When `names` is given: `filled = tagger(f, names)` for each audio file `f` in `folder`.
  3. `before = max(id)` from `items` via `sqlite3.connect(f"{library.as_uri()}?mode=ro", uri=True)`. Use 0
     when the DB or the table is missing.
  4. `runner([beet, "-c", str(config), "import", "-q", "-s", "-m", "-W", "-l", str(log), str(folder)],
     stdin=DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s)`.
     A non-zero return code raises `FilingError` with the last 3 stderr lines.
  5. Read `SELECT id, path, mb_trackid, artist, title FROM items WHERE id > ? ORDER BY id`. No rows → return
     None. More than one row → `FilingError("beets imported N items from <folder>")`.
  6. `matched = log exists and no line starts with "asis "`.
  7. When `matched`: `runner([beet, "-c", config, "write", f"path:{path}"], ...)`. A non-zero return code
     raises `FilingError`.
  8. Return `FiledItem` (with `filled`).
- Produces (tests/helpers.py):
  - `beets_items_db(path: Path) -> Path`: creates `items(id INTEGER PRIMARY KEY, path BLOB, mb_trackid TEXT,
    artist TEXT, title TEXT)`. These are the column names and types of the real `library.db` (measured above).
  - `fake_beet(music: Path, library: Path, target_rel: str, *, artist="", title="", mb_trackid="",
    matched=False, import_nothing=False, rc=0) -> Callable`: a runner that records every `cmd` in `.calls`.
    - On `import`: moves the single file in `cmd[-1]` to `music/target_rel`, inserts an `items` row with
      `path=os.fsencode(abs path)`, and writes `cmd[cmd.index("-l")+1]` with `asis <src path>` unless
      `matched`.
    - With `import_nothing`, it writes the log line `duplicate-skip <src>` and moves nothing.
    - Returns `subprocess.CompletedProcess(cmd, rc, "", "boom" if rc else "")`.

- [ ] **Step 1: Change `deploy/beets.yaml`**: `duplicate_action: keep`, commented
  `# copies and versions of one song coexist (spec Part 2); skip would drop every copy upgrade`.
- [ ] **Step 2: Write the failing tests** in `tests/test_filer.py`.
  - Helper `real_config(tmp_path) -> (config, music, library)`: copy `deploy/beets.yaml` and rewrite the
    `directory:`, `library:`, `statefile:` and `  log:` lines into `tmp_path`. Append
    `musicbrainz:\n  host: 127.0.0.1:9\n` (refused at once: offline, falls back to as-is, about 3 s).
  - Mark the real tests `pytest.mark.skipif(shutil.which("beet") is None, ...)` and
    `monkeypatch.setenv("BEETSDIR", str(tmp_path / "beetsdir"))`, so the user's beets config is never read.
  - Test audio: `make_audio(staging / "gt.flac", seconds=3)`, then tag with
    `metaflac --set-tag=ARTIST=Chic --set-tag=TITLE="Good Times" --set-tag=GENRE=Disco --set-tag=GENRE=Funk`.
    The multi-valued genre is the M2 trap. `staging = tmp/"dl"/".staging"/"ext-1-1"`.
  - `test_real_beet_files_unmatched_download_as_is`: assert
    `item.path == music/"Chic"/"Singles"/"Good Times.flac"`, `item.matched is False`, `item.mb_trackid == ""`,
    the sha256 of the file is unchanged, `metaflac --export-tags-to=-` still has both `GENRE=` lines, and the
    staging folder holds no audio.
  - `test_real_beet_keeps_a_second_copy_of_the_same_song`: import a second differently seeded file with the
    same tags from `.staging/ext-1-2`. Assert it returns an item at `music/"Chic"/"Singles"/"Good Times.1.flac"`.
  - `test_real_beet_untagged_download_is_named_from_the_wanted_row`: an untagged FLAC (`make_audio`, no
    metaflac step), `names={"artist": "Chic", "title": "Good Times"}`. Assert `item.filled == ["artist", "title"]`
    and `item.path == music/"Chic"/"Singles"/"Good Times.flac"` (not `music/"_"/"Singles.flac"`).
  - `test_tagger_fills_only_empty_fields`: a FLAC tagged `TITLE=Le Freak` only, with
    `names={"artist":"Chic","title":"Good Times"}`. `fill_missing_tags` returns `["artist"]`, and the title
    stays `Le Freak`.
  - `test_real_beet_as_is_with_uploader_recording_id_is_not_rewritten`: the file is also tagged
    `MUSICBRAINZ_TRACKID=0a1b2c3d-0000-0000-0000-000000000001`. Assert `item.matched is False`,
    `item.mb_trackid == "0a1b2c3d-..."` and the sha256 is unchanged.
  - `test_confident_match_runs_beet_write_on_the_new_file_only` (fake runner, `matched=True`,
    `mb_trackid="rec-1"`): `runner.calls[0]` equals the exact import command above. Assert
    `runner.calls[1] == ["beet", "-c", str(cfg), "write", f"path:{music/'Chic/Singles/Good Times.flac'}"]`
    and `item.matched and item.mb_trackid == "rec-1"`.
  - `test_as_is_never_runs_beet_write` (fake): exactly one call.
  - `test_nothing_imported_returns_none` (fake `import_nothing=True`): returns None.
  - `test_beets_error_raises` (fake `rc=1`): `pytest.raises(FilingError, match="boom")`.
  - `test_refuses_a_folder_outside_staging`: `filer.file(tmp/"library-import", log)` raises `ValueError`, and
    the runner was never called.
  - `test_library_path_comes_from_the_config`: `BeetsFiler(Path("deploy/beets.yaml")).library ==
    Path("/srv/docker/beets/library.db")`.
- [ ] **Step 3: Run** `~/.local/bin/pytest -q tests/test_filer.py`. Expected: FAIL (`ModuleNotFoundError: sourcing.filer`).
- [ ] **Step 4: Implement** `sourcing/filer.py` per Interfaces. The module docstring states the D22 rule: full
  tags only after an applied match, and as-is files are never rewritten. It also explains why the import log
  is the match signal, not `mb_trackid`.
- [ ] **Step 5: Run** `~/.local/bin/pytest -q tests/test_filer.py`. Expected: PASS (the real tests take about 3 s each).
- [ ] **Step 6: Commit**
  ```bash
  git add sourcing/filer.py tests/test_filer.py tests/helpers.py deploy/beets.yaml
  git commit -m "M6: BeetsFiler (beet import -q -s -m -W per staging folder; beet write only after a match); duplicate_action keep"
  ```

---

### Task 3: `fetch` files through beets, names go back onto the row, `organize` retires

**Files:**
- Modify: `sourcing/fetch.py`
- Modify: `crates/store.py` (`asked_artist`, `asked_title`, `set_wanted_names`, `find_external`)
- Modify: `sourcing/cli.py` (`fetch` builds a filer)
- Modify: `tests/test_fetch.py`: **only** the `world` fixture (adds `filer`) and `run()` (passes
  `filer=world["filer"]` by default). No test body or assertion changes.
- Delete: `sourcing/organize.py`, `tests/test_organize.py`
- Modify: `README.md` (the `organize.py` line → `filer.py   beet import of each verified download (the only beets writer)`)
- Test: `tests/test_fetch_filing.py`

**Interfaces:**
- Consumes: `BeetsFiler.file(folder, log) -> FiledItem | None`, `FilingError` (Task 2); `fake_beet`,
  `beets_items_db` (tests/helpers.py, Task 2).
- Produces:
  - `fetch(..., filer: BeetsFiler | None = None, ...)`. When `approve` is set and `filer is None`, it returns
    `FetchResult("refused", "no beets filer configured (run --approve in the worker)")`. This check comes
    after the roots check and before any search.
  - `CrateStore.set_wanted_names(wanted_id: str, artist: str, title: str) -> bool`. It returns True when the
    names changed.
    - External rows: on the first rename it copies the old names into `asked_artist`/`asked_title` (when
      NULL), then updates `artist`/`title`.
    - Crate rows: updates `artist`/`title` of that song's live `crate_tracks` rows.
    - On a change it logs event kind `renamed`, detail `"<old artist> – <old title> → <artist> – <title>"`.
    - Commits.
  - `external_wanted` gains `asked_artist TEXT`, `asked_title TEXT` (via `_migrate`). `find_external` matches
    the loose key of either (`artist`, `title`) or (`asked_artist`, `asked_title`).
- `fetch` after a passing verify, in order:
  1. Stage the file: `staging = downloads_root / ".staging" / f"{wanted_id}-{int(time.time())}"`, `mkdir(parents=True)`,
     then `shutil.move(landed, staging / landed.name)`.
  2. `item = filer.file(staging, staging.with_suffix(".log"), names={"artist": wanted.artist, "title": wanted.title})`.
     When `item.filled` is non-empty, log event `tagged`, detail `"filled <fields> from the wanted row"`.
  3. When `item is None`: `fail(f"beets did not import {landed.name}; it is still in {staging}", ...)`. Keep the
     file there.
  4. Log event `filed`, detail `f"beets {'matched' if item.matched else 'as-is'}: {item.path.relative_to(music_root)}"`.
     Remove the log, then `staging.rmdir()` (ignore `OSError`).
  5. Call `finish(item.path, best, text, query=f"{item.artist} {item.title}")`.
- `finish`/`locate_in_navidrome` take an optional `query`, defaulting to the wanted names. Size and suffix
  stay the key. On a hit, call `store.set_wanted_names(wanted_id, new.artist, new.title)` before the
  external/crate branch. A miss → `verify` as today.

- [ ] **Step 1: Edit `tests/test_fetch.py`** `world`. Add
  `lib = beets_items_db(tmp_path / "library.db")` and
  `filer=BeetsFiler(tmp_path / "beets.yaml", library=lib, runner=fake_beet(tmp_path/"music", lib, "Chic/Risqué (1979)/03 - Good Times.flac", artist="Chic", title="Good Times"), tagger=lambda path, names: [])`.
  The config file need not exist when `library` is given. The no-op tagger keeps the header-only FLACs
  byte-identical, which `test_approved_fetch_runs_to_ok` asserts. In `run()`, add `kw.setdefault("filer", world["filer"])`.
- [ ] **Step 2: Write the failing tests** in `tests/test_fetch_filing.py`. Reuse `world`, `run`, `new_song`,
  `good_flac_bytes`, `GOOD`, `RESPONSES` from `tests.test_fetch`.
  - `test_fetch_hands_the_download_to_beets_from_a_fresh_staging_folder`: assert the runner's import call
    targets a folder under `dl/.staging/` whose name starts with `s4-`, and that folder no longer exists
    after `ok`.
  - `test_names_from_navidrome_go_back_onto_an_external_row`: an external row "Chic"/"Good Times". `new_song`
    with `title='Good Times (12" Version)'`. Assert `external(ext)["title"] == 'Good Times (12" Version)'` and
    a `renamed` event whose detail is `'Chic – Good Times → Chic – Good Times (12" Version)'`.
  - `test_same_names_log_no_rename`: no `renamed` event.
  - `test_renamed_external_row_is_still_found_by_its_asked_names`: after the rename above,
    `add_external_wanted("Chic", "Good Times") == ext` and `external_count()` is unchanged.
  - `test_nothing_imported_fails_and_keeps_the_file_in_staging`: `fake_beet(..., import_nothing=True)`.
    Assert `status == "failed"`, `"still in" in reason`, and the file exists under `dl/.staging/`.
  - `test_filing_error_marks_failed_and_reraises`: `fake_beet(rc=1)`. Assert it raises `FilingError` and the
    row is `failed` with `"FilingError"` in the reason.
  - `test_approve_without_a_filer_is_refused`: `run(world, srv, approve=True, filer=None)`. Assert
    `status == "refused"` and `srv.enqueued == []`.
  - `test_fetch_passes_the_wanted_names_to_the_filer`: a recording tagger
    `def tagger(path, names): seen.append(names); return ["title"]`. Assert
    `seen == [{"artist": "Chic", "title": "Good Times"}]` and one `tagged` event whose detail contains `title`.
- [ ] **Step 3: Run** `~/.local/bin/pytest -q tests/test_fetch_filing.py tests/test_fetch.py`. Expected: FAIL (`fetch() got an unexpected keyword argument 'filer'`).
- [ ] **Step 4: Implement** the store and `fetch` changes per Interfaces. Remove the `organize` import. Update
  the module docstring's diagram (`verify ─▶ beet import ─▶ rescan`).
  - In `sourcing/cli.py`, add a helper `_fetch_env() -> dict` that returns
    `{"music_root": Path(MUSIC_ROOT or "/srv/music"), "downloads_root": Path(DOWNLOADS_ROOT or "/srv/incoming/soulseek"),
    "filer": BeetsFiler(Path(os.environ.get("BEETS_CONFIG", DEFAULT_BEETS_CONFIG)))}`, with
    `DEFAULT_BEETS_CONFIG = Path(__file__).resolve().parent.parent / "deploy" / "beets.yaml"`.
  - `fetch` uses `**_fetch_env()`. The downloads default changes from `/srv/incoming` to slskd's new folder
    (Task 7).
- [ ] **Step 5: Retire organize**: `git rm sourcing/organize.py tests/test_organize.py`. Run
  `grep -rn organize sourcing crates tests` and expect no hits.
- [ ] **Step 6: Run** `~/.local/bin/pytest -q`. Expected: all pass. The count drops by test_organize's 3 and
  grows by the new tests.
- [ ] **Step 7: Commit**
  ```bash
  git add sourcing/fetch.py sourcing/cli.py crates/store.py tests/test_fetch.py tests/test_fetch_filing.py README.md
  git commit -m "M6: fetch files via beet import from a staging folder, copies Navidrome's names back (renamed: …), retires organize.py"
  ```
  (The `git rm` in step 5 already staged the deletions.)

---

### Task 4: Copy-upgrade reference and the AcoustID lookup

**Files:**
- Create: `sourcing/acoustid.py`, `fixtures/acoustid_lookup.docs-example.json`
- Modify: `sourcing/verify.py` (`verify` parameters, a lookup step after `_recording_check`)
- Modify: `sourcing/fetch.py` (reference path, recording id, lookup)
- Modify: `sourcing/cli.py` (`_fetch_env` adds `navidrome_db`, `lookup`)
- Test: `tests/test_acoustid.py`, plus new tests in `tests/test_fetch_filing.py`

**Interfaces:**
- Produces (`sourcing/acoustid.py`):
  - `URL = "https://api.acoustid.org/v2/lookup"`.
  - `compressed_fingerprint(path: Path) -> tuple[int, str]`: `fpcalc -json -length 120 <path>` (no `-raw`)
    → `(round(duration), fingerprint)`.
  - `parse(resp: dict) -> list[dict]`: raises `ValueError` unless `resp["status"] == "ok"`. Returns
    `[{"id", "title", "score"}]` for every recording of every result, results by descending score, deduped
    by id.
  - `lookup(path: Path, key: str, *, timeout: float = 10, opener=urllib.request.urlopen) -> list[dict]`: a
    **POST** form body `client=<key>&meta=recordings&duration=<d>&fingerprint=<fp>&format=json`. The key is
    never in a URL or an error message.
  - `make_lookup(key: str) -> Callable[[Path], list[dict]]`.
- Produces (verify):
  `verify(path, expected_duration_s=None, tier=None, reference=None, tolerance_s=None, min_lossless_kbps=None,
  recording_id: str | None = None, lookup: Callable[[Path], list[dict]] | None = None) -> Verdict`. With
  `tier` and `lookup`, after the reference check:
  - Success: `m["acoustid"] = {"recording_id": recs[0]["id"] | None, "title": ..., "score": ..., "ids": [...]}`.
  - Any exception: `m["acoustid"] = {"error": f"{type(e).__name__}: {e}"}` plus the finding
    `("acoustid", "AcoustID lookup failed: …")`. That is a warning, never hard.
  - `recording_id` given, `recs` non-empty and `recording_id not in ids`: the finding
    `("recording", f"AcoustID says this is {title} ({top id}), not recording {recording_id}")`. That is hard
    on every tier.
  - Empty `recs`: the warning `("acoustid", "fingerprint not in AcoustID")`.
- Produces (fetch): `fetch(..., navidrome_db: Path | None = None, lookup=None, ...)`. For a crate row (not
  external):
  - `ref = _library_file(navidrome_db, wanted_id, music_root)`. It uses `scripts.export_playlists.open_ro`
    with `SELECT path FROM media_file WHERE id = ?`, and `music_root / path`, because Navidrome 0.64 stores
    library-relative paths (see `tests/test_export_playlists.SCHEMA`).
  - It returns None, and logs event kind `reference` with the reason, when `navidrome_db` is None or missing,
    the id is not found, or the file is missing: `"no reference: navidrome.db not at …"` /
    `"… not in navidrome.db"` / `"… missing on disk"`.
  - `rid = navidrome.song(wanted_id).music_brainz_id or None`.
  - The verifier is called as `verifier(landed, wanted.duration_s, tier=row["tier"], reference=ref, **extra)`,
    where `extra = {"recording_id": rid, "lookup": lookup}` **only when `lookup` is set**. That keeps
    `tests/test_fetch.header_only(path, duration, tier=None, reference=None)` valid unchanged.
  - External rows: `reference=None`; `extra` (when there is a lookup) has `recording_id=None`.
- Produces (cli): `_fetch_env()` adds
  `navidrome_db=Path(os.environ.get("NAVIDROME_DB", "/srv/docker/navidrome/navidrome.db"))` and
  `lookup=make_lookup(k) if (k := os.environ.get("ACOUSTID_KEY")) else None`.

- [ ] **Step 1: Write the fixture** `fixtures/acoustid_lookup.docs-example.json` from the response example on
  https://acoustid.org/webservice ("lookup", `meta=recordings`). Shape:
  `{"status":"ok","results":[{"id":…,"score":…,"recordings":[{"id":…,"title":…,"duration":…,"artists":[…]}]}]}`.
  The name says it is the documented example, not a live capture. Task 8 captures a live one if a key exists.
- [ ] **Step 2: Write the failing tests** in `tests/test_acoustid.py`.
  - `test_parse_docs_example`: the fixture → a list whose first item's `id` and `title` equal the fixture's
    first recording.
  - `test_parse_rejects_error_status`: `{"status":"error","error":{"message":"invalid API key"}}` → `ValueError`.
  - `test_lookup_posts_the_key_in_the_body_not_the_url`: a fake `opener(req, timeout)` that records `req`.
    Assert `"client=KEY" in req.data.decode()`, `"KEY" not in req.full_url`, `timeout == 10`, and
    `"meta=recordings"` in the body.
  - `test_verify_records_acoustid_and_fails_only_on_disagreement` (real audio via `make_audio`, `tier="medium"`):
    - `lookup=lambda p: [{"id":"r1","title":"T","score":0.9}]` with `recording_id="r1"` → `ok`, and
      `measurements["acoustid"]["recording_id"] == "r1"`.
    - With `recording_id="r2"` → not ok, and `"not recording r2"` in the problems.
    - With `recording_id=None` → ok.
  - `test_verify_lookup_error_is_a_warning`: `lookup` raises `urllib.error.URLError("down")` → `ok`,
    `"AcoustID lookup failed"` in the warnings, and `"error"` in `measurements["acoustid"]`.

  New tests in `tests/test_fetch_filing.py` (a recording verifier `def spy(path, duration, tier=None, reference=None, **kw)`
  that records its arguments and returns `verify(path, duration)`):
  - `test_crate_row_upgrade_passes_the_old_file_as_reference`: write a temp `navidrome.db` with the
    `media_file` schema from `tests/test_export_playlists.SCHEMA` and row `("s4", "Old/s4.mp3", …)`, create
    `music/Old/s4.mp3`, and pass `navidrome_db=`. Assert `spy.reference == music/"Old/s4.mp3"`.
  - `test_missing_navidrome_db_skips_the_reference_with_a_logged_reason`: `navidrome_db=tmp/"nope.db"` →
    `reference is None` and a `reference` event containing `"no reference"`.
  - `test_lookup_and_recording_id_reach_verify_only_when_a_lookup_is_configured`: without `lookup`, the spy
    gets no `lookup` kwarg. With `lookup=f`, it gets `lookup is f` and `recording_id is None` (the fake
    Navidrome song has no `musicBrainzId`). Then set `nd.state.songs["s4"]["musicBrainzId"]="rec-9"` and
    assert `recording_id == "rec-9"`.
- [ ] **Step 3: Run** `~/.local/bin/pytest -q tests/test_acoustid.py tests/test_fetch_filing.py`. Expected: FAIL.
- [ ] **Step 4: Implement** per Interfaces (`acoustid.py`, then `verify`, then `fetch`, then `cli._fetch_env`).
- [ ] **Step 5: Run** `~/.local/bin/pytest -q`. Expected: all pass.
- [ ] **Step 6: Commit**
  ```bash
  git add sourcing/acoustid.py sourcing/verify.py sourcing/fetch.py sourcing/cli.py fixtures/acoustid_lookup.docs-example.json tests/test_acoustid.py tests/test_fetch_filing.py
  git commit -m "M6: copy upgrades verify against the old file (navidrome.db, read-only); AcoustID lookup when ACOUSTID_KEY is set"
  ```

---

### Task 5: Stream tier "server" as the default (D19)

**Files:**
- Modify: `sourcing/policy.py`, `crates/store.py` (`stream_tier`, `set_stream_tier`), `crates/service.py`
  (`stream-tier` GET, `stream` route), `web/app.js` (`loadStreamTier` label), `web/index.html` (static options)
- Modify: `tests/test_tier_rows.py`. These are **required edits**: D19 changes the values these tests pin.
  - `test_stream_tier_setting_defaults_to_crate`: rename it to `..._defaults_to_server` and expect `"server"`.
  - `test_stream_mapping_matches_the_spec`: expect the dict below, and `list(STREAM) == ["server", *TIERS]`.
  - `test_stream_tier_endpoint_and_stream_by_tier`: the first assertion expects `v["tier"] == "server"`.
  - Nothing else changes.
- Test: `tests/test_stream_server.py`

**Interfaces:**
- Produces:
  - `STREAM = {"server": (None, None), "low": ("opus", 64), "medium": ("opus", 96), "high": ("opus", 160),
    "crate": ("raw", None)}`.
  - `STREAM_DEFAULT = "server"`.
  - `check_stream(name: str) -> str` raises `ValueError` for names outside `STREAM`.
  - `CrateStore.stream_tier()` returns `STREAM_DEFAULT` when unset. `set_stream_tier` validates with
    `check_stream`.
  - `/api/stream/<id>?tier=` uses `check_stream`.
  - `GET /api/stream-tier` `tiers.server == {"format": None, "maxBitRate": None}`.

- [ ] **Step 1: Write the failing tests** in `tests/test_stream_server.py`. Reuse `tests.test_service.svc`/`get`.
  - `test_server_tier_redirect_carries_no_format_or_bitrate`: `GET /api/stream/s1?tier=server` → 302. The
    Location contains `/rest/stream.view?` and has neither `format=` nor `maxBitRate`.
  - `test_fresh_store_streams_server_and_lists_it_first`: `GET /api/stream-tier` →
    `tier == "server"` and `list(tiers)[0] == "server"`.
  - `test_web_menu_labels_server`: `index.html` contains `value="server" selected` and
    `server · Navidrome decides`. `app.js` contains `Navidrome decides`.
- [ ] **Step 2: Run** `~/.local/bin/pytest -q tests/test_stream_server.py`. Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces.
  - In `app.js`, the option label is
    `t.format == null ? `${name} · Navidrome decides` : t.format === "raw" ? `${name} · original` : `${name} · ${t.format} ${t.maxBitRate}k``.
  - In `index.html`, the first option is `<option value="server" selected>server · Navidrome decides</option>`,
    and `selected` comes off `crate`.
  - Make the three `test_tier_rows.py` edits listed above.
- [ ] **Step 4: Run** `~/.local/bin/pytest -q tests/test_stream_server.py tests/test_tier_rows.py tests/test_service.py`. Expected: PASS.
- [ ] **Step 5: Commit**
  ```bash
  git add sourcing/policy.py crates/store.py crates/service.py web/app.js web/index.html tests/test_stream_server.py tests/test_tier_rows.py
  git commit -m "M6: stream tier 'server' (no format, no maxBitRate: Navidrome's player profile decides) is the default (D19)"
  ```

---

### Task 6: The worker loop, `sourcing.cli worker`, and the preferred candidate

**Files:**
- Create: `sourcing/worker.py`
- Modify: `sourcing/fetch.py` (`prefer`)
- Modify: `crates/store.py` (`verify_ids`)
- Modify: `sourcing/cli.py` (`worker` subcommand; `fetch --approve` records an approval)
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes:
  - `pending_approvals() -> list[dict]` and `mark_approval_used(id, result)` (Task 1), with the approval dict
    `{"id", "wanted_id", "approved_by", "candidate", "tier", "ts", "used_at", "result"}`.
  - `fetch(..., filer=, navidrome_db=, lookup=)` (Tasks 3–4), `_fetch_env()` (cli, Tasks 3–4).
- Produces:
  - `fetch(..., prefer: dict | None = None, ...)`. After ranking, when `prefer` is given:
    - If a non-rejected candidate has the same `username` and `filename`, it becomes `best`, and the event
      `pick` gets the detail `"approved candidate still offered: <basename>"`.
    - Otherwise the top-ranked candidate is used, with the detail
      `"approved candidate no longer offered; using the top-ranked <basename>"`.
  - `CrateStore.verify_ids() -> list[str]`: the wanted ids (crate song ids in enabled crates, and `ext-N`)
    whose status is `verify`, distinct, in a stable order.
  - `Worker` and `TickReport`:
    ```python
    @dataclass
    class TickReport:
        approvals: int
        rechecked: int
        results: list[str]           # "<wanted_id>: <status>: <reason>"

    class Worker:
        def __init__(self, *, store, slskd, navidrome, reconciler, fetch_kwargs: dict, fetcher=fetch, log=print): ...
        def tick(self) -> TickReport: ...
        def run(self, poll_s: float, *, ticks: int | None = None) -> None: ...
    ```
  - `tick()`:
    1. Re-check: for each `store.verify_ids()`, `fetcher(id, approve=True, **common)`. The `verify` path
       downloads nothing.
    2. For each pending approval: `mark_approval_used(a["id"], "started")` **first**. Then
       `r = fetcher(a["wanted_id"], approve=True, prefer=a["candidate"], **common)` and
       `mark_approval_used(a["id"], f"{r.status}: {r.reason}")`.
    3. An exception from one row: `mark_approval_used(a["id"], f"error: {type(e).__name__}: {e}")`, a
       `log(...)` line, then the next row.
    4. It ends with `log(f"tick: {n} approvals, {m} rechecked")`. "0 approvals" is what the live check reads.
  - `common` is `dict(store=, slskd=, navidrome=, reconciler=, **fetch_kwargs)`. No `tier` is passed: the
    row's current tier rules, and the approval's `tier` is a record of what was approved.
  - `run()` loops `tick()` and `time.sleep(poll_s)`. An exception from `tick` itself (slskd or Navidrome
    down, DB locked) is logged and the loop goes on. `ticks` bounds the loop for tests.
  - CLI: `python -m sourcing.cli worker [--once]`. It needs `SLSKD_URL`/`SLSKD_API_KEY` and
    `SUBSONIC_USER`, as `fetch` does. It builds `CrateApp(Config.from_env())`,
    `Worker(..., fetch_kwargs=_fetch_env())` and `--once` → `tick()`, else
    `run(float(os.environ.get("WORKER_POLL_S", "30")))`. Output uses `print(..., flush=True)`.
  - CLI `fetch --approve` first calls `store.approve(wanted, "michael", None, row tier)`, then marks it used
    with the result (D23: every download carries an approval). The roots and filer refusals still come
    first, so a refused run records nothing.

- [ ] **Step 1: Write the failing tests** in `tests/test_worker.py`. Reuse `tests.test_fetch.world`, `run`,
  `new_song`, `good_flac_bytes`, `GOOD`, `RESPONSES`. Helper
  `worker(world, srv, **kw) = Worker(store=…, slskd=SlskdClient(srv.url,"k"), navidrome=…, reconciler=…,
  fetch_kwargs=dict(music_root=…, downloads_root=…, filer=world["filer"], verifier=header_only, poll_s=0.01,
  download_timeout_s=1, scan_timeout_s=1), log=lines.append, **kw)`.
  - `test_tick_with_no_approvals_downloads_nothing`: s4 is `needs_source` with no approval. Assert
    `tick().approvals == 0`, `srv.enqueued == []` and `lines[-1] == "tick: 0 approvals, 0 rechecked"`.
  - `test_tick_fetches_an_approved_row_and_spends_the_approval`: `approve("s4","michael",None,"crate")` and
    `new_song`. After `tick()`: the playlist is `["s3","s9","s5"]`, `pending_approvals() == []` and
    `approval("s4")["result"].startswith("ok:")`.
  - `test_approved_candidate_is_preferred_while_offered`: `cands = rank(RESPONSES, Wanted("Chic","Good Times",
    "Risqué",501,1979), TIERS["crate"])`, and `second` = the second non-rejected candidate. Serve
    `files={second.filename: bytes}`, approve with `second.as_dict()`, and register `new_song` with that size.
    Assert `srv.enqueued == [(second.username, second.filename)]` and a `pick` event containing
    `"still offered"`.
  - `test_gone_candidate_falls_back_to_the_top_ranked`: the candidate `{"username":"x","filename":"gone.flac"}`.
    Assert `srv.enqueued[0][1] == GOOD` and a `"no longer offered"` event.
  - `test_one_failing_row_does_not_stop_the_tick`: `fetcher` is a stub that raises `RuntimeError("boom")` for
    `ext-1` and returns `FetchResult("ok","fine")` otherwise. With two approvals, assert the results are
    `error: RuntimeError: boom` and `ok: fine`.
  - `test_tick_rechecks_verify_rows_without_downloading`: run `run(world, srv, approve=True)` without `new_song`,
    which leaves `verify`. Then `new_song` and `tick()`. Assert the row is `ok`, `len(srv.enqueued) == 1`
    (no second download) and `rechecked == 1`.
  - `test_run_survives_a_tick_exception`: `Worker.tick` patched to raise once and then return. `run(0, ticks=2)`
    returns, and one log line contains the exception.
  - `test_cli_worker_once`: env via `tests.test_tier_rows._cli_env` plus `BEETS_CONFIG=<tmp copy of deploy/beets.yaml>`.
    Assert `cli.main(["worker","--once"]) == 0` and `"0 approvals"` in stdout.
  - `test_cli_fetch_approve_records_an_approval`: in-process, with `MUSIC_ROOT`/`DOWNLOADS_ROOT` dirs present,
    a fake slskd serving `GOOD`, and `sourcing.cli.BeetsFiler` monkeypatched to
    `lambda cfg: BeetsFiler(cfg, library=lib, runner=fake_beet(...), tagger=lambda p, n: [])`. Assert
    `CrateStore(db).approval("s4")["approved_by"] == "michael"` and `used_at` is set.
- [ ] **Step 2: Run** `~/.local/bin/pytest -q tests/test_worker.py`. Expected: FAIL (`ModuleNotFoundError: sourcing.worker`).
- [ ] **Step 3: Implement** `prefer` in `fetch`, `verify_ids`, `sourcing/worker.py` and the CLI per Interfaces.
  Add the `worker` line to the CLI module docstring.
- [ ] **Step 4: Run** `~/.local/bin/pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit**
  ```bash
  git add sourcing/worker.py sourcing/fetch.py sourcing/cli.py crates/store.py tests/test_worker.py
  git commit -m "M6: worker loop (approved rows only, verify rows re-checked), sourcing.cli worker [--once], approved candidate preferred (D18, D23)"
  ```

---

### Task 7: Image, compose, slskd downloads folder, beets header, docs

No new Python behaviour. The checks here are build and config checks. **Do not start the worker or restart
anything in this task**: the live steps are Task 8.

**Files:**
- Modify: `Dockerfile`, `deploy/compose.yml`, `deploy/beets.yaml` (header)
- Create: `docs/worker.md`
- Modify: `README.md` (`worker.py`, `acoustid.py` lines; a pointer to `docs/worker.md`)

- [ ] **Step 1: Dockerfile.** After `FROM`:
  ```dockerfile
  RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg flac libchromaprint-tools \
      && rm -rf /var/lib/apt/lists/*
  RUN pip install --no-cache-dir beets==1.6.0 mediafile==0.12.0 confuse==2.0.1   # = the host's working set
  ```
  Also add `COPY deploy/beets.yaml deploy/beets.yaml`, so `_fetch_env`'s default `/app/deploy/beets.yaml` exists.
- [ ] **Step 2: Compose.**
  - In `slskd.volumes`, `/srv/incoming:/app/downloads` becomes `/srv/incoming/soulseek:/app/downloads`.
    This also stops exposing `library-import` to slskd.
  - Add the `worker` service:
    ```yaml
    worker:                                  # D18: the only process that downloads or runs beets
      user: "1000:1000"
      build:
        context: ${CRATES_SRC:?set CRATES_SRC=<repo checkout> in /srv/docker/.env}
      command: ["python", "-m", "sourcing.cli", "worker"]
      environment:
        SUBSONIC_URL: http://navidrome:4533
        SUBSONIC_USER: ${ND_USER}
        SUBSONIC_PASS: ${ND_PASS}
        CRATES_DB: /data/crates.db
        SLSKD_URL: http://gluetun:5030
        SLSKD_API_KEY: ${SLSKD_API_KEY}
        ACOUSTID_KEY: ${ACOUSTID_KEY:-}        # optional; empty = no AcoustID lookup
        MUSIC_ROOT: /srv/music
        DOWNLOADS_ROOT: /srv/incoming/soulseek
        NAVIDROME_DB: /srv/docker/navidrome/navidrome.db
        BEETSDIR: /srv/docker/beets            # beets' own dir (uid 1000 has no home in the image)
        WORKER_POLL_S: "30"
      volumes:                               # identical paths: beets stores absolute paths in library.db
        - /srv/music:/srv/music
        - /srv/docker/beets:/srv/docker/beets
        - /srv/incoming/soulseek:/srv/incoming/soulseek
        - /srv/docker/crates:/data
        - /srv/docker/navidrome:/srv/docker/navidrome:ro
      depends_on: [navidrome, gluetun]
      restart: unless-stopped
    ```
  - Update the `crates` comment on `fetch --approve` to say "approve in the web client; the worker downloads".
- [ ] **Step 3: beets.yaml header.** Replace the first two comment lines with:
  `# beets config. Since M6 the worker container is the ONLY process that runs beets: it imports each verified
  # download with `beet import -q -s -m -W` from its own <downloads>/.staging/<id>-<ts>/ folder (sourcing/filer.py)
  # and runs `beet write` on that new file only after a MusicBrainz match. Do not run beet on the host.`
  Keep the existing DO-NOT block.
- [ ] **Step 4: `docs/worker.md`** for Michael, in prose with short lists. Cover:
  - What the worker does each tick.
  - Approvals: Preview → Approve → "waiting for worker"; `approved_by` values now and later (D23).
  - Filing: staging → beets → as-is vs matched (D22), `duplicate_action: keep` and why, names copied back
    (`renamed:` events).
  - Copy upgrades (reference fingerprint; AcoustID only with `ACOUSTID_KEY`, which Michael adds to
    `/srv/docker/.env` if he wants it).
  - The stream "server" default (D19).
  - Where files land, how to watch it (`docker compose logs -f worker`), and how to stop it
    (`docker compose stop worker`).
- [ ] **Step 5: Static checks.**
  - `cd /srv/docker && docker compose config --quiet && echo OK` → `OK`. Do not print `docker compose config`
    output: it contains secrets.
  - `~/.local/bin/pytest -q` → all pass.
- [ ] **Step 6: Commit**
  ```bash
  git add Dockerfile deploy/compose.yml deploy/beets.yaml docs/worker.md README.md
  git commit -m "M6: worker service (identical-path mounts), slskd downloads → /srv/incoming/soulseek, image gains ffmpeg/flac/fpcalc/beets 1.6.0, docs/worker.md"
  ```

---

### Task 8: Live verification (checklist, run by the controller or one agent; no code)

Nothing here approves, downloads or writes to the library. When a step fails, stop and record what you saw.
Do not improvise a fix on the live box.

- [ ] 1. `mkdir -p /srv/incoming/soulseek` (as mh550, no sudo). `ls -ld /srv/incoming/soulseek` shows mh550.
- [ ] 2. `cd /srv/docker && docker compose up -d --build crates worker` succeeds.
- [ ] 3. `docker compose up -d slskd` (slskd only: gluetun is not recreated). Then
  `docker compose exec -T crates python3 -c "import os; from sourcing.slskd_client import SlskdClient; c=SlskdClient(os.environ['SLSKD_URL'], os.environ['SLSKD_API_KEY']); print(c._get('/server')['state'])"`,
  or the equivalent existing CLI/API call already used in M4. Expected: contains `LoggedIn`.
- [ ] 4. `docker compose ps` shows navidrome, crates, gluetun, slskd and worker `running`/`healthy`, with no
  restart loop.
- [ ] 5. Tools in the worker: `docker compose exec -T worker sh -c 'beet version | head -1; ffmpeg -version | head -1; fpcalc -version; flac --version'`
  shows `beets version 1.6.0` and the others.
- [ ] 6. Offline beets smoke test inside the worker, on a throwaway library under `/tmp` **inside the
  container** (never `/srv/docker/beets`): copy `deploy/beets.yaml` with the four paths into `/tmp/t` and
  `musicbrainz: {host: 127.0.0.1:9}`, generate a 2 s FLAC with ffmpeg under `/tmp/t/dl/.staging/x-1/`, and run
  `BEETSDIR=/tmp/t beet -c /tmp/t/cfg.yaml import -q -s -m -W /tmp/t/dl/.staging/x-1`. Expected:
  `Importing as-is.` and the file under `/tmp/t/music/…/Singles/`. If the import fails (a pip dependency
  mismatch), record the traceback under Needs Michael. Do not change pins blindly.
- [ ] 7. Navidrome DB read-only from the worker:
  `docker compose exec -T worker python -c "from scripts.export_playlists import open_ro; print(open_ro('/srv/docker/navidrome/navidrome.db').execute('select count(*) from media_file').fetchone())"`.
  Expected: one number, about 831.
  - If it fails with `unable to open` or `readonly` (WAL on a read-only mount), record it. The fallback
    proposal for the controller is `?mode=ro&immutable=1` in a new `open_ro(db, immutable=True)` variant. It
    is good enough for old-file path lookups.
- [ ] 8. `docker compose logs --tail 20 worker` shows at least one `tick: 0 approvals, 0 rechecked` line, and no
  traceback.
- [ ] 9. Optional, only if `ACOUSTID_KEY` is already in `.env`: don't check by reading the file. Use
  `docker compose exec -T worker sh -c 'test -n "$ACOUSTID_KEY" && echo set || echo unset'`. If set, capture
  one live lookup of a library FLAC (a copy in `/tmp` inside the container) into
  `fixtures/acoustid_lookup.sample.json`, with the key never printed. Re-run `tests/test_acoustid.py`
  against it, and keep the docs example as well.
- [ ] 10. Browser check with Playwright: open `http://127.0.0.1:4580/` and take screenshots.
  - The Wanted tab, saved as `docs/screenshots/m6-wanted.png`. Rows show a Preview button. Pressing
    Preview on one row is allowed (search only). **Do not press Approve.**
  - The player menu, showing `server · Navidrome decides` selected, saved as `docs/screenshots/m6-stream-server.png`.
  - Check that no Soulseek username is visible in either screenshot before committing them.
- [ ] 11. "What Michael will see": 10 random tracks via the Subsonic API (artist / title / album / playlist)
  in the Status log. M6 changes no library file, so this is a no-change confirmation.
- [ ] 12. Commit the screenshots by name. Then the controller runs the whole-milestone review
  (`superpowers:requesting-code-review`, most capable model) and `/simplify`.
