# Next todos for the music server (hand-off list)

Written 2026-10-17. Michael approved this plan; items 1-4 are built on branch `harness/dj-2026-10-17` (not live), the rest
is not built. Read first:
[`specs/2026-10-17-amperfy-pivot.md`](specs/2026-10-17-amperfy-pivot.md) (decisions D24–D34),
[`hard-won-facts.md`](hard-won-facts.md), [`architecture.md`](architecture.md). Deploy with `scripts/deploy.sh`.
Anything that trashes files or writes tags needs a reviewed plan file and a reverse log, as in M3/M8.

## State at hand-off
- Live on 2026-10-17 (since 2026-10-21 `f4882ab85b`, below): image `dj-crates:b2df730b1d` (crates + worker), Navidrome pinned `0.64.2`, `CRATES_OWNER=app`, one DJ-quality rule.
- Done 2026-10-17: 35 playlists deleted by Michael's rules (D32; list in `/srv/docker/crates/playlists-deleted-2026-10-17.txt`,
  restore from `/srv/music/_playlists/*.m3u8` or `/srv/docker/navidrome/navidrome.db.pre-cleanup.snap`); 10 kept.
- Id backfill: a fresh `propose` with the AcoustID key finished: confirmed 77, isrc 172, **acoustid 236**, search 16,
  ambiguous 89, conflict 38, none 203 (output in `/srv/docker/crates/identity/`, the previous one in `identity/previous-2026-10-16/`).
  The 16 `search` rows were applied as a trial (revert logs `apply-20261017T051634.jsonl`, `apply-20261017T051653.jsonl`);
  Navidrome shows the ids, song ids unchanged, exports match. **The 485 default-class rows are not applied yet.**
- **2026-10-19, run `dj-2026-10-17` (branch `harness/dj-2026-10-17`, milestones N1-N4):** built and tested against the
  fakes, **none of it run live and not deployed**. (1) Duplicate cleanup `plan | repoint | trash` (N1); its trash step
  stays at `--dry-run` until Michael lifts it. (2) The imported marker moved into crates.db, with `crates.cli imported
  migrate` (dry run first, then `--apply`) still pending on the two old playlists (N2). (3) Cleanup of a vanished
  playlist's rows at reconcile (N3). (4) Placement of filed downloads at their Spotify position by the worker (N4).
  Also on the branch: snapshots, heartbeat and healthchecks (H1), the backup job in git (H2), Gatus and the disk timer
  (H3). The live steps in order, each with its undo: [`plans/2026-10-17-morning-checklist.md`](plans/2026-10-17-morning-checklist.md).
- **2026-10-21:** the live image is `dj-crates:f4882ab85b` (crates + worker). It contains N1, N1F, H1, H2 and
  H3-01..04. PRs #5-#13 are merged into `main`. H1-H3 are live, except the H3-03 timer and
  H3-05's changes to it (merged, not installed). N2-N5 are merged, not
  deployed. N1's code is live but has never been run.
- **2026-10-21, run `dj-crate-streaming-2026-10-21` (branch `harness/dj-crate-streaming-2026-10-21`, milestones
  R1-R8, spec `specs/2026-10-21-guards-and-checks.md`):** built and tested against the fakes, **none of it run live and
  not deployed**. (R1) Doc truth: image, PRs, test count, what is live. (R2) `scripts/live-run.sh` runs one-off worker
  commands in the deployed image, from `dj-worker-1`'s revision label, and `scripts/live-check.sh` is the Check (D45).
  (R3) `duplicate_cleanup plan` releases lossless pairs (D35 as Michael answered it): they get their own report
  section, and `--hold-lossless` brings the old hold back. (R4) `rank --download` is deleted; `tag_cleanup retag|move`
  and `dedupe_copies repoint|trash` refuse while the worker holds its lock. (R5) Playlist health after each export
  (`playlist_health` event, `/api/status`, web banner; our own non-smart playlists only, D46), and `.m3u8` history in
  `_playlists/.history/<date>/`, kept 30 days. (R6) AcoustID cache and a shared 3 req/s limiter, "99 Luftballons",
  disambiguation-only version labels, and a re-import reuses a failed unfiled row. (R7) The Identity tab writes `identity-choices.json`;
  `identity_backfill apply --choices` merges it (D47). The live steps in order, each with its check and undo:
  [`plans/2026-10-22-morning-checklist.md`](plans/2026-10-22-morning-checklist.md).
