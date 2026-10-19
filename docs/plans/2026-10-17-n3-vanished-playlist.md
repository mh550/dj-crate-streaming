# N3: reconcile drops the rows of a playlist that vanished from Navidrome — Implementation Plan

> REQUIRED SUB-SKILL: superpowers:executing-plans (inline) with superpowers:test-driven-development.
> **Nothing in N3-02..N3-03 writes to the live Navidrome or the live `crates.db` by hand.** Every task is built
> against `subsonic/fake_server.py` and `CrateStore()`. Once deployed, the worker's next reconcile drops the live dead
> row ("sockseek / clouds", `docs/next-todos.md` item 3) on its own; that is the only live effect.

**Goal:** when a playlist that `crates.db` knows is deleted in Navidrome, the next reconcile deletes its rows and logs
one `playlist_gone` event, instead of reporting "playlist no longer exists in Navidrome" in `rep.errors` on every run
forever. Rows a download still has to finish stay until it does. Wanted rows keep their history (D43 *default*; the feature list says D38, which the snapshot decision already holds).

## Today (checked against `ea2282e`)

- `Reconciler._run` (`crates/reconcile.py:301`) lists playlists with `self.client.playlists()` (getPlaylists),
  `known = {c.playlist_id: c for c in self.store.all()}` (the `crates` table, read before `refresh_cache`).
  If getPlaylists raises, `_run` raises before touching anything; that stays so (N3-03 checks it).
- At the end, for every `known` row with an effective tier whose id is not in `present`, it appends
  `"<name>: playlist no longer exists in Navidrome"` to `rep.errors`; nothing is deleted. An untiered vanished row is
  ignored. `rep.errors` reaches the web UI through `CrateApp.reconcile` (`crates/service.py:164`); the worker
  (`sourcing/worker.py:145`) drops the report.
- `_untier` marks live (not `in_flight`) rows `removed`; `in_flight()` (`crates/store.py:164`) is the rule for rows
  reconcile must not touch (`sourcing`, `verify`, a `review` that is a question, a `failed` row with a filed path).
- Tables keyed by playlist id: `crates` (PK), `crate_tracks` (PK playlist_id, song_id), `imported_entries`,
  `imported_playlists` (N2), `external_wanted.playlist_id/position`, `proposals.playlist_id`, `events.playlist_id`.
- `crates/migrate_attrs.py:orphans` lists enabled rows whose playlist is gone and says "the first reconcile will drop
  them": after N3 that is true.
- `crates/proposals.py` already turns a proposal on a missing playlist (Subsonic error 70) into `stale`.
- Fetch asks `store.playlists_holding([copy_id])` (`sourcing/fetch.py:262`), which counts tiered `crates` rows:
  while a gone playlist's `crates` row stays tiered, fetch would run a full copy replacement on it instead of the
  "request withdrawn" path. `verify_ids` (`crates/store.py:458`) re-checks only `verify` rows, so a `failed` row with a
  filed path is never finished by fetch, and a `review` row ends only when Michael answers it.
- The worker reconciles every 600 s (`WORKER_RECONCILE_S`, `deploy/compose.yml:97`).

## The change

### `CrateStore.forget_playlist(playlist_id) -> dict` (crates/store.py)

One transaction, the caller commits (like `mark_imported`). Returns what it deleted and what it kept:
`{"dropped": [<crate_tracks rows>], "live": <n>, "kept": <n>, "crate": <crates row or None>, "imported_entries": [song
ids], "imported_playlist": <row or None>, "wanted_removed": [ext ids]}`, every row as a dict of all its columns.

1. **Rows that wait:** only `sourcing` and `verify` rows (a download fetch will still finish), plus a `needs_source`
   row whose wanted id has `approval_in_progress` (as `upgrade_busy` does). Every other row is deleted, in one
   statement: `DELETE FROM crate_tracks WHERE playlist_id=? AND NOT (<waits>)`, after reading the same rows with the
   same `WHERE` for the return value. `review` questions and `failed` rows with a filed path are deleted too: neither
   finishes on its own (see Today), and their playlist is gone. `live` = deleted rows whose status was not `removed`.
2. **While rows wait** (`kept > 0`): the `crates` row stays but loses its crate flag and tier (`enabled=0`,
   `tier=NULL`), so `playlists_holding`, `song_tier` and `derive_external_tiers` stop counting the gone playlist and
   fetch takes the "request withdrawn" path. The old values are in the return value (and so in the reverse log).
