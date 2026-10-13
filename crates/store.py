"""SQLite state for crates. Navidrome owns *playlists*; we own *which playlists are
crates* and *what we know about each track's provisioning*.

Tables
  crates        one row per playlist we have ever looked at as a crate
  crate_tracks  per (crate, song): last-seen library facts + provisioning status
  events        append-only log so the UI can show "what did the reconciler do"
  external_wanted  tracks wanted that aren't in Navidrome at all (seeded from Spotify etc.)
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS crates (
  playlist_id   TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  enabled       INTEGER NOT NULL DEFAULT 0,      -- 1 = this playlist is a crate
  source        TEXT NOT NULL DEFAULT 'app',     -- 'app' (toggled here) | 'comment' (#crate in Navidrome comment)
  devices       TEXT NOT NULL DEFAULT '[]',      -- JSON list of device names (Phase 4)
  created_at    REAL NOT NULL,
  updated_at    REAL NOT NULL,
  last_reconciled_at REAL
);
CREATE TABLE IF NOT EXISTS crate_tracks (
  playlist_id   TEXT NOT NULL,
  song_id       TEXT NOT NULL,
  position      INTEGER NOT NULL,
  title         TEXT, artist TEXT, album TEXT, year INTEGER,
  duration      INTEGER, suffix TEXT, bit_rate INTEGER, sample_rate INTEGER, bit_depth INTEGER,
  path          TEXT,
  status        TEXT NOT NULL,                   -- ok | needs_source | sourcing | verify | failed | removed
  reason        TEXT,                            -- human-readable why
  updated_at    REAL NOT NULL,
  PRIMARY KEY (playlist_id, song_id)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL, playlist_id TEXT, song_id TEXT, kind TEXT NOT NULL, detail TEXT
);
CREATE TABLE IF NOT EXISTS external_wanted (
  id          INTEGER PRIMARY KEY,
  artist      TEXT NOT NULL, title TEXT NOT NULL, album TEXT, year INTEGER, duration INTEGER,
  source      TEXT,                               -- e.g. spotify playlist URL
  status      TEXT NOT NULL DEFAULT 'needs_source',
  reason      TEXT,
  created_at  REAL NOT NULL, updated_at REAL NOT NULL
);
"""

STATUSES = ("ok", "needs_source", "sourcing", "verify", "failed", "removed")


def _loose(s: str | None) -> str:
    import re
    return re.sub(r"[^\w]+", "", (s or "").casefold())


@dataclass
class Crate:
    playlist_id: str
    name: str
    enabled: bool
    source: str
    devices: list[str]
    created_at: float
    updated_at: float
    last_reconciled_at: float | None

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> "Crate":
        return cls(r["playlist_id"], r["name"], bool(r["enabled"]), r["source"], json.loads(r["devices"]),
                   r["created_at"], r["updated_at"], r["last_reconciled_at"])


