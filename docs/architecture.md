# dj-crate-streaming: how the system works (maintainer's guide)

Written 2026-10-16 from the code on `overnight2/2026-10-15` at `e73e803`. Where a doc and the code disagree, this
file says what the code does (see §10b). History of M1–M5: [`RECAP-M1-M5.md`](../../RECAP-M1-M5.md).
Legend: **built** = in the code; **live** = also running on the box; **planned** = only in a plan.

| Milestone | State |
|---|---|
| M6 worker, approvals, beets filing, stream "server" | built, **live** (images built 10:16) |
| M7 identity (Tasks 1–10) | built and committed, **not live**: the running image predates it |
| M7 review (Task 11) | running now |
| M7 live proposal (Task 12), gated apply (Task 13) | not done; Task 13 waits for you |
| M8 lifecycle (Parts A–D: ownership, replacement, proposals, play-now) | **built** and committed, **not live**: the running images predate it; deploy order and gates in §9 (`docs/plans/2026-10-16-m8-lifecycle.md`) |
| M9 | draft spec, nothing built: [`docs/specs/2026-10-17-m9-remaining-ownership.md`](specs/2026-10-17-m9-remaining-ownership.md) |

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
backfill of MusicBrainz ids into the library's tags. M8 makes the playlist comment the owner of crate/tier, replaces
proven-worse copies (old one to trash), asks before swapping versions and adds play-now.

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
| `navidrome` | `deluan/navidrome:latest` (0.64.2 measured), `127.0.0.1:4533`, scan hourly + file watcher | `/srv/music` → `/music` **ro**; `/srv/docker/navidrome` → `/data` |
| `crates` | `python -m crates.cli serve`, `127.0.0.1:4580` | `/srv/docker/crates` → `/data`; `/srv/_trash` → `/trash` **ro**; `/srv/docker/navidrome` → same path **ro** (`NAVIDROME_DB`, M8) |
| `worker` | `python -m sourcing.cli worker`, `DJ_WORKER=1`, no port | `/srv/music`, `/srv/docker/beets`, `/srv/incoming/soulseek` rw at the **same paths**; `/srv/docker/crates` → `/data`; `/srv/docker/navidrome` **ro**; `/srv/_trash` rw at the same path (M8, `TRASH_ROOT`) |
| `slskd` | in gluetun's network namespace; 5 upload slots, 586 KiB/s | `/srv/docker/slskd` → `/app`; `/srv/incoming/soulseek` → `/app/downloads`; `/srv/music` → `/app/shared` **ro** |
| `gluetun` | ProtonVPN WireGuard (NL), port forwarding; publishes `127.0.0.1:5030` for slskd | `/srv/docker/gluetun` |
| beets | not a service: the `beet` 1.6.0 CLI, run only by the worker's filer | config `deploy/beets.yaml` (`-c`), state `BEETSDIR=/srv/docker/beets` |

- `crates` and `worker` are one image (`Dockerfile`: python 3.12-slim + ffmpeg, flac, fpcalc, beets 1.6.0,
  mediafile 0.12.0). The build context is `CRATES_SRC` in `.env`, i.e. **the repo's working tree** (§10).
