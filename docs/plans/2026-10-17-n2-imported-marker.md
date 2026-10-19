# N2: the `#imported` marker moves into crates.db (D33) — Implementation Plan

> REQUIRED SUB-SKILL: superpowers:executing-plans (inline) with superpowers:test-driven-development.
> **Nothing in N2-02..N2-04 writes to the live Navidrome or the live `crates.db`.** Every task is built against
> `subsonic/fake_server.py` and `CrateStore()` / `tmp_path`. The live migration of the two marked playlists is
> Michael's, from the runbook at the end (a playlist comment write).

**Goal:** "this playlist was made by import-playlist" lives in a crates.db table, not in the playlist comment.
import-playlist decides "ours" (re-run vs `NameCollision`) from that table and writes no `#imported` anywhere. Under
`CRATES_OWNER=app` (live) it writes no comment at all, so a created playlist's comment stays empty (D33: "playlist
comments are left empty by this system"). A one-time command records the playlists whose comment still carries the
marker and then strips it.

**Checked against the code 2026-10-19** (after N1F and H1–H3; the line numbers below hold at `73c6d96`). **Facts (2026-10-17):** two live playlists still carry the marker: "Tea tent" and "shakori (Spotify)" (`docs/next-todos.md`
item 2). Navidrome playlist ids are UUIDs that are never reused, so a row whose playlist was deleted can never match
a new playlist; dropping such rows is N3's housekeeping (`forget_playlist`), not a correctness need here. The test
suite runs with `CRATES_OWNER=comment` (`tests/conftest.py`), so most import tests exercise the retired D21 path;
the live path is tested in `tests/test_app_owner.py`.

## Today (what reads or writes the marker)

| Where | What it does with `#imported` |
|---|---|
| `sourcing/import_playlist.py:38-44` | `MARKER`, `_MARKER_TOKEN` (whole token, any case), `is_imported(comment)` |
| `import_playlist.py:49-54` | `NameCollision` message: "… is not marked #imported" |
| `import_playlist.py:256-263` | `_rerun_comment`: `--merge` on a foreign playlist appends `MARKER`; a given tier rewrites `#tier:` (comment owner) |
| `import_playlist.py:295` | `ours = existing is not None and is_imported(existing.comment)` |
| `import_playlist.py:327` | a created playlist gets `#imported` (app) or `#imported #tier:<t>` (comment) |
| `crates/migrate_attrs.py:17,47` | `plan`: an `#imported` playlist with no tier gets `#tier:<t>` (M8, refused under app) |
| `sourcing/cli.py:214-215` | prints `NameCollision` + "; re-run with --merge to add to it, or pick another --name" |

Nothing else in `crates/`, `sourcing/`, `scripts/` or `web/` reads it (grep `MARKER\|is_imported\|#imported`).
Reconcile under app never reads comments; under comment it parses `#crate` / `#tier:` only (`crates/attrs.py`), and
`#imported` is just another word there.

## Design

### The table (N2-02) — `crates/store.py`

Added to `SCHEMA` beside `imported_entries`; `CREATE TABLE IF NOT EXISTS` creates it in an existing crates.db on
the next open, so `_migrate` needs no change.

```sql
CREATE TABLE IF NOT EXISTS imported_playlists (   -- playlists import-playlist made or adopted (D33; was #imported)
  playlist_id TEXT PRIMARY KEY, name TEXT,        -- name: as last imported (for `imported list` only)
  source TEXT,                                    -- the import's source text, or 'migrated' (N2-03)
  imported_at REAL                                -- first recorded
);
```

| Method | Behaviour |
|---|---|
| `mark_playlist_imported(playlist_id, name, source, detail=None) -> bool` | `INSERT … ON CONFLICT(playlist_id) DO UPDATE SET name=excluded.name`: `source` and `imported_at` stay those of the first record. Returns True when the row is new; then logs one event (`self.log(playlist_id, None, "imported", …)`), detail `detail or f"made by import-playlist: {source}"` (the migration passes its own, see N2-03). Does not commit (like `mark_imported`); the caller commits. |
| `is_playlist_imported(playlist_id) -> bool` | the row exists |
| `imported_playlists() -> list[dict]` | every row, `ORDER BY name, playlist_id` |
| `forget_playlist` (N3) | N3-01's `forget_playlist(playlist_id)` also deletes the `imported_playlists` row, in the same "no rows in flight" branch that deletes `imported_entries`. N2 adds no deleter. |

