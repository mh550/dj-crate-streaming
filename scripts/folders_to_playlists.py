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


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").casefold()
    s = re.sub(r"[\(\[].*?[\)\]]", "", s)            # drop "(Deluxe)", "[2003 Remaster]"
    return re.sub(r"[\W_]+", "", s)


def _matches(part: str, candidates: list[str]) -> bool:
    p = _norm(part)
    if not p or p in {_norm(x) for x in PLACEHOLDERS}:
        return True
    return any(p == _norm(c) or (len(p) > 3 and (p in _norm(c) or _norm(c) in p)) for c in candidates if c)


def playlist_name(folder: str, album: str | None, artists: list[str],
                  album_dir=lambda f: False, has_audio=lambda f: True) -> str | None:
    """album_dir(folder): the source folder looks like an album (cover art inside);
    has_audio(folder): some track sits directly in that folder (from the map)."""
    parts = [p for p in folder.split("/") if p]
    if not parts:
        return None
    was_album = False
    if len(parts) > 1 and (_matches(parts[-1], [album or ""]) or album_dir("/".join(parts))):
        parts.pop(); was_album = True
    if len(parts) > 1 and (_matches(parts[-1], artists) or (was_album and not has_audio("/".join(parts)))):
        parts.pop()
    return " / ".join(parts)


def plan(rows: list[dict], songs_by_path: dict[str, dict], source: Path | None = None) -> tuple[dict[str, list[str]], list[str]]:
    """songs_by_path: new_path → {"id", "album", "artists"}. Returns ({playlist: [song ids]}, skipped originals)."""
    folders_with_audio = {r["folder"] for r in rows}
    def album_dir(folder: str) -> bool:
        return bool(source) and any(next((source / folder).glob(ext), None) for ext in ("*.jpg", "*.jpeg", "*.png"))
    out: dict[str, list[str]] = {}
    skipped: list[str] = []
    for r in sorted(rows, key=lambda r: r["original_path"].casefold()):
        song = songs_by_path.get(r["new_path"]) if r["new_path"] else None
        name = playlist_name(r["folder"], song["album"], song["artists"], album_dir, folders_with_audio.__contains__) if song else None
        if not song or not name:
            skipped.append(r["original_path"])
            continue
        ids = out.setdefault(name, [])
        if song["id"] not in ids:
            ids.append(song["id"])
    return out, skipped


def _load_songs(navidrome_db: Path) -> dict[str, dict]:
    import sqlite3
    con = sqlite3.connect(f"file:{navidrome_db}?mode=ro", uri=True)
    rows = con.execute("select id, path, album, artist, album_artist from media_file").fetchall()
    con.close()
    return {path: {"id": sid, "album": album or "", "artists": [artist or "", album_artist or ""]}
            for sid, path, album, artist, album_artist in rows}


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__); return 2
    apply = "--apply" in argv
    db = Path(argv[argv.index("--navidrome-db") + 1]) if "--navidrome-db" in argv else Path("/srv/docker/navidrome/navidrome.db")
    source = Path(argv[argv.index("--source") + 1]) if "--source" in argv else None
    rows = list(csv.DictReader(Path(argv[0]).open(newline="")))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from subsonic.client import SubsonicClient
    client = SubsonicClient(os.environ.get("SUBSONIC_URL", "http://127.0.0.1:4533"),
                            os.environ["SUBSONIC_USER"], os.environ["SUBSONIC_PASS"])
    songs = _load_songs(db)
    todo, skipped = plan(rows, songs, source)
    existing = {p.name for p in client.playlists()}
    for name, ids in sorted(todo.items(), key=lambda kv: kv[0].casefold()):
        flag = "exists, skipped" if name in existing else ("created" if apply else "would create")
        if apply and name not in existing:
            client.create_playlist(name, ids)
        print(f"{len(ids):4d}  {name}  [{flag}]")
    print(f"{len(todo)} playlists, {sum(len(v) for v in todo.values())} entries; "
          f"{len(skipped)} originals not in any playlist (root files / unmapped)")
    for s in skipped:
        print(f"  skipped: {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