- Only `127.0.0.1` ports are published; `tailscale serve` on the host puts 4533 and 4580 on the tailnet.
- Who may write what: Navidrome writes only its DB (never files). `crates` writes `crates.db` and Navidrome
  playlists (the comment attributes, add/create, a proposal's one-slot swap); it has no library mount, so it cannot download or file
  (`fetch` refuses, `sourcing/fetch.py:142-148`). The worker is the only process that downloads, runs beets or
  moves files into `/srv/music`. slskd writes only its downloads folder; it sees `/srv/music` read-only and
  never sees `/srv/incoming/library-import` (your originals).

Code map: `subsonic/` Navidrome client + fake; `crates/` store, attrs, reconcile, playlist_edit, trash, proposals, HTTP service, CLI; `sourcing/` scorer,
verify, fetch, replace, filer, worker, identity, policy, import, MusicBrainz/AcoustID/Spotify/slskd clients;
`scripts/` one-off and backfill tools (tag cleanup, dedupe, export playlists, identity backfill); `web/` vanilla JS.

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
| Is a crate / tier | the playlist comment (`#crate`, `#tier:<t>`); `crates.db` only caches it (M8) | you in any client; the toggle and `crates.cli tier` write it; reconcile rebuilds the cache | D21 |
| Tier a track should reach | derived: the highest tier among the tiered playlists holding it (M8) | — | D21 fact 7 |
| Tier rules, version prefs | `deploy/policy.toml` | you | D16, D17 |
| Quality of a file | measured by `verify` | worker (`verifications` is a cache) | re-measurable |
| Queue, approvals, log | `crates.db` | crates service, worker | nowhere else to live |
| Stream quality | the client / Navidrome player profile | you | D19 |
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
| `external_wanted` | tracks not in the library: names, length, tier, playlist + position, `asked_*` | import, seed, fetch |
| `imported_entries` | every song import-playlist added (D13: removed stays removed) | import |
| `approvals` | `approved_by`, candidate JSON, tier, `used_at`, `result` | Approve, worker |
| `previews` | last search-and-rank per wanted id | Preview |
| `verifications` | last `verify` result per wanted id | worker |
| `events` | append-only log (`approved`, `pick`, `filed`, `renamed`, `reference`…) | everything |
| `settings` | `stream_tier` (absent = `server`) | web client |

Row statuses: `needs_source → sourcing → verify → ok | failed`, plus `removed` (left a crate) and `review`
(import found several versions; a person must pick). A filed file's path rides **in the reason text**
(`store.py:85` regex `filed_path`), not in a column.

Other stores:
- **`navidrome.db`**: songs (`media_file`, real library-relative `path`), playlists (`playlist_tracks`, position =
  row id). Read read-only by `fetch._library_file`, `export_playlists`, identity `apply`. Never written by us.
- **beets `library.db`**: a disposable index of the library. Rebuild with `beet update -M` (file → DB, no
  moves). Nothing reads a fact from it in preference to the file. The filer reads it read-only to find what an
  import just added (`filer.py:238-254`).
- **Playlist comment**: owns the playlist's attributes (M8): `#crate`, `#tier:<t>`, plus `#imported` (import-playlist's
  marker). Whitespace-delimited tokens, any case; `#crates` or `x#crate` are not tokens. Name markers `[crate]` / `🎛`
  also flag a crate. Only `crates/attrs.py` writes our tokens; the rest of your comment is never touched.
- **Trash**: `/srv/_trash/<date>/<path>` with `MOVES.txt` of reverse `mv`s. Never emptied by code.
  M3's `scripts/dedupe_copies.py` and (M8) the worker's copy replacement write it; the worker mounts it rw.
- **`.m3u8` exports**: `/srv/music/_playlists/*.m3u8`, written by `scripts/export_playlists.py export` (by hand
  today). Navidrome's auto-import of them is off on purpose (it would duplicate every playlist).
- **Identity outputs**: `/srv/docker/crates/identity/` (= `/data/identity` in the worker): proposal, report,
  MB cache, apply logs. Does not exist yet.

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
3. A same-named playlist without `#imported` raises `NameCollision` unless `--merge`.
4. Matched songs are appended unless already there or added by an earlier run (so a track you removed stays
   removed, D13); a new playlist is made public with comment `#imported`. Missing rows →
   `add_external_wanted` (tier `medium` by default, D15). Ambiguous rows → status `review` with the candidate ids. Stand-ins are listed as "matched with another version".
5. A re-run appends new matches **at the end** and closes wanted rows whose track is now matched.

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
4. **fetch** (`sourcing/fetch.py:127`): search + rank again; take the approved file if still offered, else the
   top one (`pick` event). Intent (`fetch.py:252-259`): crate row = **copy** upgrade; external row whose file
   name parses to another version = **version**; else plain. Row → `sourcing`; slskd enqueue; poll until
   `Completed` (timeout 600 s); find the file under the downloads folder.
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
   (`renamed` event; the Spotify names stay in `asked_*`). External row → `ok`. A copy upgrade of a
   playlist row → a **copy replacement** (§9): proof, then repoint every playlist through `playlist_edit`, then the old
   file to the trash. No proof → both files stay and the row is `review`.
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
2. **review**: you read the report; set `"skip": true` or `"choose": "<mbid>"` (must be a listed candidate; only
   on `search`/`ambiguous`/`none` rows) in the JSON.
3. **apply** (`:873`): default classes `confirmed`, `isrc`, `acoustid` + rows with `choose`; `--classes` may add
   `search`, `ambiguous`. Per file: refuse if size/mtime/tags changed since propose or a target field is not empty
   (`_check_file`, `:732`); log first (`apply-<time>.jsonl`, with prior values), `write_minimal` the id fields,
   read back, verify no other tag changed; first problem stops the run. Then scan and check: song ids unchanged,
   Navidrome shows the recording id, `.m3u8` exports still match (`export_playlists.check`).
4. **revert** (`:958`): newest first, remove a field only where the file still holds exactly the logged value
   (`tag_cleanup.remove_ids`). Re-applying after a revert needs a fresh propose (mtime changed).

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

