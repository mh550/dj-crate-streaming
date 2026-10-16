# M8: lifecycle (playlist attributes, derived tiers, copy replacement, proposals, play-now) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task, with superpowers:test-driven-development.
> Steps use checkbox (`- [ ]`) syntax for tracking. **Nothing in Tasks 1–13 writes to the live Navidrome, the live
> `crates.db`, `/srv/music` or the trash.** The only live writes are in Task 15, after a dry run, gated.

**Goal:** a playlist's own comment says whether it is a crate and which tier it is sourced at; crates.db only caches
that. Every track's tier is derived from the playlists that hold it. A verified better copy of the same recording
replaces the old one everywhere (playlists repointed, old file to trash); a new *version* never replaces anything and
becomes a proposal Michael answers. Pressing play on a track that is queued but not owned fetches one fast
provisional copy and queues its upgrade, which waits for approval.

**Why M8 exists** (read this before judging an edge case):
1. **One owner per fact** (spec Part 1). Fact #6 (is a playlist a crate, its tier) moves from crates.db to the
   playlist comment (D21). Today crates.db owns the flag and mirrors `#crate` best-effort; a failed mirror leaves two
   stores disagreeing, the exact bug class the spec was written against. Fact #7 (the tier a track should reach) has
   no owner today: crate rows are hard-coded `crate`, external rows carry a stored tier.
2. **The invariants** (spec Part 2): at most one copy per version; a better copy replaces, the old one goes to
   trash; a new version is an addition, never a replacement. M7 built the same-version test and verify's
   `replaceable` flag; M8 is the code that acts on them.
3. **The playlists are Michael's** (fact #5). Repointing changes what he hears, so a copy replacement may only happen
   with proof (`replaceable`), and a version swap only with his yes (D23).
4. **Navidrome edits playlists by index, and hides missing songs** (measured fact 5). Every index edit is guarded,
   and the old copy is trashed only after no playlist refers to it.
5. **Play-now (D20)** is the first approval with `tier` ≠ the row's tier, and the first one that must be fast.

**Architecture:**
- `crates/attrs.py` (pure): `parse(comment) -> Attrs(crate, tier, problems)` and `write(comment, crate=…, tier=…)`
  that touches only our tokens (`#crate`, `#tier:<t>`).
- `crates/reconcile.py`: `run()` reads every playlist comment, rebuilds the cache (`crates.enabled`, new
  `crates.tier`), logs every cache/comment disagreement, derives each song's tier as the max over its tiered
  playlists and judges it once at that tier. `set_crate` / `set_tier` write the comment first, read it back, then
  refresh the cache.
- `crates/playlist_edit.py`: the only code that edits playlist membership by index — guard against hidden missing
  rows (navidrome.db vs getPlaylist), `repoint_everywhere`, `replace_slot`, `references`.
- `crates/trash.py`: `move_to_trash` (moved from `scripts/dedupe_copies.py`, never overwrites, reverse `mv` in
  `MOVES.txt`). `BeetsFiler.forget` drops a trashed file from beets' index with `beet remove -f` (no beets import).
- `sourcing/replace.py`: a resumable copy replacement (`replacements` table: repoint → trash → scan → done), started
  by `fetch.finish` only when the stored verification says `replaceable is True`; the worker resumes unfinished ones.
- `crates/proposals.py`: `proposals` table (kinds `version_swap`, `unproven_copy`), creation after a filing,
  `apply` = `replace_slot` of that one slot. Web client shows them; `crates.cli proposals` too.
- Play-now: `approvals.purpose` (`download` | `play-now`), `fetch(score_tier=…)`, `external_wanted.library_song_id`
  and `.provisional`; the worker takes play-now first and wakes for it within a second.

**Tech Stack:** stdlib Python 3.12 (`sqlite3`, `urllib`, `tomllib`), mediafile/mutagen, beets 1.6.0 CLI in the
worker only, vanilla JS web client, Docker Compose.

**Spec:** `docs/specs/2026-10-16-ownership-and-identity.md`: Part 1 facts #5–#7 and "Who may write what", Part 2
invariants, Part 3 (Imports, Play-now D20, Approval D23), "What changes in the plan" (M8 row), "Open choices" (D20,
D21, D23 defaults are in place). Runbook: `~/projects/OVERNIGHT-2.md` § "M8 — lifecycle" and "Decisions already
made" (D10, D15, D16, D20, D21, D23). Rulings that bind M8: the M6 ledger
`.superpowers/sdd/2026-10-16-m6-worker-and-filing/progress.md` (a filed file is never forgotten; the worker daemon is
the only `fetch(approve=True)` path and the only beets writer) and the M7 ledger
`.superpowers/sdd/2026-10-16-m7-identity/progress.md` (`replaceable` = compared ∧ BER ≤ 0.20 ∧ durations agree ∧
different files ∧ ok, and it is the ONLY licence to replace a copy; `same_version` errs toward "different version").

## Global Constraints

Every task's requirements include these (M7's, carried over):

- **No sudo.** Anything root-only goes to "Needs Michael" with the exact command.
- **No real Soulseek downloads** (D7). Tests use `sourcing/fake_slskd.py` and `subsonic/fake_server.py`. No task
  and no live step creates an approval on the live `crates.db` (play-now included: it is exercised on fakes only).
- **Never write to `/srv/incoming/library-import/`.**
- **Secrets** live only in `/srv/docker/.env`; never printed, logged, committed or put in a URL. Do not source `.env`.
  Navidrome calls run inside the containers.
- **stdlib Python only** (plus `mediafile`/`mutagen`). New code never imports the beets package; beets is called as
  the `beet` CLI from the worker (`BeetsFiler`).
- **beets never writes to existing files.** No `beet write`/`modify`/`mbsync`/`move` on library files in M8.
  `beet remove -f` (index only, no `-d`) on a file M8 just trashed is the one new beets call.
- **Every tool subprocess** gets `stdin=subprocess.DEVNULL` and reads output with `encoding="utf-8", errors="replace"`.
- **Soulseek peer names stay out of events and logs.**
- **Tests:** `~/.local/bin/pytest -q`. Record the count and `git rev-parse HEAD` (the M8 base) at the start of M8
  (M7 work is still landing on this branch). Existing tests stay unchanged except the edits this plan names
  (Task 8, Task 11). New test functions may be added to existing files. Fakes mirror captured live responses or
  Navidrome's v0.64.2 source as quoted in "Measured"; Task 15 step 1 re-checks them on a throwaway Navidrome.
- **Commits:** `git add` files by name (never `-A`). Check `git show --stat HEAD` after each commit.

M8's own:

- **The comment owns crate and tier (D21).** Nothing reads `crates.enabled`/`crates.tier` as truth: `reconcile`
  rebuilds them from comments, and when the cache and a comment disagree the comment wins and an `attrs` event
  records both values. Every setter (web toggle, web tier menu, `crates.cli toggle|tier`, `create_playlist(crate=True)`,
  `import-playlist`) reads the playlist, writes the comment, reads it back, and only then refreshes the cache. A
  readback that does not parse to what was written raises; the cache is not touched.
- **Our code never changes any other byte of a comment.** `attrs.write` adds or removes only `#crate` and
  `#tier:<t>` tokens (and one adjacent space each). `#imported` is import-playlist's existing marker and stays.
- **Nothing is trashed without proof.** A copy goes to trash only when (a) the verification stored for that very
  download has `measurements["replaceable"] is True` (the literal boolean), (b) the old file's path at trash time
  equals the reference path that verification compared, (c) navidrome.db shows no `playlist_tracks` row (missing
  rows included) pointing at the old song, and (d) the old path is not the new copy's path. A new version is never
  trashed and never replaces: it becomes a proposal.
- **Repoint before trash, always.** The old file moves only after every playlist entry points at the new song, and
  the new song was indexed by an earlier scan (measured fact 6).
- **Index edits only through `crates/playlist_edit.py`,** which refuses a playlist where getPlaylist and navidrome.db
  disagree (measured fact 5). Smart playlists (`rules` set) are never edited. `scripts/dedupe_copies.repoint` is
  M3's one-off and is left alone.
- **No auto-approval.** M8 adds exactly one caller of `CrateStore.approve`: the play-now endpoint (`approved_by
  "michael"`, one `low` copy). Upgrade rows and proposals wait for Michael. The final review greps for `approve(`.
- **Trash only through `crates.trash.move_to_trash`** (never overwrites, logs the reverse `mv`).
- **A filed file is never forgotten** (M6): a replacement records old and new paths before its first step; a crash
  at any step leaves a `replacements` row the worker resumes, never a half-done swap nobody knows about.

## Measured before writing this plan (2026-10-16)

Each item says what it changes.

1. **Live playlists (navidrome.db read-only, `mode=ro`).** Navidrome **0.64.2** (image label). 44 playlists, all
   owned by `michael` (admin; the other user `amperfy` owns none). 0 smart playlists (`rules`), 0 file-synced
   (`path`). Comments: 11 are `#imported`, 1 is `#crate` ("sockseek / clouds"), 32 are empty; the longest is 9
   characters. getPlaylists omits `comment` when it is empty (fixture `navidrome_playlist_song_search3.sample.json`);
   the fake always sends `""` and `tests/test_subsonic.py` pins that, so the fake keeps it.
   **Changes:** the migration is small (item 3); `Playlist.comment` may be `None` and `attrs` treats it as `""`.
2. **Comment round trip, from Navidrome v0.64.2's source** (`server/subsonic/playlists.go`, `utils/req/req.go`,
   `core/playlists/playlists.go`; no live write was made). `updatePlaylist` reads `comment` with `StringPtr`, so a
   present-but-empty `comment=` sets `""` (clearing works) and an absent one leaves it alone. `updateMetadata`
   assigns it verbatim (no trim, no length check); the column is `varchar(255)`, which SQLite does not enforce.
   Owner **or admin** may update. Our client sends it as a GET query parameter (URL-encoded; newlines and unicode
   survive encoding).
   **Changes:** `attrs` needs no escaping, and `""` is a valid write. Because nothing was written live, every setter
   reads the comment back and refuses on a mismatch, and Task 15 step 1 round-trips unicode, a newline, 1000
   characters and `""` on a throwaway Navidrome of the same image before the migration runs.
