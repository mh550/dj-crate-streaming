# Guards, checks and doc truth (night of 2026-10-21, milestones R1–R8)

Written 2026-10-21 from the read-only review `~/projects/dj-review-2026-10-21.md`. **Build-only:** nothing here runs live;
every live step is written into `docs/plans/2026-10-17-morning-checklist.md` for Michael (R8). The pivot spec wins on
conflict; M9 items keep the mechanism and safety rules of `docs/specs/2026-10-17-m9-remaining-ownership.md`.

Facts this spec relies on (checked 2026-10-21):
- Live `crates`/`worker` run `dj-crates:f4882ab85b` (N1, N1F, H1, H2, H3-01..04). N2–N5 and H3-05 are merged, not deployed.
- I1 and I2 are fixed in `scripts/duplicate_cleanup.py` (`_scan_time`/the repoint-log check, the size check).
- The H2 backup script and the restic timeout are installed (identical to main). The H3-03 timer is not enabled.
- `docker compose run … worker` from `/srv/docker` uses `dj-crates:${GIT_SHA:-dev}`; `GIT_SHA` is exported only by
  `scripts/deploy.sh`. A `dj-crates:dev` image (revision `dev`, 2026-10-17 18:39) exists.
- Michael answered D35 on 2026-10-19 (run INBOX): "trash the extras … Override the hold default — apply D31 literally."

## R1: doc truth (docs only; after: [])
1. `CLAUDE.md`:
   - "Staged runbooks": I1 and I2 are fixed (name the functions). Trash stays at `--dry-run` until a live `trash --dry-run` has
     confirmed `lastScan` and Michael lifts it.
   - "How to verify": 1,523 tests, about 9–10 minutes.
2. `docs/next-todos.md` "State at hand-off":
   - Live image `f4882ab85b` and what it contains.
   - PRs #5–#13 merged into main.
   - H1–H3 live, except the H3-03 timer.
   - N2–N5 merged, not deployed.
   - N1 code live, never run.
3. `docs/architecture.md`: the status rows at the top (M7 review is done; add H1–H3; N1–N4 merged, not live), and a note at
   §11 that the pivot supersedes questions 1, 2, 5, 8 and 10.
4. M9 spec header: "items 1 and 3 built (N4, N1); the rest not built".
5. `docs/hard-won-facts.md`: H2 is installed, so the nightly snapshot runs the installed copy, not the checkout.
6. A test or grep step proves each changed sentence. No code changes.

## R2: run commands in the deployed image (after: [])
Problem: the Check and the worker-stopped trash step run `dj-crates:${GIT_SHA:-dev}`, not what `scripts/deploy.sh`
deployed.
1. `scripts/live-run.sh <command…>` (bash, `set -euo pipefail`):
   - Reads the image revision of the `dj-worker-1` container, running or stopped:
     `docker inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}'`.
   - Refuses with a clear message when the container is missing, the revision is empty or `dev`, or `dj-crates:<rev>` is not
     present locally.
   - Otherwise runs `GIT_SHA=<rev> docker compose --project-directory /srv/docker run --rm --no-deps worker <command…>`, and
     prints the revision it used first.
   - `--print` prints the command without running it.
2. `scripts/live-check.sh`: the Check (`export` then `check`) through `live-run.sh`.
3. Tests with a stub `docker` first on PATH (record argv, fake `inspect` output), in the style of `tests/test_deploy_script.py`.
   Cover: the happy path; each refusal; that `GIT_SHA` is passed; that `--no-deps` is always there.
4. Docs: CLAUDE.md "Check", `docs/worker.md` "Duplicate cleanup" (trash commands) and the morning checklist use the scripts.
   D45 *default* in the pivot spec: "live one-off commands run in the deployed image, resolved from the worker container's
   revision label".
5. Never run either script in this milestone (build-only).

## R3: D35 as Michael answered it (after: [])
1. `duplicate_cleanup plan` no longer holds a group whose extra is lossless beside a lossless keeper. Such a group gets
   `"hold": null` and a `"note": "lossless pair: released by Michael 2026-10-19 (D35)"`. The keeper is still `keep_rank`.
2. `plan --hold-lossless` restores the old hold for anyone who wants it.
3. `report.md` lists these groups in their own section ("lossless pairs, will be trashed"), so Michael sees them before
   `trash`.
