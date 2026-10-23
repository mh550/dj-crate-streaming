# dj-crate-streaming: how the system works (maintainer's guide)

Written 2026-10-16 from the code on `overnight2/2026-10-15` at `e73e803`. Where a doc and the code disagree, this
file says what the code does (see §10b). History of M1–M5: [`RECAP-M1-M5.md`](../../RECAP-M1-M5.md).
Legend: **built** = in the code; **live** = also running on the box; **planned** = only in a plan.

> **2026-10-17 pivot** ([`specs/2026-10-17-amperfy-pivot.md`](specs/2026-10-17-amperfy-pivot.md)): one download quality
> (lossless, or lossy at 256 kbps or more), no 12" preference or stand-in (exact track), and **the crates app owns the
> crate flag** (`CRATES_OWNER=app`; no `#tier` or `#crate` in playlist comments). Text below that describes the
> comment-owned design (D21, tiers, D16) is the retired design, kept where the code still has it.

| Milestone | State |
|---|---|
| M6 worker, approvals, beets filing, stream "server" | built, **live** (images built 10:16) |
| M7 identity (Tasks 1–10) | built, **live** since 2026-10-17 (image `dj-crates:328eca5f2f`) |
| M7 review (Task 11) | done |
| H1-H3 (snapshots, heartbeat, healthchecks, backup job, Gatus, disk timer) | **live** (image `dj-crates:f4882ab85b`), except the H3-03 timer and H3-05's changes to it (merged, not installed) |
| M7 live proposal (Task 12), gated apply (Task 13) | not done; Task 13 waits for you |
| M8 lifecycle (Parts A–D: replacement, proposals, play-now; ownership changed by the pivot) | **built, live** since 2026-10-17; the trash-move probe in §9 has not been run (it needs the first real replacement) |
| N1-N4 (run `dj-2026-10-17`: duplicate cleanup, imported marker in crates.db, vanished-playlist cleanup, placement) | merged into `main`, **not live** except N1's code (never run); live steps in `docs/plans/2026-10-22-morning-checklist.md` |
| R1-R7 (run `dj-crate-streaming-2026-10-21`: doc truth, `live-run.sh`, D35 lossless pairs, guards, playlist health and history, M9 small items, identity picker) | built on `harness/dj-crate-streaming-2026-10-21`, **not deployed**; live steps in `docs/plans/2026-10-22-morning-checklist.md` |
| M9 | [`docs/specs/2026-10-17-m9-remaining-ownership.md`](specs/2026-10-17-m9-remaining-ownership.md): item 3 built (N1, not run live), item 1 placement built (N4, not deployed), items 5a, 6, 7 and 8a/8b/8c/8h built (R7, R4, R5, R6; not deployed); the rest not built |

Checked live (read-only) when this was written: the worker image has no `deploy/policy.toml` and no
`scripts/identity_backfill.py`, so every M7 and M8 command below needs a rebuild first. The M8 rebuild has a required
order: read §9 before running `docker compose up --build`.

---

## 1. What it does, end to end

Navidrome serves the library in `/srv/music` to the phone (Amperfy, or our web client). Spotify playlists are
imported as Navidrome playlists: tracks the library has are put in, in Spotify order; tracks it lacks become
**wanted rows** in `crates.db`. A playlist can be flagged a **crate** (files that go on real DJ systems); its tracks
are judged against the crate quality policy, and weak ones become wanted rows too. For a wanted row you press
**Preview** (search Soulseek, rank, show the pick) and **Approve**. The **worker** container then downloads that
file through slskd behind the VPN, checks it (`verify`), files it into `/srv/music` with beets, asks Navidrome to
rescan, copies Navidrome's names back onto the row, and for a crate swaps the new song into the playlist. Nothing
downloads without an approval. M7 adds one definition of "same song / same version / same copy" and a reviewed
backfill of MusicBrainz ids into the library's tags. M8 replaces proven-worse copies (old one to trash), asks
before swapping versions and adds play-now. (The pivot moved the crate flag's owner from the playlist comment to
`crates.db`, set in the crates web client.)

## 2. Components

```
 Amperfy ─────────── Subsonic over the tailnet ──────────┐
 web client ──▶ crates :4580 ── 302 signed stream URL ───┤
                  │ (API, web UI, Preview)               ▼
                  │                         navidrome :4533 ─ro─▶ /srv/music
                  │ search                    navidrome.db ─ro─┐
                  ▼                                            │
 gluetun (VPN) ═netns═ slskd ──▶ /srv/incoming/soulseek        │
                  ▲               │ downloaded file            │
                  │ search,       ▼                            ▼
   crates.db ◀──▶ worker ── verify ── beet import ──▶ /srv/music (rw)
   (crates and      enqueue    └── beets index: /srv/docker/beets/library.db
    worker write)
```

| Service | Runs | Mounts (host → container) |
|---|---|---|
| `navidrome` | `deluan/navidrome:0.64.2` (pinned 2026-10-17; was `:latest`, same image), `127.0.0.1:4533`, scan hourly + file watcher | `/srv/music` → `/music` **ro**; `/srv/docker/navidrome` → `/data` |
| `crates` | `python -m crates.cli serve`, `127.0.0.1:4580` | `/srv/docker/crates` → `/data`; `/srv/_trash` → `/trash` **ro**; `/srv/docker/navidrome` → same path **ro** (`NAVIDROME_DB`, M8) |
| `worker` | `python -m sourcing.cli worker`, `DJ_WORKER=1`, no port | `/srv/music`, `/srv/docker/beets`, `/srv/incoming/soulseek` rw at the **same paths**; `/srv/docker/crates` → `/data`; `/srv/docker/navidrome` **ro**; `/srv/_trash` rw at the same path (M8, `TRASH_ROOT`) |
| `slskd` | in gluetun's network namespace; 5 upload slots, 586 KiB/s | `/srv/docker/slskd` → `/app`; `/srv/incoming/soulseek` → `/app/downloads`; `/srv/music` → `/app/shared` **ro** |
| `gluetun` | ProtonVPN WireGuard (NL), port forwarding; publishes `127.0.0.1:5030` for slskd | `/srv/docker/gluetun` |
| beets | not a service: the `beet` 1.6.0 CLI, run only by the worker's filer | config `deploy/beets.yaml` (`-c`), state `BEETSDIR=/srv/docker/beets` |

- `crates` and `worker` are one image (`Dockerfile`: python 3.12-slim + ffmpeg, flac, fpcalc, beets 1.6.0,
  mediafile 0.12.0). The build context is `CRATES_SRC` in `.env`, i.e. **the repo's working tree** (§10).