How D16 (prefer 12" for crates) bites:

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
- Loaded **once at import** from the copy baked into the image: edit, then `docker compose up -d --build crates
  worker`. A typo stops the start with the key named.
- **D17 is open**: raising medium to ≥128 and high to ≥192 is two numbers here.

## 7. Safety invariants (what the code enforces, and where)

| Rule | Enforced at |
|---|---|
| No download without an approval | only `fetch(approve=True)` downloads; only the worker calls it; worker needs `DJ_WORKER=1` (`cli.py:227`); CLI `--approve` only records (`cli.py:50`) |
| One worker at a time | `fcntl.flock` on `/data/worker.lock` (`worker.py:36`) |
| An approval is spent once | `claim_approval` conditional UPDATE (`store.py:324`) |
| One beets writer | filer exists only with `DJ_WORKER=1` (`cli.py:38`); host convention for the rest (§10) |
| beets only sees fresh downloads | filer refuses a folder not under `.staging` (`filer.py:268`); exactly one audio file |
| beets writes tags only on a confirmed match | `-W` import + `confirm` hook (`filer.py:291-299`) |
| A filed file is never downloaded twice | row → `verify` with path as soon as beets filed it (`fetch.py:307-313`); re-checks never search (`fetch.py:211-224`) |
| Originals read-only | not mounted in any container; slskd sees only its own folder |
| Trash, never delete library files | no code deletes a library file; trash never overwrites (`(2)` suffix); the one library-file mover is `trash.move_to_trash`, reached only through `sourcing/replace.py` after the licence and an empty `references()` |
| Playlist index edits are guarded | only `crates/playlist_edit.py` edits by index; it cross-checks `navidrome.db` and refuses on any difference, on smart playlists and on playlists owned by another user |
| One reconcile at a time | flock on `/data/reconcile.lock`, 60 s, then 503 / skip (`reconcile.py`) |
| Never overwrite an id | `apply` writes only empty fields, file unchanged since propose (`identity_backfill.py:732`) |
| Other tags untouched | `write_minimal` sets only named fields; `apply` re-reads all others |
| Peer names never in UI/logs/events | `explain(peers=False)`, basenames only in events and worker stdout |
| Navidrome DB read-only | `open_ro` (`mode=ro`) and a `:ro` mount |
| Policy typos stop the start | `load_policy` raises naming the key (`policy.py:95`) |

## 8. Operations

All from `/srv/docker` (compose file is a symlink to `deploy/compose.yml`; `.env` there supplies secrets).

```
docker compose ps                                  # what runs
docker compose up -d --build crates worker         # after any code or policy.toml change
docker compose logs -f worker                      # watch ticks, downloads, filings
docker compose logs --tail 5 worker                # after a policy edit: did it start?
docker compose stop worker / up -d worker          # pause / resume (a stop mid-download: approve again)
```

| Task | How |
|---|---|
| Approve a download | web client Wanted tab: Preview, then Approve |
| …from a shell | `docker compose exec -T worker python -m sourcing.cli fetch --wanted <id> --approve [--wait]` |
| One tick by hand | stop the service first, then `docker compose run --rm worker python -m sourcing.cli worker --once` (an `exec … --once` beside the daemon exits "worker already running") |
| Re-check a never-indexed row | web client **Re-check**, or approve it again |
| Import a playlist | `docker compose exec -T crates python -m sourcing.cli import-playlist <url> [--name N] [--tier T] --dry-run`, then without `--dry-run` |
| Toggle a crate / set a tier | web client, or `docker compose exec -T crates python -m crates.cli toggle <playlist-id> on` / `… tier <playlist-id> medium` (`none` clears it); both write the playlist comment |
| Move crates.db flags into comments (once) | `docker compose exec -T crates python -m crates.cli attrs migrate [--out PATH]`, then `--apply` (§9: before the first reconcile) |
| Reconcile now | web client, or `docker compose exec -T crates python -m crates.cli reconcile` (the worker does it every 600 s) |
| Answer a version / copy question | Wanted tab (Swap / Keep), or `docker compose exec -T crates python -m crates.cli proposals [--all]`, `proposals accept\|decline <id>` |
| Undo a trashed copy | run its reverse `mv` line from `/srv/_trash/<day>/MOVES.txt` on the host (`docs/worker.md`) |
| Export / check playlists | `docker compose exec -T worker python -m scripts.export_playlists export` (or `check`) |
| Identity propose | `docker compose exec -T worker python -m scripts.identity_backfill propose [--limit 40]` |
| Identity apply | `… identity_backfill apply /data/identity/identity-proposal.json --dry-run`, then `--yes [--limit 5] [--classes …] [--only GLOB]` |
| Undo apply | `… identity_backfill revert /data/identity/apply-<time>.jsonl` |
| Tests | `cd ~/projects/dj-crate-streaming && ~/.local/bin/pytest -q` (about 1,100 tests, a few minutes) |
| Offline demo | `python3 -m crates.cli demo` → http://127.0.0.1:4580 |

Where to look: worker stdout (`docker compose logs worker`), the web client's log tab (`events`), approvals'
`result`, `/srv/docker/beets/import.log`, `.staging/` for files beets refused, `/srv/docker/crates/identity/`.

Undo: identity → `revert`; a filed download → it is a normal library file (move it to trash by hand, then
reconcile); a repoint or swap → put the old song back in the playlist in any client (after restoring its file from
the trash if it was trashed); a policy edit → git revert + rebuild; trash → the `mv` lines in `MOVES.txt`; a comment
the migration wrote → edit the comment in any client. An approval cannot be cancelled (a new one only supersedes it): stop the worker before
its next tick if you change your mind.

## 9. M8 (built)

Built and committed on this branch, **not live**. Design: `docs/specs/2026-10-16-ownership-and-identity.md`; details
and commands: `docs/worker.md`. What changed, and why:

- **The playlist comment owns crate and tier** (D21): `#crate`, `#tier:medium` (`crates/attrs.py`). `crates.db`
  caches them; `reconcile` rebuilds the cache from the comments, and on disagreement the comment wins and an `attrs`
  event records both. The setters (web toggle, `crates.cli toggle|tier`, import) write the comment, read it back,
  and only then refresh the cache. Why: a failed mirror used to leave two stores disagreeing. If a comment names an
  unknown tier, or several, the playlist shows a problem in the reconcile report and the highest valid tier is used.
  A comment crate wins over a stored tier (the API shows both).
- **A track's tier is derived**: the highest tier among the tiered playlists holding it. `crate_tracks` covers every
  tiered playlist, not only crates. Listening tiers (low/medium/high) queue an upgrade only below their floor (a
  format they do not allow, or a lossy file under the bit rate floor), not for "lossless preferred" (ruling; it
  avoids about 144 pointless upgrade rows).
- **Reconcile runs in the worker** every 600 s and in the crates service on demand. Both take one flock
  (`reconcile.lock`, 60 s, then the web answers 503 and the worker skips). A row in flight (`sourcing`, `verify`,
  `review`, or `failed` with a filed path) keeps its status whatever the verdict, and survives its playlist losing
  its tier.
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
2. **Migrate before the new code's first reconcile.** Today the import tiers exist only in `crates.db`, and the crate
   flag is mirrored into a comment only when it was set through the app. The first reconcile of the new code
   rebuilds `crates.db` from comments, so without the migration it would forget the tiers and switch off any crate
   whose comment lacks `#crate`. The new worker reconciles
   on its first tick, so keep it stopped until the comments are written:

   ```
   cd /srv/docker
   docker compose stop worker
   docker compose up -d --build --no-deps crates
   docker compose exec -T crates python -m crates.cli attrs migrate --out /data/attrs-migration-report.md   # dry run
   # read the report (/srv/docker/crates/attrs-migration-report.md), then:
   docker compose exec -T crates python -m crates.cli attrs migrate --apply
   docker compose exec -T crates python -m crates.cli reconcile
   docker compose up -d --build worker
   ```

   Do not tap reconcile or toggle in the web client before the `--apply`. The migration only adds tokens, never
   removes, refuses a playlist whose comment changed since the plan, and exits 1 if anything was refused. When
   planned, the expected report was: the 11 imported playlists each gain `#tier:medium`, no crate changes, no
   upgrades queued. If it differs, stop and read it. `--apply` writes the comments; to undo, edit the comment.
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
   - The "#crate" lookalike list. The old crate test was a substring match; the new one needs `#crate` as a whole
     word. The migration report's "Contains #crate but is not read as a crate" section lists playlists like
     `#crates` or `#crate.` that were crates before and are not now. Decide each: fix its comment, or say so and it
     gets flagged.
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
    beets package and write `library.db`. **Medium** if run while the worker files. *Stop the worker first.*
15. **`rank --download` bypasses everything.** `sourcing.cli rank --slskd … --download` enqueues in slskd
    directly (`cli.py:311-313`): no approval, verify or filing, and it prints peer names. *Don't use it.*
16. **Import `review` rows have no picker.** Since M8 the Wanted tab lists `review` rows with their reason, and the
    retryable ones from copy replacement (kept beside, declined, not made, filed beside) offer Preview and Approve.
    The 11 live import `review` rows (several versions fit) are visible but still cannot be resolved. **Medium.**
    (Question 15.)
17. **Failed rows duplicate on re-import.** `find_external` skips failed unfiled rows (`store.py:367`), so a re-run
    of the import queues a second row for the same track. **Low.**
18. **Filed external rows are not put in their playlist** (re-run the import to append them at the end). **Medium**
    for DJ order. (Question 11.)
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

19. **M8 migration, "#crate" lookalikes:** after the dry run, which playlists whose comment or name contains `#crate`
    but not as a whole word (`#crates`, `#crate.`) should be crates? *Default: none; the migration leaves them
    alone and lists them.* You fix the comment, or tell me to flag them.
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