4. Tests:
   - default plan: no hold;
   - `--hold-lossless`: hold;
   - the report section;
   - `repoint` and `trash` treat a released lossless pair like any other group.
   - Every existing safety test stays green.
5. Pivot spec D35 row: Michael's answer (not *default*). Morning checklist step 3.1: the manual hold release is gone;
   read the new report section instead.

## R4: M9 §6 guards (Q10 default yes; after: [])
As M9 §6 "Mechanism":
1. Delete `rank --download` (`sourcing/cli.py`). An old invocation fails with a message naming Preview + Approve.
2. `scripts/tag_cleanup.py retag|move` and `scripts/dedupe_copies.py` refuse unless they can take
   `<dirname(CRATES_DB)>/worker.lock` non-blocking (the worker's lock, D18/D36), with a message saying to stop the worker.
   Use the same lock helper `duplicate_cleanup trash` uses; don't write a second one.
3. `identity_backfill apply` stays outside the lock (M9 §6).
4. Tests: refusal while a held lock exists (a background `flock` or fcntl in the test), success when free, and the removed flag.

## R5: M9 §7 playlist health and `.m3u8` history (Q11 default yes; after: [])
As M9 §7 "Mechanism":
1. After each export, the worker counts `playlist_tracks` rows on a missing or unknown `media_file`, per playlist (the
   `playlist_edit` skew condition), from read-only `navidrome.db`.
2. When the set changes, it writes one `playlist_health` event. `/api/status` carries the counts. The web client shows a
   banner ("2 entries in Tea tent point at missing files").
3. Before rewriting a changed `.m3u8`, the export keeps the previous file in `_playlists/.history/<date>/`, pruned after 30
   days. Pruning never touches anything outside `.history/`.
4. Healing stays manual.
5. Tests against the fake navidrome.db: add every column the new SELECT reads to `subsonic/fake_server.py`
   `NAVIDROME_SCHEMA` and the fake's INSERT in the same commit (hard-won facts).
6. Live steps (deploy, then what to look at) go into the morning checklist.

## R6: M9 §8a, 8b, 8c, 8h (after: [])
As the M9 §8 table:
- **8a:** an AcoustID cache by path + size + mtime (`acoustid-cache.jsonl` beside the proposal), through a process-wide
  3 req/s limiter.
- **8b:** `strip_trackno` keeps a bare leading "NN " when the rest no longer fits the wanted title ("99 Luftballons").
- **8c:** parse a MusicBrainz disambiguation-only version (`12" version`), recall only.
- **8h:** a re-import reuses a failed unfiled row (back to `needs_source`) instead of queuing a second one.

Each gets its own tests, with no network: use the captured fixtures in `fixtures/` and never invent a response shape.

## R7: M9 §5a identity picker (Q7, Q8 defaults; after: [])
As M9 §5a "Mechanism":
- An "Identity" view in the web client, served by the crates container from `/data/identity`.
- The buttons are Accept, Choose and Skip; `conflict` and `error` rows offer Skip only.
- The only candidate on the file's own album is pre-selected, and nothing is applied without a click.
- Choices go to `identity-choices.json` (crates writes only its own data dir).
- `identity_backfill apply --choices <file>` merges them, with the existing "a choice is among the row's candidates" check.
- Every pick is an event with `decided_by=michael`.
- Tests: API (fake data dir), the choices file, `apply --choices` on fixtures (dry run only).
- The live apply stays Michael's (next-todos 6), written into the checklist.

## R8: morning checklist v2 and whole-run review (after: [R1, R2, R3, R4, R5, R6, R7])
1. Rewrite `docs/plans/2026-10-17-morning-checklist.md` as `docs/plans/2026-10-22-morning-checklist.md`. Keep the old file,
   with a pointer to the new one. In order, each step with its check and undo:
   1. Pull the main checkout (the `git checkout -- …INBOX.md` first, if still there).
   2. The H3-03 timer.
   3. `grep -c '^GIT_SHA=' /srv/docker/.env`.
   4. Deploy main from a fresh worktree.
   5. `imported migrate`.
   6. `plan` (the new lossless-pair section), the repoint stages, and `trash --dry-run` through `scripts/live-run.sh`.
   7. Reconcile.
   8. The import re-runs.
   9. What R4–R7 change live and how to look at it.
2. A whole-run review (Opus) of the diff since the run's base; fix Critical and Important findings; the suite green.