3. **crates.db (read-only).** One crate row: "sockseek / clouds", enabled, `source='app'`, and its comment already
   says `#crate`. 2 `crate_tracks` rows, both `needs_source` (mp3 189 and 191 kbps). 62 `external_wanted` rows, all
   tier `medium` (49 `needs_source`, 2 `ok`, 11 `review`), in 7 playlists — all 7 are `#imported`. 0 approvals,
   no settings row.
   **Changes:** the migration writes nothing for the crate and adds `#tier:medium` to the 11 `#imported` playlists
   (7 with rows, 4 without: D15 says the importing playlist gets the import tier). No row changes tier.
4. **How playlist entries reference songs.** `playlist_tracks(id, playlist_id, media_file_id)`, where `id` is the
   1-based position. 1308 entries over 819 distinct songs; **401 songs sit in more than one playlist** (335 in 2,
   50 in 3, 15 in 4, one in 5, one in 6). No playlist holds the same song twice today.
   **Changes:** a copy replacement repoints *every* playlist that holds the old song, not only enabled crates
   (today's `fetch.finish` swaps crates only and would leave the old song in, say, "secondset" and the folder
   playlist, which then go silent when the old file is trashed).
5. **Missing songs (source).** `GetWithTracks` filters `missing = false`, so getPlaylist hides an entry whose file is
   gone, but its `playlist_tracks` row stays with its position. `songIndexToRemove=N` deletes position `N+1`
   *counting hidden rows*, then renumbers. So once a playlist holds a missing song, visible indexes no longer match
   positions and an index edit removes the wrong song: this is how a retag + move (new id, old id missing) broke
   playlists in M2. Today 28 `media_file` rows are missing and **0 playlist entries point at them**.
   **Changes:** `playlist_edit.checked_entries` compares getPlaylist with navidrome.db and refuses on any
   difference; every index edit goes through it; the old file is trashed only after no row (hidden ones included)
   points at it. The fake Navidrome learns the same hiding behaviour (Task 2).
6. **Navidrome's moved-file match (`scanner/phase_2_missing_tracks.go`) and its watcher.** A missing file is matched
   only against files created *after the current scan started* with the same PID; a match gives the new file the
   **old** id and deletes the new row. Navidrome also runs a filesystem watcher (log: "Watcher: Scan completed",
   per-folder scans in about 50 ms; a full scan took 5.7 s).
   **Changes:** order is fixed: the new copy is indexed by its own scan (its new id is known; `fetch` already waits
   for it), then every playlist is repointed, then the old file is trashed, then a scan. Trashing in the same scan
   window as the filing could merge the two and delete the id we repointed to; the order rules that out.
7. **The M3 trash mechanism** is in `scripts/dedupe_copies.py`: `free_path` (never overwrite: "name (2).ext"),
   `trash()` moving to `/srv/docker/_trash/<YYYY-MM-DD>/<rel>` with a reverse `mv` appended to `MOVES.txt`,
   `StillReferenced` (navidrome.db `playlist_tracks`), and `_forget_in_beets` (imports beets). The trash is empty
   today. The **worker has no trash mount**; `crates` mounts it read-only at `/trash`.
   **Changes:** `free_path` + a `move_to_trash` move into `crates/trash.py` (dedupe imports them, behaviour unchanged);
   forgetting in beets becomes `beet remove -f path:<abs>` through `BeetsFiler` (no beets import); the worker gets
   `/srv/docker/_trash:/srv/docker/_trash` read-write and `TRASH_ROOT`.
8. **What `judge` would queue at listening tiers.** The 11 `#imported` playlists hold 374 distinct songs: 230 flac,
   51 mp3 ≥320, 47 mp3 192–319, 42 mp3 128–191, 4 m4a 128–191; **none under 128 kbps**. Today's `judge` flags any
   lossy file "acceptable; lossless preferred" at every tier, because `preferred` is not a per-tier setting: tiering
   these playlists would queue 144 upgrades nobody asked for.
   **Changes:** at a tier with `strict_verify = false` (low/medium/high) `judge` checks only the allowed formats and
   the lossy floor; the "lossless preferred" upgrade and the lossless sanity checks stay crate's. The migration then
   queues 0 upgrades (also under D17's proposed floors, medium ≥128 / high ≥192).
9. **Filed external rows never reach their playlist.** `fetch.finish` sets an external row `ok` and stops; the store
   comment on `external_wanted.position` ("where a later fetch inserts the track") is unimplemented. A re-run of
   `import-playlist` appends the matched track at the end.
   **Changes:** none in M8 (Open items, question 1). It means a version-swap proposal can only target slots that
   already exist, and a play-now track plays but does not appear in its playlist until the import is re-run.
10. **The web client** shows only Navidrome entries in a playlist; external (not-owned) rows appear only in the
    Wanted tab, with no play button. **Changes:** the playlist view lists the playlist's not-owned rows with ▶
    (play-now), and the Wanted tab gets ▶ on not-owned rows (Task 12).
11. **Worker timing:** a tick every `WORKER_POLL_S` = 30 s; a filed-but-unindexed row is re-checked at most every
    `WORKER_RECHECK_S` = 300 s. **Changes:** play-now would add up to 30 s before the download starts and 300 s if
    the first scan wait misses it. The worker wakes within 1 s for a play-now approval, and play-now rows are
    re-checked every tick.

## Design decisions (made here, each with its reason)

- **Comment grammar.** Tokens are whitespace-delimited and case-insensitive: `#crate`, and `#tier:<t>` where `<t>` is
  a tier in `deploy/policy.toml`. `#tier:crate` reads as `#crate` (crate is a flag; the others are a level), and
  writing tier `crate` writes `#crate`. `#crates`, `x#crate` and `#crate,` are not tokens. An unknown tier is a
  reported problem, never an error and never written over. Several `#tier:` tokens: the highest counts, reported.
  The name markers (`[crate]`, `🎛`) still count as `#crate` for clients that cannot edit comments (today's
  behaviour); a crate flagged only by its name cannot be turned off from the web client (409: rename it).
- **Track tier = max over tiered playlists**, order = `deploy/policy.toml` order (low < medium < high < crate). A song
  in no tiered playlist has no derived tier: a `crate_tracks` row does not exist for it, and an external row keeps
  its stored tier (seed-spotify rows, rows of untiered playlists). Lowering a playlist's tier lowers its rows (it is
  Michael's explicit act; D15's "a plain re-run never lowers" is about `import-playlist` re-runs, which now write
  `#tier:` only when created or when `--tier` is given). Rows in flight (`sourcing`, `verify`) are never re-tiered.
- **`crate_tracks` covers every tiered playlist** (not only crates), judged at the song's derived tier. The table name
  stays (renaming is churn); the wanted row gains `playlists` (tiered playlists holding it) beside `crates`.
- **Proposals get their own table, not `approvals` with a kind.** An approval is a download licence the worker
  *consumes* (`pending_approvals` → `fetch`); a proposal is a question the system asks whose answer edits one
  playlist slot and downloads nothing. In one table every reader of approvals would have to filter by kind, and a
  missed filter would turn a swap into a download. They share the approver vocabulary: a proposal's `decided_by` is
  `michael` | `policy:<name>` | `agent:<id>`, so "`repoint: auto` for a tier" later is a policy deciding, not a
  redesign.
- **A copy upgrade that is not `replaceable` keeps both and asks** (kind `unproven_copy`, one proposal per slot of
  the old song in a tiered playlist). Without it the old copy stays in the crate, the next reconcile judges it
  `needs_source` again and a second approval would download a third copy. The row becomes `review` (reconcile does
  not overwrite `review`); accepting repoints that slot only and **never trashes** (not proven redundant); declining
  sets the row `failed` "swap declined; the new copy stays in the library as <rel>".
- **The worker re-exports the `.m3u8` files** every `WORKER_EXPORT_S` (300 s): `export_playlists.export` rewrites
  only changed files, so it also picks up proposal swaps made from the crates container and Michael's own edits.
- **The worker reconciles** every `WORKER_RECONCILE_S` (600 s), so a comment edited in Amperfy takes effect without
  opening the web client.
- **The crates container gets navidrome.db read-only** (`/srv/docker/navidrome:/srv/docker/navidrome:ro`,
  `NAVIDROME_DB`), because applying a proposal is an index edit and needs the guard.

## Review Focus

These are the inputs most likely to bite that no ruling covers. Each has a test in the task that owns the code:

1. **A comment edited in another client between our read and our write**, or a Navidrome that stores a comment
   differently from what we sent. Expected: the readback mismatch raises, the cache is untouched, the UI says so.
   → Task 3 `test_readback_mismatch_refuses_and_keeps_the_cache`.
2. **A playlist holding a missing (hidden) song.** Expected: every index edit on it is refused with a reason naming
   the playlist; no replacement trashes anything while it blocks. → Task 6
   `test_hidden_missing_entry_is_refused`, Task 8 `test_hidden_missing_entry_blocks_the_repoint_and_nothing_is_trashed`.
3. **A `replaceable` that is not literally `True`** (missing, `"true"`, `1`), or an old copy moved or retagged-and-
   moved since verification. Expected: keep both / blocked, never trash. → Task 8
   `test_only_a_literal_true_replaceable_licenses_the_trash`, `test_old_copy_moved_since_verification_blocks_the_trash`.
4. **A crash between repoint and trash** (worker restart). Expected: the `replacements` row resumes on the next tick
   and re-checks references before the move. → Task 8 `test_a_crash_between_steps_resumes_in_the_worker`.
5. **beets files a same-format upgrade as "… .1.flac"** next to the old file (`duplicate_action: keep`). Expected:
   the new path differs from the old; trashing the old one leaves the ".1" name (Open items). If the paths were
   equal, nothing is trashed. → Task 8 `test_new_path_equal_to_old_path_is_never_trashed`.
6. **A version swap proposed for a 12" Dub** (crate prefers extended) or for another song with a similar title.
   Expected: no proposal. → Task 9 `test_a_dub_is_not_preferred_as_a_12in`, `test_no_proposal_for_the_same_version_or_another_song`.
7. **Play-now on a row that is already owned, in flight, or `review`.** Expected: 409, no approval, no download.
   → Task 11 `test_play_now_is_refused_for_owned_in_progress_and_review_rows`.
8. **A re-run of `import-playlist` after play-now** matching the provisional copy. Expected: the upgrade row stays
   queued (today the import would set it `ok` "in library"). → Task 11 `test_reimport_does_not_close_an_upgrade_row`.

---

## File map