- Only `127.0.0.1` ports are published; `tailscale serve` on the host puts 4533 and 4580 on the tailnet.
- The request routes (`/api/requests`, `/api/catalog/search`) are documented for clients in [`api.md`](api.md).
- Who may write what: Navidrome writes only its DB (never files). `crates` writes `crates.db` and Navidrome
  playlists (the comment attributes, add/create, a proposal's one-slot swap), plus the Identity view's
  `/data/identity/identity-choices.json` (R7, below); it has no library mount, so it cannot download or file
  (`fetch` refuses, `sourcing/fetch.py:142-148`). The worker is the only process that downloads, runs beets or
  moves files into `/srv/music`. slskd writes only its downloads folder; it sees `/srv/music` read-only and
  never sees `/srv/incoming/library-import` (your originals).

Code map: `subsonic/` Navidrome client + fake; `crates/` store, attrs, reconcile, playlist_edit, trash, proposals, HTTP service, CLI; `sourcing/` scorer,
verify, fetch, replace, filer, worker, identity, policy, import, MusicBrainz/AcoustID/Spotify/slskd clients;
`scripts/` one-off and backfill tools (tag cleanup, dedupe, export playlists, identity backfill); `web/` vanilla JS.

Album requests (S2, run `dj-crate-streaming-2026-10-22-build`, not deployed): `sourcing/requests.py` records a Spotify
album or track URL as one request (`add_spotify`, its MusicBrainz release by `match_request_release`) and a playlist
import as one `playlist` request (`add_playlist`); `sourcing/album.py` is the album-first planner, pure (no I/O:
search responses in, `AlbumPlan` out: one primary folder, a same-release secondary, per-track rows); `sourcing/album_job.py`
searches, plans, takes the request's approval (`album` purpose, D7) and runs the job in the worker: one enqueue per
peer, fetch in planned mode per row, a folder switch on trouble, each row capped at its planned folder, one other
folder and one per-track fetch. (e) below; plans `plans/2026-10-22-s2-album-requests.md`, `plans/2026-10-22-S2-album-tags.md`.

## 3. Data stores and who owns each fact

The rule (spec `docs/specs/2026-10-16-ownership-and-identity.md` Part 1): one owner per fact; every other copy is
derived or a mirror.

| Fact | Owner | Writers | Why |
|---|---|---|---|
| Names (artist, title, album…) | file tags | `write_minimal`; beets on fresh downloads | travels with the file |
| Which recording (MB id, ISRC, AcoustID) | file tags | identity `apply`; beets on confirmed match | keeps Navidrome ids stable |
| Where a file lives | `deploy/beets.yaml` paths | beets in the worker | one convention |
| Which songs exist, their ids | Navidrome (`navidrome.db`) | Navidrome's scan | every client asks it |
| Playlist membership + order | Navidrome | you in any client; our logged commands | you edit in Amperfy |
| Made by import-playlist | `crates.db` `imported_playlists`, one row per playlist id (D33, built in N2); no comment is read | import (`--merge` adopts), `crates.cli imported migrate` | D33, D37 |
| Is a crate | `crates.db` (`crates.enabled`, source `app`); no comment or name is read | you, in the crates web client (`crates.cli toggle`) | D27 (was D21) |
| Quality a file must reach | one rule: lossless or lossy ≥ 256 kbps | `deploy/policy.toml` | D24 |
| Version preferences | none: the exact track is sourced | `deploy/policy.toml` (no `[versions.*]`) | D26 (was D16) |
| Quality of a file | measured by `verify` | worker (`verifications` is a cache) | re-measurable |
| Queue, approvals, log | `crates.db` | crates service, worker | nowhere else to live |
| Stream quality | the client / Navidrome player profile | you | D25 (D19) |
| Originals | `/srv/incoming/library-import` | nobody (read-only) | safety net |
| Secrets | `/srv/docker/.env` | you | never printed |

**crates.db** (`crates/store.py:26-77`, SQLite WAL, `/srv/docker/crates/crates.db`). A *wanted id* is a Navidrome
song id for a crate row, or `ext-N` for an external row.

| Table | Holds | Written by |
|---|---|---|
| `crates` | cache of the comment: playlist id, name, `enabled`, `tier`, `source` (`app`/`comment`) | reconcile, the setters |
| `replacements` | one copy replacement: old/new song and path, `state` (`repoint`/`trash`/`scan`/`done`/`blocked`), `trash_path` | fetch, worker |
| `proposals` | one question per playlist slot (`version_swap`/`unproven_copy`), decision, who decided | fetch, Wanted tab / CLI |
| `crate_tracks` | per crate × song: facts, `status`, `reason` | reconcile, fetch |
| `external_wanted` | tracks not in the library: names, length, tier, playlist + position, `asked_*`; S2: `request_id` (the first request that asked for it; a playlist request holds it loosely, `takeable`), `track_no`, `mb_recording_id` (verify's recording id, S2-03) | import, seed, fetch |
| `imported_entries` | every song import-playlist added or the worker placed (D13: removed stays removed) | import, placement |
| `imported_playlists` | playlists import-playlist made or adopted (D33; was the `#imported` comment) | import, `imported migrate` |
| `import_order` | every row of a playlist's last real import in Spotify order: position, matched song or queued `ext-N` (N4) | import (replaced per run), `forget_playlist` |
| `placements` | one per (wanted row, playlist): `open`/`writing`/`done`/`given_up`, `attempts`, `detail` (N4) | worker (`crates/placement.py`), `forget_playlist` |
| `requests` | one album, playlist or track request (S2-01): `kind`, `source` URL, `artist`, `album` (a playlist's name), `year`, `mb_release_id`, `tracktotal`; **no status column**: `request_status` derives it from its rows (`done`/`failed`/`partly`/`approved`/`open`) | `sourcing/requests.py` (seed-spotify, `import-playlist --request`) |
| `approvals` | `approved_by`, candidate JSON, tier, `used_at`, `result`; `purpose` `download`, `play-now` (D20) or `album` (one row of a request's album job, S2-05) | Approve, worker |
| `previews` | last search-and-rank per wanted id | Preview |
| `verifications` | last `verify` result per wanted id | worker |
| `events` | append-only log (`approved`, `pick`, `filed`, `renamed`, `reference`, `playlist_health`…) | everything |
| `settings` | `stream_tier` (absent = `server`); `playlist_health`: JSON list of `{id, name, missing}`, our user's non-smart playlists (D46) with entries on a missing or unknown song (absent = never counted, `/api/status` `playlistHealth` `[]`) | web client; worker (after each export, R5) |

Row statuses: `needs_source → sourcing → verify → ok | failed`, plus `removed` (left a crate) and `review`
(import found several versions; a person must pick). A filed file's path rides **in the reason text**
(`store.py:85` regex `filed_path`), not in a column.

Other stores:
- **`navidrome.db`**: songs (`media_file`, real library-relative `path`), playlists (`playlist_tracks`, position =
  row id). Read read-only by `fetch._library_file`, `export_playlists`, identity `apply`. Never written by us.
- **beets `library.db`**: a disposable index of the library. Rebuild with `beet update -M` (file → DB, no
  moves). Nothing reads a fact from it in preference to the file. The filer reads it read-only to find what an
  import just added (`filer.py:238-254`).
- **Playlist comment**: left empty by this system (D33). Nothing reads it to decide anything; import-playlist
  writes none, and `crates.cli imported migrate` strips the old `#imported` marker (N2). Under the retired
  `CRATES_OWNER=comment` it owned the playlist's attributes (M8): `#crate`, `#tier:<t>`, plus `#imported`. Whitespace-delimited tokens, any case; `#crates` or `x#crate` are not tokens. Name markers `[crate]` / `🎛`
  also flag a crate. Only `crates/attrs.py` writes our tokens; the rest of your comment is never touched.
- **Trash**: `/srv/_trash/<date>/<path>` with `MOVES.txt` of reverse `mv`s. Never emptied by code.
  M3's `scripts/dedupe_copies.py` and (M8) the worker's copy replacement write it; the worker mounts it rw.
- **`.m3u8` exports**: `/srv/music/_playlists/*.m3u8`, written by `scripts/export_playlists.py export` (the worker
  every `WORKER_EXPORT_S` = 300 s, or by hand). Navidrome's auto-import of them is off on purpose (it would duplicate
  every playlist). They mirror Navidrome within 5 minutes, so the restore source is
  **`/srv/music/_playlists/.history/<YYYY-MM-DD>/<name>.m3u8`**: the previous text of each changed file, the first
  one of the day (UTC), kept 30 days (R5, M9 §7). `check` and the stale list ignore `.history/`.
- **Identity outputs**: `/srv/docker/crates/identity/` (= `/data/identity` in the worker and in `crates`,
  `CRATES_IDENTITY_DIR`): proposal, report, MB cache, apply logs, and `identity-choices.json` (R7: the Identity
  view's taps, latest per path, written atomically by `crates/identity_view.py`, the only file `crates` writes
  there). Not checked on the live box since 2026-10-17 (it did not exist then): the R7 plan's "Live steps" step 1
  checks that it exists and is writable by uid 1000.

## 4. Key flows

### (a) Spotify playlist → Navidrome playlist + wanted rows

`sourcing.cli import-playlist <src>... [--name N] [--tier T] [--dry-run] [--merge]` (`sourcing/cli.py:179-208`):
1. `playlist_sources.load` reads a Spotify URL (public embed page, **100-track cap**), an Exportify CSV (has ISRCs)
   or a SpotiFLAC report into `Row`s; several sources concatenate in order.
2. `import_playlist.match` searches Navidrome (`search3`, up to 5 pages), then `choose` (`import_playlist.py:137`)
   asks in order: same recording (row ISRC in the hit's ISRCs) → same version (same version key, length ±4 s) →
   an **accepted other version** (same lead artist and base title, every version word on the tier's `accept`
   list). Otherwise `ambiguous` (why: several versions / other version / length differs / title differs) or
   `missing`.
3. A same-named playlist with no `imported_playlists` row in crates.db raises `NameCollision` unless `--merge`,
   which adopts it (records the row, leaves its comment alone). The comment is not read: `#imported` there means nothing.
   Another user's playlist of that name is refused even with `--merge` (rename one of them).
4. Matched songs are appended unless already there or added by an earlier run (so a track you removed stays
   removed, D13); a new playlist is recorded in `imported_playlists` at once, then made public; its comment stays
   empty (under the retired owner `comment` it gets `#tier:<t>`). Missing rows →
   `add_external_wanted` (tier `medium` by default, D15). Ambiguous rows → status `review` with the candidate ids. Stand-ins are listed as "matched with another version".
5. A real run (never `--dry-run`) records the whole Spotify order in `import_order`, replacing the previous record
   for that playlist: song id for matched rows, `ext-N` for missing and review rows. A re-run appends new matches
   **at the end** and closes wanted rows whose track is now matched. A wanted row filed later is not appended: the
   worker places it at its Spotify position ((b) step 7, D44). Playlists imported before N4 get an order on their
   next re-run; until then their filed rows are not placed.

`seed-spotify <url>` only queues wanted rows. Crate flag: web toggle or `crates.cli toggle` →
`Reconciler.set_crate` → `store.set_enabled` + best-effort `#crate` mirror → `reconcile_playlist` → `judge`
(crate policy, Subsonic facts only) → `crate_tracks` rows `ok` / `needs_source`.

### (b) Preview → Approve → worker → filed

1. **Preview** (`POST /api/wanted/<id>/preview` → `CrateApp.preview`, `service.py:169`): `fetch(approve=False)`
   in the crates container: slskd search (≤30 s), `scorer.rank` at the row's tier, pick cached in `previews`.
   409 for `sourcing`/`verify` rows; a filed row answers "already filed as …" and searches nothing.
2. **Approve** (`CrateApp.approve`, `service.py:184`) → `store.approve` (`store.py:307`): one row in `approvals`
   (`approved_by=michael`, the candidate you saw, the row's tier); an older unused approval is superseded.
   CLI: `fetch --wanted <id> --approve [--wait]` (container only; it refuses without `CRATES_DB`).
3. **Worker tick** every 30 s (`worker.py`): play-now approvals first, then the reconcile (every 600 s), the
   `verify` re-checks (below), then for each pending approval `claim_approval` (atomic conditional UPDATE, `store.py:324`) and `fetch(approve=True, prefer=candidate)`.
   The outcome is written to `approvals.result`.
4. **fetch** (`sourcing/fetch.py` `fetch`): **library first** (S1-07): an external row that is not a copy upgrade
   is matched against Navidrome as the import does (`import_playlist.match`); its same recording or same version
   makes the row `ok` with that `library_song_id` (`matched` event) and nothing is downloaded. Else search + rank
   again (a candidate whose title slot names another song is rejected, S1-01); take the approved file if still
   offered, else the top one (`pick` event). Intent (`intent_for`): crate row = **copy** upgrade; external row whose
   file name parses to another version = **version**; else plain. Row → `sourcing`; forget the file's completed
   records (`?remove=true`), enqueue, poll the record whose id wasn't there before the enqueue (S1-04) until
   `Completed` (timeout 600 s); find the file under the downloads folder. **Retry once** (S1-06): `Completed,
   Errored|TimedOut|Rejected|Cancelled`, or slskd unreachable or 5xx, cancels and forgets that attempt, waits 20 s
   and downloads the next acceptable candidate from another peer (`retry` event); a second failure fails the row with
   both reasons. Every failed attempt, our own timeout included, cancels and forgets its own transfer.
5. **verify** (`sourcing/verify.py:232`) at the row's tier. For a copy upgrade the reference is the old file, read
   from `navidrome.db` (`_library_file`); with `ACOUSTID_KEY` an AcoustID lookup also runs. Result →
   `verifications`. A failed file is deleted (it is our download, not library material) and the row `failed`.
6. **Filing** (`sourcing/filer.py:261`): move the file to `/srv/incoming/soulseek/.staging/<id>-<ts>/`;
   fill an empty artist/title tag from the row (`tagged` event); `beet import -q -s -m -W -l <log>`. A new
   `items` row and no `asis` line in that log = beets matched. The moment beets has filed it, `on_imported`
   sets the row `verify` with the path (so a crash never refiles). Then `beet write path:<file>` **only** if
   `musicbrainz.confirm_recording_length` says MusicBrainz's length is within 4 s of the file. `filed` event:
   `beets matched: …` or `beets as-is: … (why)`.
7. **finish** (`fetch.py:176`): `start_scan`, wait ≤120 s, `search3` by the filed file's artist + title, pick the
   hit with the same suffix and byte size. Found: `set_wanted_names` copies Navidrome's names onto the row
   (`renamed` event; the Spotify names stay in `asked_*`). External row → `ok`. A title that can't be the asked
   song (`identity.can_be_song`, S1-03) is not copied: the row is `review` "filed <X> as <rel>, asked for <Y>"
   (`wrong_song` event), not placed; `crates.cli wanted reopen` puts it back to `needs_source` (S1-08). A copy upgrade of a
   playlist row → a **copy replacement** (§9): proof, then repoint every playlist through `playlist_edit`, then the old
   file to the trash. No proof → both files stay and the row is `review`.
   **Placement** (N4, D44, `crates/placement.py`): no call from here. Each tick the worker asks
   `due_placements()` for external rows that are `ok`, filed (`library_song_id`), not provisional, named by an
   `import_order` row of an imported playlist, not yet in `imported_entries` and with no `done`/`given_up`
   placement (play-now's copy, once `ok`, is due the same way). For each, `place` re-reads the playlist and inserts
   the song after its nearest earlier Spotify neighbour still there, else before the nearest later one, else at
   the end: one `playlist_edit.rewrite`, insert only. Then `imported_entries` and a `placed` event. Refusals retry
   after `WORKER_RECHECK_S`, each wait doubling up to a day; the 12th gives up with `not_placed` ("re-run the
   import to append it"). An edit Navidrome did not confirm is only looked at next tick, never sent again. `docs/worker.md` → "Placement".
8. **Not found yet**: row stays `verify` "filed as <rel> but Navidrome has not picked it up yet". Each tick
   re-checks rows idle ≥300 s (`WORKER_RECHECK_S`; each re-check starts a scan) and counts `(check N)`; at 12
   (about an hour) the row fails "Navidrome never indexed <rel>; file is in the library", and the web client
   shows **Re-check** (approval without a candidate: re-check, never re-download).
9. **Restarts**: on start the worker takes `/data/worker.lock` (flock), then `recover_interrupted`
   (`store.py:332`): approvals left `started` become "interrupted: worker restarted", their `sourcing` rows
   `failed`. Approve again.

Since M8 a copy upgrade acts on verify's `replaceable` flag, and only on it (§9); without it both files stay.

### (c) Streaming (D19)

The web client plays `/api/stream/<id>?tier=<t>`; the service answers 302 to a freshly signed Navidrome
`stream` URL under client name `dj-crates-web` (`service.py:288-293`, `policy.py:152`). Tier `server` (default)
sends no format and no bitrate, so Navidrome's player profile for `dj-crates-web` decides. Overrides: `low`
opus 64, `medium` opus 96, `high` opus 160, `crate` raw. The choice is saved in `settings` (live DB: none
stored, so `server` is in effect). Amperfy talks to Navidrome directly with its own Wi-Fi/cellular settings.
Audio never passes through our process.

### (d) Identity backfill (built, not yet run live)

Runs in the worker (`scripts/identity_backfill.py`), because it has `/srv/music` rw, fpcalc and credentials.
1. **propose** (read-only, `:469`): per file, ISRC lookup → check an existing recording id → MusicBrainz search by
   artist + base title (+ AcoustID with a key). A recording fits only if lead artists are equal, base title and
   label agree, it is not a video, and the length is within 4 s (no length = no fit). Classes: `confirmed`,
   `isrc`, `acoustid`, `search`, `ambiguous`, `conflict`, `none`, `error`. Writes proposal JSON + report + cache.
   ~45–70 min for the library (1 req/1.05 s, 503 retries), resumable from `mb-cache.jsonl`.
2. **review**: in the web client's **Identity view** (R7, built, not live; `crates/identity_view.py`,
   `GET /api/identity`, `POST /api/identity/choice`): one row per `search`/`ambiguous`/`none`/`conflict`/`error`
   file with ▶ and the candidates; Accept (a `search` row's recording), Choose (a listed candidate; the only one on
   the file's own album is pre-selected, Q8), Skip; `conflict`/`error` rows offer only Skip. A tap writes no tag: it
   is stored in the **choices file** `identity-choices.json` beside the proposal and logged as `identity_pick`
   (`decided_by=michael`). Or, by hand: set `"skip": true` or `"choose": "<mbid>"` in the proposal JSON.
3. **apply** (`:873`): default classes `confirmed`, `isrc`, `acoustid` + rows with `choose`; `--classes` may add
   `search`, `ambiguous`; `--choices identity-choices.json` adds the picked rows (each choice is checked against
   the row again: class, size, mtime, candidates; a refused one is never written by its class). Per file: refuse
   if size/mtime/tags changed since propose or a target field is not empty (`_check_file`, `:732`); log first
   (`apply-<time>.jsonl`, with prior values), `write_minimal` the id fields, read back, verify no other tag changed;
   first problem stops the run. Then scan and check: song ids unchanged, Navidrome shows the recording id, `.m3u8`
   exports still match (`export_playlists.check`).
4. **revert** (`:958`): newest first, remove a field only where the file still holds exactly the logged value
   (`tag_cleanup.remove_ids`). Re-applying after a revert needs a fresh propose (mtime changed).

### (e) Album request → plan → approve → album job

Built in S2 and S3 (run `dj-crate-streaming-2026-10-22-build`) against the fakes: **not deployed, PRs open**. Spec
S2/S3, plan `plans/2026-10-22-s2-album-requests.md`; the live steps for Michael are
`plans/2026-10-22-downloads-checklist.md` sections 4 (a request, its album job) and 6 (the Spotify capture).
Entry points (S3), the HTTP routes and the CLI calling the same `CrateApp` methods, so add, preview and approve have
one implementation each:
- HTTP (`crates/service.py`, documented for clients in [`api.md`](api.md)): `POST /api/requests` (`{url}` →
  `requests.add_link`, `{mbReleaseId}` → `add_release`, `{mbRecordingId}` → `add_recording`; then
  `mark_in_library`), `GET /api/requests` (`requests.listed`), `GET /api/requests/<id>` (`requests.detail`),
  `POST /api/requests/<id>/preview` (`album_job.plan_request`, slskd searched outside the app lock, `album_job.shown`)
  and `/approve` (`album_job.approve_request`), `GET /api/catalog/search?q=&kind=album|track` (`sourcing/catalog.py`:
  one `MusicBrainzCatalog` in `PROVIDERS`; Spotify is the next provider, after `scripts/capture_spotify.py`'s capture).
  Every body goes through `store.public`: no peer, no path. Nothing on the HTTP thread enqueues on slskd.
- CLI (`sourcing/cli.py` `request_cmd`): `python -m sourcing.cli request add <link> | list | show <id> | preview <id> |
  approve <id> [--json]`, the morning path in `worker.md`.
1. **Request.** `seed-spotify <album or track URL> [--musicbrainz]` → `requests.add_spotify`: one `requests` row, one
   `external_wanted` row per track (`request_id`, `track_no`, `year`). A row belongs to the first request that asked
   for it. The embed has no year for an album; `match_request_release` takes the MusicBrainz release that matches the
   rows one to one (`mb_release_id` and each row's `mb_recording_id`; not its year), else the request goes on without
   ids. Only `seed-spotify` with `--musicbrainz` or `$MUSICBRAINZ_CACHE` calls it: `POST /api/requests` and `request add` with a Spotify album link
   make the request without asking MusicBrainz.
   `import-playlist --request` records the import as one `playlist` request (`add_playlist`, keyed by the playlist's
   name); a later album request takes its rows that nothing is doing yet.
2. **Plan.** `album_job.plan_request`: one slskd search `"<artist> <album>"`, `album.plan_album` over the responses
   (a primary folder, a same-release secondary, per-track rows; failed peers and folders excluded), cached in `previews`
   as `req-<id>` (a playlist's album group: `req-<id>:<loose artist>/<loose album>`, 3+ rows). What it returns and its
   `plan` event name folders `folder 1`, `folder 2` and files by basename: never a peer (`store.public`).
3. **Approve** (D7). `album_job.approve_request`: one `album` approval per open row, with its planned file; a playlist's
   rows outside an album group get ordinary `download` approvals. Refused while a row is in flight.
4. **Run.** `Worker._spend` hands a request's `album` approvals to `album_job.run`: claim them; the library first
   (S1-07); plan again if the cached plan is older than `ALBUM_PLAN_MAX_AGE_S` (3600 s); one enqueue per peer (its
   earlier `Completed` records of those files forgotten first); then each row through `fetch(planned=True)` (no
   search, no enqueue: it follows the job's transfer, verifies with the row's recording id, files, finishes, places).
5. **Switch** (S2-05b). A transfer error or timeout, no transfer started within `ALBUM_START_TIMEOUT_S` (600 s),
   one "not what it claims" verify finding (`transcode`, `fake_24bit`, `fake_hires`, `recording`) or 2 failed rows
   distrust the folder: its unfiled records are cancelled and forgotten (`remove=true`), and its rows are planned again over the
   cached and a fresh search without the failed folders (`switch` event). Caps (S2-05c): a row gets its planned folder,
   one other folder, then one per-track fetch excluding every failed peer; a row that fails all of them is `failed`
   with every attempt in its reason. The cached plan keeps the failed folders: an approval again plans without them.
6. **Filing** (S2-06). An album row is filed with the request's identity (`AlbumIdentity`: album, album artist, track
   number/total, year, release ids). The `tagged {json}` event (the old values) is committed before
   `write_minimal`, then `beet import … --set dj_album=1`, and `deploy/beets.yaml` files `dj_album:1` items at
   `$albumartist/$album ($year)/$track - $title` (D50). Reverse: `scripts.tag_cleanup.restore_fields`.
7. **Status.** A request's status is never stored: `store.request_status` over its rows.

## 5. Identity model: song, version, copy (`sourcing/identity.py`, `docs/identity.md`)

- **Song** = lead artist + base title (`song_key`). A cover by someone else is another song.
- **Version** = one recording (radio edit, 12", dub, live, remix by X). **Copy** = a file; a remaster is a copy.
- `parse_title` (`identity.py:192`) peels **trailing** `(...)`, `[...]`, ` - ...` decorations. One with a version
  word is a label; a remaster note, "Album Version" or "feat. X" is a copy marker; anything else stops peeling
  and stays in the name ("Mary Jane (All Night Long)"). `VERSION`/`TIT3` counts only if it parses as a label
  (35 of 37 library files hold a year there).
- Vocabulary (`KINDS`): `edit extended club dub instrumental acappella live remix reedit demo alt original`.
  Every 12" spelling = `extended`. Clean/explicit/mono/stereo, take numbers and live years are versions, not
  copy words. `original` is **neutral**: "Glide - Original Mix" is the same version as "Glide", but a
  `prefer` list can still favour it.
- Version key = (kinds minus `original`, credit). **`same_version`** (`identity.py:264`): both recording ids →
  they decide; different work ids → different; else same lead artist, base title, key, and both lengths known
  within 4 s. A shared work id decides only the song. Every doubt is "different" (a false "same" would let M8
  trash a real version).
- **Accepted other version**: every kind of the candidate is on the tier's list (subset rule), so "12" Dub" is a
  dub, not a 12" stand-in.

How D16 (prefer 12" for crates) bit, **retired by D26**: `deploy/policy.toml` now lists no preferred or accepted
version, so every row below is inert and the exact track is sourced. The machinery stays because policy files can
still list words:

| Where | Effect |
|---|---|
| matcher | at any tier, a library 12"/extended can fill a radio-version row (logged as a stand-in); at crate also club |
| scorer | crate `prefer = extended, club, original`: +6/+4/+2 bonus; an accepted other version not shorter than asked gets the +15 length points (`scorer.py:202`) |
| scorer, crate upgrade | another version is **rejected** (`scorer.py:171`): a radio edit is never "upgraded" to a 12" |
| verify | copy intent: full-length fingerprint vs old file; version intent: no reference, no expected length, but arrived length must match the peer's listing (±max(10 s, 5%)) |

`replaceable` (`verify.py:264`) is true only when the reference was compared, BER ≤ 0.20, durations agree
within tolerance, the files differ and the verdict is ok. Missing reference ⇒ false. M8 trashes only on it, and
only after `sourcing/replace.py` re-checks the old file is still the one compared.

## 6. Tiers and `deploy/policy.toml`

**Since 2026-10-17 (D24) all four tiers hold one rule:** flac / wav / aiff / alac / m4a / mp3 only; lossy at 256 kbps
or more; quality only (speed weight 0); strict verify. The table below is the **retired** four-tier design, still what
the test fixture `tests/fixtures/policy-legacy.toml` holds.

| Tier | Lossy floor | Speed weight | Strict verify |
|---|---|---|---|
| low | 32 kbps | 0.8 (budget 60 s) | no |
| medium | 64 kbps | 0.6 (60 s) | no |
| high | 128 kbps | 0.35 (300 s) | no |
| crate | 320 kbps, no opus | 0 | yes |

- Listening tiers allow flac/wav/aiff/alac/m4a/mp3/ogg/opus; all deny wma/ra/mid. Download cap assumed 1 MB/s
  (crate: none) for the arrival estimate.
- **Not in the TOML** (code defaults in `QualityPolicy`, `policy.py:16-44`): format preference order, lossless
  sanity floor 500 kbps, accepted sample rates/bit depths, duration tolerance 4 s.
- **Strict vs lenient** (`verify.py:228-229`): every tier hard-fails missing/unreadable/integrity/duration/
  truncated/wrong recording. Crate also hard-fails transcode (cutoff ≤16 kHz on a lossless or ≥315 kbps file),
  fake 24-bit, fake hi-res, low implied kbps, sample rate <44.1 kHz; listening tiers only warn.
- Which tier a row uses: crate rows always `crate`; imports/seeds `medium` unless `--tier`; the store default
  for anything else is `crate` (`policy.py:145-146`). `judge` in reconcile always uses the crate policy.
- Loaded **once at import** from the copy baked into the image: edit, commit, then `scripts/deploy.sh`
  from that clean checkout (`docs/worker.md` → "Deploying, and what healthy means"). A typo stops the start with the key named.
- **D17 is answered by D24**: every tier has the 256 kbps floor.

## 7. Safety invariants (what the code enforces, and where)

| Rule | Enforced at |
|---|---|
| No download without an approval | only `fetch(approve=True)` downloads; only the worker calls it; worker needs `DJ_WORKER=1` (`cli.py:227`); CLI `--approve` only records (`cli.py:50`) |
| One worker at a time | `fcntl.flock` on `/data/worker.lock` (`worker.py:36`) |
| An approval is spent once | `claim_approval` conditional UPDATE (`store.py:324`) |
| One beets writer | filer exists only with `DJ_WORKER=1` (`cli.py:38`); host convention for the rest (§10) |
| Only the worker downloads; host scripts write beets only with the worker stopped (built R4, not deployed) | `sourcing.cli rank` has no `--download` (an old invocation exits 2 naming Preview + Approve); `scripts/tag_cleanup.py retag|move` and `scripts/dedupe_copies.py repoint|trash` hold `<dirname(CRATES_DB)>/worker.lock` (`sourcing.worker.with_worker_lock` → `hold_lock`) for the whole command, else exit 1 "refused: stop the worker first"; `identity_backfill apply` stays outside the lock |
| beets only sees fresh downloads | filer refuses a folder not under `.staging` (`filer.py:268`); exactly one audio file |
| beets writes tags only on a confirmed match | `-W` import + `confirm` hook (`filer.py:291-299`) |
| A filed file is never downloaded twice | row → `verify` with path as soon as beets filed it (`fetch.py:307-313`); re-checks never search (`fetch.py:211-224`) |
| Originals read-only | not mounted in any container; slskd sees only its own folder |
| Trash, never delete library files | no code deletes a library file; trash never overwrites (`(2)` suffix); the one library-file mover is `trash.move_to_trash`, reached only through `sourcing/replace.py` (after the licence and an empty `references()`) and `scripts/duplicate_cleanup.py trash` (below) |
| Playlist index edits are guarded | only `crates/playlist_edit.py` edits by index; it cross-checks `navidrome.db` and refuses on any difference, on smart playlists and on playlists owned by another user |
| One reconcile at a time | flock on `/data/reconcile.lock`, 60 s, then 503 / skip (`reconcile.py`) |
| Never overwrite an id | `apply` writes only empty fields, file unchanged since propose (`identity_backfill.py:732`) |
| Other tags untouched | `write_minimal` sets only named fields; `apply` re-reads all others |
| Peer names never in UI/logs/events | `explain(peers=False)`, basenames only in events and worker stdout; a slskd error is `SlskdError` "slskd <method> <endpoint template>: HTTP <code>" (S1-05), never the peer, URL or key |
| A file is never filed as another song (S1, built, not deployed) | scorer rejects a title slot naming another song (S1-01); with no recording id, a confident AcoustID title that can't be the asked one is a hard `recording` finding (S1-02, `verify._acoustid_check`); `finish` never renames a row onto another song's title, the row goes to `review` (S1-03) |
| fetch follows only its own transfer (S1) | forgets with `?remove=true`; follows the record whose id wasn't there before its enqueue, never the last one (S1-04); one switch to another peer per fetch call, the first attempt cancelled and forgotten first (S1-06) |
| No download of a song the library has (S1-07) | an external non-copy row is matched against Navidrome before any search; a hit is `ok` with that song |
| `wanted reopen` writes only crates.db (S1-08) | `store.reopen_external`: one write lock, dry run by default, refuses in-flight and question rows, the `reopened` event holds the reverse |
| Duplicate cleanup never trashes a file a playlist holds (built N1, not run live) | `scripts/duplicate_cleanup.py`: groups recomputed from navidrome.db right before each repoint and move; `repoint` only via `playlist_edit.repoint_everywhere`, reverse line before each write, then a waited scan; `trash` under `worker.lock`, no scan running, `references()` empty (hidden rows, other owners) before and after each move and after the closing scan (else put back), `CrateStore.song_in_use` empty, `MOVES.txt` before each move; every repoint and move a `cleanup` event |
| Placement only inserts, only in our imported playlists, once per track (built N4, not deployed) | `crates/placement.py`: the playlist needs an `imported_playlists` row (D37); a track already in `imported_entries` is never due, so a removed one stays removed; every edit is one `playlist_edit.rewrite` (refuses on hidden missing rows, another owner, a smart playlist or a concurrent edit); an unconfirmed edit is looked at, never resent; `given_up` after 12 refusals, with a `not_placed` event |
| Navidrome DB read-only | `open_ro` (`mode=ro`) and a `:ro` mount |
| Policy typos stop the start | `load_policy` raises naming the key (`policy.py:95`) |

## 8. Operations

All from `/srv/docker` (compose file is a symlink to `deploy/compose.yml`; `.env` there supplies secrets).

```
docker compose ps                                  # what runs
scripts/deploy.sh                                  # after any code or policy.toml change: from a clean, pushed checkout,
                                                   # not `up` here (docs/worker.md → "Deploying, and what healthy means")
docker compose logs -f worker                      # watch ticks, downloads, filings
docker compose logs --tail 5 worker                # after a policy edit: did it start?
docker compose stop worker / start worker          # pause / resume (a stop mid-download: approve again)
```

| Task | How |
|---|---|
| Approve a download | web client Wanted tab: Preview, then Approve |
| …from a shell | `docker compose exec -T worker python -m sourcing.cli fetch --wanted <id> --approve [--wait]` |
| One tick by hand | stop the service first, then `docker compose run --rm --no-deps worker python -m sourcing.cli worker --once` (an `exec … --once` beside the daemon exits "worker already running") |
| Re-check a never-indexed row | web client **Re-check**, or approve it again |
| Import a playlist | `docker compose exec -T crates python -m sourcing.cli import-playlist <url> [--name N] [--tier T] --dry-run`, then without `--dry-run` |
| Toggle a crate | web client (the crate switch), or `docker compose exec -T crates python -m crates.cli toggle <playlist-id> on`; writes `crates.db` only. `tier` and `attrs migrate` are retired under `CRATES_OWNER=app` |
| Record a hand-made import / strip old markers | `docker compose exec -T crates python -m crates.cli imported migrate` (dry run), then `--apply`: records each playlist of ours whose comment still says `#imported` in crates.db `imported_playlists`, then strips the token (read back; the `imported` event holds the old comment). `crates.cli imported list` shows the table. Runbook: `docs/plans/2026-10-17-n2-imported-marker.md` → "Live runbook" |
| Reconcile now | web client, or `docker compose exec -T crates python -m crates.cli reconcile` (the worker does it every 600 s) |
| Answer a version / copy question | Wanted tab (Swap / Keep), or `docker compose exec -T crates python -m crates.cli proposals [--all]`, `proposals accept\|decline <id>` |
| Undo a trashed copy | run its reverse `mv` line from `/srv/_trash/<day>/MOVES.txt` on the host (`docs/worker.md`) |
| Export / check playlists | `docker compose exec -T worker python -m scripts.export_playlists export` (or `check`) |
| Playlist health / old playlist versions | the crates page's banner (or `/api/status` `playlistHealth`) names playlists with entries on a missing song; the `playlist_health` event logs each change. An older version of a playlist is `/srv/music/_playlists/.history/<YYYY-MM-DD>/<name>.m3u8` (30 days; restore by hand, `docs/worker.md` "A playlist that lost entries") |
| Identity propose | `docker compose exec -T worker python -m scripts.identity_backfill propose [--limit 40]` |
| Identity apply | `… identity_backfill apply /data/identity/identity-proposal.json --dry-run`, then `--yes [--limit 5] [--classes …] [--only GLOB]` |
| Undo apply | `… identity_backfill revert /data/identity/apply-<time>.jsonl` |
| Duplicate cleanup | `docker compose exec -T worker python3 -m scripts.duplicate_cleanup plan`, then `repoint [--dry-run] [--limit N]`; with the worker stopped `scripts/live-run.sh python3 -m scripts.duplicate_cleanup trash [--dry-run] [--limit N]` (the deployed image, D45); staged runbook and undo in `docs/worker.md` "Duplicate cleanup" |
| Tests | `cd ~/projects/dj-crate-streaming && ~/.local/bin/pytest -q` (1,750 tests, about 11 minutes) |
| Offline demo | `python3 -m crates.cli demo` → http://127.0.0.1:4580 |

Where to look: worker stdout (`docker compose logs worker`), the web client's log tab (`events`), approvals'
`result`, `/srv/docker/beets/import.log`, `.staging/` for files beets refused, `/srv/docker/crates/identity/`.

Undo: identity → `revert`; a filed download → it is a normal library file (move it to trash by hand, then
reconcile); a repoint or swap → put the old song back in the playlist in any client (after restoring its file from
the trash if it was trashed); a policy edit → git revert + rebuild; trash → the `mv` lines in `MOVES.txt`; a comment
the retired migration wrote → edit the comment in any client. An approval cannot be cancelled (a new one only supersedes it): stop the worker before
its next tick if you change your mind.

## 9. M8 (built)

Built and committed on this branch, **not live**. Design: `docs/specs/2026-10-16-ownership-and-identity.md`; details
and commands: `docs/worker.md`. What changed, and why:

- **(Retired by the pivot) The playlist comment owned crate and tier** (D21): `#crate`, `#tier:medium`
  (`crates/attrs.py`). The code is still there under `CRATES_OWNER=comment`; production uses `CRATES_OWNER=app`
  (the default), where `crates.db` is the owner, reconcile never reads a comment, and the toggle never writes one.

- **A track's tier is derived**: the highest tier among the tiered playlists holding it. `crate_tracks` covers every
  tiered playlist, not only crates. Listening tiers (low/medium/high) queue an upgrade only below their floor (a
  format they do not allow, or a lossy file under the bit rate floor), not for "lossless preferred" (ruling; it
  avoids about 144 pointless upgrade rows).
- **Reconcile runs in the worker** every 600 s and in the crates service on demand. Both take one flock
  (`reconcile.lock`, 60 s, then the web answers 503 and the worker skips). A row in flight (`sourcing`, `verify`,
  `review`, or `failed` with a filed path) keeps its status whatever the verdict, and survives its playlist losing
  its tier.
- **A deleted playlist's rows are dropped by the next reconcile** (N3, D43; `Reconciler._forget_vanished`,
  `CrateStore.forget_playlist`). Only a playlist with a `crates` or `imported_playlists` row that a successful
  getPlaylists does not list, and that getPlaylist answers with error 70 (not found), counts as gone; a failed
  getPlaylists drops nothing, nor does an empty listing or more than 3 missing at once (an error instead). Its
  `crate_tracks` rows go, except `sourcing`/`verify` ones and ones with an approval in progress, which wait (the
  `crates` row stays, flag and tier cleared, until they finish); then the `crates`, `imported_entries` and
  `imported_playlists` rows go too. Open wanted rows become `removed` ("playlist deleted"). One `playlist_gone`
  event per run that changes something, and one reverse-log line in `playlists-gone.jsonl` beside `crates.db`
  (replay newest first). It used to be the error "playlist no longer exists in Navidrome" on every run.
- **Copy replacement** (`sourcing/replace.py`): a resumable job (`replacements` table: repoint, trash, scan, done,
  or blocked). It starts only when the stored verification has `replaceable` literally true and the old file is
  still the one compared; it repoints **every** playlist (not only crates), then moves the old copy to
  `/srv/_trash` and tells beets (`beet remove`, index only). It never trashes while any playlist entry
  (hidden ones too) still holds the old song, so a smart playlist or Amperfy's own playlist makes it wait. No proof:
  both copies stay and the row is `review`. `docs/worker.md` "Copy replacement and the trash" has the undo.
- **The Navidrome trap it guards**: `getPlaylist` hides songs whose file is missing, but their `playlist_tracks`
  rows keep their positions, and `songIndexToRemove` counts the hidden rows. With one missing song in a playlist, an
  index edit removes the wrong track. Every index edit goes through `crates/playlist_edit.py`, which compares
  getPlaylist with `navidrome.db` and refuses on any difference (and on smart playlists, and playlists owned by
  another user), writes in one call and reads it back. Order: new copy indexed by its own scan, repoint, trash, scan
  (trashing in the same scan window could merge ids).
- **Version swaps are questions** (`proposals` table, never automatic): a new preferred version, or a better copy
  that could not be proven the same recording, asks once per playlist slot. Swap edits that slot only and never
  trashes; Keep is final. Wanted tab, or `crates.cli proposals`. `repoint: auto` is not built.
- **Play-now** (D20): the play button on a track you do not have approves one `low` copy. The worker takes it first
  and wakes within a second; the file is provisional, the web client plays it when Navidrome lists it, and the
  upgrade at the row's tier waits for your approval. A fast copy is final only if it was verified at least as
  strictly as the row's tier; a crate never accepts a copy verified at low. One open request per song. The file is
  **not** placed in its playlist (M9).
- **API hygiene**: Preview picks have an opaque `token`; no row response shows a peer name or an absolute path;
  Preview and Approve answer 409 while a play-now approval is claimed.
- The worker also re-exports `.m3u8` every 300 s, mounts the trash read-write, and the crates container opens
  `navidrome.db` read-only.

### Deploy order and gates

Do these in order. Nothing is live yet, and the rebuild itself needs your permission (it replaces both running
containers; see `TODO-MICHAEL.md`).

1. **Tasks 5–8 ship together.** Until Task 8 routed the swap in `fetch.finish` through `playlist_edit` and
   `replace.py`, a download would swap into every tiered playlist with an unguarded index edit (the trap above).
   Build the branch tip, never a commit between Task 5 and Task 8.
2. **No comment migration.** The comment-owned design needed `attrs migrate` to write `#tier:` tokens before the first
   reconcile. Under `CRATES_OWNER=app` (the default) there is nothing to migrate: `crates.db` already holds the one
   crate flag, and the first reconcile leaves it alone. Build the committed tip, then:

   ```
   scripts/deploy.sh                          # from the clean checkout of that tip
   cd /srv/docker && docker compose logs --tail 20 worker       # started? (a policy typo stops it, naming the key)
   ```

3. **Live checks** (each needs the real containers, so none has run):
   - `navidrome.db` opens read-only in the crates container. It is a WAL database on a `:ro` mount, and SQLite may
     need to touch the `-shm`/`-wal` files. A number back means it works; "unable to open database file" means
     proposals and playlist edits answer 503 until the mount is fixed:

     ```
     docker compose exec -T crates python -c "import os; from scripts.export_playlists import open_ro; \
       print(open_ro(os.environ['NAVIDROME_DB']).execute('select count(*) from playlist_tracks').fetchone())"
     ```
   - A trash move inside the worker container. `/srv/music` and `/srv/_trash` are two bind mounts of one
     filesystem, so a hard link or rename between them fails (EXDEV) and the move must take the copy path:

     ```
     docker compose exec -T worker sh -c 'mkdir -p /srv/music/_probe && echo x > /srv/music/_probe/probe.txt'
     docker compose exec -T worker python -c "from crates.trash import move_to_trash; \
       print(move_to_trash('_probe/probe.txt', '/srv/music', '/srv/_trash'))"
     ```

     Expect the printed trash path to exist, `/srv/music/_probe/probe.txt` to be gone, the day's `MOVES.txt` to hold
     the reverse `mv` line, and no `.partial-` file beside it. Then remove `/srv/music/_probe` and the probe file
     from the trash by hand.
4. **iOS autoplay on a real phone.** The play-now tap primes the audio player so the file can start when it lands
   seconds later. Desktop browsers do this fine; Safari on iOS is stricter. The first real test is a play-now on your
   phone, which downloads a real file (D7: your go).

Not exercised live until your first approved download: copy replacement, proposals and play-now all need a real
download.

## 10. Quirks and trouble spots

Each: what, **impact**, *mitigation*.

1. **Build context is the working tree.** `CRATES_SRC` is the checkout; `--build` bakes in whatever branch and
   uncommitted edits are there (the 10:16 image holds a pre-commit `identity.py`). **Medium.** *Commit, check the
   branch, then rebuild.*
2. **Live is pre-M7.** No `policy.toml`/backfill in the image; docs describe M7. **Medium.** *Rebuild (M7 Task 12).*
3. **The download path has never run live.** 0 approvals ever; slskd → verify → beets → Navidrome was tested on
   fakes and real beets in temp dirs only. **High** for the first download. *Do D7's first download with one
   row and watch the log.*
4. **Navidrome ids vs PID.** A retag in place keeps the song id; a retag *and* move between two scans gives a
   new id, the old one goes missing and silently drops out of playlists (M2). The PID uses
   `musicbrainz_trackid` when present, so the backfill should make ids survive; whether writing the id keeps the
   current id is to be proven on a throwaway Navidrome (M7 Task 13 step 1). **High.** *`apply` checks ids after
   its scan; never retag + `beet move` without a scan in between (`tag_cleanup` two passes).*
5. **Subsonic paths are virtual** (built from tags). The real path is only in `navidrome.db media_file.path`
   (library-relative in 0.64). `finish` matches by suffix + byte size, path only as tie-break. **Low.**
6. **Hidden missing songs** (see §9) broke index edits. Since M8 every index edit goes through
   `crates/playlist_edit.py`, which refuses when `navidrome.db` and getPlaylist disagree. **Closed in M8** once the
   build is deployed; the old unguarded swap in `fetch.finish` is gone, which is why §9 gate 1 says Tasks 5–8 ship
   together. 0 playlist entries point at missing songs today (28 missing `media_file` rows, none in a playlist).
7. **reconcile can reset a filed crate row.** **Closed in M8:** an in-flight row (`sourcing`, `verify`, `review`, or
   `failed` with a filed path) keeps its status whatever the verdict, and survives its playlist losing its tier.
8. **beets 1.6 config order.** MusicBrainz is configured before `-c` is read, so `musicbrainz:` settings go in
   `$BEETSDIR/config.yaml` (`/srv/docker/beets/config.yaml`, absent today), not `deploy/beets.yaml`. This made the
   real-beet tests go online until fixed. Also: beets 1.6 applies a length-less match on artist+title, hence the
   confirm step. **Low** now.
9. **Unconfirmed beets match.** The file keeps its tags, but `library.db` holds the matched metadata and the file
   sits under the *matched* artist/title path. **Low.** *`beet update -M` refreshes the index; the path stays.*
10. **`.1` names.** `duplicate_action: keep` files a same-format upgrade as "… .1.flac" beside the old one. **Low.**
11. **slskd incomplete dir.** slskd checks `/app/downloads/.incomplete` but never creates it: on a fresh box run
    `mkdir -p /srv/incoming/soulseek/.incomplete` as mh550 before `up`, or slskd restart-loops. **Low.**
12. **Stream tier stored per DB.** A DB that stores a tier keeps it over the `server` default. The live DB stores
    none (checked), so `server` is in effect; picking a preset in the menu stores it. **Low.**
13. **Worker lock.** `worker.lock` is a harmless empty file; the flock dies with the process. `exec … --once`
    next to the daemon refuses. `identity_backfill apply` does **not** take the lock (different files; low risk).
14. **Other beets writers on the host.** `scripts/tag_cleanup.py` and `scripts/dedupe_copies.py` still import the
    beets package and write `library.db`. **Medium** if run while the worker files. *Stop the worker first.* Since R4
    `tag_cleanup retag|move` and `dedupe_copies repoint|trash` refuse while the worker holds `worker.lock` (§7).
15. **`rank --download` is gone (R4).** It used to enqueue in slskd directly: no approval, verify or filing, and it
    printed peer names. An old invocation now exits 2 naming Preview + Approve; `rank` only ranks.
16. **Import `review` rows have no picker.** Since M8 the Wanted tab lists `review` rows with their reason, and the
    retryable ones from copy replacement (kept beside, declined, not made, filed beside) offer Preview and Approve.
    The 11 live import `review` rows (several versions fit) are visible but still cannot be resolved. **Medium.**
    (Question 15.) The re-run of the imports after the duplicate cleanup (next-todos item 5) re-matches them against
    a library without duplicates, which may clear some; the picker is for what is left.
17. **Failed rows duplicate on re-import.** `find_external` skips failed unfiled rows (`store.py:367`), so a re-run
    of the import queues a second row for the same track. **Low.**
18. **Closed (N4).** Filed external rows were not put in their playlist; the worker now places them at their Spotify
    position ((b) step 7), from state each tick, so a worker restart loses nothing. Built, not deployed. Still: a
    playlist imported before N4 has no `import_order` until its next re-run (next-todos item 5), and a placement
    refused 12 times is given up (event `not_placed`; the re-run appends it).
19. **Exports.** Since M8 the worker rewrites changed `.m3u8` files every 300 s (`WORKER_EXPORT_S`), so repoints and
    your edits reach them. A restore from them still needs `ND_AUTOIMPORTPLAYLISTS` on for one scan.
20. **crates.db backup.** WAL mode: the main file is 4 KB and the WAL ~900 KB; restic copies them live. It now
    holds approvals, the one store whose loss loses information. **Medium.** *`sqlite3 … ".backup …"` before
    restic (needs root to add to the script).*
21. **Unpinned images** (`navidrome:latest`, `slskd:latest`, `gluetun`). The code depends on 0.64 behaviour
    (relative paths, PID, hidden missing rows). A `pull` can change it. **Medium.** (Question 17.)
22. **No auth on the crates API** beyond loopback + tailnet: anyone on the tailnet can approve. Stream redirects
    carry `michael`'s (admin) token + salt, brute-forceable offline. **Low** on a private tailnet.
23. **Peer names in JSON.** **Closed in M8:** the stored candidate keeps `username` (the worker needs it) but every
    wanted, approval and preview response drops it and any absolute path (`store.public`); Preview picks carry an
    opaque `token` that Approve posts back.
24. **Filed path lives in free text** (`reason`), parsed by regex. Rewording a reason breaks re-checks. **Low.**
25. **Preview holds the service lock** up to ~30 s; toggles and approvals wait. **Low.**
26. **MusicBrainz rate limit is per process.** A propose run and the worker's confirm lookup can overlap; 503
    retries absorb it. **Low.**
27. **Spotify embed caps at 100 tracks** and has no ISRCs; use an Exportify CSV for long lists. **Low.**
28. **Test suite** ~3 min; real-beet tests need `beet` + `metaflac` on the host. **Low.**
29. **Ledger minors still real**: `beet write` rc 0 with no matched item is undetected; `TimeoutExpired` from beets
    is not a `FilingError`; approval of an `ok` row is accepted (no-op); no index on `approvals.wanted_id`.

### 10b. Doc vs code discrepancies

- `docs/download-validation.md` says `fetch` passes no reference and downloads are verified/filed on the host: since
  M6 the worker passes the library copy and does everything. (fixed 2026-10-16)
- `deploy/compose.yml:24` mentions `scripts/export_playlists.py restore`: there is no such command (`export`, `check`). (fixed 2026-10-16)
- `README.md`: wanted rows "default `crate`" (imports default `medium`); the quality menu is "four tiers" (five,
  with `server`); "612 tests" (702). (fixed 2026-10-16)
- `sourcing/import_playlist.py:245` docstring: ambiguous rows "parked as `verify`"; the code sets `review`.
- Spec §0 D22 says `deploy/policy.yaml`; it is `deploy/policy.toml`. (fixed 2026-10-16)
- Spec fact 5 says exports are rewritten after each change, and fact 4 that a playlist check runs after every
  scan: neither is automated (only identity `apply` runs the check). (Spec now says "planned", fixed 2026-10-16)
- Spec fact 2 says Navidrome builds its song id from the recording id; measured, the id is not the PID: the PID
  uses it, which is what keeps the id across a move.
- `docs/backup-plan.md` item 4 ("crates.db is tiny, not worth it") predates approvals. (fixed 2026-10-16)
- The M7 rulings (a–c) and the M8 defaults went to `TODO-MICHAEL.md` ("M7/M8 defaults to confirm"); §11 is the full list.

## 11. Outstanding questions for you

> The 2026-10-17 pivot supersedes questions 1, 2, 5, 8 and 10 (one quality rule, app-owned crate flag, exact track).

Each has a default in place; answering changes only what is named.

1. **D17:** raise floors to medium ≥128, high ≥192 kbps? *Default: 64 / 128.* Changes two numbers in
   `policy.toml`; what future downloads may be. Recommended: yes.
2. **D21:** should a playlist's comment (`#crate`, `#tier:medium`) own its crate flag and tier? *Default: yes.*
   M8 is built on it; "no" means redesigning M8 Part A.
3. **D22:** should beets write full tags on fresh downloads only after a confirmed MusicBrainz match? *Default: yes;
   never on existing files.*
4. **D22:** should the version label stay in the title *and* go into `VERSION`/`TIT3`? *Default: yes, but the
   field write is a later reviewed proposal (M7 ruling c).*
5. **D23:** should a newly arrived 12" be proposed for a playlist slot rather than swapped? *Default: propose.*
   "Swap" would be a `repoint: auto` policy per tier.
6. **D20:** does pressing play on a track you don't own approve one fast download? *Default: yes; the upgrade
   still waits for you.*
7. **M7 ruling a:** should `apply` also write the `search` class (one name+length match, no ISRC or fingerprint)?
   *Default: no.* Yes = `--classes …,search`.
8. **M7 ruling b:** may a 12"/extended stand in for a radio-version row in listening playlists? *Default: yes*
   (`accept = ["extended"]` at low/medium/high). No = empty those lists.
9. **M7 ruling c:** write version labels into `VERSION`/`TIT3` later, as its own reviewed proposal? *Default: later.*
10. **M8 ruling:** should listening tiers queue an upgrade only when a file is below the tier's floor (not for
    "lossless preferred")? *Default: yes.* No = ~144 upgrade rows for the imported playlists.
11. **M8 default:** should a downloaded external track (and a play-now track) go into the playlist that wanted it?
    *Default: no (re-run the import to append it); M9 would insert it at its Spotify position (M9 spec §1).*
12. **Task 13:** after the live proposal, which classes may `apply` write? *Default: confirmed, isrc, acoustid
    and your `choose` rows, after you read the report.*
13. **AcoustID key:** will you register one (acoustid.org, put `ACOUSTID_KEY` in `.env`)? *Default: none* — no
    `acoustid` class, no right-recording lookup for new versions.
14. **First real download (D7):** which `ext-N` row? *Default: none; nothing has ever downloaded.* Automatic
    approval stays off until you say go after it.
15. **The 11 import `review` rows:** add a picker (Wanted tab shows candidates, you pick one)? *Default: listed in
    Wanted with their reason since M8, but nothing resolves them (M9 spec §5).*
16. **Shakori:** send the two Spotify URLs to build one Spotify-ordered "shakori"? *Default: the merged sockseek one.*
17. **Pin Navidrome** to `0.64.2` in `compose.yml`? *Default: `latest`.* Pinning protects the measured behaviour.
18. **Sudo items:** `/srv/_trash` (mkdir + chown), `tailscale set --ssh`, `ufw status verbose`, confirm restic
    snapshots `/srv/music` and excludes the Navidrome cache, and (new) a consistent `crates.db` copy before restic.

### New with M8 (each has a default in place)

19. **(Void since the pivot)** The "#crate" lookalike question belonged to the comment migration, which no longer runs.
20. **M8, other users' playlists:** a copy replacement never edits a playlist owned by another Navidrome user
    (Amperfy's account), so if one holds the old copy the replacement waits and the old file stays. *Default: wait;
    you remove the old song there.* Allowing admin edits would remove the wait but touch playlists that are not yours
    to change.
21. **M8, a blocked replacement:** `blocked` is final and has no retry button. *Default: no button; you read the
    reason (`docs/worker.md`).* A retry would need a rule for which blocks are safe to retry.
22. **M8, play-now:** a fast copy that was verified as strictly as the row's tier and passes it counts as the row's
    file, with no upgrade queued; otherwise the upgrade waits for your approval. *Default: yes.* And if a tiered
    playlist later holds the same song, its row takes over the upgrade (one open request per song). *Default: yes.*
23. **M8, the trash:** nothing empties `/srv/_trash`, and it is not size-limited. *Default: you empty it by
    hand; `crates.cli status` shows size and oldest day.*
24. **M8, ".1" names and the 102 old copy groups:** left alone; a same-format upgrade stays "… .1.flac", and the
    groups M7 found are for M9 to clean up in a reviewed step. *Default: leave both.*
25. **M8 rebuild:** may `docker compose up -d --build` replace the running crates and worker containers (in the
    order of §9)? *Default: not until you say; also in `TODO-MICHAEL.md`.*

M9 has its own questions (14, with defaults) in
[`docs/specs/2026-10-17-m9-remaining-ownership.md`](specs/2026-10-17-m9-remaining-ownership.md): placement of
downloaded tracks, proposals for playlists tiered later, cleaning the old copy groups, writing the version label,
pickers, and the small items. Question 11 above is its first.
