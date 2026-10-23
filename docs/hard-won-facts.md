# Hard-won facts (each cost time; don't relearn them)

Carried from `HANDOFF-M6.md` (removed 2026-10-17), updated for the current setup. For anyone, human or agent, working
on this system.

## Running things
- **Credentials** live only in the containers (`/srv/docker/.env`; never print or source it into a shell). Navidrome calls
  go through the container: `cd /srv/docker && docker compose exec -T crates python3 -m <module> …`. The crates container
  holds `SLSKD_URL`/`SLSKD_API_KEY`; `fetch --approve` refuses inside it (only the worker downloads).
- **Deploy from a commit:** `scripts/deploy.sh [service…]` (refuses a dirty tree, tags the image `dj-crates:<sha>`).
  `/srv/docker/compose.yml` is a symlink to a checkout's `deploy/compose.yml`; the script uses the checkout it runs from.
- **The permission classifier** may block "production" actions (a rebuild, reads of `/srv/docker/navidrome/`). What
  passes: repo CLI commands in the container, `curl 127.0.0.1:4580/api/...`, `scripts/deploy.sh` once the user has
  allowed the rebuild, read-only SQLite (`mode=ro`) on `navidrome.db` and `crates.db`.
- **`git add -A` sweeps scratch files in.** Write scratch output elsewhere, check `git show --stat HEAD` before pushing.
  Soulseek peer names stay out of logs and UI (p1, p2, …).
- **Tests:** `~/.local/bin/pytest -q` (1,750 tests, about 11 minutes). Fakes must mirror captured live responses
  (`fixtures/`). The suite reads a frozen old policy (`tests/fixtures/policy-legacy.toml`) and runs the older
  comment-owned mode (`CRATES_OWNER=comment`) by default via `tests/conftest.py`; new-mode tests are in `tests/test_app_owner.py`.

## Navidrome 0.64
- The Subsonic `path` is virtual; real paths are only in `navidrome.db` (read-only via `scripts.export_playlists.open_ro`).
- Retagging in place keeps the song id; a move with unchanged tags keeps it; **retag + move between two scans gives a
  new id**, so playlists must be repointed. `ND_AUTOIMPORTPLAYLISTS` is false on purpose (the `.m3u8` exports are backups).
  The exports follow Navidrome within 5 minutes, so the restore source is `_playlists/.history/<date>/` (the previous
  file, kept 30 days, R5-02).
- `getPlaylist` hides songs whose file is missing but their `playlist_tracks` rows keep positions: index edits go through
  `crates/playlist_edit.py`, which cross-checks `navidrome.db` first.

## beets 1.6
- **Never `beet write` / `beet modify` / `import -L` on the whole library.** beets 1.6 rewrites every field and collapsed
  multi-valued genres in M2. `deploy/beets.yaml` has `import.write: yes`, and `beet import` writes all tags on the
  imported copy; the filer imports with `-W` and writes only after a confident MusicBrainz match (`sourcing/filer.py`).
- `incremental: yes` skips directories already seen, so each download comes from a fresh directory (or `-I`).
- Tag writes elsewhere go through `scripts.tag_cleanup.write_minimal`.

## Files and tools
- **Trash** is `/srv/_trash/<date>/` with `MOVES.txt` of reverse `mv` lines. `free_path` never overwrites. Never emptied by code.
- **ffmpeg reads stdin:** pass `stdin=subprocess.DEVNULL` and `-nostdin` to every tool, or a shell `while read` loop loses input.
- ffmpeg `[error]` lines are not all errors (webp covers, odd ID3 frames, one junk mp3 frame); for FLAC `flac -t` decides.
- ffprobe estimates mp3 length for VBR files without a Xing header or with large cover art; trust the decoded length
  (`AudioInfo.duration_exact`).
- Tool output is not UTF-8 (Soulseek tags come as cp1251/latin-1): read with `encoding="utf-8", errors="replace"`.
- astats prints `-inf` for silence; JSON can't hold it (`finite()`).
- Test audio: an `anullsrc` concat silently negotiates down to 8-bit; force `aformat=sample_fmts=…` at every stage
  (`tests/helpers.make_audio`, `convert`).
