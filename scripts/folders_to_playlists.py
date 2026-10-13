"""Recreate Michael's genre/vibe folders as Navidrome playlists.

The import re-filed everything as Artist/Album, so this reads docs/library-map.csv
(original folder → new path), turns each curation folder into a playlist named
"Parent / Child", and fills it via the Subsonic API. Artist/Album directories that
sit *inside* a curation folder are not curation: trailing path parts that match the
track's album or artist tags are stripped before naming.

    SUBSONIC_URL=http://127.0.0.1:4533 SUBSONIC_USER=.. SUBSONIC_PASS=.. \
      python3 -m scripts.folders_to_playlists docs/library-map.csv [--apply] [--navidrome-db PATH] [--source /srv/incoming/library-import]

Song ids come from Navidrome's own SQLite (read-only; default /srv/docker/navidrome/navidrome.db),
because the Subsonic API's `path` field is a virtual Artist/Album/Title path, not the file on
disk. Without --apply it only prints the plan. Existing playlists with the same name are
left alone (idempotent); re-run after deleting one to rebuild it.
"""
from __future__ import annotations

import csv
import os
import re
import sys
import unicodedata
from pathlib import Path

PLACEHOLDERS = {"unknown artist", "various artists", "unknown album", "va"}
_PLACEHOLDER_NORMS = set()  # filled after _norm is defined


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").casefold()
    s = re.sub(r"[\(\[].*?[\)\]]", "", s)            # drop "(Deluxe)", "[2003 Remaster]"
    return re.sub(r"[\W_]+", "", s)


def _matches(part: str, candidates: list[str]) -> bool:
    p = _norm(part)
    if not p or p in _PLACEHOLDER_NORMS:
        return True                       # "Unknown Artist/" style dirs are never curation
    ncs = [n for n in (_norm(c) for c in candidates) if n and n not in _PLACEHOLDER_NORMS]
    return any(p == n or (len(p) > 3 and p in n) for n in ncs)   # folder name inside the tag, not the reverse


_PLACEHOLDER_NORMS.update(_norm(x) for x in PLACEHOLDERS)


def playlist_name(folder: str, album: str | None, artists: list[str],
                  album_dir=lambda f: False, has_audio=lambda f: True,
                  albums_in=lambda f: None) -> str | None:
    """Strip the non-curation tail of a folder path and join the rest with " / ".

    album_dir(folder): the source folder looks like an album (cover art inside);
    has_audio(folder): some track sits directly in that folder (from the map);
    albums_in(folder): distinct album tags among the tracks directly in it (None = unknown).

    A leaf is an album dir when it holds one album and is named after it, has cover art,
    or sits at depth >= 3 under a parent with no audio of its own (and isn't named after
    the artist); its parent then goes too when it is the artist or holds no audio. Else a
    leaf named after the artist is an artist dir (pop once). A folder holding several
    albums is curation whatever its name.
    """
    parts = [p for p in folder.split("/") if p]
    if len(parts) <= 1:
        return parts[0] if parts else None
    leaf = "/".join(parts); parent = "/".join(parts[:-1])
    n_albums = albums_in(leaf)
    leaf_is_artist = _matches(parts[-1], artists)
    structurally_album = len(parts) >= 3 and n_albums == 1 and not has_audio(parent) and not leaf_is_artist
    leaf_is_album = (n_albums is None or n_albums <= 1) and (
        _matches(parts[-1], [album or ""]) or album_dir(leaf) or structurally_album)
    if leaf_is_album:                      # checked first so a self-titled album pops both levels
        parts.pop()
        if len(parts) > 1 and (_matches(parts[-1], artists) or not has_audio(parent)):
            parts.pop()
    elif leaf_is_artist:
        parts.pop()
    return " / ".join(parts)