- **2026-10-22, run `dj-crate-streaming-2026-10-22-fixes` (branch `harness/dj-crate-streaming-2026-10-22-fixes`,
  milestone S1 of `specs/2026-10-22-downloads-and-requests.md`):** built and tested against the fakes, **not deployed,
  PR open**. The download fixes from the Al Green attempts: a title slot naming another song is rejected (S1-01); a
  confident AcoustID title that can't be the asked one fails verify (S1-02); a row is never renamed onto another song,
  it goes to `review` (S1-03, D48); slskd forgets with `?remove=true` and fetch follows only its own new transfer
  (S1-04); slskd errors name the step and endpoint, never the peer (S1-05); one more peer on a transfer error or a VPN
  drop (S1-06); the library is asked before downloading (S1-07); `crates.cli wanted reopen` (S1-08, D49). The live
  steps, each with its check and undo:
  [`plans/2026-10-22-downloads-checklist.md`](plans/2026-10-22-downloads-checklist.md) (S1-09).

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
4. **Insert a downloaded track at its Spotify position (M9 item 1, spec §1).** **Built (N4), not deployed:** each
   real import records `import_order`; the worker places every filed external row (play-now's final copy included)
   into its imported playlists through `playlist_edit.rewrite`, insert only (`crates/placement.py`, D44,
   `docs/worker.md` → "Placement"). Playlists imported before N4 are placed into only after their next re-run (item 5).
   Before N4: `fetch.finish` (`sourcing/fetch.py`), `external_wanted.position`, `crates/playlist_edit.py`. Also play-now.
5. **Re-run the imports after the cleanup** so the 13 `review` rows (`external_wanted`, status `review`) and "shakori
   (Spotify)"'s 2 ambiguous rows are re-matched against a library without duplicates (`sourcing.cli import-playlist`;
   M9 spec §5b picker only for what is left). **Not started** (needs items 1 and 4 live). Since N4 a real re-run also
   records `import_order`, which the worker needs to place a playlist's downloads, so this re-run is also what
   switches placement on for playlists imported before N4.
6. **Id backfill:** after Michael has looked at `identity-backfill-report.md`, apply the default classes (`confirmed`, `isrc`,
   `acoustid`; 485 files): dry run, then `--limit 5`, then all, as in `docs/worker.md`; scan and check after each stage
   (the trial's checks: ids appear in `navidrome.db`, song ids unchanged, `scripts.export_playlists check`). Then the
   `search`/`ambiguous`/`none`/`conflict` picker (M9 item 5a): **built (R7), not deployed**. Michael picks in the
   Identity tab, then runs `apply --choices` himself, staged as in `docs/plans/2026-10-21-r7-identity-picker.md`
   "Live steps". `revert` undoes any run.
7. **Version tag (`VERSION`/`TIT3`)** as its own reviewed proposal (M9 item 4, approved "later").
8. **Before the first real download:** run the M8 trash-move probe (`docs/architecture.md` §9 step 3); Michael says "go" with an
   `ext-N`; check the whole chain on one file (D7).
9. **Low priority, explore only (D34):** Spotify ↔ Navidrome playlist **sync**, with a marker in the playlist title (Michael's
   idea; note it reverses "no hashtags in names", so ask first) or kept in the crates app.
10. **When the custom client replaces Amperfy:** remove the vestigial tier code (`crates.tier`, `crates/attrs.py`,
    `crates/migrate_attrs.py`, stream presets in `sourcing/policy.py`) and build the client features listed in the pivot spec.

## Michael's open items (not for the agent): `~/projects/TODO-MICHAEL.md`