The flag is per playlist **id**. A playlist deleted and re-created in Navidrome under the same name (new id) is
foreign to import until re-imported with `--merge` or migrated; that is the safe direction (D11's 2026-10-14 lesson:
never merge into a playlist we did not make).

### import-playlist (N2-02) — `sourcing/import_playlist.py`

- `ours = existing is not None and store.is_playlist_imported(existing.id)`. `is_imported(comment)` is no longer
  called here.
- `NameCollision` message: `playlist 'X' already exists (<id>) and is not recorded as imported in crates.db (re-run
  with --merge to adopt it)`. `sourcing/cli.py` stops adding its own `--merge` hint, so the hint is said once:
  it prints `f"{e}, or pick another --name"`. `test_sourcing_cli.test_import_playlist_name_collision_needs_merge`
  still finds `--merge` in stderr.
- **Created playlist:** `create_playlist`, then at once `store.mark_playlist_imported(id, name, source)` and
  `store.commit()`, before anything else can fail, so a crash after the create leaves a playlist the next run calls
  ours (today that window is the comment write). Then `update_playlist(public=True)`.
  - owner `app`: no comment write at all (no `updatePlaylist` with a `comment` parameter); `comment` stays `""`.
  - owner `comment`: the comment is `attrs.write("", tier=tier or IMPORT_TIER)` → `#tier:medium`, written with
    `write_comment` (read back, `CommentNotKept` handled as today), then `Reconciler.refresh_cache` (as built, the
    two helpers named here and below are inlined).
- **Existing playlist, ours:** append as today. `_rerun_comment(old, tier)` loses `ours` and never appends `MARKER`;
  it returns a new comment only when `tier` is given under owner comment (D15), else `None`. Under app it is never
  called (`tier` has no effect on the comment, as today).
- **Existing playlist, foreign, `merge=True`:** `mark_playlist_imported(existing.id, name, source)`; the comment is
  left byte for byte (owner comment with `--tier`: only `#tier:` is rewritten, as today). Visibility stays alone.
- **Dry run:** records nothing, as today (the dry run of a foreign playlist still needs `--merge`).
- `MARKER`, `_MARKER_TOKEN` and `is_imported` stay in `import_playlist.py` as the **legacy reader**: used only by
  `crates/migrate_attrs.py` (unchanged, retired under app) and the N2-03 migration. The `MARKER` comment says so.
- Under app, `_write_comment_and_cache` was the only `refresh_cache` call, which only refreshed `crates.name`; the
  next reconcile does the same, so nothing is lost by not calling it.

### The migration (N2-03) — `python -m crates.cli imported migrate [--apply]`, `imported list`

New module `crates/imported.py` (small, testable without the CLI): `plan(client, store) -> list[Step]`,
`apply(client, store, steps) -> (migrated names, failures)`, `strip_marker(comment) -> str`. As built, `--apply`
re-reads each playlist first and refuses one whose comment changed since the plan ("comment changed since the plan;
run again"), and the dry run ends with "Dry run: nothing was written…".

For every playlist in `client.playlists()` whose comment `is_imported()` (whole token; `x#imported` is not):

| Case | Dry run (default) prints | `--apply` does |
|---|---|---|
| owner is not `client.user` | `skipped: owned by <owner>: <name> (<id>)` | nothing (never written) |
| ours, no row yet | `would record + strip: <name> (<id>): <old>  →  <new>` | 1. `mark_playlist_imported(id, name, "migrated")` with event detail `migrated from comment <old>` (the old comment verbatim: the event is the reverse log), `commit()`. 2. `write_comment(client, pl, strip_marker(old))` (sends, reads back). |
| ours, row already there (an earlier strip failed) | `would strip: …` | step 2 only, after an `imported` event `stripped the marker from comment <old>` (committed; as built in N5-02, so a row adopted with `--merge` keeps its old comment too) |

- Order is the safety rule: the row is committed **before** the comment loses the token, so at no moment is the
  playlist foreign to import. A `CommentNotKept` (or any `update_playlist` error) leaves the row recorded, names the
  playlist on stderr, carries on with the next one, and the command exits 1. A re-run finishes the strip.
- A second `--apply` finds no token and prints `nothing to migrate` (exit 0).
- `strip_marker`: each whole token, with the spaces/tabs around it, becomes one space; a space left at the start or
  end of that line is dropped; newlines and the other lines are kept byte for byte. Tests take this table:

  | old | new |
  |---|---|
  | `#imported` | `""` (empty string, sent as `comment=`; never `None`, which would send nothing) |
  | `Tea #imported notes` | `Tea notes` |
  | `mine #imported` | `mine` |
  | `#imported #tier:medium` | `#tier:medium` |
  | `sunset only\n#imported #tier:medium` | `sunset only\n#tier:medium` |
  | `x#imported #IMPORTED` | `x#imported` |

- Owner-independent: the marker meant the same under both owners. Under owner comment, stripping leaves `#crate` /
  `#tier:` untouched, so the cached tier does not change and no `refresh_cache` is needed.
- **Unverified fact:** whether Navidrome 0.64.2's `updatePlaylist` with an empty `comment=` clears the comment (the
  fake does). `write_comment` reads back, so if it does not, the run says `CommentNotKept` for that playlist and
  nothing is lost. Live, the runbook checks the one empty case first (see below). Add the answer to
  `docs/hard-won-facts.md` either way.
