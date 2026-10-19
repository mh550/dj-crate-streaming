# N4: a downloaded track goes into its playlist at its Spotify position — Implementation Plan

> REQUIRED SUB-SKILL: superpowers:executing-plans (inline) with superpowers:test-driven-development.
> **Nothing in N4-02..N4-05 writes to the live Navidrome or the live `crates.db` by hand.** Every task is built
> against `subsonic/fake_server.py` (with its `navidrome.db` mirror) and `CrateStore()`. Once deployed, placement
> happens only for playlists whose import was re-run after the deploy (they get an `import_order`), and only when a
> wanted track of theirs is filed.

**Goal:** M9 item 1 (`docs/specs/2026-10-17-m9-remaining-ownership.md` §1, `docs/next-todos.md` item 4). An external
row filed into the library today ends `ok` and stays out of its playlist; a re-run of `import-playlist` appends it at
the end, so a Spotify-ordered set loses its order. After N4 the worker inserts it after its nearest earlier Spotify
neighbour still in the playlist (else before the nearest later one, else at the end), once, insert-only, through
`playlist_edit.rewrite`. Q1 and Q2 are answered by their defaults (D44 *default*, below).

## Today (checked against `b7b8b87`)

- `import_playlist` (`sourcing/import_playlist.py:263`): `matches = [match(...) for r in rows]` in Spotify order
  (`m.row.position`, 1-based); a matched row's `m.song_id` is switched to a copy already in the playlist (`present`)
  when one of its candidates is. `ordered` (matched song ids, deduplicated) → `new_ids` (not in `present`) are
  created/appended; `store.mark_imported(playlist_id, ordered)` records them in `imported_entries` (D13: removed stays
  removed). `pending` = the non-matched rows (`missing` and `ambiguous`); each becomes `store.add_external_wanted(...,
  playlist_id, position)`, which returns the existing id when the lead artist/title is already queued
  (`find_external`) and **overwrites** its `playlist_id`/`position` (M9 §1's "last slot wins"). Ambiguous ones go to
  `review`. A dry run writes nothing. A re-run also sets a queued row whose track is now matched to `ok` ("in library:
  <song>"), without `library_song_id`.
- `fetch.finish` (`sourcing/fetch.py:220`) has two sites that end an external row `ok`:
  1. `copy_id is None`: `store.set_library_song(wanted_id, new.id)`, `set_status("ok", done)` (line 256-258);
  2. via `replace._settle` (`sourcing/replace.py:317`): a copy upgrade of play-now's provisional song repointed every
     playlist; the row gets `set_external_song(wid, new_song_id, False)` and `ok`.
  3. the unproven-copy accept in the web app's process (`crates/proposals.py:257-260`): the external row names the
     new copy, `provisional` 0, `ok`.
  The provisional branch (line 234-254): a play-now copy that already meets the row's tier (verified at least as
  strictly, `judge` ok) becomes the row's file (`provisional` 0) and falls through to site 1. Under the live policy
  (`deploy/policy.toml`: the four tiers identical, `strict_verify = true`, D24/D30) that is always the case, so a
  play-now copy ends `ok` with its `library_song_id` too. Otherwise (legacy, tiers differ) the row goes back to
  `needs_source` with `provisional` 1 and becomes `ok` only through site 2.
- `Worker._tick` (`sourcing/worker.py:216`): play-now approvals, `reconcile_due`, `verify` re-checks (each at most
  every `recheck_s`, `WORKER_RECHECK_S` 300 in `deploy/compose.yml:96`), other approvals, `advance_replacements`
  (jobs open at tick start), `export_due`. `self.common` (the fetch kwargs) carries `navidrome` and `navidrome_db`.
- `crates/playlist_edit.py`: `checked_entries(client, db, pid)` (raises `NotOwned` unless getPlaylist's owner is the
  client's user, `NotEditable` for a smart playlist, `PlaylistSkew` when getPlaylist and `navidrome.db` disagree, e.g.
  a hidden missing row); `rewrite(client, db, pid, before, after)` (`PlaylistChanged` when the playlist is not
  `before`; refuses to add a song that is not present in `navidrome.db`; one `updatePlaylist` that removes from the
  first differing index to the end and re-adds the tail; readback, else `EditNotKept`, which is *not* a refusal).
- `CrateStore` (`crates/store.py`): `imported_entries(playlist_id, song_id)`, `imported_playlists` (N2, D37;
  `is_playlist_imported`), `external_wanted.library_song_id`/`provisional`, `forget_playlist` (N3, D43: deletes a
  vanished playlist's rows once none waits; its docstring and the N3 plan expect N4's tables to join it).
- No `import_order`, no `placements`, no `crates/placement.py`. `docs/architecture.md` §10 quirk 18 ("Filed external
  rows are not put in their playlist") is open.

## The change

### Tables (crates/store.py `SCHEMA`, `CREATE TABLE IF NOT EXISTS`, so an old crates.db gains them on open)

```sql
CREATE TABLE IF NOT EXISTS import_order (       -- every row of the last real import of a playlist, Spotify order (N4)
  playlist_id TEXT NOT NULL, position INTEGER NOT NULL,  -- Row.position (1-based)
  song_id TEXT,                                 -- the Navidrome song it matched (after the `present` switch), or NULL
  wanted_id TEXT,                               -- the ext-N row it queued (missing / ambiguous), or NULL
  PRIMARY KEY (playlist_id, position)
);
CREATE TABLE IF NOT EXISTS placements (         -- one per (wanted row, playlist), ever (M9 §1)
  wanted_id TEXT NOT NULL, playlist_id TEXT NOT NULL,
  song_id TEXT,                                 -- the song placed (or tried)
  state TEXT NOT NULL,                          -- open | writing | done | given_up
  attempts INTEGER NOT NULL DEFAULT 0,          -- counted failures toward the limit (12)
  detail TEXT, updated_at REAL NOT NULL,
  PRIMARY KEY (wanted_id, playlist_id)
);
```

`import_order` makes wanted row × playlist many-to-many (a track wanted by two playlists has a row in each), so
`external_wanted.playlist_id/position` stays as it is (the last import's slot) and placement never reads it. A wanted
row is never re-keyed. N3's `forget_playlist` does read it (below).

### Store methods

- `record_import_order(playlist_id, rows: list[tuple[int, str | None, str | None]])`: deletes the playlist's rows and
  inserts the new ones; the caller commits, so it is one transaction with the rest of the import's writes.
- `import_order(playlist_id) -> list[dict]` (by position); `import_order_for(wanted_id) -> list[dict]` (the feature
  list asks for it; N3's `forget_playlist` uses it, below).
- `due_placements() -> list[dict]`: `(wanted_id, playlist_id, song_id, position)` derived from state alone, **one row
  per (wanted_id, playlist_id)** with `MIN(position)` (two Spotify rows can queue the same wanted id: `find_external`),
  in `(playlist_id, position)` order: an `import_order` row naming `wanted_id`, whose external row is `ok`, has
  `library_song_id` set and `provisional = 0`; no `imported_entries` row for (playlist, that song); no `placements`
  row for (wanted, playlist) in `done` or `given_up`. An `open` row that stops being due (a re-run appended the song)
  is inert: nothing reads it again.
- `placement(wanted_id, playlist_id) -> dict | None`; `note_placement(wanted_id, playlist_id, song_id, state, detail,
  count: bool)`: upsert; `attempts += 1` only when `count`, `updated_at` always.

### import-playlist (sourcing/import_playlist.py)

On a real run, after the `pending` loop (so every wanted id is known) and before the final `store.commit()`:
`store.record_import_order(playlist_id, [(m.row.position, m.song_id if matched else None, ext id if pending else
None) for m in matches])`. The `pending` loop keeps the ext id it gets per row. A dry run records nothing (M9 §1 said
"dry runs too, as a report"; a report needs no table, and the feature list says nothing, so nothing). Each real run
replaces the playlist's record: the newest import is the order.

### crates/placement.py (new)

- `insert_index(order: list[tuple[int, str | None]], entries: list[str], position: int) -> tuple[int, str]`, pure.
  `order` is the playlist's import_order as `(position, song)` where song is the row's song now (below), sorted by
  position (positions may have gaps). Walk the rows before `position`, nearest first: the first usable one →
  `(the index after its last occurrence in entries, "after <song>")`. None → the rows after `position`, nearest
  first: the first usable one → `(its first occurrence's index, "before <song>")`. None → `(len(entries),
  "append")`. A row is usable when its song is not `None` (still wanted) and is in `entries` (not removed by
  Michael): M9 §1's "a neighbour Michael removed is skipped and the next one is used". As built (N4-03, the feature
  step binds): a song in `entries` twice, or at two Spotify positions, is still a neighbour (last/first occurrence),
  not skipped as this plan first said.
- `place(store, client, db, playlist_id, wanted_id, song_id) -> str`, recomputing everything right before acting:
  1. `not store.is_playlist_imported(playlist_id)` → `"skipped: not an imported playlist"`;
  2. `(playlist_id, song_id)` in `store.imported(...)` → `"skipped: added before (removed stays removed)"`;
  3. the playlist's `import_order` no longer names `wanted_id` (a re-run committed since `due_placements`) →
     `"skipped: no longer in the import"`, and the caller writes no row (it is simply not due any more);
  4. `entries = checked_entries(client, db, playlist_id)`; getPlaylist's `SubsonicError` code 70 →
     `"skipped: playlist gone"`; `NotOwned` / `NotEditable` / `PlaylistSkew` propagate (all `EditRefused`);
  5. `song_id in entries` → `mark_imported(playlist_id, [song_id])`, `"skipped: already in playlist"`;
  6. the song is not a present `media_file` (`missing = 0`) in `navidrome.db` (a retag + move gave it a new id, a
     cleanup trashed it: only `_settle` and the accept update `library_song_id`) → `EditRefused("song <id> is not in
     the library now")`, counted, so the give-up names the real reason, not rewrite's "hidden row";
  7. `order` = `import_order(playlist_id)` with each row's song = its `song_id`, else its wanted row's
     `library_song_id` when that row is `ok` and not provisional (a track placed earlier is a neighbour; a stale one
     is simply not in `entries` and skipped), else `None`; `i, how = insert_index(order, entries, position)` with
     the smallest position naming `wanted_id`;
  8. **intent first:** `note_placement(..., "writing", "inserting at <i> into <n> entries (<how>)")` and commit;
  9. `rewrite(client, db, playlist_id, entries, entries[:i] + [song_id] + entries[i:])`; `mark_imported(playlist_id,
     [song_id])`; event kind `placed`, playlist id, wanted id, `"<playlist name>: <artist> – <title> at <i+1>
     (<how>)"` (the row's names; the event is the reverse: remove that entry in Amperfy); return
     `"placed at <i> (<how>)"`. The caller commits (`done`).
- **An unconfirmed write is never retried** (as `crates/proposals.py:292` treats `EditNotKept`): `rewrite` removes
  the tail and re-adds it, so a second blind try could double an entry. On `EditNotKept`, or a `writing` row found by
  a later tick (a crash between the write and the commit), `advance_all` only looks: the song in `entries` →
  `mark_imported`, `done`, a `placed` event ("… confirmed after an unconfirmed edit"); absent → `given_up` with
  `not_placed` "<playlist>: edit not confirmed, look at the playlist; re-run the import to append it". Not marked
  imported in that case, so the re-run can append it (if Michael removed it in that window, the re-run re-adds it
  once: accepted). A failure of the look itself leaves the row `writing` for the next tick. As built (N4-04, after review): the look
  happens on the *next* tick, not right after the EditNotKept (Navidrome may still be applying a timed-out edit), and
  any failure after rewrite confirmed the edit (crates.db locked during `mark_imported`) also leaves the `writing` row
  to be looked at, never `open`. The look checks the song the intent row names.
- `advance_all(store, client, db, recheck_s, now) -> list[str]`: for each due pair whose `placements` row is absent,
  or `open` and `updated_at <= now - recheck_s`: `place()`; a `placed`/`skipped` result → `done` (detail = result);
  a `writing` row is resolved by looking (above), whatever its age; `EditRefused` and any unexpected exception (a
  non-70 `SubsonicError`, a bug) → `open`, counted, detail = the reason; the 12th counted failure → `given_up` with
  event kind `not_placed` `"<playlist>: not placed after 12 tries: <why>; re-run the import to append it"`; only a
  transient error (`OSError`, which covers `URLError` and timeouts, and `sqlite3.OperationalError`) → `open`, not
  counted, so a Navidrome outage never gives a placement up. Every failure is logged. Commit after each pair. Returns one line per pair tried:
  `"<wanted_id> → <playlist_id>: <result>"`. `PLACE_LIMIT = 12` (fetch's `RECHECK_LIMIT` habit).

### Worker (sourcing/worker.py)

Step 3b, after `advance_replacements` (which may settle an external row `ok`) and before `export_due` (so the export
sees the edit): `placement.advance_all(self.store, c["navidrome"], c.get("navidrome_db"), self.recheck_s, time.time())`,
each line appended to `results` and logged (wanted ids and playlist ids only: no peers). Skipped when `navidrome_db`
is not given (no `checked_entries` without it); one bad pair never stops the tick. The docstring's step list gains
the step.

**State-driven, so no new calls elsewhere:** `fetch.finish`'s two `ok` sites, `replace._settle` and play-now (a copy
that ends `ok`) need no hook. A crash, a restart or a failed tick loses nothing: the next tick derives the same due
pairs. A legacy provisional copy (`provisional` 1) is not due until its upgrade settles.

### N3's forget_playlist

When it deletes the import rows (none waits), it also deletes the playlist's `import_order` and `placements` rows and
returns them (`"import_order"`, `"placements"`) for the reverse log. A placement attempted first just ends `done`
("skipped: playlist gone"). N4-05 checks no due pair dangles. And it no longer marks an open wanted row `removed`
while another playlist's `import_order` names it (`import_order_for`): with many-to-many, the row whose last slot
was the deleted playlist is still wanted by the other one.

## Safety rules (each with a test, N4-03/N4-04/N4-05)

- Imported playlists only: `is_playlist_imported` (N2's table), checked in `place()`; `import_order` is written only
  by import-playlist anyway. Never a playlist Michael made by hand (no `imported_playlists` row) or the amperfy
  account's (`NotOwned` from `checked_entries`).
- Insert only: `after` is `before` with one song inserted; a test asserts `after[:i] == before[:i]`, `after[i] ==
  song` and `after[i+1:] == before[i:]` (the re-added tail is the old tail). A track an earlier re-run appended stays where it is (Q2): it is in
  `imported_entries`, so it is never due, and nothing ever moves an existing entry.
- One placement per (wanted row, playlist), ever: the `placements` PK, `done`/`given_up` are final, and an
  unconfirmed write is looked at, never retried. A later
  upgrade (a copy replacement repoints the song) is not placed again.
- Every edit through `playlist_edit.rewrite` (hidden-row, concurrent-edit and present-song guards, readback).
- Removed stays removed (D13): `imported_entries` is checked before and written after every insert.
- Residual race, accepted: an `import-playlist` re-run (another process) that reads the playlist just before a
  placement and appends the same song just after it gives one duplicate entry, visible and harmless; both mark
  `imported_entries`, so it happens at most once.

## Decision

`D44 *default*` (pivot spec): placement is a worker step driven by state; insert after the nearest earlier Spotify
neighbour still present, else before the nearest later one, else append (Q1); tracks an earlier re-run appended are
never moved (Q2); a refused placement retries at most every `recheck_s`, gives up after 12 refusals with a
`not_placed` event; imported playlists only. (The feature list said D39, which the backup decision holds.)

## Tasks

- **N4-02** `import_order`: the table and the three store methods (tests/test_crates.py); import-playlist records it
  on real runs (tests/test_import_playlist.py: matched/missing/matched → positions 1..3 with `s…`/`ext-N`/`s…`; a
  re-run with one more row gives 4 rows, no duplicates; `dry_run=True` records nothing; a track wanted by two
  playlists has a row in each; tests/test_app_owner.py still passes).
- **N4-03** `crates/placement.py`: `insert_index` (after / before / append, removed neighbour skipped, `None` skipped,
  a duplicated neighbour uses its last / first occurrence) and `place()` on the fake (pl-1 `[s1, s2, s3]`, order
  1:s1, 2:ext-7, 3:s2, 4:s3, ext-7 filed as s9 → `[s1, s9, s2, s3]`; s1 removed → before s2; alone → append; hidden
  missing row → `PlaylistSkew`, nothing written; already present → no `updatePlaylist`; one `updatePlaylist`; a
  second `place()` → "skipped: added before"; not imported; playlist gone; no longer in the import; song not in the
  library; a neighbour at two Spotify positions; positions with gaps; a playlist deleted between place's read and
  rewrite's → "skipped: playlist gone"). Built: `place(..., before_write=None)` is the hook for step 8's intent row.
  rewrite re-reads after it, so an `EditRefused` can follow a committed `writing` row with nothing written: N4-04
  must treat that as `open` (counted), not "look and give up" (test: PlaylistChanged after the intent).
- **N4-04** worker: `placements`, `due_placements`, `note_placement`, `advance_all`, the tick step; tests with
  `tests/test_worker.worker` and `tests/test_fetch.world` (filed → placed in one tick with a `placed` event; legacy
  provisional copy not due; refusal → open, attempts 1, no retry inside `recheck_s`, `given_up` + `not_placed` after
  12, playlist untouched; an `OSError` is not counted, a `KeyError` is; a pair in `imported_entries` never due; two
  due rows of one playlist placed in position order in one tick; a wanted id at two positions of one playlist → one
  placement, one line; a re-run that appends the song while the pair is `open` → never tried again; `EditNotKept`
  that landed → `done` with `placed`, then removed by Michael → not re-inserted; `EditNotKept` that did not land →
  `given_up`, no second write; a crash after the write (`writing` row) → resolved by looking; an unproven-copy
  accept in the app → placed on the next tick; an `ok` row reached through `find_external` by a second playlist's
  import → placed there too); `forget_playlist` drops `import_order`/`placements` and keeps a wanted row another
  playlist's order names.
- **N4-05** review the N4 diff from a file against the rules above; docs (`docs/architecture.md` §3, §4, quirk 18;
  `docs/worker.md` tick list + "Placement"; M9 spec item 1 built; `docs/next-todos.md` item 4).

## Live effect and runbook (after N4 is merged and deployed)

Nothing is placed until a playlist has an `import_order`: existing playlists get one only on their next re-run of
`import-playlist` (`docs/next-todos.md` item 5, after the duplicate cleanup). That re-run appends whatever is already
in the library, as today; placement covers what is filed after it. To watch: `crates.db` events `placed` /
`not_placed`, `SELECT * FROM placements`. To undo one placement: remove that entry in Amperfy (the `placed` event
names the position); its `imported_entries` row keeps it from coming back. To stop placement entirely: deploy the
previous image (CLAUDE.md "Deploy and rollback"); the tables are inert without the code. To retry a given-up
placement (e.g. after the duplicate cleanup removed the hidden row that refused it): `DELETE FROM placements WHERE
state='given_up' AND playlist_id='<id>'` in crates.db (snapshot first); the next tick tries again.