| File | Change | Responsibility |
|---|---|---|
| `crates/attrs.py` | create | `Attrs`, `parse`, `write` (the comment grammar) |
| `sourcing/policy.py` | modify | `tier_rank`, `max_tier` |
| `subsonic/fake_server.py` | modify | optional navidrome.db mirror; missing songs hidden but kept in positions |
| `crates/reconcile.py` | modify | cache from comments; `set_crate`/`set_tier` write first; derived tiers; `judge` per tier kind |
| `crates/store.py` | modify | `crates.tier`; tiered-playlist rows in `wanted`/`verify_ids`/`set_wanted_status`; `replacements`, `proposals`; `approvals.purpose`; `external_wanted.library_song_id`/`provisional` |
| `crates/migrate_attrs.py` | create | one-time crates.db → comments (plan, report, apply) |
| `crates/playlist_edit.py` | create | `checked_entries`, `references`, `rewrite`, `repoint_everywhere`, `replace_slot` |
| `crates/trash.py` | modify | `free_path`, `move_to_trash` (from dedupe) |
| `scripts/dedupe_copies.py` | modify | imports `free_path`/`move_to_trash` from `crates.trash` (same behaviour) |
| `sourcing/filer.py` | modify | `BeetsFiler.forget` |
| `sourcing/replace.py` | create | the resumable copy replacement |
| `crates/proposals.py` | create | `version_swaps`, `unproven_copy`, `apply`, `decline` |
| `sourcing/scorer.py` | modify | `version_rank` (the D16 bonus loop, extracted) |
| `sourcing/fetch.py` | modify | `copy_of`; verification records `reference`; `finish` → replacement / keep both / proposals; `score_tier`, `provisional` |
| `sourcing/worker.py` | modify | replacements, export, reconcile intervals; play-now first, wake, re-check every tick |
| `sourcing/import_playlist.py` | modify | `#imported #tier:<t>` on create; `--tier` rewrites `#tier:`; upgrade rows stay open |
| `sourcing/cli.py` | modify | `_fetch_env` adds `trash_root`; `retier` skips playlist-owned rows; worker intervals |
| `crates/service.py`, `crates/cli.py` | modify | tier endpoint/command; proposals; play-now; `GET /api/wanted/<id>`; `attrs migrate` |
| `web/index.html`, `web/app.js`, `web/app.css` | modify | tier menu; proposals; not-owned rows with ▶ and "fetching…" |
| `deploy/compose.yml` | modify | worker: trash rw + `TRASH_ROOT` + intervals; crates: navidrome ro + `NAVIDROME_DB` |
| `tests/test_attrs.py`, `tests/test_fake_navidrome_db.py`, `tests/test_attrs_owner.py`, `tests/test_migrate_attrs.py`, `tests/test_derived_tiers.py`, `tests/test_playlist_edit.py`, `tests/test_replace.py`, `tests/test_proposals.py`, `tests/test_play_now.py`, `tests/test_web_m8.py` | create | new behaviour |
| `tests/test_fetch.py`, `tests/test_worker.py` | modify | the named fixture edits (Task 8) |
| `tests/test_trash.py`, `tests/test_filer.py` | modify | new test functions only |
| `README.md`, `docs/worker.md`, `docs/specs/2026-10-16-ownership-and-identity.md` | modify | docs (Task 13) |
| `docs/attrs-migration-report.md` | create (Task 15, from the live dry run) | what the migration did |

---

## Part A — ownership of playlist attributes (Tasks 1–5)

### Task 1: `crates/attrs.py`, the comment grammar (model: **Sonnet**)

**Files:**
- Create: `crates/attrs.py`
- Modify: `sourcing/policy.py` (`tier_rank`, `max_tier`); `crates/reconcile.py` (`has_crate_tag`/`with_crate_tag`
  become one-line wrappers over `attrs`)
- Test: `tests/test_attrs.py`

**Interfaces:**
- Produces:
  ```python
  # sourcing/policy.py
  def tier_rank(name: str) -> int                     # index in TIERS (file order); ValueError for an unknown tier
  def max_tier(*names: str | None) -> str | None      # the highest of the non-None names; None when there are none

  # crates/attrs.py
  CRATE_TAG = "#crate"
  TIER_PREFIX = "#tier:"
  @dataclass(frozen=True)
  class Attrs:
      crate: bool
      tier: str | None                 # a valid non-crate tier from #tier:, else None
      problems: tuple[str, ...] = ()
      @property
      def effective(self) -> str | None   # DEFAULT_TIER ("crate") when crate, else tier
  def parse(comment: str | None) -> Attrs
  UNSET: object
  def write(comment: str | None, *, crate: bool | None = None, tier: str | None | object = UNSET) -> str
  ```
- Rules:
  - A token is a run of non-whitespace bounded by whitespace or the ends (`(?<!\S)…(?!\S)`), compared
    case-insensitively. `#tier:crate` sets `crate=True`. An unknown tier → problem `unknown tier 'x' in #tier:x (one
    of low, medium, high, crate)`; it is ignored for `tier` and never removed by `write` unless `tier=` is given.
    Several valid `#tier:` → the highest, plus a problem.
  - `write` with no change returns `comment or ""` unchanged. `crate=True` appends `#crate` when absent; `crate=False`
    removes every crate token (`#crate`, `#tier:crate`). `tier="<t>"` removes every `#tier:` token and appends
    `#tier:<t>` (`check_tier`; `"crate"` means `crate=True`); `tier=None` removes every `#tier:` token.
  - Removing a token removes it plus one adjacent space or tab: the one before it, else the one after it. Newlines are
    never removed. Appending: `c + ("" if not c or c[-1].isspace() else " ") + token`.

- [ ] **Step 1: Write the failing tests** in `tests/test_attrs.py`.
  - `test_parse_reads_crate_and_tier`: `"warmup #crate"` → crate; `"#tier:medium"` → tier medium;
    `"#imported #tier:HIGH"` → high; `"#CRATE"` → crate; `"#crates"`, `"x#crate"`, `"#crate,"`, `"crate digging"` →
    not crate; `""` and `None` → `Attrs(False, None)`; `"#tier:crate"` → crate.
  - `test_effective_tier`: `parse("#crate #tier:medium").effective == "crate"`; `parse("#tier:low").effective == "low"`;
    `parse("").effective is None`.
  - `test_unknown_and_repeated_tier_tags_are_problems_not_errors`: `"#tier:hgh"` → tier None, one problem naming
    `hgh`; `"#tier:low #tier:high"` → high, one problem.
  - `test_write_keeps_michaels_text_byte_for_byte`, parametrized over `"Late sets 🎛 — 120–124 BPM"`,
    `"line one\nline two\n"`, `"  leading spaces"`, `"tab\tseparated"`, `"naïve café ガ"`, a 1000-character string,
    `""`: `write(write(c, crate=True), crate=False) == c` and `write(write(c, tier="medium"), tier=None) == c`.
  - `test_write_is_idempotent_and_minimal`: `write(c) == c` for every case above;
    `write("warmup", crate=True) == "warmup #crate"`; `write("", tier="medium") == "#tier:medium"`;
    `write("#imported", tier="medium") == "#imported #tier:medium"`;
    `write("#imported #tier:medium", tier="high") == "#imported #tier:high"`;
    `write("#tier:low mix\nnotes", tier=None) == "mix\nnotes"`; `write("a #tier:hgh", tier=None) == "a"`;
    `write("x", tier="crate") == "x #crate"`; a second identical `write` changes nothing.
  - `test_write_refuses_an_unknown_tier`: `write("", tier="hgh")` raises `ValueError`.
  - `test_max_tier`: `max_tier("medium", None, "crate", "low") == "crate"`; `max_tier() is None`;
    `tier_rank("low") < tier_rank("crate")`.
- [ ] **Step 2: Run** `~/.local/bin/pytest -q tests/test_attrs.py`. Expected: FAIL (`ModuleNotFoundError: crates.attrs`).
- [ ] **Step 3: Implement** per Interfaces. `crates/attrs.py` imports only `sourcing.policy` (no Subsonic, no store).
  `reconcile.has_crate_tag(c)` becomes `parse(c).crate`; `with_crate_tag(c, on)` becomes `write(c, crate=on)`.
- [ ] **Step 4: Run** `~/.local/bin/pytest -q tests/test_attrs.py tests/test_crates.py`. Expected: PASS
  (`test_crate_tag_helpers` unchanged).
- [ ] **Step 5: Commit**
  ```bash
  git add crates/attrs.py sourcing/policy.py crates/reconcile.py tests/test_attrs.py
  git commit -m "M8: crates/attrs.py — #crate and #tier:<t> in a playlist comment, Michael's text untouched"
  ```

---

### Task 2: the fake Navidrome mirrors navidrome.db and hides missing songs (model: **Sonnet**)

**Files:**
- Modify: `subsonic/fake_server.py`
- Test: `tests/test_fake_navidrome_db.py`

**Interfaces:**
- Produces:
  ```python
  NAVIDROME_SCHEMA: str     # the subset of v0.64.2's tables M8 reads (measured fact 1/4/5):
  #   playlist(id, name, comment, owner_id, rules)       rules NULL unless state.smart has the id
  #   playlist_tracks(id INTEGER, playlist_id, media_file_id)   id = 1-based position, hidden rows included
  #   media_file(id, path, title, artist, album, duration, suffix, size, missing, mbz_recording_id)
  class FakeSubsonicServer:
      def __init__(self, port=0, username="demo", password="demo", db_path: Path | None = None): ...
  class FakeState:
      db_path: Path | None
      missing: set[str]          # song ids whose file is "gone"
      smart: set[str]            # playlist ids with rules
      def sync(self) -> None     # rewrite the mirror (no-op without db_path)
  ```