- `imported list`: one line per row, `playlist_id  name  source  imported_at` (local time, `%Y-%m-%d %H:%M`), or
  `no imported playlists`.
- `crates/cli.py`: an `imported` parser with `migrate` (`--apply`) and `list`, like `attrs migrate`. It runs in the
  crates container (Subsonic + crates.db), beside the daemon (the only writer of these rows is import-playlist,
  which Michael runs by hand).

### Review and docs (N2-04)

Diff review against the invariants below; then `docs/architecture.md` §3 owner row ("Made by import-playlist" →
crates.db `imported_playlists`, D33, built), the "Playlist comment" bullet (left empty by this system), §4(a) steps 3
and 4, `docs/next-todos.md` item 2 ("built (N2); live migration pending"), the pivot spec's "Consequences in the code"
bullet for `import_playlist`. `_rerun_comment` and `_write_comment_and_cache` may shrink to the owner-comment tier write.

**Done (N2-04, 2026-10-19):** both helpers inlined (one caller each, owner comment only); `--merge` never adopts
another user's playlist (`NameCollision` names the owner); a re-run of ours refreshes the row's name; an adoption's
event says `adopted with --merge: <source>`. Tests: the re-created playlist (new id) is foreign until `--merge`.

## Invariants (each is a test)

1. Every path that decides "ours" reads the store; no code path writes `#imported` (a grep in N2-04, plus the
   app-owner request-log test).
2. Under app, an import (create, re-run, merge) sends no `updatePlaylist` with a `comment` parameter.
3. A playlist with `#imported` in its comment but no row is foreign to import-playlist (`NameCollision`).
4. The migration commits the row before it changes the comment; a failed comment write leaves the row.
5. The migration never writes another user's playlist, and never touches a lookalike (`x#imported`, `#imported-old`).
6. A dry run (import or migration) writes neither crates.db nor Navidrome.

## Tests that change (by name)

