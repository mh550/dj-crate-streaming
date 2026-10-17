# N1: Navidrome duplicate cleanup (D31) — Implementation Plan

> REQUIRED SUB-SKILL: superpowers:executing-plans (inline) with superpowers:test-driven-development.
> **Nothing in N1-02..N1-05 writes to the live Navidrome, the live `crates.db`, `/srv/music` or the trash.** Every
> task is built against `subsonic/fake_server.py` and `tmp_path`. The live run is Michael's, from the runbook below.

**Goal:** for each group of files that are one recording, the best copy (lossless first) stays, every playlist is
repointed to it, and the other files go to `/srv/_trash/<day>/` with their reverse `mv` in `MOVES.txt` (D31; replaces
M9 §3's `copy_gc`). Nothing is trashed while any playlist row, hidden rows included, still holds it.

**Facts (snapshot `docs/duplicates-report.md`, 2026-10-17; the tool recomputes them every run):** 831 songs;
**102 groups, 115 extra files** (1.2 GB); **59 extras are in at least one playlist**; **9 extras are lossless beside a
lossless keeper** (9 groups, 4 of those extras in a playlist). Groups come from `scripts.duplicate_report.load` +
`duplicate_groups` (`identity.same_version`: same lead artist, base title and version label, lengths within 4 s, or
one MusicBrainz recording id), each sorted best-first by `keep_rank` (lossless, then bit rate for lossy, then
`library_map._copy_rank`: no beets ".1", not Compilations/Singles/`_`). M3 already trashed the bit-identical copies,
so every extra here is a *different file* of the same recording.

**Why not M9 §3 (fingerprint licence through `sourcing/replace.py`):** a replacement job needs a stored verification
with `replaceable is True`; tag-based groups have none, and fingerprinting 217 files is the slow part D31 dropped.
Michael reviewed the report and chose "keep the flac, repoint, trash the rest". What stays from `replace.py` is the
step order and its guards: the keeper is listed and on disk, `references()` is empty right before each move, the move
goes through `move_to_trash`, beets forgets the file, a scan follows. The trash is reversible, so the cost of a wrong
group is one `mv` and one playlist rewrite.

## Design — `python -m scripts.duplicate_cleanup plan | repoint | trash`

One module, three commands, each safe to run twice. Files live in `$CLEANUP_DIR` (default `/data/duplicate-cleanup`,
i.e. `/srv/docker/crates/duplicate-cleanup/` on the host, inside the existing `/data` mount of both containers).

| Command | Runs in | Reads | Writes |
|---|---|---|---|
| `plan` | worker image (needs `/srv/music` to see the keeper on disk), beside the daemon | navidrome.db (`open_ro`), `MUSIC_ROOT` | `plan.json`, `report.md` |
| `repoint` | crates or worker container, beside the daemon | plan, navidrome.db, Subsonic | playlists (only via `playlist_edit`), `repoint-<ts>.jsonl`, one `startScan` |
| `trash` | `docker compose run --rm worker …` **with the worker stopped** (D36) | plan, navidrome.db, Subsonic `getScanStatus` | `/srv/_trash/<day>/…` + `MOVES.txt`, `trash-<ts>.jsonl`, `beet remove`, one `startScan` |

### `plan` (N1-02) — read-only

`build_plan(navidrome_db, music_root) -> dict`, `write_plan(plan, out_dir)`. Keeper = `group[0]`. `held_by` comes from
`playlist_edit.references(db, extra)` (navidrome.db `playlist_tracks`, so hidden rows on missing files and other users'
playlists count), resolved to playlist names. `--limit N` keeps the first N unheld groups. Prints one counts line.

**Plan JSON** (`plan.json`; `made_at` is the only field that differs between two runs on an unchanged library):

```json
{"made_at": "2026-10-17T22:10:00Z",
 "groups": [{"keep":   {"id": "…", "path": "Artist/Album/01 Title.flac", "suffix": "flac", "bit_rate": 912,
                       "size": 41230000},
             "extras": [{"id": "…", "path": "Artist/Album/01 Title.mp3", "suffix": "mp3", "bit_rate": 320,
                         "size": 9450000, "held_by": ["Disco Edits", "Chicago 86"]}],
             "hold": null}],
 "playlists": [{"id": "…", "name": "Disco Edits", "before": ["s1", "s2", "s3"], "after": ["s1", "s2", "s9"]}]}
```

- `path` is relative to the music root (navidrome.db's `media_file.path`), as `move_to_trash` wants it.
- `hold` is `null` (act on it) or one reason; a held group is listed and never touched:
  - `"both lossless"`: an extra is lossless beside a lossless keeper (**D35**: often two masters; Michael clears the
    hold by editing it to `null` in `plan.json`, after which `keep_rank`'s order — the properly filed path — decides);
  - `"keeper missing on disk"`: `music_root / keep.path` is not a file;
  - `"keeper missing in Navidrome"`: the keeper's `media_file.missing` is set. `load()` returns present rows only, so
    `plan` cannot produce this one; `repoint` and `trash` report it from their own re-check (below).
- `playlists` is a **preview**: for every playlist holding an extra of an unheld group, `before` = navidrome.db order,
  `after` = `dedupe_copies.remap(before, replace)` with **one** mapping `replace = {extra: keeper}` over every unheld
  extra of every group (so a playlist holding extras of two groups gets one correct entry), in place, dropped when the
  keeper is already there. `repoint` does not replay it; it is for the report and for Michael to read.

**Report** (`report.md`): counts line; groups to act on (keeper, each extra with format, bit rate and playlists);
held groups with the reason; playlists to repoint with `before → after` entry counts. Not copied into `docs/` by the
tool (Michael copies it by hand if he wants it in the GitHub app).

### Recompute before acting (both `repoint` and `trash`)

The plan is advice; the live navidrome.db decides. For each unheld group, per extra, right before acting:
0. (`trash` only) if `music_root / extra.path` is already gone, the extra is `already gone` and the checks below are
   skipped: after the post-trash scan its row is missing, so `load()` no longer returns it and step 1 would misreport
   it as "no longer a duplicate";
1. `duplicate_groups(load(db)[0])` must still put the extra and the plan's keeper in **one** group, else
   `skipped: no longer a duplicate of <keeper>` (a retag, a new version label, a file that moved);
2. the keeper must be a present `media_file` row (not missing) — else `skipped: keeper missing`; `trash` also
   requires `music_root / keep.path` to be a file;
3. a group whose `hold` is not `null` in the plan is `skipped: held (<why>)`, whatever the recompute says.

`load()` is read once per command run (one navidrome.db read; a run over 102 groups is seconds), and
`references()` is re-read per extra right before each move, because that is the guard that must be fresh.

### `repoint` (N1-03)

Per unheld extra (in plan order, `--limit N` groups): recompute; then `playlist_edit.repoint_everywhere(client, db,
extra, keeper)`, which reads each playlist's **current** entries (so a playlist Michael edited after the plan is still
repointed correctly) and refuses on skew (a hidden row), smart playlists, other owners and concurrent edits.
Result per extra: `repointed N playlists` | `skipped: …` | `refused: <playlist>: <why>` | `dry run: would repoint
<names>` (since N1F-02, review I4: `dry run: would refuse <playlist>: <why>; …; would repoint <names>`, from
`repoint_everywhere(dry_run=True)`, the same read-only `checked_entries` checks; exit 1 as the real run would). Any
value from `repoint_everywhere` other than `repointed` is reported and makes the exit code 1; the other
groups still run. After the loop, if anything was repointed (and not `--dry-run`), **one scan, waited for**: the
scan between repoint and trash. Reuse `scripts/identity_backfill._scan` (start, then poll `getScanStatus` until
`scanning` is false *and* `lastScan` has moved; a timeout or error is reported and exits 1) — lift it to a shared
helper rather than copy it. So a `repoint` that exits 0 has had its scan; one that exits 1 tells the runbook to stop.

**Reverse log** `repoint-<UTC ts>.jsonl` beside the plan (as built in N1-03): one line per playlist
`{ts, playlist_id, name, extra, keeper, before, after}`, written by `repoint_everywhere`'s `before_write` hook once
that playlist passed its checks and **right before its own write**, fsynced. So `before` is exactly what the write
replaces (even if Amperfy edited the playlist since the plan), and a refused playlist gets no line. No second line is
needed: `repointed` means `rewrite` read the playlist back equal to `after` (else `EditNotKept`, reported as
`failed`). The happy-path test counts two lines (pl-1, pl-2). Every run that is not a dry run and reached a playlist
check ends with the waited scan, so a re-run after a scan timeout cannot exit 0 unscanned. `--dry-run` writes no log,
sends no `updatePlaylist` and opens no crates.db.

Each playlist written is also a crates.db event (`after_write` hook, below). The worker's own reconcile
(`WORKER_RECONCILE_S`, 600 s) re-reads the repointed playlists and refreshes `crate_tracks`; the runbook also runs
`crates.cli reconcile` once.

### `trash` (N1-04)

Preconditions for the whole run, each raising `CleanupRefused` before anything moves:
- **the worker lock** `<dirname(CRATES_DB)>/worker.lock` is taken with `sourcing.worker.hold_lock` for the whole run
  (held by the daemon → `CleanupRefused("stop the worker first")`). **D36**: beets has one writer and nothing files
  or replaces a copy while this moves files; `plan` and `repoint` do not take it.
- **no scan running**: `client.scan_status()["scanning"]` is false (a scan in progress makes navidrome.db's view of
  `missing` and `playlist_tracks` momentary). Checked again before every move, not only once: `ND_SCANSCHEDULE: 1h`
  can start one mid-run; a scan found mid-run stops the run (`CleanupRefused`, the files moved so far stay logged).
  Since N1F-02 (review I3), when files had moved, it first waits for that scan to end, starts one more and waits
  (the running one may have begun before a move), then re-reads `references()` for every moved file and puts back
  any a playlist now holds (a `restored` trash line, a `cleanup` event; one more scan after a put-back).

Per unheld extra: recompute (above); **`playlist_edit.references(db, extra)` must be empty** — hidden rows, smart
playlists and other users' playlists included — else `refused: still in <n> playlist entries` and the file stays;
an extra that is the `library_song_id` of an in-flight `external_wanted` row (status not `ok`/`removed`) or the old or
new song of an open replacement job (`REPLACEMENT_OPEN`) is `refused: in use by <ext-N | replacement #k>` (an `ok`
row that names an extra stays as history: the keeper is the same recording); likewise an approval not yet finished
for a wanted row whose song is the extra (it would file a new copy no playlist uses). The keeper and the extra must
be different files (`os.path.samefile` false, as `replace.proof` refuses `old_path == new_path`). Then:
1. `crates.trash.move_to_trash(extra.path, music_root, trash_root)`: it writes `mv <trash path> <library path>`
   (shell-quoted) to `<trash>/<day>/MOVES.txt` **before** the move, never overwrites (`free_path`), and survives a
   crash with the file in one place or the other;
2. **`references(db, extra)` again, right after the move** (as `replace._trash` does): Amperfy and the web client
   stay up while `trash` runs, and Navidrome accepts adding a song whose file has just gone; that row would become
   hidden after the scan. If non-empty, `crates.trash.restore(trash_path, extra.path, music_root)` puts the file
   back and the extra is `refused: added to <n> playlist entries during the move` (no `forget`, no trash line);
3. `forget(music_root / extra.path)` (`BeetsFiler.forget`, i.e. `beet remove -f path:<abs>`; a failure is logged,
   not fatal: beets' index is a cache);
4. one line `{ts, extra, path, keeper, trash_path}` to `trash-<UTC ts>.jsonl`, written **after** `forget`.

An extra whose file is already gone is `already gone`; `forget` is called for it only when no `trash-*.jsonl` line
names it (a crash between the move and `forget` is healed by the next run; a finished one is not forgotten twice).

After the loop, if a file moved, one scan, waited for as in `repoint`, so Navidrome marks the extras missing (their
`media_file` rows stay, with no playlist rows on them, until Michael purges missing files in Navidrome). The run then
re-checks `references()` for every extra it moved; one that reappeared is restored as in step 2 and reported, and
the run scans once more (the first scan marked it missing, so its playlist row would stay hidden until the next one). Exit 1 when anything was refused. No new deleting code:
`move_to_trash` stays the only library-file mover; this is its second caller after `sourcing/replace.py`.

**Why the keeper is never re-identified by Navidrome:** measured fact 6 (retag + move between scans gives a new id)
is about a file that moves; here the keeper does not move and was indexed long ago, and the extras leave the library,
so the scan after `trash` only marks the extras missing.

### Events (N1-05)

Every repoint and move is also a crates.db event (`store.log`, kind `cleanup`, `song_id` = the extra; `detail` names
the playlist or the trash path relative to the trash root). No peer names exist here; no absolute library path goes
into an event beyond what `MOVES.txt` already holds. As built: `repointed <playlist> to <keeper>` (`playlist_id` set,
from `repoint_everywhere(after_write=…)`, after the readback), `trashed to <day>/<path>` (after the trash-log line),
`put back from <day>/<path>: in <n> playlist entries during|after the move`. Each is committed at once (no write lock
held over a scan). The jsonl logs and `MOVES.txt` stay the record: an event that cannot be written (crates.db busy)
is noted on stderr and never fails the action. `CRATES_DB` must be set and name an existing file (exit 2): never
`Config.from_env`'s `./data/crates.db` default, whose folder would hold the wrong `worker.lock`.

### Undo

- A trashed file: its `MOVES.txt` line run as `mv -n …` (never over a file placed at that path since), or
  `crates.trash.restore`, which refuses the same way; then scan. The song comes back under its old id only while
  its missing `media_file` row still exists, i.e. **before** Michael purges missing files in Navidrome.
- A repointed playlist: after its files are back and scanned, replay the playlist's lines of `repoint-<ts>.jsonl`
  **newest first** (a playlist touched for several extras has several lines; each `before` is the state just before
  that edit), each as `playlist_edit.rewrite(client, db, playlist_id, after, before)`; the oldest line's `before` is
  the playlist as it was. The `.m3u8` exports are a 5-minute mirror (M9 §7) and the runbook re-exports at every
  stage, so they are not an undo source; the jsonl is.

## Safety tests each task must have

| Rule | Task | Test |
|---|---|---|
| Never trash while `references(db, extra)` is non-empty, hidden rows included | N1-04 | before repoint → `refused: still in 2 playlist entries`, nothing moved; a hidden missing row in a third playlist alone blocks the move |
| Refuse while a scan is running | N1-04, N1F-02 | `state.scanning = True` → `CleanupRefused` before any move or log line; a scan that starts after the first move stops the run before the second, is waited for, one more scan follows, and a moved file a playlist took meanwhile is put back |
| Scan between repoint and trash | N1-03 | `repoint` waits until `lastScan` moves (the fake's `getScanStatus` gains `lastScan`, set by `startScan`); a scan that never finishes → exit 1; `trash` refuses to start unless `lastScan` is after the newest `repoint-*.jsonl`'s mtime (N1F-01) |
| The file on disk is the planned file | N1F-01 | a file of another size at the extra's path than `media_file.size` or the plan's `size` (plans record it since N1F-01) → `refused: <path> is N bytes on disk, navidrome.db says M, the plan says P: not the planned file`, the other extras move |
| A row added during the move puts the file back | N1-04 | the `before=` hook adds the extra to a playlist in the fake → file restored at its path, `refused`, no `forget`, no trash line |
| Keeper and extra are different files | N1-04 | extra path a hard link / same file as the keeper → refused, nothing moved |
| Crash between move and `forget` heals | N1-04 | file gone, no trash line → next run calls `forget` once; file gone with a trash line → not called |
| Refuse while the worker runs | N1-04 | another fd holds `worker.lock` → `CleanupRefused("stop the worker first")` |
| A pair no longer in one `duplicate_groups` group is skipped | N1-03, N1-04 | retag the extra in the fake after `plan` → `skipped: no longer a duplicate of <keeper>`, no write |
| Keeper on disk and not missing in navidrome.db | N1-02 (hold), N1-03, N1-04 | keeper file absent → held at plan; keeper removed from the fake / marked missing after plan → `skipped: keeper missing` |
| Held groups are never touched | N1-02, N1-03, N1-04 | two flac copies → `both lossless`, no `playlists` entry, repoint/trash skip it |
| Every move has its `MOVES.txt` line before it happens | N1-04 | read back `mv <quoted trash path> <quoted library path>`; `before=` hook sees the line already written |
| Every playlist edit has its reverse line before the write | N1-03 | log lines exist with the fixture's `before` even when the fake's `updatePlaylist` raises; replaying them newest first restores the fixture order |
| Only `playlist_edit` edits playlists | N1-03 | `srv.state.requests` holds no `updatePlaylist` outside `repoint_everywhere`'s; `--dry-run` sends none |
| Idempotent | N1-02..N1-04 | plan twice → equal JSON but `made_at`; repoint twice → no second `updatePlaylist`; trash twice → `already gone`, `forget` not called again |
| Nothing written by `plan` | N1-02 | navidrome.db bytes, fake playlists and `music_root` listing equal before and after |

## Tasks

- **N1-01** (this file): the plan; ledger rows D35, D36 in the pivot spec.
- **N1-02** `plan`: `bit_rate` in the fake navidrome.db mirror (`NAVIDROME_SCHEMA` + INSERT from `bitRate`), the s9
  flac copy of s3 as the fixture group; `build_plan`, `write_plan`, `--limit`, `--out`.
- **N1-03** `repoint`: recompute, `repoint_everywhere`, reverse log, one waited scan (shared `_scan` helper; the
  fake's `getScanStatus` gains `lastScan`), `--limit`, `--dry-run`.
- **N1-04** `trash`: lock, scan check before every move, already-gone first, recompute, `references()` empty before
  and after each move (restore on a late reference), keeper ≠ extra, in-flight crates.db rows and approvals,
  `move_to_trash`, `forget` (healing a crash), trash log, one waited scan, `--limit`, `--dry-run`.
- **N1-05** review and simplify; `main()` with the worker's environment (`NAVIDROME_DB`, `MUSIC_ROOT`, `TRASH_ROOT`,
  `CRATES_DB` for the lock and events, `SUBSONIC_*` via `crates.service.Config.from_env`, `CLEANUP_DIR`); events;
  one end-to-end test plan → repoint → trash → `export_playlists` export + check; docs: `docs/worker.md` runbook,
  `docs/architecture.md` §7 ("the one library-file mover" row names both callers) and the §8 operations table,
  `docs/next-todos.md` item 1 "built (N1), not run live". `scripts/dedupe_copies.py` is not retired here (M9 Q10).

## Live runbook (for Michael, morning; N1-05 copies it into `docs/worker.md`)

All from `/srv/docker`, image deployed from this branch with `scripts/deploy.sh` (note the previous image tag for
rollback). One live writer at a time. Stop at the first surprise and undo from the logs.

**check** below means `docker compose run --rm worker sh -c 'python3 -m scripts.export_playlists export &&
python3 -m scripts.export_playlists check'`: only the worker image mounts `/srv/music` (the crates container has no
library, so its `check` finds no `.m3u8` files), the worker's own export runs only every 300 s and not at all while
it is stopped, and a check without a fresh export reports "stale" by design. The re-export overwrites the `.m3u8`
mirror, which is why the repoint jsonl, not the exports, is the playlist undo.

1. **Before:** `scripts/snapshot-crates-db.sh`; `sqlite3 /srv/docker/navidrome/navidrome.db ".backup …/navidrome.db.pre-n1.snap"`;
   note the last restic run and the running image; **check** is green.
2. `docker compose exec -T worker python3 -m scripts.duplicate_cleanup plan` → read `duplicate-cleanup/report.md`;
   clear any `both lossless` hold you want acted on by setting it to `null` in `plan.json`.
3. `docker compose exec -T worker python3 -m scripts.duplicate_cleanup repoint --dry-run`, then `repoint --limit 5`
   (it waits for its scan), **check**; `--limit 50`, check; all, check. Then
   `docker compose exec -T crates python3 -m crates.cli reconcile`.
4. `docker compose stop worker`; `docker compose run --rm worker python3 -m scripts.duplicate_cleanup trash --dry-run`;
   `trash --limit 5` (it waits for its scan), **check**; `--limit 50`, check; all, check. Every refusal is read before
   going on.
5. `docker compose up -d worker`. Expected end state: 831 − 115 + the extras of held groups songs listed (**730** if
   the 9 `both lossless` groups stay held: they hold 14 extras, 9 lossless and 5 lossy, and a hold covers the whole
   group), 0 playlist rows on a missing file, check green. Do not purge missing files in Navidrome until you are sure:
   the purge is what makes a restored file come back under a new id.

## Review focus

An extra held only by a hidden row or a smart playlist (must stay on disk); a playlist holding both the extra and the
keeper (the extra's row is dropped, the keeper keeps its place); a playlist holding the extra twice; a group of three
where one extra is refused and the other moves; the keeper retagged between plan and trash; a crash between
`MOVES.txt` and the move, between the move and `forget`, and between the repoint log line and the write; a playlist
added to while `trash` moves its extra; re-running every command; an
`external_wanted` row in flight on an extra; the worker started again while `trash` runs (the lock is held, so it
exits).