- Behaviour (mirrors measured facts 4–5): a song in `missing` is left out of getPlaylist entries, `songCount`,
  search3 and getSong (error 70), but stays in `playlist["songs"]`; `songIndexToRemove=N` removes `songs[N]` counting
  hidden songs (exactly Navidrome's position arithmetic). updatePlaylist on a `smart` playlist with track changes
  fails with error 50 ("not editable"). The mirror is rewritten at start and after every mutating method. Without
  `db_path` nothing changes for existing tests.

- [ ] **Step 1: Write the failing tests** in `tests/test_fake_navidrome_db.py`.
  - `test_db_mirrors_playlists_and_positions`: with `db_path`, `playlist_tracks` for pl-1 is
    `[(1,"s1"),(2,"s2"),(3,"s3")]`, `media_file.path` equals the song's `path`, `playlist.comment` matches.
  - `test_db_follows_every_update`: create, update (add/remove/comment), delete → the mirror matches getPlaylist each time.
  - `test_missing_song_is_hidden_but_keeps_its_position`: mark s2 missing → getPlaylist pl-1 is `[s1, s3]`, the db
    still has 3 rows with s2 at position 2 and `missing=1`; `update_playlist("pl-1", remove_indexes=[1])` removes s2
    (the hidden one) and getPlaylist is still `[s1, s3]`: the trap reproduced.
  - `test_smart_playlist_tracks_cannot_be_edited`: comment update works, track update raises `SubsonicError` code 50.
- [ ] **Step 2: Run** `~/.local/bin/pytest -q tests/test_fake_navidrome_db.py`. Expected: FAIL.
- [ ] **Step 3: Implement.** The module docstring gains one paragraph citing v0.64.2 (`GetWithTracks` filters
  `missing = false`; positions count hidden rows).
- [ ] **Step 4: Run** `~/.local/bin/pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit**
  ```bash
  git add subsonic/fake_server.py tests/test_fake_navidrome_db.py
  git commit -m "M8: fake Navidrome mirrors navidrome.db; missing songs hidden but keep their positions (v0.64.2)"
  ```

---

### Task 3: the comment owns crate and tier (model: **Opus**: it moves the owner of a fact and touches every setter)

**Files:**
- Modify: `crates/reconcile.py`, `crates/store.py`, `crates/service.py`, `crates/cli.py`, `sourcing/import_playlist.py`
- Test: `tests/test_attrs_owner.py`

**Interfaces:**
- Produces:
  ```python
  # crates/reconcile.py
  class NameMarked(Exception): ...          # the playlist's *name* carries [crate]/🎛: rename it to turn it off
  class CommentNotKept(Exception): ...      # the readback does not parse to what we wrote
  class Reconciler:                          # `mirror_tag` is removed
      def set_crate(self, playlist_id: str, enabled: bool) -> dict     # crate_view
      def set_tier(self, playlist_id: str, tier: str | None) -> dict   # None clears #tier:
      def refresh_cache(self, pl: Playlist) -> list[str]               # cache := comment; the changes as text
  @dataclass
  class ReconcileReport:                     # + two fields
      attr_changes: list[str]                # "<name>: crate off→on (comment wins)"
      problems: list[str]                    # attrs problems, "<name>: unknown tier …"
  # crates/store.py
  crates.tier TEXT                          # new column (_migrate); NULL = no #tier
  def set_attrs(self, playlist_id: str, name: str, crate: bool, tier: str | None) -> tuple[bool, str | None] | None
      # writes the cache; returns the OLD (crate, tier) when they changed, None otherwise; source='comment'
  Crate.tier: str | None
  # crates/service.py
  CrateApp.set_tier(pid, tier) -> dict;  POST /api/playlists/<id>/tier {"tier": "<t>" | null}
  set_crate / set_tier: NameMarked → 409, CommentNotKept → 502, ValueError (unknown tier) → 400
  # crates/cli.py
  python -m crates.cli tier <playlist-id> <low|medium|high|crate|none>
  ```
- `_write_attrs(pid, **change)`: `pl = client.playlist(pid)` → `new = attrs.write(pl.comment, **change)` → if
  `new != (pl.comment or "")`: `client.update_playlist(pid, comment=new)` → `back = client.playlist(pid)` → if
  `back.comment or "" != new` (exact) → `CommentNotKept` → `refresh_cache(back)` → `run()` (the derived tiers
  follow, Task 5; until then today's per-playlist reconcile). An `update_playlist` exception propagates; the cache is
  not touched.
- `run()`: for every playlist from getPlaylists: `a = attrs.parse(p.comment)`; `crate = a.crate or
  has_name_marker(p.name)`; `old = store.set_attrs(p.id, p.name, crate, a.tier)`; when `old` is not None and the
  playlist was in the cache, log an `attrs` event `"<name>: cache said crate=<…> tier=<…>; comment says
  crate=<…> tier=<…> (comment wins)"` and append to `attr_changes`; a crate flip also goes to `toggled_from_comment`
  (kept for the API). Problems go to `problems` and an `attrs_problem` event. Crates whose playlist vanished: an error,
  as today.
- `crate_view` adds `"tier"` (effective), `"tierTag"` (`a.tier`), `"crateByName"` (bool).
- `import_playlist`: a created playlist gets `comment = attrs.write(MARKER, tier=tier or IMPORT_TIER)` in the same
  `update_playlist(public=True, …)` call; a re-run with `tier` given rewrites `#tier:` through
  `attrs.write(existing.comment, tier=tier)` (adding `MARKER` when adopting with `merge`); a re-run without `tier`
  leaves the comment alone.

- [ ] **Step 1: Write the failing tests** in `tests/test_attrs_owner.py` (fake Navidrome + `CrateStore()`; the
  `svc` fixture from `tests/test_service.py` for HTTP).
  - `test_toggle_writes_the_comment_before_the_cache`: a client wrapper whose `update_playlist` raises
    `SubsonicError(0, "down")` → `set_crate("pl-1", True)` raises and `store.get("pl-1")` is None or not enabled.
  - `test_toggle_keeps_the_rest_of_the_comment`: comment `"late set\nno vocals"`; on → `"late set\nno vocals #crate"`;
    off → `"late set\nno vocals"` exactly.
  - `test_comment_wins_over_the_cache_and_the_disagreement_is_logged`: `store.set_attrs("pl-1", "Disco Edits",
    True, None)`; the comment is empty; `run()` → not enabled; one `attrs` event containing `comment wins`; the
    report's `attr_changes` names Disco Edits.
  - `test_tier_tag_sets_the_cached_tier`: comment `"#tier:high"` → after `run()`, `store.get(pid).tier == "high"`.
  - `test_set_tier_writes_and_clears`: `set_tier("pl-3", "high")` → comment `"#tier:high"`; `set_tier("pl-3", None)` → `""`.
  - `test_tier_crate_is_the_crate_flag`: `set_tier("pl-3", "crate")` → comment `"#crate"` and the crate is on.
  - `test_name_marker_counts_but_cannot_be_turned_off_here`: rename to `"Sunday Listening [crate]"`, `run()` → on;
    `set_crate("pl-3", False)` raises `NameMarked`; over HTTP → 409.
  - `test_readback_mismatch_refuses_and_keeps_the_cache`: a client wrapper whose `playlist()` returns the comment
    without our token after a write → `CommentNotKept`; the cache is unchanged.
  - `test_unknown_tier_tag_is_reported_not_applied`: comment `"#tier:hgh"` → `run()` report `problems` names it,
    cached tier None, comment unchanged (no `updatePlaylist` in the fake's request log).
  - `test_service_tier_endpoint`: `POST /api/playlists/pl-3/tier {"tier":"high"}` → 200, view `tier == "high"`;
    `{"tier":"hgh"}` → 400; `{"tier": null}` → 200, tier None.
  - `test_crates_cli_tier`: `crates.cli tier pl-3 medium` (env as in `test_crates.py::test_publish…`) prints the view;
    the comment holds `#tier:medium`.
  - `test_import_creates_the_playlist_with_imported_and_tier`: a new import → comment `"#imported #tier:medium"`;
    with `tier="high"` → `"#imported #tier:high"`; a re-run with `tier="crate"` → `"#imported #crate"`; a re-run
    without a tier leaves it.
- [ ] **Step 2: Run** `~/.local/bin/pytest -q tests/test_attrs_owner.py`. Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces. The `crates/reconcile.py` and `crates/store.py` docstrings say the
  comment owns the flag and the tier and crates.db caches them (spec fact #6); the old "the store wins" sentence goes.
- [ ] **Step 4: Run** `~/.local/bin/pytest -q`. Expected: all pass, with `tests/test_crates.py`,
  `tests/test_service.py` and `tests/test_import_playlist.py` unchanged. If one fails, stop and report it: it is a
  regression or a ruling for the controller.
- [ ] **Step 5: Commit**
  ```bash
  git add crates/reconcile.py crates/store.py crates/service.py crates/cli.py sourcing/import_playlist.py tests/test_attrs_owner.py
  git commit -m "M8: the playlist comment owns #crate and #tier (D21); setters write it first and read it back; crates.db caches"
  ```

---

### Task 4: one-time migration of crates.db flags into comments (model: **Sonnet**)

**Files:**
- Create: `crates/migrate_attrs.py`
- Modify: `crates/cli.py` (`attrs migrate [--apply] [--out PATH]`)
- Test: `tests/test_migrate_attrs.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class Change:
      playlist_id: str; name: str; old: str; new: str; why: str    # old/new: the whole comment
  def plan(client: SubsonicClient, store: CrateStore) -> list[Change]
  def report(changes: list[Change], client, store) -> str          # markdown, phone-friendly
  def apply(client, changes: list[Change]) -> tuple[list[str], list[str]]   # (written, refused: changed since plan)
  ```
- Rules (measured fact 3): an enabled `crates` row whose comment has no crate token and whose name has no marker →
  add `#crate` ("crates.db said crate"). A `#imported` playlist with no `#tier:` and no crate token → `#tier:<t>`,
  where `<t>` is `max_tier` of its external rows' tiers, else `IMPORT_TIER` ("imported at <t>", D15). Nothing is
  ever removed. Disabled crate rows and other playlists: nothing.
- `report` lists each change (`name: "old" → "new"`, why), then "at the new tier, these tracks would be queued for an
  upgrade" per playlist (judge each entry at the new effective tier with Task 5's `judge`; until Task 5 lands, the
  current `judge`), then totals. It never prints anything but names, comments and counts.
- `apply` re-reads each playlist and refuses one whose comment is no longer `old`; writes go through
  `Reconciler._write_attrs` semantics (readback check). The CLI without `--apply` writes nothing to Navidrome.

- [ ] **Step 1: Write the failing tests** in `tests/test_migrate_attrs.py`.
  - `test_plan_flags_crates_and_tiers_imported_playlists`: a store crate row for pl-1 (comment empty) and an
    `#imported` playlist with two medium rows → two changes: `"#crate"` and `"#imported #tier:medium"`.
  - `test_plan_leaves_tagged_playlists_and_others_alone`: a crate already `#crate` (as "sockseek / clouds"), an
    `#imported #tier:high` playlist, an untagged non-imported playlist → no changes.
  - `test_rows_at_several_tiers_take_the_highest`.
  - `test_dry_run_writes_nothing`: `crates.cli attrs migrate` → exit 0, the report printed, no `updatePlaylist` in
    the fake's request log.
  - `test_apply_refuses_a_comment_changed_since_the_plan`.
  - `test_report_counts_tracks_that_would_queue`: an `#imported` playlist holding a 48 kbps mp3 at medium → 1.
  - `test_cli_apply_writes_and_a_rerun_plans_nothing`.
- [ ] **Step 2: Run** `~/.local/bin/pytest -q tests/test_migrate_attrs.py`. Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** `~/.local/bin/pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit**
  ```bash
  git add crates/migrate_attrs.py crates/cli.py tests/test_migrate_attrs.py
  git commit -m "M8: crates.cli attrs migrate — today's crate flags and import tiers into playlist comments (dry run by default)"
  ```

---

### Task 5: derived track tiers (model: **Opus**: the queue's shape changes for crates, tiered playlists and external rows)

**Files:**
- Modify: `crates/reconcile.py` (`judge`, `run`), `crates/store.py`, `sourcing/fetch.py` (tier override refusal),
  `sourcing/cli.py` (`retier`, worker interval), `sourcing/worker.py` (periodic reconcile), `deploy/compose.yml`
  (`WORKER_RECONCILE_S: "600"`)
- Test: `tests/test_derived_tiers.py`

**Interfaces:**
- Produces:
  ```python
  def judge(song: Song, policy: QualityPolicy = DEFAULT_POLICY) -> tuple[str, str]
      # policy.strict_verify (crate): today's rules, unchanged
      # otherwise: "needs_source" only when the format is not allowed/denied or a lossy file is under
      # min_lossy_bitrate; never "lossless preferred", no lossless sanity checks (measured fact 8)
  class Reconciler:
      def run(self) -> ReconcileReport
          # 1. getPlaylists → refresh_cache (Task 3)
          # 2. tiered = playlists whose effective tier is not None; getPlaylist each
          # 3. derived[song] = max_tier(effective tiers of the tiered playlists holding it)
          # 4. judge each song once at TIERS[derived[song]]; upsert a crate_tracks row per (playlist, song);
          #    an existing row in sourcing/verify/review keeps its status (today's guard, + review)
          # 5. rows of playlists no longer tiered → removed ("playlist no longer tiered")
          # 6. store.derive_external_tiers() → events
      def reconcile_playlist(self, pl) -> tuple[int, int, int]    # kept (set_crate/add_to_playlist use it); judges at
                                                                   # each song's derived tier via store.song_tier
  class CrateStore:
      def song_tier(self, song_id: str) -> str | None        # max over cached tiers of tiered playlists with a live row
      def derive_external_tiers(self) -> list[str]           # rows (not sourcing/verify) of a tiered playlist take its
                                                             # tier; each change logged as today's `tier` event
      # wanted(), _crate_wanted(), verify_ids(), set_wanted_status(), find_wanted(): "enabled crate" becomes
      # "tiered playlist" (c.enabled=1 OR c.tier IS NOT NULL); row["tier"] = song_tier; row["crates"] = crate names;
      # row["playlists"] = tiered playlist names; summary() unchanged
  Worker(..., reconcile_s: float = 0, reconciler=...)        # tick step 0: reconciler.run() when reconcile_s elapsed
  ```
- `fetch(tier=…)` on a playlist row (not external) is refused as today, with the reason "its tier comes from its
  playlists (<derived>)". `sourcing.cli retier` skips external rows whose playlist is tiered, printing
  `skipped N rows whose playlist owns the tier (crates.cli tier)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_derived_tiers.py` (fake Navidrome; comments set with
  `update_playlist`).
  - `test_track_tier_is_the_highest_of_its_playlists`: s3 is in pl-1 (`#tier:medium`) and pl-2 (`#crate`) → its
    wanted row has tier `crate` (320 mp3 needs lossless at crate); un-flag pl-2, `run()` → s3 is judged at medium →
    `ok`, gone from `wanted()`.
  - `test_flagging_a_playlist_crate_queues_upgrades_without_approving`: `set_crate("pl-1", True)` → needs_source rows
    appear in `wanted()`; `store.pending_approvals() == []` and no `approved` event exists.
  - `test_listening_tiers_do_not_ask_for_lossless`: `judge` at `TIERS["medium"]`: mp3 320 → ok; mp3 48 → needs_source;
    flac 900 → ok; wma 320 → needs_source. At crate: unchanged from `test_crates.py::test_judge_policy`.
  - `test_track_in_no_tiered_playlist_has_no_row_and_external_rows_keep_their_tier`: an external row without a
    playlist keeps `high`; a row of an untiered playlist keeps `medium`.
  - `test_external_rows_follow_their_playlists_tier`: `set_tier(pl, "high")` → the playlist's `needs_source` rows
    become `high` (a `tier` event each); a `sourcing` row is untouched; `set_tier(pl, "low")` lowers them.
  - `test_untiering_removes_its_rows`.
  - `test_review_rows_are_not_clobbered_by_reconcile`.
  - `test_fetch_refuses_a_tier_override_on_a_playlist_row`.
  - `test_retier_skips_rows_whose_playlist_owns_the_tier`.
  - `test_worker_reconciles_every_interval`: `Worker(reconcile_s=600)` with a fake clock → one `run()` on the first
    tick, none on the second at +30 s, one at +601 s.
- [ ] **Step 2: Run** `~/.local/bin/pytest -q tests/test_derived_tiers.py`. Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces. `crates/reconcile.py`'s docstring states fact #7 in two lines.
- [ ] **Step 4: Run** `~/.local/bin/pytest -q`. Expected: all pass with no existing test edited
  (`test_tier_rows.py::test_crate_rows_carry_tier_crate` still holds: a crate's songs derive `crate`).
- [ ] **Step 5: Commit**
  ```bash
  git add crates/reconcile.py crates/store.py sourcing/fetch.py sourcing/cli.py sourcing/worker.py deploy/compose.yml tests/test_derived_tiers.py
  git commit -m "M8: a track's tier is the highest of its playlists' (fact #7); listening tiers judge floors only; worker reconciles every 10 min"
  ```

---

## Part B — copy replacement (Tasks 6–8)

### Task 6: `crates/playlist_edit.py`, guarded index edits (model: **Opus**: the M2 trap lives here)

**Files:**
- Create: `crates/playlist_edit.py`
- Modify: `crates/service.py` (`Config.navidrome_db` from `NAVIDROME_DB`), `deploy/compose.yml` (crates:
  `- /srv/docker/navidrome:/srv/docker/navidrome:ro`, `NAVIDROME_DB: /srv/docker/navidrome/navidrome.db`)
- Test: `tests/test_playlist_edit.py`

**Interfaces:**
- Produces:
  ```python
  class PlaylistSkew(Exception): ...      # getPlaylist and navidrome.db disagree: an index edit would hit the wrong row
  class PlaylistChanged(Exception): ...   # the playlist is not what the caller expected (edited meanwhile)
  class NotEditable(Exception): ...       # smart playlist
  class StaleSlot(Exception): ...
  def checked_entries(client, db: Path, playlist_id: str) -> list[str]
      # visible ids from getPlaylist; raises PlaylistSkew unless navidrome.db's playlist_tracks for it, in position
      # order, has the same ids and no missing/absent media_file row
  def references(db: Path, song_id: str) -> list[tuple[str, int]]   # (playlist_id, position) incl. hidden rows
  def rewrite(client, db, playlist_id: str, before: list[str], after: list[str]) -> None
      # checked_entries must equal `before` (else PlaylistChanged); ONE updatePlaylist removing from the first
      # differing index to the end and re-adding the tail of `after`; the readback must equal `after`
  def repoint_everywhere(client, db, old: str, new: str) -> dict[str, str]
      # every playlist with `old` (from references): old→new in place, dropped when `new` is already there
      # (dedupe's remap rule); returns {playlist name: "repointed" | "skipped: smart playlist" | "refused: <why>"}
  def replace_slot(client, db, playlist_id: str, index: int, old: str, new: str) -> None
      # only entries[index]; StaleSlot when entries[index] != old; `new` may already be elsewhere in the playlist
  ```
- `open_ro` from `scripts.export_playlists` is the only way it opens navidrome.db. No function here trashes anything.

- [ ] **Step 1: Write the failing tests** in `tests/test_playlist_edit.py` (Task 2's fake with `db_path`).
  - `test_checked_entries_match_the_db`.
  - `test_hidden_missing_entry_is_refused`: s2 missing in pl-1 → `checked_entries` raises `PlaylistSkew` naming
    "Disco Edits"; `rewrite`, `replace_slot`, `repoint_everywhere` on pl-1 write nothing.
  - `test_rewrite_is_one_call_and_verified`: exactly one `updatePlaylist` in the request log; readback equals `after`.
  - `test_rewrite_detects_a_concurrent_edit`: `before` ≠ the current entries → `PlaylistChanged`, no write.
  - `test_repoint_everywhere_replaces_in_place_in_every_playlist`: s3 is in pl-1 (index 2) and pl-2 (index 0), and
    pl-1 is *not* a crate → both now hold s9 at the same index; order otherwise unchanged.
  - `test_repoint_drops_a_duplicate_when_the_new_song_is_already_there`.
  - `test_references_counts_hidden_rows`: s2 missing → `references(db, "s2") == [("pl-1", 2)]`.
  - `test_replace_slot_touches_only_that_slot`: a playlist `[s3, s1, s3]` → `replace_slot(…, 2, "s3", "s9")` →
    `[s3, s1, s9]`; another playlist with s3 untouched.
  - `test_replace_slot_refuses_a_stale_slot`.
  - `test_smart_playlist_is_skipped`.
- [ ] **Step 2: Run** `~/.local/bin/pytest -q tests/test_playlist_edit.py`. Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces; the module docstring quotes measured fact 5 in four lines.
- [ ] **Step 4: Run** `~/.local/bin/pytest -q`. Expected: all pass. `cd /srv/docker && docker compose config --quiet
  && echo OK` → `OK` (never print the config).
- [ ] **Step 5: Commit**
  ```bash
  git add crates/playlist_edit.py crates/service.py deploy/compose.yml tests/test_playlist_edit.py
  git commit -m "M8: guarded playlist edits — refuse when Navidrome hides a missing entry; repoint everywhere; replace one slot"
  ```

---

### Task 7: trash and beets forget for the worker (model: **Sonnet**)

**Files:**
- Modify: `crates/trash.py`, `scripts/dedupe_copies.py`, `sourcing/filer.py`, `sourcing/cli.py` (`_fetch_env` adds
  `trash_root` from `TRASH_ROOT`, default `/srv/docker/_trash`), `deploy/compose.yml` (worker:
  `- /srv/docker/_trash:/srv/docker/_trash`, `TRASH_ROOT: /srv/docker/_trash`)
- Test: `tests/test_trash.py`, `tests/test_filer.py` (new functions only)

**Interfaces:**
- Produces:
  ```python
  # crates/trash.py
  def free_path(target: Path) -> Path                     # moved from dedupe_copies, unchanged
  def move_to_trash(rel: str, music_root: Path, trash_root: Path, day: str | None = None) -> Path
      # <trash_root>/<day or today>/<rel> via free_path; refuses a rel that escapes music_root (.., absolute) and a
      # missing source; mkdir parents; shutil.move; appends "mv <dst> <src>" (shlex-quoted) to <day>/MOVES.txt
      # before returning; returns the destination
  # sourcing/filer.py
  class BeetsFiler:
      def forget(self, path: Path) -> bool    # `beet -c <cfg> remove -f path:<abs>` (no -d); True when rc 0;
                                              # the file must already be gone (asserted), so beets can't delete it
  ```
- `scripts/dedupe_copies.trash` keeps its own loop and `MOVES.txt` at the trash root it is given; it imports
  `free_path` from `crates.trash` (its tests pin the behaviour).

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_trash.py::test_move_to_trash_never_overwrites_and_logs_the_reverse_move`: two moves of the same rel
    → `x.flac` and `x (2).flac`; `MOVES.txt` has two lines whose `mv` would restore each.
  - `tests/test_trash.py::test_move_to_trash_refuses_paths_outside_the_library` (`../x`, `/etc/x`, missing source).
  - `tests/test_filer.py::test_forget_removes_the_item_but_not_the_file`: real `beet` on a temp library (as the M6
    real-beet tests, offline config): import one file, move it away, `forget` → `items` has no row for that path;
    another item stays.
  - `tests/test_filer.py::test_forget_refuses_a_file_still_on_disk` and `::test_forget_runs_with_stdin_devnull`
    (runner spy).
- [ ] **Step 2: Run** `~/.local/bin/pytest -q tests/test_trash.py tests/test_filer.py`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `~/.local/bin/pytest -q`. Expected: all pass, `tests/test_dedupe_copies.py` unchanged.
  `docker compose config --quiet && echo OK` → `OK`.
- [ ] **Step 5: Commit**
  ```bash
  git add crates/trash.py scripts/dedupe_copies.py sourcing/filer.py sourcing/cli.py deploy/compose.yml tests/test_trash.py tests/test_filer.py
  git commit -m "M8: move_to_trash (never overwrites, reverse mv logged) and BeetsFiler.forget; the worker mounts the trash"
  ```

---

### Task 8: copy replacement = repoint everywhere + old copy to trash (model: **Opus**: the one code path that deletes)

**Files:**
- Create: `sourcing/replace.py`
- Modify: `crates/store.py` (`replacements`), `sourcing/fetch.py`, `sourcing/worker.py`, `sourcing/cli.py`
  (`WORKER_EXPORT_S`), `deploy/compose.yml` (`WORKER_EXPORT_S: "300"`)
- Test: `tests/test_replace.py`; **named edits** in `tests/test_fetch.py` and `tests/test_worker.py` (below)

**Interfaces:**
- Produces:
  ```python
  # crates/store.py
  CREATE TABLE IF NOT EXISTS replacements (
    id INTEGER PRIMARY KEY, wanted_id TEXT NOT NULL,
    old_song_id TEXT NOT NULL, new_song_id TEXT NOT NULL,
    old_path TEXT NOT NULL, new_path TEXT NOT NULL,         -- library-relative; recorded before the first step
    state TEXT NOT NULL,                                     -- repoint | trash | scan | done | blocked
    detail TEXT, trash_path TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL);
  def add_replacement(...) -> int;  def replacement(id) -> dict;  def open_replacements() -> list[dict]
  def set_replacement(id, state, detail=None, **cols) -> None      # logs a `replace` event per state change

  # sourcing/replace.py
  @dataclass
  class Ctx:
      store; navidrome: SubsonicClient; navidrome_db: Path; music_root: Path; trash_root: Path
      forget: Callable[[Path], bool] | None; scan_timeout_s: float = 120; poll_s: float = 1.0
  def licensed(verification: dict | None) -> bool          # measurements["replaceable"] is True and "reference" set
  def start(store, *, wanted_id, old_song_id, new_song_id, old_path, new_path) -> int    # state 'repoint'
  def advance(job_id: int, ctx: Ctx) -> str                # runs steps until done / blocked / an exception; idempotent
  ```
- Steps of `advance`:
  1. **repoint**: `playlist_edit.repoint_everywhere(old, new)`; then `references(db, old)` must be `[]` → `trash`.
     A refusal or a remaining reference → stays `repoint` with the reason in `detail` (the worker retries).
  2. **trash**: re-check `references(db, old) == []`; read old's current `media_file.path` from navidrome.db: it must
     equal `old_path` (else `blocked`: "old copy moved since verification"); `old_path != new_path` (else `blocked`);
     the file exists → `move_to_trash` → `trash_path`; `forget(abs old)` (a False result is logged, not fatal: the
     beets index is disposable); absent file → detail "old copy already gone". → `scan`.
  3. **scan**: `start_scan`, wait ≤ `scan_timeout_s`; old's `media_file` is `missing` or gone → `done`, else stays.
  4. `blocked` is terminal until a person acts (it shows in the Wanted row's reason and the Log tab).
- `fetch` changes:
  - `copy_of(row)`: a playlist row → its song id; an external row with `library_song_id` and status ≠ `ok` → that id
    (Task 11 creates these); else None. Everything that today keys on "not external" for copy intent (`_owned`,
    `_library_file`, the recording id, `intent = "copy"`) keys on `copy_of`.
  - `set_verification` also stores `"reference": <library-relative path of ref>` when there was one.
  - `finish(...)` after `locate_in_navidrome` found `new` (both the first call and the re-check path read the
    *stored* verification, so a re-check behaves the same):
    - `copy_of is None` → today's external path (`ok`), plus `library_song_id = new.id`.
    - `licensed(store.verification(wanted_id))` → `start` + `advance` inline; playlist rows are reconciled (the new
      song's rows `ok`, the old `removed`); FetchResult `ok` "filed; replaced the old copy (<n> playlists)" or "filed;
      replacement #<id> continues in the worker (<detail>)".
    - otherwise → **keep both**: no playlist edit; the row → `review` "kept beside <old rel>: not proven the same
      recording (<why>)" where why is "no reference compared" | "fingerprint differs (BER x)" | "lengths differ" |
      "verification failed"; event `kept_both`; FetchResult `ok` "filed; kept both (…)". (Task 9 adds the
      `unproven_copy` proposals here.)
  - The old "swap in every crate" loop is deleted.
- `Worker`: tick step 3 advances every `open_replacements()` (errors logged, the job stays); step 4 runs
  `scripts.export_playlists.export(navidrome_db, music_root, music_root / "_playlists")` when `export_s` has elapsed.
  `fetch_kwargs` carries `trash_root`.
- **Named edits to existing tests** (the only ones in this task; their assertions stay as they are):
  - `tests/test_fetch.py::world`: `FakeSubsonicServer(db_path=tmp_path / "navidrome.db")`; write a stand-in file at
    s4's library path under `tmp_path / "music"` (its fake `path`); add `trash=tmp_path / "trash"` to the dict.
  - `tests/test_fetch.py::run`: `kw.setdefault("navidrome_db", world["nd"].state.db_path)` and
    `kw.setdefault("trash_root", world["trash"])`.
  - `tests/test_fetch.py::header_only`: returns `verify(path, duration)` with `measurements["replaceable"] = True`
    when `kw.get("intent") == "copy" and reference is not None` (it models "the fingerprint matched"; the real flag is
    tested in `test_verify_*` and `test_fetch_intent.py`).
  - `tests/test_worker.py::worker`: `fetch_kwargs` gains `navidrome_db` and `trash_root` from `world`.
  - Expected afterwards: `test_fetch.py:86`, `:127`, `test_fetch_swaps_song_in_every_crate` and `test_worker.py:48`
    pass unchanged, now through the replacement, and the stand-in old file is in the trash. Any other existing test
    that fails is a regression: stop and report it.

- [ ] **Step 1: Make the named edits** to `tests/test_fetch.py` and `tests/test_worker.py` (fixtures only).
- [ ] **Step 2: Write the failing tests** in `tests/test_replace.py` (the `world` above).
  - `test_replaceable_copy_repoints_every_playlist_then_trashes_the_old_file`: s4 also in pl-1 (not a crate) and pl-3;
    after fetch: no playlist holds s4, all hold s9 in its place; the stand-in is under `trash/<today>/<rel>`;
    `MOVES.txt` reverses it; a `move_to_trash` spy asserts `references(db, "s4") == []` at the moment it is called.
  - `test_not_replaceable_keeps_both_and_touches_no_playlist`: verifier without the flag → no `updatePlaylist`, old file
    in place, row `review` with "not proven the same recording", event `kept_both`, FetchResult `ok`.
  - `test_only_a_literal_true_replaceable_licenses_the_trash`: parametrized `replaceable` ∈ {missing, `"true"`, `1`,
    `False`} → keep both every time.
  - `test_old_copy_moved_since_verification_blocks_the_trash`: change s4's path in the fake (mirror) between verify
    and trash → state `blocked`, playlists repointed, nothing moved.
  - `test_new_path_equal_to_old_path_is_never_trashed`.
  - `test_hidden_missing_entry_blocks_the_repoint_and_nothing_is_trashed`: another song in pl-2 missing → state
    `repoint` with the skew reason; the old file stays; a later tick after the fix finishes the job.
  - `test_a_crash_between_steps_resumes_in_the_worker`: `move_to_trash` raises once → job in `trash`; a worker tick
    finishes it: `done`, file in trash.
  - `test_trash_forgets_the_old_file_in_beets`: `forget` spy called once with the absolute old path, after the move.
  - `test_replacement_rows_and_events`: crate row s9 `ok`, s4 `removed`; `replace` events for repoint → trash → scan →
    done; no peer name in any event.
  - `test_worker_exports_playlists_on_its_interval`: `export` spy called on the first tick and not again before
    `export_s`.
- [ ] **Step 3: Run** `~/.local/bin/pytest -q tests/test_replace.py`. Expected: FAIL.
- [ ] **Step 4: Implement** per Interfaces. The `fetch.py` header diagram and docstring paragraph on crate rows are
  rewritten for copy replacement (repoint everywhere, then trash, only with `replaceable`; else keep both).
- [ ] **Step 5: Run** `~/.local/bin/pytest -q`. Expected: all pass.
- [ ] **Step 6: Commit**
  ```bash
  git add sourcing/replace.py crates/store.py sourcing/fetch.py sourcing/worker.py sourcing/cli.py deploy/compose.yml tests/test_replace.py tests/test_fetch.py tests/test_worker.py
  git commit -m "M8: copy replacement — only with replaceable: repoint every playlist, then old copy to trash, resumable; else keep both"
  ```

---

## Part C — version swaps are proposals (Tasks 9–10)

### Task 9: proposals (model: **Opus**: creation decides what Michael is asked)

**Files:**
- Create: `crates/proposals.py`
- Modify: `crates/store.py` (`proposals`), `sourcing/scorer.py` (`version_rank`), `sourcing/fetch.py` (two hooks),
  `crates/service.py`, `crates/cli.py`
- Test: `tests/test_proposals.py`

**Interfaces:**
- Produces:
  ```python
  # crates/store.py
  CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL,              -- version_swap | unproven_copy
    playlist_id TEXT NOT NULL, position INTEGER NOT NULL,    -- 0-based index in getPlaylist when proposed
    old_song_id TEXT NOT NULL, new_song_id TEXT NOT NULL,
    summary TEXT NOT NULL,                                   -- 'secondset #32: My Love Is Free (459 s) → (Tom Moulton 12" Mix) (580 s)'
    wanted_id TEXT, created_at REAL NOT NULL,
    decided_by TEXT, decided_at REAL,                        -- michael | policy:<name> | agent:<id> (as approvals)
    decision TEXT, result TEXT);                             -- accepted | declined | stale
  def add_proposal(...) -> int | None    # None when the same (kind, playlist, old, new) exists, open or decided
  def proposals(open_only: bool = True) -> list[dict];  def proposal(id) -> dict | None
  def decide(id, decision, decided_by, result) -> None    # logs a `proposal` event

  # sourcing/scorer.py
  def version_rank(t: Title, policy: QualityPolicy) -> int | None
      # index of the best preferred kind when _all_in(t, prefer_versions), else None; score_candidate uses it

  # crates/proposals.py
  def version_swaps(store, db: Path, new_song_id: str) -> list[int]
      # for each (playlist, position) in navidrome.db holding a song S with S != new, song_key(S) == song_key(new) and
      # not same_version(S, new), in a playlist whose effective tier T (cache) has
      # version_rank(new, TIERS[T]) is not None and (version_rank(S) is None or new's rank < S's) → a proposal
  def unproven_copy(store, db, old_song_id, new_song_id, why, wanted_id) -> list[int]
      # one per slot of old in a tiered playlist
  def apply(store, client, db, proposal_id: int, decided_by: str) -> str
      # the slot must still hold old: at `position`, else the one index holding old when there is exactly one;
      # replace_slot there; StaleSlot / PlaylistSkew / several candidates → decision 'stale' with the reason;
      # never trashes anything; an unproven_copy row whose slots are all accepted → reconcile → row ok
  def decline(store, proposal_id, decided_by) -> None
      # an unproven_copy row with no open proposal left → failed "swap declined; the new copy stays as <rel>"
  # HTTP: GET /api/proposals → open ones (+ playlist name); POST /api/proposals/<id>/accept | /decline
  #       (409 when already decided). CLI: crates.cli proposals [--all] | proposals accept|decline <id>
  ```
- Hooks in `fetch.finish`: after an external row's new song is located (copy_of None), `version_swaps(new.id)`; on
  keep-both (Task 8), `unproven_copy(...)`. A hook failure is logged as an event and never fails the fetch.
- The `copy` Song/`Copy` data for `same_version` and `song_key` come from navidrome.db `media_file` (title, artist,
  duration, `mbz_recording_id`).

- [ ] **Step 1: Write the failing tests** in `tests/test_proposals.py` (fake Navidrome with `db_path`).
  - `test_a_preferred_12in_arriving_proposes_a_swap_for_the_crate_slot`: a `#crate` playlist holds "Double Exposure —
    My Love Is Free" (459 s) at index 1; a new song "My Love Is Free (Tom Moulton 12” Mix)" (580 s) is filed for an
    external row → exactly one `version_swap` proposal, position 1, summary naming both lengths.
  - `test_no_proposal_when_the_tier_prefers_nothing`: the same in a `#tier:medium` playlist → none.
  - `test_no_proposal_for_the_same_version_or_another_song`: same label within ±4 s → none; another lead artist → none.
  - `test_a_dub_is_not_preferred_as_a_12in`: `'(12" Dub)'` → none.
  - `test_accept_repoints_only_that_slot`: the radio edit also sits at index 4 of the same playlist and in another
    playlist → accept changes index 1 only.
  - `test_accept_of_a_stale_slot_changes_nothing`: Michael removed it meanwhile → decision `stale`, no write.
  - `test_decline_is_remembered_and_not_proposed_again`.
  - `test_proposals_are_never_approvals`: after creating and accepting, `pending_approvals() == []` and a worker tick
    downloads nothing.
  - `test_unproven_copy_becomes_a_proposal_per_slot_and_accepting_never_trashes`.
  - `test_decline_of_the_last_unproven_copy_fails_the_row_with_the_new_path`.
  - `test_version_rank_matches_the_scorer_bonus`: `test_scorer_versions.py` stays green and `version_rank` agrees.
  - `test_api_accept_and_decline` (the `svc` fixture with a `db_path` fake) and `test_cli_lists_and_accepts`.
- [ ] **Step 2: Run** `~/.local/bin/pytest -q tests/test_proposals.py`. Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** `~/.local/bin/pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit**
  ```bash
  git add crates/proposals.py crates/store.py sourcing/scorer.py sourcing/fetch.py crates/service.py crates/cli.py tests/test_proposals.py
  git commit -m "M8: version swaps and unproven copies become proposals (D23); accepting edits only that slot"
  ```

---

### Task 10: the web client — tier menu and proposals (model: **Sonnet**)

**Files:**
- Modify: `web/index.html`, `web/app.js`, `web/app.css`
- Test: `tests/test_web_m8.py`

**What changes:**
- Playlist detail: beside the crate checkbox, a `<select id="detail-tier">` with `—`, low, medium, high (crate is the
  checkbox). It posts to `/api/playlists/<id>/tier`; an error (409 for a name-marked crate, 502 for a comment that did
  not stick) is shown with `alert` and the menu reverts. The summary line reads "tier medium · 40 ready · 2 need
  sourcing" for a tiered playlist.
- Wanted tab: a "Proposals" list above the rows (`GET /api/proposals`), each with its summary and **Swap** / **Keep**
  buttons (`POST …/accept` / `…/decline`), then reload. A row in `review` from keep-both shows its reason.
- Plain DOM, as today; no new library.

- [ ] **Step 1: Write the failing tests** in `tests/test_web_m8.py`: the served `index.html` has `#detail-tier` and
  `#proposals`; the served `app.js` references `/api/proposals`, `/accept`, `/decline` and `/tier`.
- [ ] **Step 2: Run** `~/.local/bin/pytest -q tests/test_web_m8.py`. Expected: FAIL.
- [ ] **Step 3: Implement.** Then check by hand with `python -m crates.cli demo` (fake Navidrome): set a tier, toggle
  a crate, and see the comment change in `/api/playlists/<id>`.
- [ ] **Step 4: Run** `~/.local/bin/pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit**
  ```bash
  git add web/index.html web/app.js web/app.css tests/test_web_m8.py
  git commit -m "M8 web: playlist tier menu; proposals with Swap / Keep"
  ```

---

## Part D — play-now (Tasks 11–12; optional if the milestone runs long: the controller may defer both to M9)

### Task 11: play-now backend (model: **Opus**)

**Files:**
- Modify: `crates/store.py`, `crates/service.py`, `sourcing/fetch.py`, `sourcing/worker.py`, `sourcing/import_playlist.py`
- Test: `tests/test_play_now.py`; **named edit**: none expected (the `approve` signature only gains a keyword)

**Interfaces:**
- Produces:
  ```python
  # crates/store.py
  approvals.purpose TEXT NOT NULL DEFAULT 'download'         # download | play-now (_migrate)
  external_wanted.library_song_id TEXT, external_wanted.provisional INTEGER NOT NULL DEFAULT 0   (_migrate)
  def approve(self, wanted_id, approved_by, candidate, tier, purpose: str = "download") -> int
  def pending_approvals(self) -> list[dict]      # play-now first, then by id
  def has_play_now(self) -> bool                 # an unused play-now approval exists
  def set_external_song(self, ext_id, song_id, provisional: bool) -> None
  def verify_ids(self, updated_before=None) -> list[str]   # rows with a play-now approval ignore the throttle

  # crates/service.py
  CrateApp.play_now(wanted_id) -> dict
      # external rows only; 404 missing; 409 when: not external ("play the library file"), library_song_id set
      # ("already in the library: play <id>"), sourcing/verify (in progress), review (pick a version first), or a
      # pending approval exists. Records approve(id, "michael", None, "low", purpose="play-now").
  POST /api/wanted/<id>/play-now → the approval;  GET /api/wanted/<id> → the row (find_wanted + approval + verify)

  # sourcing/fetch.py
  fetch(..., score_tier: str | None = None, provisional: bool = False)
      # score_tier: rank and verify at TIERS[score_tier]; the row's tier is untouched (unlike tier=)
      # provisional (external rows): finish sets library_song_id = new.id, provisional = 1, status needs_source,
      # reason "provisional low copy filed as <rel>; upgrade at <row tier> waits for approval", event
      # `upgrade_queued`; FetchResult ok "filed (provisional); upgrade queued"
  # the upgrade is then an ordinary copy row (Task 8's copy_of = library_song_id): approved by Michael, verified
  # against the provisional file, replaced with replaceable, else kept both.

  # sourcing/worker.py
  tick: a play-now approval is fetched with score_tier="low", provisional=True
  run(poll_s, *, ticks=None, sleep=time.sleep, now=time.time)   # sleeps in ≤1 s steps; ends the wait early when
                                                                 # store.has_play_now()
  ```
- `import_playlist`: a matched row is set `ok` only when it has no `library_song_id` (an upgrade row stays queued).

- [ ] **Step 1: Write the failing tests** in `tests/test_play_now.py`.
  - `test_play_now_records_michaels_approval_for_one_low_copy`: approved_by `michael`, tier `low`, purpose
    `play-now`; the row's tier stays `medium`.
  - `test_play_now_is_refused_for_owned_in_progress_and_review_rows`: 409 each; no approval written.
  - `test_worker_takes_play_now_first`: a download approval then a play-now approval → the play-now row is fetched first.
  - `test_play_now_wakes_a_sleeping_worker`: `run(poll_s=30, ticks=2)` with a fake clock/sleep; a play-now approval
    appears during the first sleep → the second tick starts ≤ 1 fake second later.
  - `test_play_now_scores_and_verifies_at_low_without_changing_the_row_tier`: verifier spy gets `tier="low"`; the
    fake slskd's fast 128 kbps mp3 wins over the slow FLAC (`tests/test_tiers.py`'s `FAST_MP3`/`SLOW_FLAC`).
  - `test_provisional_copy_requeues_the_row_as_an_upgrade_awaiting_approval`: after the tick: `library_song_id` set,
    `provisional == 1`, status `needs_source`, `pending_approvals() == []`, event `upgrade_queued`.
  - `test_upgrade_of_a_provisional_copy_is_a_copy_replacement`: Michael approves the upgrade; header-only verifier with
    replaceable → the provisional file is in the trash, `library_song_id` is the new song, `provisional == 0`, `ok`.
  - `test_reimport_does_not_close_an_upgrade_row`.
  - `test_play_now_rows_are_rechecked_every_tick`.
  - `test_get_wanted_row_endpoint`.
- [ ] **Step 2: Run** `~/.local/bin/pytest -q tests/test_play_now.py`. Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** `~/.local/bin/pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit**
  ```bash
  git add crates/store.py crates/service.py sourcing/fetch.py sourcing/worker.py sourcing/import_playlist.py tests/test_play_now.py
  git commit -m "M8: play-now (D20) — Michael's approval for one fast low copy, worker takes it first, provisional file, upgrade queued"
  ```

---

### Task 12: play-now in the web client (model: **Sonnet**)

**Files:**
- Modify: `crates/service.py` (`playlist(pid)` view gains `"wanted"`: the playlist's external rows that are not `ok`,
  with status, tier, `library_song_id`, approval), `web/app.js`, `web/app.css`
- Test: `tests/test_web_m8.py` (new functions)

**What changes:**
- The playlist detail lists "Not in the library yet (N)" under the entries; a row in `needs_source`/`failed` without
  a pending approval has ▶. Pressing it posts `/api/wanted/<id>/play-now`, shows "fetching…" and polls
  `GET /api/wanted/<id>` every 3 s for up to 180 s; when the row has `library_song_id`, it plays that song with
  `playTrack` (and shows "provisional · upgrade queued"). A failure or timeout shows the row's reason.
- The Wanted tab gets the same ▶ on external rows without a library song.

- [ ] **Step 1: Write the failing tests:** `test_playlist_view_lists_its_not_owned_rows` (service level: an
  external row of pl-1 at `needs_source` appears in `view["wanted"]`, an `ok` one does not) and
  `test_app_js_posts_play_now_and_polls_the_row` (static: `/play-now` and a `setTimeout`/`setInterval` poll of
  `/api/wanted/`).
- [ ] **Step 2: Run** `~/.local/bin/pytest -q tests/test_web_m8.py`. Expected: FAIL.
- [ ] **Step 3: Implement**, then check in `python -m crates.cli demo` that ▶ on a not-owned row shows "fetching…"
  (no worker runs in the demo, so it times out with the row's reason).
- [ ] **Step 4: Run** `~/.local/bin/pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit**
  ```bash
  git add crates/service.py web/app.js web/app.css tests/test_web_m8.py
  git commit -m "M8 web: not-owned playlist rows with play-now; fetching… then plays the provisional copy"
  ```

---

## Part E — finish (Tasks 13–15)

### Task 13: Docs (model: **Sonnet**)

**Files:**
- Modify: `README.md`: the "A crate is a playlist plus a promise" bullet (the comment owns `#crate`/`#tier:`; name
  markers still count); "Not done yet" (filed external rows are not placed in their playlist; `repoint: auto`; the
  ".1" names; the 99 existing copy groups).
- Modify: `docs/worker.md`: tick order (re-check, approvals with play-now first, replacements, export, reconcile);
  "Copy replacement and the trash" (when a copy is replaced, where the old file goes, how to undo it from
  `MOVES.txt`, what `blocked` means); "Proposals"; "Play-now"; the new env vars.
- Modify: `docs/specs/2026-10-16-ownership-and-identity.md`: fact #6 "Change from today" → "Done in M8"; Part 3 a
  note that play-now's file is not yet placed in its playlist; the proposal table decision (one line, pointing here).

- [ ] **Step 1: Write the docs** in prose with short lists, for Michael.
- [ ] **Step 2: Run** `~/.local/bin/pytest -q`. Expected: all pass. `cd /srv/docker && docker compose config --quiet
  && echo OK` → `OK`.
- [ ] **Step 3: Commit**
  ```bash
  git add README.md docs/worker.md docs/specs/2026-10-16-ownership-and-identity.md
  git commit -m "M8 docs: playlist attributes in the comment, copy replacement and trash, proposals, play-now"
  ```

---

### Task 14: Whole-milestone review and `/simplify` (controller; review on **Opus**)

- [ ] 1. `superpowers:requesting-code-review` on `<M8 base>..HEAD`, most capable model. The reviewer reads this
  plan's Global Constraints and Review Focus first. Specific checks:
  - `grep -n "approve(" -r crates sourcing web` → the only new caller is `CrateApp.play_now`;
  - `grep -n "move_to_trash\|shutil.move\|unlink" sourcing/replace.py crates/` → the trash move is reachable only
    after `licensed(...)` and `references(...) == []`;
  - `grep -n "update_playlist" -r crates sourcing` → index edits only in `crates/playlist_edit.py`; comment writes only
    through `attrs.write`; `scripts/dedupe_copies.py` unchanged in behaviour;
  - nothing reads `crates.enabled`/`crates.tier` without a reconcile having rebuilt it from comments in that process
    (the service's views read comments live through `crate_view`).
- [ ] 2. Fix Critical/Important findings test-first, one wave. Re-review the fixes.
- [ ] 3. `/simplify`. The full suite stays green.

---

### Task 15: Live: throwaway checks, rebuild, migration (dry run, then gated apply), reconcile (controller checklist)

Stop at the first failed check and record what you saw in the Status log.

- [ ] 1. **Throwaway Navidrome first** (as M2/M7 did): `deluan/navidrome` at the live tag (0.64.2, read from
  `docker inspect`) on `127.0.0.1:4599` with scratchpad data and a scratchpad music folder holding three small
  files copied from `/srv/music` (A, B, C). Scan. Then, with our `SubsonicClient`:
  - (a) comment round trip: write `"late set — ガ\nline two"`, a 1000-character string, then `""` → each reads back
    identical, and `attrs.parse` agrees;
  - (b) the hidden-entry trap: a playlist `[A, B, C]`; move B's file out; scan → getPlaylist `[A, C]`, navidrome.db
    `playlist_tracks` still 3 rows; `playlist_edit.checked_entries` raises `PlaylistSkew`;
  - (c) the replacement order: put B back, scan; file a copy N of A (a re-encode with the same tags) into the music
    folder; scan; `repoint_everywhere(A, N)`; move A out; scan → the playlist is `[N, B, C]` and N's id is unchanged;
  - (d) record (no expectation) what happens when a copy is added and the old one removed within one scan window.
  If (a)–(c) differ, stop: the fake (Task 2) or the plan is wrong. Remove the container and its data.
- [ ] 2. `cd /srv/docker && docker compose up -d --build crates worker`. `docker compose ps` shows both running;
  `docker compose logs --tail 5 worker` shows a `tick:` line; the worker sees `/srv/docker/_trash` (writable) and
  the crates container sees `$NAVIDROME_DB` (read-only).
- [ ] 3. Migration dry run: `docker compose exec -T crates python -m crates.cli attrs migrate --out /data/attrs-migration-report.md`.
  **Expected exactly** (measured facts 3 and 8): 11 changes, each `"#imported" → "#imported #tier:medium"`; 0 crate
  changes; 0 tracks would queue. Copy the report to `docs/attrs-migration-report.md`.
- [ ] 4. **Gate:** if step 3 matched exactly, run the same command with `--apply` (it writes 11 Navidrome comments).
  Otherwise stop: the report goes to the Status log with a direct question to Michael.
- [ ] 5. `docker compose exec -T crates python -m crates.cli reconcile` → `crates_enabled: 1`, `problems: []`,
  `attr_changes` only for the 11 tier additions (cache filled) and "sockseek / clouds" (`source` app → comment). The
  Wanted count equals the count before step 4 (the 2 clouds rows + the open external rows).
- [ ] 6. `docker compose exec -T worker python -m scripts.export_playlists check` → `ok`. Read navidrome.db
  read-only: 0 `playlist_tracks` rows point at missing songs.
- [ ] 7. What is not exercised live: copy replacement, proposals and play-now need a real download (D7). The Status
  log says so: the first real replacement happens with Michael's first approved crate upgrade.
- [ ] 8. "What Michael will see": the 11 playlists with their comments, plus 10 random tracks through the Subsonic API
  (artist / title / album / playlist), as tables in the Status log. Republish the status page.
- [ ] 9. Commit the report and the Status log. Milestone push and notification. Handoff `~/projects/HANDOFF-M9.md`
  per the runbook protocol, with the open questions below as direct questions.

---

## Open items (not M8; recorded for Michael / M9)

- **Question 1 — where a downloaded track goes in its playlist.** A filed external row (and a play-now track) is in
  the library but not in the playlist that wanted it (measured fact 9); today a re-run of `import-playlist` appends it
  at the end. *Default: unchanged in M8; M9 stores each import row's neighbours and inserts the file at its Spotify
  position, so a DJ set keeps its order.*
- **".1" file names:** a same-format upgrade is filed by beets next to the old copy as "… .1.flac" (`duplicate_action:
  keep`). After the old copy goes to trash the ".1" stays. A `beet move` would rename it but changes the Navidrome id
  unless the file carries a recording id (M7 backfill). Default: leave it; fix after the backfill.
- **The 99 "copies of one version" groups** found by M7 in the existing library are not touched: replacement in M8
  is for downloads that verify against the old copy. A reviewed GC proposal (fingerprint + `same_version`) is M9+.
- **`repoint: auto` per tier** (D23 later): a `policy:<name>` decider on proposals; not built.
- **D17** (tier floors) is still open; derived tiers make its effect visible per playlist.