3. **When nothing waits:** delete the `crates` row, the `imported_entries` rows, the `imported_playlists` row and
   the settings key `problems:attrs_problem:<pid>` (`note_problems`); once N4 adds `import_order`, its rows too (N4
   adds the line and a test).
4. **Wanted rows** (`external_wanted` with this `playlist_id`): they keep `playlist_id`, `position` and `tier` (the
   history of what an import asked for). Those not in flight and not `ok`/`removed` are set `removed` with reason
   `playlist deleted` through `set_external_status` (one `status` event each), so `wanted()` and policy approvals stop
   offering them. Their ids are in the return value.
5. Untouched: `proposals` (an open one goes `stale` on error 70 when acted on, as today; `_proposal_view`,
   `crates/service.py:300`, shows the playlist id instead of its name once the `crates` row is gone — acceptable, the
   summary text names the playlist) and `events` (history).

### `Reconciler._run` (crates/reconcile.py)

Replace the "Tiered playlists that vanished" loop:

- **Which ids:** every `crates` row and every `imported_playlists` row whose id is not in this run's getPlaylists,
  tiered or not (an untiered vanished row is clutter too; an imported playlist that was never a crate has no `crates`
  row but has import rows).
- **Mass-vanish guard:** if getPlaylists returned no playlist, or more than `VANISH_LIMIT = 3` known ids are missing
  in one run, nothing is forgotten and one `rep.errors` line says
  `"<n> known playlists missing from Navidrome at once (<names>); nothing dropped"`. Reason: Navidrome started on a
  fresh or restored DB, or with the wrong user, lists nothing and answers 70 for every id; one run would erase every
  crate choice (under `CRATES_OWNER=app` the `crates` row *is* Michael's choice, D27). Michael deleting four
  playlists at once is rare; he gets the line and the rows wait (a follow-up can add `crates.cli forget <id>` if it
  ever happens).
- **Confirm each id:** `self.client.playlist(pid)` must raise `SubsonicError` with code 70. Any other outcome (it
  reads, another code, a network error) means "not sure": nothing is dropped, and
  `"<name>: missing from getPlaylists but getPlaylist says <…>; kept"` goes to `rep.errors`. This guards against a
  listing glitch only: Navidrome filters getPlaylist like getPlaylists (owner or public), so another user's playlist
  made private also answers 70 and is treated as gone. The reverse log below covers that case.
- **Reverse log:** when `forget_playlist` deleted anything, `_run` appends one JSON line (time, playlist id, name and
  the whole return value) to `<dirname(store.path)>/playlists-gone.jsonl` before committing; an in-memory store
  writes none. Every deleted row can be put back from that line (a test does exactly that), whatever the nightly
  snapshot has since overwritten.
- **Event**, once per deleting run: `store.log(pid, None, "playlist_gone", f"{name}: playlist no longer exists in
  Navidrome; {len(dropped)} rows dropped")`, with `, {kept} in flight kept` when rows wait, and the old crate flag and
  tier (`crate=on|off tier=<t|none>`) when the `crates` row was deleted or cleared.
- **Report:** `rep.tracks_removed += live` (rows already `removed` were counted when they were removed). A new
  `ReconcileReport.playlists_gone: list[str]` gets one line per vanished playlist acted on or waiting:
  `"<name>: playlist no longer exists in Navidrome; <n> rows dropped[, <k> in flight kept]"`. Nothing goes to
  `rep.errors` for a confirmed-gone playlist.
- **In flight:** each run the waiting playlist is listed in `rep.playlists_gone` (`0 rows dropped, <k> in flight
  kept`), but an event and a reverse-log line are written only when that run deletes something, so the 600 s worker
  loop does not flood `events`. Once fetch finishes the row (`ok`, `failed`, or `review` "request withdrawn"), the
  next run drops it and the `crates` row and logs the event.
- A run after a full drop finds no row for the id: nothing is listed, nothing logged.
- If getPlaylists raises, `_run` raises before this point, as today.

## Tests (N3-02, test-first)

- `tests/test_crates.py` (owner comment) and `tests/test_app_owner.py` (owner app), each on its `env` fixture: enable
  `pl-2` ("Chicago 86", songs s3–s5), reconcile, `del srv.state.playlists["pl-2"]; srv.state.sync()`, reconcile →
  `store.get("pl-2") is None`, `store.tracks("pl-2", include_removed=True) == []`, `store.imported("pl-2") == set()`,
  `not store.is_playlist_imported("pl-2")`, `rep.errors == []`, `rep.tracks_removed == 3`, exactly one
  `playlist_gone` event naming "Chicago 86" and "3 rows dropped"; a third reconcile adds no event and an empty
  `rep.playlists_gone`.
- In flight: `store.set_track_status("pl-2", "s3", "sourcing", …)` before the delete → s3 stays, s4/s5 go, the
  `crates` row stays with `enabled == 0` and no tier, `store.playlists_holding(["s3"])` lacks pl-2, the event says
  "2 rows dropped, 1 in flight kept"; the next run lists it but logs nothing new; after
  `set_track_status("pl-2", "s3", "failed", "no file")` the next run drops s3 and the `crates` row, one event.
  A `review` question row and a `failed` row with a filed path are dropped at once, not kept.
- Mass vanish: delete pl-1, pl-2, pl-3 and pl-4 (or empty `srv.state.playlists`) → nothing deleted, one `rep.errors`
  line naming them.
- Not sure ≠ gone: the fake has no switch to hide a playlist from getPlaylists only, so wrap the client:
  `monkeypatch.setattr(client, "playlists", lambda: [p for p in real() if p.id != "pl-2"])` → nothing deleted, one
  `rep.errors` line. getPlaylists raising (`monkeypatch` it to raise) → `run()` raises, store unchanged.
- Reverse log: on a `tmp_path` store, the line in `playlists-gone.jsonl` holds every deleted row; re-inserting them
  from it gives back `store.get`, `store.tracks(include_removed=True)`, `store.imported` and the imported row equal
  to before.
- Wanted rows: an imported, never-crated playlist (`mark_playlist_imported` + `mark_imported` + an `external_wanted`
  row at a position) that vanishes loses its import rows; its `needs_source` wanted row becomes `removed`
  ("playlist deleted") with `playlist_id`, `position` and `tier` kept; a `sourcing` wanted row is left alone.
- A `needs_source` crate row with an approval in progress is kept.
- `CrateStore.forget_playlist` unit test: deletes nothing of another playlist, leaves `events` alone, clears the
  `problems:attrs_problem:<pid>` setting.
- `crates.cli status` and the web playlists view (via `CrateApp`, as the service tests do) do not 500 while a gone
  playlist still has its `crates` row (in-flight wait).
- No existing test asserts the old `rep.errors` line (`grep -rn 'no longer exists' tests/` finds only
  `test_proposals.py` and `test_migrate_attrs.py`, which test their own messages).

## Docs (N3-03)

`docs/architecture.md` §4 or §9: a playlist deleted in Navidrome loses its `crates.db` rows at the next reconcile
(in-flight rows wait; wanted rows keep their history; reverse log `playlists-gone.jsonl`). `docs/next-todos.md` item
3: "Built (N3)". `crates/migrate_attrs.py:orphans` docstring stays true.

## As built (checked in N5-02)

Where the code differs from the text above, the code is right:
- **Rows that wait** (`store.py` `forget_playlist`): `sourcing`/`verify` rows, plus any row not `removed` whose wanted
  id has an unused or started approval (not only `needs_source`). An `external_wanted` row in flight counts into `kept`.
- **Return value** also has `problems`, `import_order` and `placements` (N4). A wanted row that another playlist's
  `import_order` still names is kept, not set `removed`.
- **Reconcile:** the loop is `Reconciler._forget_vanished`, called from `_run`. The guard counts only *guarded* missing
  ids (imported, or with an effective tier), and an empty listing says "getPlaylists listed no playlist; nothing
  dropped (<n> known: …)". The reverse-log line is `{ts, playlist_id, name, forgotten}`. The event is written when
  any part of the return value is non-empty, not only when rows were deleted.

## Live

No runbook: no command to run by hand. After N3 deploys, the worker's next reconcile (≤ 600 s) drops "sockseek /
clouds" (one vanished id, under the guard's limit). Check afterwards: `docker compose run --rm --no-deps worker python3
-m crates.cli status` no longer lists it, `/srv/docker/crates/playlists-gone.jsonl` has its line, and the events show
one `playlist_gone` for it. Restore point: the line itself, and the run-named `crates.db` snapshot taken before the
deploy (CLAUDE.md "Snapshots").

## Review (2026-10-19, N3-01)

An Opus review of this plan against the code found 1 Critical, 5 Important and 7 Minor issues; all are taken in the
text above: the mass-vanish guard (C1), the JSONL reverse log (I1), the 70-check's real reach (I2), waiting only on
`sourcing`/`verify` (I3), clearing the flag of a waiting row (I4), retiring open wanted rows (I5), and the minors
(live count, one DELETE, approvals, settings key, proposal view, 600 s, the client wrapper for the "not sure" test).