class CrateStore:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL") if self.path != ":memory:" else None
        self.db.executescript(SCHEMA)

    # --- crates
    def get(self, playlist_id: str) -> Crate | None:
        r = self.db.execute("SELECT * FROM crates WHERE playlist_id=?", (playlist_id,)).fetchone()
        return Crate.from_row(r) if r else None

    def all(self, enabled_only: bool = False) -> list[Crate]:
        q = "SELECT * FROM crates" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY name"
        return [Crate.from_row(r) for r in self.db.execute(q)]

    def set_enabled(self, playlist_id: str, name: str, enabled: bool, source: str = "app") -> Crate:
        now = time.time()
        self.db.execute(
            "INSERT INTO crates(playlist_id,name,enabled,source,created_at,updated_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(playlist_id) DO UPDATE SET name=excluded.name, enabled=excluded.enabled, "
            "source=excluded.source, updated_at=excluded.updated_at",
            (playlist_id, name, int(enabled), source, now, now))
        self.log(playlist_id, None, "crate_on" if enabled else "crate_off", source)
        self.db.commit()
        return self.get(playlist_id)  # type: ignore[return-value]

    def set_devices(self, playlist_id: str, devices: list[str]) -> None:
        self.db.execute("UPDATE crates SET devices=?, updated_at=? WHERE playlist_id=?", (json.dumps(devices), time.time(), playlist_id))
        self.db.commit()

    def mark_reconciled(self, playlist_id: str) -> None:
        self.db.execute("UPDATE crates SET last_reconciled_at=? WHERE playlist_id=?", (time.time(), playlist_id))
        self.db.commit()

    # --- tracks
    def upsert_track(self, playlist_id: str, song_id: str, position: int, facts: dict, status: str, reason: str | None) -> None:
        assert status in STATUSES, status
        self.db.execute(
            "INSERT INTO crate_tracks(playlist_id,song_id,position,title,artist,album,year,duration,suffix,bit_rate,"
            "sample_rate,bit_depth,path,status,reason,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(playlist_id,song_id) DO UPDATE SET position=excluded.position, title=excluded.title, "
            "artist=excluded.artist, album=excluded.album, year=excluded.year, duration=excluded.duration, "
            "suffix=excluded.suffix, bit_rate=excluded.bit_rate, sample_rate=excluded.sample_rate, "
            "bit_depth=excluded.bit_depth, path=excluded.path, status=excluded.status, reason=excluded.reason, "
            "updated_at=excluded.updated_at",
            (playlist_id, song_id, position, facts.get("title"), facts.get("artist"), facts.get("album"), facts.get("year"),
             facts.get("duration"), facts.get("suffix"), facts.get("bit_rate"), facts.get("sample_rate"),
             facts.get("bit_depth"), facts.get("path"), status, reason, time.time()))

    def set_track_status(self, playlist_id: str, song_id: str, status: str, reason: str | None = None) -> None:
        assert status in STATUSES, status
        self.db.execute("UPDATE crate_tracks SET status=?, reason=?, updated_at=? WHERE playlist_id=? AND song_id=?",
                        (status, reason, time.time(), playlist_id, song_id))
        self.log(playlist_id, song_id, "status", status)
        self.db.commit()

    def tracks(self, playlist_id: str, include_removed: bool = False) -> list[dict]:
        q = "SELECT * FROM crate_tracks WHERE playlist_id=?" + ("" if include_removed else " AND status!='removed'") + " ORDER BY position"
        return [dict(r) for r in self.db.execute(q, (playlist_id,))]

    def track_status_map(self, playlist_id: str) -> dict[str, dict]:
        return {t["song_id"]: t for t in self.tracks(playlist_id, include_removed=True)}

    def summary(self, playlist_id: str) -> dict[str, int]:
        out = {s: 0 for s in STATUSES if s != "removed"}
        for r in self.db.execute("SELECT status, COUNT(*) n FROM crate_tracks WHERE playlist_id=? AND status!='removed' GROUP BY status", (playlist_id,)):
            out[r["status"]] = r["n"]
        out["total"] = sum(out.values())
        return out

    def wanted(self) -> list[dict]:
        """Every track across enabled crates that still needs a file — the sourcing queue.
        One entry per song even if it sits in several crates (`crates` lists them)."""
        out: dict[str, dict] = {}
        for r in self.db.execute(
                "SELECT t.*, c.name AS crate_name FROM crate_tracks t JOIN crates c USING(playlist_id) "
                "WHERE c.enabled=1 AND t.status IN ('needs_source','failed') ORDER BY c.name, t.position"):
            d = dict(r)
            if d["song_id"] in out:
                out[d["song_id"]]["crates"].append(d["crate_name"])
            else:
                d["crates"] = [d.pop("crate_name")]
                out[d["song_id"]] = d
        ext = self.db.execute("SELECT * FROM external_wanted WHERE status IN ('needs_source','failed') ORDER BY id")
        return list(out.values()) + [self._ext_row(r) for r in ext]

    def find_wanted(self, song_id: str) -> dict | None:
        """One wanted-shaped row for this id whatever its status (crate rows: first enabled crate holding it)."""
        if song_id.startswith("ext-"):
            return self.external(song_id)
        rows = self.db.execute(
            "SELECT t.*, c.name AS crate_name FROM crate_tracks t JOIN crates c USING(playlist_id) "
            "WHERE c.enabled=1 AND t.song_id=? AND t.status!='removed' ORDER BY c.name", (song_id,)).fetchall()
        if not rows:
            return None
        d = dict(rows[0]); d["crates"] = [r["crate_name"] for r in rows]; d.pop("crate_name", None)
        return d

    # --- external wanted (not in Navidrome at all; seeded from Spotify etc.)
    def find_external(self, artist: str, title: str) -> dict | None:
        """A live (not failed) external row for the same artist/title, ignoring case and punctuation."""
        key = _loose(artist) + "|" + _loose(title)
        for r in self.db.execute("SELECT * FROM external_wanted WHERE status!='failed'"):
            if _loose(r["artist"]) + "|" + _loose(r["title"]) == key:
                return self._ext_row(r)
        return None

    def add_external_wanted(self, artist: str, title: str, album: str | None = None, duration_s: float | None = None,
                            year: int | None = None, source: str | None = None) -> str:
        """Returns the existing id when the same artist/title is already queued (re-running a seed is a no-op)."""
        existing = self.find_external(artist, title)
        if existing:
            return existing["song_id"]
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO external_wanted(artist,title,album,year,duration,source,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (artist, title, album, year, int(duration_s) if duration_s else None, source, now, now))
        self.log(None, f"ext-{cur.lastrowid}", "wanted", f"{artist} — {title}")
        return f"ext-{cur.lastrowid}"

    def external(self, ext_id: str) -> dict | None:
        r = self.db.execute("SELECT * FROM external_wanted WHERE id=?", (int(ext_id.split('-', 1)[1]),)).fetchone()
        return self._ext_row(r) if r else None

    def set_external_status(self, ext_id: str, status: str, reason: str | None = None) -> None:
        assert status in STATUSES, status
        self.db.execute("UPDATE external_wanted SET status=?, reason=?, updated_at=? WHERE id=?",
                        (status, reason, time.time(), int(ext_id.split('-', 1)[1])))
        self.log(None, ext_id, "status", status)

    @staticmethod
    def _ext_row(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["song_id"] = f"ext-{d.pop('id')}"
        d["crates"], d["external"] = [], True
        return d

    # --- events
    def log(self, playlist_id: str | None, song_id: str | None, kind: str, detail: str | None = None) -> None:
        self.db.execute("INSERT INTO events(ts,playlist_id,song_id,kind,detail) VALUES(?,?,?,?,?)",
                        (time.time(), playlist_id, song_id, kind, detail))

    def events(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))]

    def commit(self) -> None:
        self.db.commit()