def plan(rows: list[dict], songs_by_path: dict[str, dict], source: Path | None = None) -> tuple[dict[str, list[str]], list[str]]:
    """songs_by_path: new_path → {"id", "album", "artists"}. Returns ({playlist: [song ids]}, skipped originals)."""
    folders_with_audio = {r["folder"] for r in rows}
    albums_in_folder: dict[str, set[str]] = {}
    for r in rows:
        song = songs_by_path.get(r["new_path"]) if r["new_path"] else None
        if song:
            albums_in_folder.setdefault(r["folder"], set()).add(_norm(song["album"]))
    def album_dir(folder: str) -> bool:
        return bool(source) and any(next((source / folder).glob(ext), None) for ext in ("*.jpg", "*.jpeg", "*.png"))
    def albums_in(folder: str):
        a = albums_in_folder.get(folder); return None if a is None else len(a)
    out: dict[str, list[str]] = {}
    skipped: list[str] = []
    for r in sorted(rows, key=lambda r: r["original_path"].casefold()):
        song = songs_by_path.get(r["new_path"]) if r["new_path"] else None
        name = playlist_name(r["folder"], song["album"], song["artists"], album_dir,
                             folders_with_audio.__contains__, albums_in) if song else None
        if not song or not name:
            skipped.append(r["original_path"])
            continue
        ids = out.setdefault(name, [])
        if song["id"] not in ids:
            ids.append(song["id"])
    return out, skipped


def _load_songs(navidrome_db: Path) -> dict[str, dict]:
    import sqlite3
    con = sqlite3.connect(navidrome_db.resolve().as_uri() + "?mode=ro", uri=True)
    rows = con.execute("select id, path, album, artist, album_artist from media_file").fetchall()
    con.close()
    return {path: {"id": sid, "album": album or "", "artists": [artist or "", album_artist or ""]}
            for sid, path, album, artist, album_artist in rows}


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", type=Path)
    ap.add_argument("--apply", action="store_true", help="create the playlists (default: print the plan)")
    ap.add_argument("--navidrome-db", type=Path, default=Path("/srv/docker/navidrome/navidrome.db"))
    ap.add_argument("--source", type=Path, help="original library root, for the cover-art check")
    a = ap.parse_args(argv)
    if not (os.environ.get("SUBSONIC_USER") and os.environ.get("SUBSONIC_PASS")):
        print("set SUBSONIC_USER / SUBSONIC_PASS (and SUBSONIC_URL)", file=sys.stderr); return 2
    rows = list(csv.DictReader(a.csv.open(newline="")))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from subsonic.client import SubsonicClient
    client = SubsonicClient(os.environ.get("SUBSONIC_URL", "http://127.0.0.1:4533"),
                            os.environ["SUBSONIC_USER"], os.environ["SUBSONIC_PASS"])
    songs = _load_songs(a.navidrome_db)
    missing = [r["original_path"] for r in rows if r["new_path"] and r["new_path"] not in songs]
    if missing:
        print(f"{len(missing)} mapped files are not in Navidrome yet (scan pending?); refusing to plan:", file=sys.stderr)
        for m in missing[:10]: print(f"  {m}", file=sys.stderr)
        return 1
    if a.apply and client.scan_status().get("scanning"):
        print("Navidrome is scanning; try again when it finishes", file=sys.stderr); return 1
    todo, skipped = plan(rows, songs, a.source)
    existing = {p.name for p in client.playlists()}   # this Subsonic user's playlists (+ public ones)
    for name, ids in sorted(todo.items(), key=lambda kv: kv[0].casefold()):
        flag = "exists, skipped" if name in existing else ("created" if a.apply else "would create")
        if a.apply and name not in existing:
            client.create_playlist(name, ids)
        print(f"{len(ids):4d}  {name}  [{flag}]")
    print(f"{len(todo)} playlists, {sum(len(v) for v in todo.values())} entries; "
          f"{len(skipped)} originals not in any playlist (root files)")
    for sk in skipped:
        print(f"  skipped: {sk}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
