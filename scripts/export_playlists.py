"""Every Navidrome playlist as a portable .m3u8 file next to the music (spec §4.1).

    python3 scripts/export_playlists.py export     # write/refresh /srv/music/_playlists/<name>.m3u8
    python3 scripts/export_playlists.py check      # every entry resolves to a file, in the playlist's order

Reads navidrome.db read-only: the Subsonic `path` field is virtual (built from tags), so the real
file path exists only in media_file.path. Entries are relative to the .m3u8 file
("../Artist/Album/NN - Title.flac"), so any player opens them. Unchanged playlists are not
rewritten; files for playlists that no longer exist are reported, never deleted. Before a changed file is
rewritten, its previous text goes to _playlists/.history/<YYYY-MM-DD>/ (the day's first version; folders older than
30 days are pruned), the restore source for a playlist that lost entries (M9 §7). Navidrome is set to
ND_AUTOIMPORTPLAYLISTS=false so it does not turn these files back into duplicate playlists.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

DEFAULT_DB = Path("/srv/docker/navidrome/navidrome.db")
DEFAULT_MUSIC = Path("/srv/music")
HISTORY_DAYS = 30


@dataclass
class PL:
    id: str
    name: str
    entries: list[tuple[str, float, str, str]]       # (path relative to the music folder, duration, artist, title)


@dataclass
class Summary:
    written: int = 0
    unchanged: int = 0
    stale: list[str] = field(default_factory=list)   # .m3u8 files with no playlist behind them
    pruned: list[str] = field(default_factory=list)  # .history/<date> folders removed (older than HISTORY_DAYS)


def open_ro(db: Path) -> sqlite3.Connection:
    """navidrome.db, read-only: these scripts never write Navidrome's database."""
    return sqlite3.connect(f"{Path(db).resolve().as_uri()}?mode=ro", uri=True)


def load(db: Path) -> list[PL]:
    con = open_ro(db)
    try:
        pls = [PL(pid, name, []) for pid, name in con.execute("SELECT id, name FROM playlist ORDER BY name COLLATE NOCASE, id")]
        for pl in pls:
            pl.entries = [tuple(r) for r in con.execute(
                "SELECT m.path, m.duration, m.artist, m.title FROM playlist_tracks t JOIN media_file m ON m.id = t.media_file_id "
                "WHERE t.playlist_id = ? ORDER BY t.id", (pl.id,))]
        return pls
    finally:
        con.close()


def _path_ids(db: Path) -> dict[str, str]:
    con = open_ro(db)
    try:
        return {path: mid for mid, path in con.execute("SELECT id, path FROM media_file")}
    finally:
        con.close()


def playlist_health(db: Path) -> list[dict]:
    """Playlists holding entries getPlaylist hides (the playlist_edit skew condition): rows on a media_file that is
    missing or gone. One {"id", "name", "missing"} each, by name; empty when every entry plays (M9 §7)."""
    with closing(open_ro(db)) as con:
        rows = con.execute(
            "SELECT p.id, p.name, COUNT(*) FROM playlist p JOIN playlist_tracks t ON t.playlist_id = p.id"
            " LEFT JOIN media_file m ON m.id = t.media_file_id WHERE m.id IS NULL OR COALESCE(m.missing, 0)"
            " GROUP BY p.id, p.name ORDER BY p.name COLLATE NOCASE, p.id").fetchall()
    return [{"id": pid, "name": name, "missing": n} for pid, name, n in rows]


def file_name(name: str, taken: set[str]) -> str:
    """'playlists / perfect songs' → 'playlists - perfect songs.m3u8'; characters Windows/Samba refuse → '_'."""
    base = re.sub(r'[<>:"\\|?*\x00-\x1f]', "_", name.replace("/", "-")).strip().lstrip(".").strip() or "playlist"
    out, n = f"{base}.m3u8", 2
    while out.casefold() in taken:
        out, n = f"{base} ({n}).m3u8", n + 1
    taken.add(out.casefold())
    return out


