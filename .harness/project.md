# Project rules — dj-crate-streaming (unattended harness run)

_Appended to every harness prompt. Binding on every session._

## The one rule that shapes this night: build and test, never operate
This repo runs Michael's live music server: Navidrome, the crates and worker containers,
`/srv/music`, `/srv/_trash`. **An unattended session never touches anything live.** Every item is
built test-first against the fakes, `tmp_path` and the sandboxed suite (`.harness/check.sh`). The
live run is written down for Michael, never executed.
- Never run `docker` / `docker compose`, `scripts/deploy.sh`, or any `crates.cli` / `sourcing.cli` /
  `scripts.*` command against real data. Never read or write under `/srv`. Never call Navidrome
  (`:4533`) or slskd. Never read `/srv/docker/.env` or any secret.
- No Soulseek transfers: never `fetch --approve`.
- Read-only inputs: the repo's `docs/`, `fixtures/` and `tests/`. Facts about the live system come
  from the docs (`docs/next-todos.md` "State at hand-off", `docs/duplicates-report.md`,
  `docs/hard-won-facts.md`), not from probing it.
- **For every item that has a live step,** the closing feature writes
  `docs/live-steps/<date>-<item>.md`: the exact commands Michael runs (dry run → `--limit` → all),
  what to check after each stage, and the revert. Model it on `docs/worker.md` and the M3/M8 plans.
- Stay in this worktree. Never run git commands in `~/projects` or `~/projects/dj-crate-streaming`
  (another session and the live deploy use them).

## The spec
- **Build list:** `docs/next-todos.md` → "In order". **Tonight: items 1–4, code only.**
  1. the duplicate cleanup flow (plan → repoint → trash, D31);
  2. the `#imported` marker into `crates.db` (D33);
  3. reconcile drops the rows of a vanished playlist;
  4. insert a downloaded track at its Spotify position (M9 item 1).

  Use milestone ids `N1`…`N4`, plus `N5` for docs and wrap-up. Items 5–10 are live operations or
  "later": out of scope. Don't build pickers, the version tag or sync.
- **Design:** `docs/specs/2026-10-17-amperfy-pivot.md` (decisions D24–D34; it wins on conflict),
  `docs/specs/2026-10-17-m9-remaining-ownership.md`, `docs/specs/2026-10-16-ownership-and-identity.md`,
  `docs/architecture.md`, `docs/hard-won-facts.md` (read it before touching beets, Navidrome scans or playlists).
- **Decisions D1–D34 are settled.** A new decision that is Michael's gets the simplest reversible
  default, is recorded in the pivot spec as `D<n> *default*`, and is asked as a direct question in
  your progress entry.
- **Plans:** each milestone's first feature writes `docs/plans/<date>-n<k>-<topic>.md`. A flow that
  trashes files or writes tags needs a reviewed plan file and a reverse log (as in M3/M8).

## Code rules
- **Simple beats clever:** stdlib Python 3.10+. Adopt beets, Navidrome and slskd; don't
  re-implement them. The smallest thing that works.
- **Use what exists:**
  - `crates/playlist_edit.py` (guarded index edits);
  - `sourcing/replace.py`;
  - `crates/trash.py` (trash + `MOVES.txt`);
  - `scripts/dedupe_copies.py` (the pattern for plan → repoint → trash);
  - `scripts/duplicate_report.py` (`keep_rank`);
  - `crates/store.py`;
  - `crates/reconcile.py`.
- **Safety invariants to test:** never trash while any playlist (hidden entries included) still
  holds the file; scan between repoint and trash; recompute groups right before acting; every
  destructive step has a logged reverse.

## How to verify
- Suite: `.harness/check.sh`, which is pytest with every path in scratch and live credentials
  unset. Pass pytest arguments through for a subset (`.harness/check.sh tests/test_trash.py`).
  About 1,120 tests, **about 7 minutes**. While iterating, run the test files you touch; run the
  full suite once at the end, before flipping `passes`. The harness caches a green result per code
  tree, so an unchanged tree isn't re-run.
- No dev server. Tests use the fake Navidrome/slskd in `tests/`. New tests follow the existing
  fakes and fixtures.
