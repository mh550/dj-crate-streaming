"""Read-only report of duplicate songs in Navidrome: the start of the Navidrome cleanup (2026-10-17).

    python3 -m scripts.duplicate_report [--navidrome-db PATH] [--out docs/duplicates-report.md]

It reads navidrome.db (read-only) and writes one markdown file. It moves, trashes and edits nothing.

Two kinds of group, both found with the same identity rules the rest of the system uses (sourcing/identity.py):

* **Same recording, several files** (`same_version`: same lead artist, base title and version label, lengths within
  4 s, or the same MusicBrainz recording id). These are duplicates. The report names the file to keep (best
  quality: lossless before lossy, then bit rate, then the properly filed path) and lists the playlists holding each
  file, because a copy in a playlist must be repointed before it can be trashed (scripts/dedupe_copies.py and
  sourcing/replace.py do that safely).
* **Same song, different versions** (e.g. radio edit, 12", live). Not duplicates; listed for information only.
"""
from __future__ import annotations

import argparse
import sys
from contextlib import closing
from pathlib import Path

try:
    from scripts.export_playlists import open_ro
    from scripts.library_map import _copy_rank
    from sourcing.identity import Copy, parse_title, song_key, version_groups
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.export_playlists import open_ro
    from scripts.library_map import _copy_rank
    from sourcing.identity import Copy, parse_title, song_key, version_groups

LOSSLESS = {"flac", "wav", "aiff", "aif", "alac", "ape", "wv"}
DEFAULT_DB = Path("/srv/docker/navidrome/navidrome.db")


def keep_rank(row: dict) -> tuple:
    """Sort key, best first: lossless, then (lossy only) higher bit rate, then the properly filed path
    (library_map._copy_rank). Two lossless files count as equal: 938 vs 934 kbps is noise, not quality."""
    lossless = row["suffix"].lower() in LOSSLESS
    return (not lossless, 0 if lossless else -(row["bit_rate"] or 0), _copy_rank(row["path"]))


def duplicate_groups(rows: list[dict]) -> list[list[dict]]:
    """Groups of two or more rows that are one recording, each sorted best-first (the first is the one to keep)."""
    copies = [Copy(r["artist"], r["title"], r["duration"] or None, r["mbz_recording_id"] or "") for r in rows]
    return [sorted((rows[i] for i in g), key=keep_rank) for g in version_groups(copies)]


def other_version_groups(rows: list[dict], dup_ids: set[str]) -> dict[str, list[dict]]:
    """Songs that exist in more than one version (different version labels/lengths), by song key."""
    by_song: dict[str, list[dict]] = {}
    for r in rows:
        by_song.setdefault(song_key(r["artist"], r["title"]), []).append(r)
    out = {}
    for k, members in by_song.items():
        keys = {parse_title(m["title"], m["artist"]).key for m in members} | {round((m["duration"] or 0) / 4) for m in members}
        if len(members) > 1 and len(keys) > 1 and not all(m["id"] in dup_ids for m in members):
            out[k] = members
    return out


def load(db: Path) -> tuple[list[dict], dict[str, list[str]]]:
    with closing(open_ro(db)) as con:
        con.row_factory = lambda cur, r: dict(zip([c[0] for c in cur.description], r))
        rows = con.execute("SELECT id, artist, title, album, path, suffix, bit_rate, duration, size, mbz_recording_id "
                           "FROM media_file WHERE missing = 0 ORDER BY artist, title, id").fetchall()
        held: dict[str, list[str]] = {}
        for r in con.execute("SELECT pt.media_file_id AS mid, p.name AS name FROM playlist_tracks pt "
                             "JOIN playlist p ON p.id = pt.playlist_id"):
            held.setdefault(r["mid"], []).append(r["name"])
    return rows, held


def mmss(s) -> str:
    s = int(s or 0)
    return f"{s // 60}:{s % 60:02d}"


def render(rows: list[dict], held: dict[str, list[str]]) -> str:
    groups = duplicate_groups(rows)
    dup_ids = {r["id"] for g in groups for r in g}
    others = other_version_groups(rows, dup_ids)
    extra = sum(len(g) - 1 for g in groups)
    gb = sum(r["size"] for g in groups for r in g[1:]) / 1e9
    out = ["# Duplicate songs in Navidrome", "",
           "Read-only report from `scripts/duplicate_report.py`. Nothing was moved or deleted.", "",
           f"- Songs in Navidrome: {len(rows)}",
           f"- **Same recording in several files: {len(groups)} groups, {extra} extra files ({gb:.1f} GB)**",
           f"- Same song in different versions (not duplicates): {len(others)} songs", "",
           "## How to read the duplicate groups", "",
           "The first file of each group is the suggested keeper (lossless before lossy, then bit rate, then the properly "
           "filed path). *In playlists* lists where each file is used: a file that is in a playlist has to be repointed to the "
           "keeper before it can be trashed, so nothing is trashed by this report.", "",
           "## Same recording, several files", ""]
    for g in groups:
        first = g[0]
        out.append(f"### {first['artist']} — {first['title']}")
        for i, r in enumerate(g):
            use = ", ".join(sorted(set(held.get(r["id"], [])))) or "no playlist"
            out.append(f"- {'**keep**' if i == 0 else 'extra '} `{r['path']}` · {r['suffix']} {r['bit_rate']} kbps · "
                       f"{mmss(r['duration'])} · album: {r['album'] or '—'} · in playlists: {use}")
        out.append("")
    out += ["## Same song, different versions (information)", ""]
    for members in others.values():
        m0 = members[0]
        out.append(f"- **{m0['artist']} — {m0['title']}**: " + "; ".join(
            f"{m['title']} ({mmss(m['duration'])}, {m['suffix']})" for m in members))
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--navidrome-db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "docs" / "duplicates-report.md")
    a = ap.parse_args(argv)
    rows, held = load(a.navidrome_db)
    text = render(rows, held)
    a.out.write_text(text, encoding="utf-8")
    print(f"wrote {a.out}: {text.splitlines()[5]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