- A full-library `verify` takes about 75 minutes with 6 in parallel (CPU-bound).
- **slskd 0.26.1 keeps a transfer on a plain `DELETE /transfers/downloads/<peer>/<id>`** (it only cancels, 204); the
  record goes only with `?remove=true`, and an unknown id is 404. Its listing order is not known: fetch follows the
  record whose id wasn't there before its enqueue (S1-04), never the last one.
- **slskd 0.26.1 answers 404 to `GET /transfers/downloads/<peer>` for a peer with no transfers** (yet, or any more),
  not an empty listing. `SlskdClient.downloads` reads that 404 as empty; it failed all 8 Al Green rows on 2026-10-21
  before any enqueue.
- **A confident AcoustID result can name another song of the same length.** ext-74 asked for "I'm Still In Love With
  You" (Spotify 196 s) and got track 09 "One of These Good Old Days" (195 s) from a folder named after the album;
  AcoustID said so at 0.958, MusicBrainz has the two at 195.7 s and 195.6 s. Duration can't catch it: the file's
  title slot (S1-01), AcoustID's title against the asked one (S1-02) and Navidrome's title at filing (S1-03) do.
- **Spotify's album embed has `releaseDate: null`** (captured 2026-10-22): an album request's year comes from
  MusicBrainz (`requests.match_request_release`, S2-03), else it stays unknown (D51 *default*: the files' year is cleared).
- **slskd's multi-file enqueue is not captured.** The album job POSTs one peer's planned files in one
  `POST /transfers/downloads/<peer>` (S2-05) and, like fetch, never reads the response: it follows the records whose
  ids weren't listed before. Capture the response shape on the live box before relying on it (S4 checklist).

## SQLite
- `crates.db` and `navidrome.db` are in WAL mode: data can sit in `<db>-wal` while the main file is 4 KB. Copy them
  only with `scripts/snapshot-crates-db.sh` (`sqlite3 .backup`, both databases since H1); `--suffix <run>` gives a
  run its own restore point. The nightly restic job (`/usr/local/sbin/restic-backup`, installed from
  `deploy/restic-backup` by H2) runs it first, from its installed copy `/usr/local/lib/dj-crates/snapshot-crates-db.sh`,
  not from a checkout; a change to the script reaches the backup only when Michael reinstalls it.

## Learned in the N1-N4 run (2026-10-19)
- **The fake `navidrome.db` mirror must carry every column a script SELECTs.** `subsonic/fake_server.py`
  `NAVIDROME_SCHEMA` lists only what earlier code read; `duplicate_report.load` SELECTs `bit_rate`, which the mirror
  lacked, so the test failed on the fake, not on the code. When a script reads a new column, add it to the schema and
  to the fake's INSERT in the same commit.
- **The cleanup's trash step needs the worker stopped.** Only the worker container has `DJ_WORKER=1`, so only it can
  make beets forget a trashed path, and beets has one writer (D18, D36). `trash` refuses while the worker holds
  `worker.lock`; run it with `docker compose run --rm --no-deps worker …` after `docker compose stop worker`.
  `repoint` and `plan` run beside the daemon.
- **Scan between repoint and trash.** Navidrome still lists a trashed song until a scan finishes, and Amperfy can add
  it to a playlist meanwhile. `trash` refuses unless a scan finished after the newest `repoint-<time>.jsonl`.
- **Placement is state-driven, so a restart loses nothing.** What is due comes from `import_order`, `imported_entries`
  and `placements` each tick, not from a queue in memory. An unconfirmed edit is looked at on the next tick, never
  resent. It only works for playlists imported (or re-run) since N4: older ones have no `import_order`.
- **A copy replacement or a repoint changes the song id,** so crates.db rows that name it (`import_order`,
  `imported_entries`, filed `external_wanted`, unfinished `placements`) follow through `CrateStore.repoint_song`.
- **The marker for "ours" is a crates.db row, not the comment** (`imported_playlists`, D37): `#imported` in a comment
  means nothing to the code now.
