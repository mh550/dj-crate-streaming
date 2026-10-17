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
- **Tests:** `~/.local/bin/pytest -q` (about 1,120 tests, 7 minutes). Fakes must mirror captured live responses
  (`fixtures/`). The suite reads a frozen old policy (`tests/fixtures/policy-legacy.toml`) and runs the older
  comment-owned mode (`CRATES_OWNER=comment`) by default via `tests/conftest.py`; new-mode tests are in `tests/test_app_owner.py`.

## Navidrome 0.64
- The Subsonic `path` is virtual; real paths are only in `navidrome.db` (read-only via `scripts.export_playlists.open_ro`).
- Retagging in place keeps the song id; a move with unchanged tags keeps it; **retag + move between two scans gives a
  new id**, so playlists must be repointed. `ND_AUTOIMPORTPLAYLISTS` is false on purpose (the `.m3u8` exports are backups).
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

## SQLite
- `crates.db` and `navidrome.db` are in WAL mode: data can sit in `<db>-wal` while the main file is 4 KB. Copy them
  only with `scripts/snapshot-crates-db.sh` (`sqlite3 .backup`, both databases since H1); `--suffix <run>` gives a
  run its own restore point. The nightly restic job runs it first, from `~/projects/dj-crate-streaming`, so
  `navidrome.db.snap` exists only once that checkout has this version (H2 installs a fixed copy instead).
