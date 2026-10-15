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

### Task 2: `scripts/tag_cleanup.py` — fix what Amperfy shows (spec §3 backfill)

**Facts this task is built on (2026-10-15):**
- **Navidrome ids** (throwaway Navidrome 0.64 on copies of two files): *retag in place* keeps the song id;
  *move with unchanged tags* keeps the id (matched by PID); *retag + move between two scans* gives a
  **new id**: the old one is marked missing and playlists silently drop the song. → **two passes,
  each followed by a completed Navidrome scan: (1) write tags in place, (2) move files.** No playlist
  repointing needed if the order holds.
- **The beets DB has drifted from the files.** As-is imports left item fields such as artist "08"
  and albumartist "Various Artists" where the file says otherwise, and 351 of the 366 Compilations
  items have an item album ≠ album-entity album. Navidrome (so Amperfy) reads the *files*. → every
  item is first re-read from its file (`item.read()`): the file is the truth (D5).
- Census on file-backed fields: 366 under `Compilations/`, 19 " - Remaster…" titles, 4 sockseek
  `Artist - 'Title' (Album)`, 4 "NN - Artist - Title.mp3" junk titles (= artist), 1 "Artist - Title"
  with no artist tag, 16 " - Live" titles (**kept**, D14 default: a live take is a different recording
  for a DJ; spec §3 said strip, so this is asked).
- beets runs as `/usr/bin/python3` with `/usr/share/beets` on the path (Debian package). Scripts add
  that path themselves; the pipx pytest (3.12.3) can import it the same way.

**Design:** `scripts/tag_rules.py` holds the rules as pure functions (no beets):
`clean(f: dict) -> tuple[dict, list[str]]` on keys `title, artist, albumartist, album, comp, comments,
in_compilations`, returning only changed keys plus rule names. Rules, in order: junk filename title →
artist/title; no artist + one " - " → artist/title; sockseek → title (+ album when empty/placeholder);
artist prefix "Artist - Title" → title; remaster suffix → title, suffix appended to `comments` as
`version: <suffix>`; under Compilations → `albumartist = artist`, `comp = False`. Idempotent.
`scripts/tag_cleanup.py` is the beets glue:
- `plan` — copies library.db to a temp file, re-reads every item from its file, applies `clean`,
  regroups the Compilations items into one album per (albumartist, album), computes each item's new
  destination with the real `deploy/beets.yaml` path formats, and writes `docs/tag-cleanup-report.md`
  (counts per rule, every field change, every planned move, destination collisions, and any
  *untouched* item whose destination would also change). Touches no file and not the real DB.
- `retag` — backs up library.db, same steps on the real DB, `item.store()` + `item.write()` in
  place, no moves; writes `/srv/docker/beets/tag-cleanup-manifest.json` (id, path, old and new values).
- `move` — refuses unless every manifest path's row in navidrome.db (read-only) shows the new title
  and artist, i.e. Navidrome has scanned pass 1; then `item.move()` for the manifest items only and
  records the new paths.
Tests build a temp beets library from ffmpeg-generated one-second files tagged with mediafile,
including a fake "pure soul 128" compilation whose DB fields disagree with the files.
