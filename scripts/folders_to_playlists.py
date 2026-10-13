"""Recreate Michael's genre/vibe folders as Navidrome playlists.

The import re-filed everything as Artist/Album, so this reads docs/library-map.csv
(original folder → new path), turns each curation folder into a playlist named
"Parent / Child", and fills it via the Subsonic API. Artist/Album directories that
sit *inside* a curation folder are structure, not curation, and are stripped first.

    SUBSONIC_URL=http://127.0.0.1:4533 SUBSONIC_USER=.. SUBSONIC_PASS=.. \\
      python3 -m scripts.folders_to_playlists docs/library-map.csv [--apply] [--navidrome-db PATH]

Song ids come from Navidrome's own SQLite (read-only; default /srv/docker/navidrome/navidrome.db),
because the Subsonic API's `path` field is a virtual Artist/Album/Title path, not the file on
disk. Without --apply it only prints the plan. Existing playlists with the same name (for this
Subsonic user) are left alone, so re-running is a no-op; delete one to rebuild it.
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

from crates.service import Config
from scripts.library_map import read_csv
from subsonic.client import SubsonicClient

_PLACEHOLDERS = {"unknown artist", "unknown album", "various artists"}


def _norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKC", s or "").casefold().strip()
    if s in _PLACEHOLDERS:
        return ""
    s = re.sub(r"[\(\[].*?[\)\]]", "", s)            # drop "(Deluxe)", "[Unknown Album]"
    return re.sub(r"[\W_]+", "", s)


def _matches(part: str, tags: set[str]) -> bool:
    """Folder part names one of the tags: equal, or (when not tiny) contained in it."""
    p = _norm(part)
    if not p:
        return True
    tags = {n for n in map(_norm, tags) if n}
    return any(p == n or (len(p) > 3 and p in n) for n in tags)


def playlist_name(folder: str, albums: set[str], artists: set[str], folders_with_audio: set[str]) -> str | None:
    """Name the playlist for a folder, given the album/artist tags of the tracks directly in it.

    A trailing Artist/Album pair is structure: the leaf is an album dir when the folder holds
    one album and is named after it, or (depth >= 3) its parent holds no audio of its own and
    the leaf isn't named after the artist; the parent then goes too when it is the artist or
    holds no audio. A lone trailing artist dir is structure only when its name matches the
    artist tag. A folder holding several albums is curation whatever its name.
    """
    parts = [p for p in folder.split("/") if p]
    if len(parts) <= 1:
        return parts[0] if parts else None
    parent = "/".join(parts[:-1])
    leaf_is_artist = _matches(parts[-1], artists)
    structural = len(parts) >= 3 and len(albums) == 1 and parent not in folders_with_audio and not leaf_is_artist
    leaf_is_album = len(albums) <= 1 and (any(_matches(parts[-1], {a}) for a in albums) or structural)
    if leaf_is_album:                      # before the artist test, so a self-titled album pops both levels
        parts.pop()
        if len(parts) > 1 and (_matches(parts[-1], artists) or parent not in folders_with_audio):
            parts.pop()
    elif leaf_is_artist:
        parts.pop()
    return " / ".join(parts)


def plan(rows: list[dict], songs_by_path: dict[str, dict]) -> tuple[dict[str, list[str]], list[str]]:
    """songs_by_path: new_path → {"id", "album", "artists"}. Returns ({playlist: [song ids]}, skipped originals)."""
    pairs = [(r, songs_by_path.get(r["new_path"])) for r in sorted(rows, key=lambda r: r["original_path"].casefold())]
    albums: dict[str, set[str]] = {}
    artists: dict[str, set[str]] = {}
    for r, song in pairs:
        if song:
            albums.setdefault(r["folder"], set()).add(song["album"])
            artists.setdefault(r["folder"], set()).update(song["artists"])
    names = {f: playlist_name(f, albums[f], artists[f], set(albums)) for f in albums}
    out: dict[str, list[str]] = {}
    skipped: list[str] = []
    for r, song in pairs:
        name = names.get(r["folder"]) if song else None
        if not name:
            skipped.append(r["original_path"])
            continue
        ids = out.setdefault(name, [])
        if song["id"] not in ids:
            ids.append(song["id"])
    return out, skipped


def _load_songs(navidrome_db: Path) -> dict[str, dict]:
    con = sqlite3.connect(navidrome_db.resolve().as_uri() + "?mode=ro", uri=True)
    rows = con.execute("select id, path, album, artist, album_artist from media_file").fetchall()
    con.close()
    return {path: {"id": sid, "album": album, "artists": [artist, album_artist]}
            for sid, path, album, artist, album_artist in rows}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", type=Path)
    ap.add_argument("--apply", action="store_true", help="create the playlists (default: print the plan)")
    ap.add_argument("--navidrome-db", type=Path, default=Path("/srv/docker/navidrome/navidrome.db"))
    a = ap.parse_args(argv)
    cfg = Config.from_env()
    if not (cfg.username and cfg.password):
        print("set SUBSONIC_USER / SUBSONIC_PASS (and SUBSONIC_URL)", file=sys.stderr); return 2
    client = SubsonicClient(cfg.subsonic_url, cfg.username, cfg.password)
    rows = read_csv(a.csv)
    songs = _load_songs(a.navidrome_db)
    missing = [r["original_path"] for r in rows if r["new_path"] and r["new_path"] not in songs]
    if missing:
        print(f"{len(missing)} mapped files are not in Navidrome yet (scan pending?); refusing to plan:", file=sys.stderr)
        for m in missing[:10]: print(f"  {m}", file=sys.stderr)
        return 1
    if a.apply and client.scan_status().get("scanning"):
        print("Navidrome is scanning; try again when it finishes", file=sys.stderr); return 1
    todo, skipped = plan(rows, songs)
    existing = {p.name for p in client.playlists()}
    for name, ids in sorted(todo.items(), key=lambda kv: kv[0].casefold()):
        if name in existing:
            flag = "exists, skipped"
        elif a.apply:
            client.create_playlist(name, ids); flag = "created"
        else:
            flag = "would create"
        print(f"{len(ids):4d}  {name}  [{flag}]")
    print(f"{len(todo)} playlists, {sum(len(v) for v in todo.values())} entries; "
          f"{len(skipped)} originals not in any playlist (root files)")
    for sk in skipped:
        print(f"  skipped: {sk}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
