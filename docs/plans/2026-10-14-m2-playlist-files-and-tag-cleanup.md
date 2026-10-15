# M2: playlist files on disk, then the tag cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline) with superpowers:test-driven-development.

**Goal:** every Navidrome playlist exists as `/srv/music/_playlists/<name>.m3u8` (portable, survives a DB loss), and the playlists are provably intact after M2's tag cleanup re-files songs.

**Architecture:** `scripts/export_playlists.py` reads `navidrome.db` **read-only** (Subsonic `path` is virtual; the real path exists only in `media_file.path`) and writes one m3u8 per playlist with entries relative to the m3u8 file (`../Artist/Album/NN - Title.flac`), so any player resolves them. `check` re-reads the files, resolves every entry, maps it back to a `media_file` id by path, and compares with the playlist's order in the DB. That is the round-trip. Runs on the host: no Navidrome credentials needed, nothing secret read.

**Tech stack:** Python 3.12 stdlib (`sqlite3`, `pathlib`, `os.path.relpath`). Tests: `~/.local/bin/pytest -q`.

**Spec:** `docs/specs/2026-10-13-next-session-design.md` §4.1 (playlist files on disk) and §3 (backfill).

## Global constraints
- Read `navidrome.db` with `?mode=ro` only. Never write to it.
- Idempotent: an unchanged playlist's file is not rewritten (content compare); stale files are reported, never deleted.
- Navidrome must not import these files: `ND_AUTOIMPORTPLAYLISTS=false` (done 2026-10-14, compose).
- Test DB mirrors the live schema's column names (captured 2026-10-14: `playlist(id, name, owner_id, …)`, `playlist_tracks(id, playlist_id, media_file_id)` ordered by `id`, `media_file(id, path, title, artist, duration, missing, …)`).

## Review focus
1. Playlist names with `/` ("playlists / perfect songs") or full-width characters ("firstset？") → safe, unique file names.
2. Paths with `'`, `’`, `#`, `,`, leading `#` lines: an entry line must never start with `#`.
3. Re-run with nothing changed rewrites nothing (mtime kept).
4. A file moved or deleted after export → `check` names the playlist and entry and exits 1.
5. A playlist reordered or edited in Navidrome after export → `check` reports "stale", and `export` refreshes it.

### Task 1: `scripts/export_playlists.py export | check` (tests in `tests/test_export_playlists.py`)
Functions: `load(db) -> list[PL]` (PL = name, id, entries[(path, duration, artist, title)]), `file_name(name, taken) -> str`, `render(pl, out_dir, music_dir) -> str`, `export(db, music_dir, out_dir) -> Summary(written, unchanged, stale)`, `parse(text) -> list[str]`, `check(db, music_dir, out_dir) -> list[str]` (problems). CLI `export|check [--db] [--music] [--out]`.

### Task 2: `scripts/tag_cleanup.py` — planned at runbook M2 step 2 after a fresh tag census (appended below then).
