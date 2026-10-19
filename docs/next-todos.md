# Next todos for the music server (hand-off list)

Written 2026-10-17. Michael approved this plan; **none of it is built yet** except where marked done. Read first:
[`specs/2026-10-17-amperfy-pivot.md`](specs/2026-10-17-amperfy-pivot.md) (decisions D24–D34),
[`hard-won-facts.md`](hard-won-facts.md), [`architecture.md`](architecture.md). Deploy with `scripts/deploy.sh`.
Anything that trashes files or writes tags needs a reviewed plan file and a reverse log, as in M3/M8.

## State at hand-off
- Live: image `dj-crates:b2df730b1d` (crates + worker), Navidrome pinned `0.64.2`, `CRATES_OWNER=app`, one DJ-quality rule.
- Done 2026-10-17: 35 playlists deleted by Michael's rules (D32; list in `/srv/docker/crates/playlists-deleted-2026-10-17.txt`,
  restore from `/srv/music/_playlists/*.m3u8` or `/srv/docker/navidrome/navidrome.db.pre-cleanup.snap`); 10 kept.
- Id backfill: a fresh `propose` with the AcoustID key finished: confirmed 77, isrc 172, **acoustid 236**, search 16,
  ambiguous 89, conflict 38, none 203 (output in `/srv/docker/crates/identity/`, the previous one in `identity/previous-2026-10-16/`).
  The 16 `search` rows were applied as a trial (revert logs `apply-20261017T051634.jsonl`, `apply-20261017T051653.jsonl`);
  Navidrome shows the ids, song ids unchanged, exports match. **The 485 default-class rows are not applied yet.**

## In order

1. **Navidrome duplicate cleanup: keep the flac, repoint the playlists, trash the rest (D31; M9 item 3).**
   **Built (N1), not run live:** `scripts/duplicate_cleanup.py plan | repoint | trash`; the staged runbook and the undo
   are in `docs/worker.md` "Duplicate cleanup", the design in `docs/plans/2026-10-17-n1-duplicate-cleanup.md`.
   Input: `docs/duplicates-report.md` (regenerate: `python3 -m scripts.duplicate_report`; 102 groups, 115 extra files).
   Keeper rule is `keep_rank` in `scripts/duplicate_report.py` (lossless first, then bit rate, then the properly filed path).
   Build a plan → repoint → trash flow like `scripts/dedupe_copies.py`, using `crates/playlist_edit.py` (guarded index
   edits), `sourcing/replace.py` and `crates/trash.py` (trash to `/srv/_trash`, `MOVES.txt`). Never trash while any playlist,
   hidden entries included, still holds the file. Scan between repoint and trash. Check with
   `python -m scripts.export_playlists check`. Recompute the groups right before acting.
2. **Move the `#imported` marker into crates.db (D33).** **Built (N2); live migration pending:** `crates.db`
   `imported_playlists` (D37), `crates.cli imported migrate | list`; the runbook is at the end of
   `docs/plans/2026-10-17-n2-imported-marker.md`. Before N2, `MARKER`/`is_imported`/`_rerun_comment`/`NameCollision` in
   `sourcing/import_playlist.py` read and write the playlist comment. Store "this playlist was made by import-playlist" in
   `crates.db` (a table or column in `crates/store.py`, beside `imported_entries`), switch the checks to it, migrate the two
   marked playlists left ("Tea tent", "shakori (Spotify)"), then strip `#imported` from their comments with
   `crates.reconcile.write_comment`. Update tests (`tests/test_import_playlist.py` marker tests, `tests/test_app_owner.py`).
3. **Drop the dead crate row** ("sockseek / clouds", playlist deleted). **Built (N3), not deployed:** the next reconcile
   drops a deleted playlist's rows with a `playlist_gone` event and a reverse log (`docs/architecture.md` §9,
   `docs/plans/2026-10-17-n3-vanished-playlist.md`) instead of reporting "playlist no longer exists". Before N3: make `Reconciler._run` (`crates/reconcile.py`) remove the rows of a playlist that vanished, with an event.
4. **Insert a downloaded track at its Spotify position (M9 item 1, spec §1).** `fetch.finish` (`sourcing/fetch.py`),
   `external_wanted.position`, `crates/playlist_edit.py`. Also play-now.
5. **Re-run the imports after the cleanup** so the 13 `review` rows (`external_wanted`, status `review`) and "shakori
   (Spotify)"'s 2 ambiguous rows are re-matched against a library without duplicates (`sourcing.cli import-playlist`;
   M9 spec §5b picker only for what is left).
6. **Id backfill:** after Michael has looked at `identity-backfill-report.md`, apply the default classes (`confirmed`, `isrc`,
   `acoustid`; 485 files): dry run, then `--limit 5`, then all, as in `docs/worker.md`; scan and check after each stage
   (the trial's checks: ids appear in `navidrome.db`, song ids unchanged, `scripts.export_playlists check`). Then the
   `ambiguous`/`none`/`conflict` pickers (M9 item 5a). `revert` undoes any run.
7. **Version tag (`VERSION`/`TIT3`)** as its own reviewed proposal (M9 item 4, approved "later").
8. **Before the first real download:** run the M8 trash-move probe (`docs/architecture.md` §9 step 3); Michael says "go" with an
   `ext-N`; check the whole chain on one file (D7).
9. **Low priority, explore only (D34):** Spotify ↔ Navidrome playlist **sync**, with a marker in the playlist title (Michael's
   idea; note it reverses "no hashtags in names", so ask first) or kept in the crates app.
10. **When the custom client replaces Amperfy:** remove the vestigial tier code (`crates.tier`, `crates/attrs.py`,
    `crates/migrate_attrs.py`, stream presets in `sourcing/policy.py`) and build the client features listed in the pivot spec.

## Michael's open items (not for the agent): `~/projects/TODO-MICHAEL.md`