| Test | Change |
|---|---|
| `tests/test_crates.py` (new) | `test_imported_playlists_table_survives_reopening` (tmp_path DB: mark, close, reopen, `is_playlist_imported`); `test_mark_playlist_imported_keeps_the_first_source_and_refreshes_the_name` (second call returns False, one event) |
| `tests/test_import_playlist.py::test_import_marks_its_playlists_so_reruns_need_no_merge_flag` | asserts `store.is_playlist_imported(first.playlist_id)` and `"#imported" not in comment`, not the comment marker |
| `…::test_import_refuses_a_foreign_playlist_unless_merge_and_never_publishes_it` | adds: no row after the refusal and after the dry run; a row after `merge=True` |
| `…::test_marker_is_a_token_not_a_substring` | unchanged: it tests the legacy reader `is_imported` only |
| `…::test_a_lookalike_marker_is_a_foreign_playlist_for_import` | renamed `test_a_comment_marker_without_a_row_is_a_foreign_playlist`: a hand-made playlist with comment `old #imported` (a *real* token) raises `NameCollision`; `merge=True` records the row and leaves `old #imported` byte for byte |
| `…::test_a_comment_write_error_after_the_add_still_records_our_facts_and_reports` | kept (owner comment: the `#tier:` write on creation); adds `store.is_playlist_imported(pid)` |
| `tests/test_attrs_owner.py::test_import_create_whose_comment_is_not_kept_raises_but_keeps_our_own_facts` | the lossy fake drops `#tier:` from the creation's `#tier:medium`, so `CommentNotKept` is still raised; expect `comment(srv, pid) == ""` (was `#imported`) and add `store.is_playlist_imported(pid)` (the row is committed before the comment write) |
| `tests/test_app_owner.py::test_import_leaves_no_tier_in_the_comment` | renamed `test_import_writes_no_comment`: comment `== ""` after the create and after a re-run; no `("updatePlaylist", q)` in `srv.state.requests` with `"comment" in q`; plus a `merge=True` case on a foreign playlist with comment `mine`, which stays `mine` |
| `tests/test_attrs_owner.py::test_import_creates_the_playlist_with_imported_and_tier` | renamed `…_with_its_tier`: `#tier:medium`, `#tier:high`, `#crate`, `#tier:medium` |
| `…::test_import_rerun_with_tier_keeps_michaels_text` | hand-set comment `sunset only\n#tier:medium` (no marker); expectations drop `#imported` |
| `…::test_import_adopting_with_merge_adds_the_marker_and_the_tier` | renamed `…_records_the_row_and_adds_only_the_tier`: `mine` stays `mine`; with `tier="high"` → `mine #tier:high`; the row is recorded |
| `tests/test_derived_tiers.py::test_import_rerun_without_tier_queues_new_rows_at_the_comments_tier` | hand-set comment `#tier:high`; expectation `#tier:high` |
| `…::test_import_rerun_without_tier_matches_at_the_comments_tier` | hand-set comment `#crate` |
| `…::test_import_into_a_playlist_named_as_a_crate_matches_and_queues_at_crate` | the hand-made `Tea tent [crate]` is foreign now: drop the `#imported` comment and pass `merge=True` |
| `tests/test_sourcing_cli.py::test_import_playlist_name_collision_needs_merge` | unchanged (stderr still names `--merge`) |
| `tests/test_migrate_attrs.py`, `tests/test_attrs.py` | unchanged (legacy reader; `#imported` is plain text to `attrs`) |
| `tests/test_imported_migrate.py` (new, N2-03) | the cases in the migration table and the `strip_marker` table; `imported list`; `main(["imported", "migrate"])` exit codes 0 / 1 |

## Tasks

- **N2-02** store table + import-playlist switch + the test edits above (not the migration).
- **N2-03** `crates/imported.py`, `crates.cli imported migrate | list`, `tests/test_imported_migrate.py`, the
  `docs/architecture.md` §8 row "Record a hand-made import / strip old markers: `crates.cli imported migrate --apply`".
- **N2-04** review from `$HARNESS_SCRATCH/n2.diff`, simplify, docs.

## Live runbook (Michael, after N2-02/03 are deployed with `scripts/deploy.sh`)

1. `sqlite3 /srv/docker/crates/crates.db ".backup /srv/docker/crates/crates.db.pre-n2.snap"` and the same for
   `navidrome.db`; note the running image.
2. `docker compose exec -T crates python -m crates.cli imported migrate`: expect exactly "Tea tent" and
   "shakori (Spotify)" as `would record + strip`, with their old and new comments.
3. `… imported migrate --apply`; then `… imported list` shows both rows (source `migrated`), and in Navidrome both
   comments no longer say `#imported`. A `CommentNotKept` for an empty comment means Navidrome ignores `comment=`:
   stop and log it (the rows are recorded, so import-playlist already treats both as ours).
4. Re-run `… imported migrate`: `nothing to migrate`. A dry run of `sourcing.cli import-playlist` on "Tea tent"
   reports `updated existing playlist`, not `NameCollision`.
5. Undo: the `imported` events hold each old comment; set it back in Navidrome (or from the navidrome.db snapshot) and
   delete the row (`DELETE FROM imported_playlists WHERE playlist_id=…`).