def render(pl: PL, out_dir: Path, music_dir: Path) -> str:
    lines = ["#EXTM3U", f"#PLAYLIST:{pl.name}"]
    for path, duration, artist, title in pl.entries:
        rel = os.path.relpath(Path(music_dir) / path, Path(out_dir)).replace(os.sep, "/")
        lines += [f"#EXTINF:{round(duration or 0)},{artist} - {title}", rel]
    return "\n".join(lines) + "\n"


def _files(pls: list[PL]) -> list[tuple[PL, str]]:
    taken: set[str] = set()
    return [(pl, file_name(pl.name, taken)) for pl in pls]


def _write(target: Path, text: str) -> None:
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)                                  # atomic: a reader never sees half a playlist


def export(db: Path, music_dir: Path, out_dir: Path, today: date | None = None) -> Summary:
    out_dir, today = Path(out_dir), today or date.today()
    out_dir.mkdir(parents=True, exist_ok=True)
    s, produced = Summary(), set()
    for pl, fname in _files(load(db)):
        produced.add(fname)
        text, target = render(pl, out_dir, music_dir), out_dir / fname
        old = target.read_text(encoding="utf-8") if target.exists() else None
        if old == text:
            s.unchanged += 1
            continue
        kept = out_dir / ".history" / today.isoformat() / fname
        if old is not None and not kept.exists():       # the day's first version is the one kept
            kept.parent.mkdir(parents=True, exist_ok=True)
            _write(kept, old)
        _write(target, text)
        s.written += 1
    s.stale = sorted(p.name for p in out_dir.glob("*.m3u8") if p.name not in produced)
    s.pruned = prune_history(out_dir, today)
    return s


def prune_history(out_dir: Path, today: date, days: int = HISTORY_DAYS) -> list[str]:
    """Removes `.history/<YYYY-MM-DD>/` folders older than `days`; nothing else. A linked `.history` or day folder is
    left alone (never followed), as is anything not named like a date. Returns the removed folders' names."""
    hist, cutoff, gone = Path(out_dir) / ".history", today - timedelta(days=days), []
    if hist.is_symlink() or not hist.is_dir():
        return gone
    for d in sorted(hist.iterdir()):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name) or d.is_symlink() or not d.is_dir():
            continue
        try:
            dated = date.fromisoformat(d.name)
        except ValueError:                               # 2026-13-45
            continue
        if dated < cutoff:
            shutil.rmtree(d)                             # a real folder under .history; rmtree never follows links in it
            gone.append(d.name)
    return gone


def parse(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]


def check(db: Path, music_dir: Path, out_dir: Path) -> list[str]:
    """Problems, one line each; empty means every file matches Navidrome and every entry exists."""
    out_dir, music_dir = Path(out_dir), Path(music_dir).resolve()
    ids, problems = _path_ids(db), []
    for pl, fname in _files(load(db)):
        f = out_dir / fname
        if not f.exists():
            problems.append(f"{pl.name}: no file {fname} (run export)")
            continue
        got = []
        for entry in parse(f.read_text(encoding="utf-8")):
            real = (out_dir / entry).resolve()
            if not real.is_file():
                problems.append(f"{pl.name}: missing file {entry}")
            try:
                got.append(ids.get(real.relative_to(music_dir).as_posix()))
            except ValueError:                           # points outside the music folder
                got.append(None)
        want = [ids.get(path) for path, *_ in pl.entries]
        if got != want:
            problems.append(f"{pl.name}: stale ({fname} has {len(got)} entries, Navidrome {len(want)}"
                            f"{'' if len(got) != len(want) else ', order or tracks differ'}) — run export")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["export", "check"])
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--music", type=Path, default=DEFAULT_MUSIC)
    ap.add_argument("--out", type=Path, help="default: <music>/_playlists")
    a = ap.parse_args(argv)
    out = a.out or a.music / "_playlists"
    if a.cmd == "export":
        s = export(a.db, a.music, out)
        print(f"{s.written} written, {s.unchanged} unchanged → {out}")
        for name in s.stale:
            print(f"  stale (no playlist any more, kept): {name}")
        for name in s.pruned:
            print(f"  history pruned: .history/{name}")
        return 0
    problems = check(a.db, a.music, out)
    for p in problems:
        print(p)
    print("ok: every playlist file matches Navidrome and every entry exists" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
