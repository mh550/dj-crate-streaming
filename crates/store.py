"""SQLite state for crates. Navidrome owns *playlists*, and each playlist's comment owns whether it is a crate
and its tier (D21, spec fact #6: `#crate`, `#tier:<t>`, read by crates.attrs); the `crates` table only caches
those, and reconcile rebuilds it from the comments. We own *what we know about each track's provisioning*.

Tables
  crates        one row per playlist that is or was a crate or tiered: the cached flag and tier
  crate_tracks  per (crate, song): last-seen library facts + provisioning status
  events        append-only log so the UI can show "what did the reconciler do"
  external_wanted  tracks wanted that aren't in Navidrome at all (seeded from Spotify etc.)
  settings      small key/value settings (the web client's stream tier)
  verifications the last download check per wanted id
  approvals     who allowed which download (D23); the worker consumes the unused ones
  previews      the last search-and-rank result per wanted id, so the Wanted tab can show the pick
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from sourcing.identity import lead_artist, loose
from sourcing.policy import DEFAULT_TIER, STREAM_DEFAULT, check_stream, check_tier

SCHEMA = """
CREATE TABLE IF NOT EXISTS crates (
  playlist_id   TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  enabled       INTEGER NOT NULL DEFAULT 0,      -- 1 = this playlist is a crate
  source        TEXT NOT NULL DEFAULT 'app',     -- 'comment' (cached from the playlist comment, D21) | 'app' (before M8)
  devices       TEXT NOT NULL DEFAULT '[]',      -- JSON list of device names (Phase 4)
  created_at    REAL NOT NULL,
  updated_at    REAL NOT NULL,
  last_reconciled_at REAL,
  tier          TEXT                             -- the comment's #tier:<t> (a cache); NULL = none
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
  playlist_id TEXT, position INTEGER,             -- import-playlist: where a later fetch inserts the track
  tier        TEXT NOT NULL DEFAULT 'crate',      -- quality tier it is sourced at (spec §1): low|medium|high|crate
  asked_artist TEXT, asked_title TEXT,            -- the names first asked for (Spotify), kept once Navidrome's replace them
  created_at  REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS imported_entries (     -- every song import-playlist ever added to a playlist,
  playlist_id TEXT NOT NULL, song_id TEXT NOT NULL, -- so a track Michael removes by hand is never re-added
  PRIMARY KEY (playlist_id, song_id)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS verifications (        -- the last download check per wanted id (spec §3a): JSON of
  song_id TEXT PRIMARY KEY, result TEXT NOT NULL, -- ok, tier, problems, warnings, measurements, file
  ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (            -- one row per "yes, download this" (D23); at most one unused per wanted id
  id INTEGER PRIMARY KEY, wanted_id TEXT NOT NULL, approved_by TEXT NOT NULL,  -- michael | policy:<name> | agent:<id>
  candidate TEXT, tier TEXT NOT NULL, ts REAL NOT NULL, used_at REAL, result TEXT);
CREATE TABLE IF NOT EXISTS previews (song_id TEXT PRIMARY KEY, result TEXT NOT NULL, ts REAL NOT NULL);
"""

STATUSES = ("ok", "needs_source", "sourcing", "verify", "failed", "removed", "review")   # review: a person must pick a version

# A filed download's path rides in its row's reason until a jobs table exists, in one of two shapes: a `verify`
# row's "filed as <rel> but Navidrome has not picked it up yet…" and, after sourcing.fetch.RECHECK_LIMIT misses,
# a `failed` row's "Navidrome never indexed <rel>; file is in the library". Both mean: the file is in the library,
# so the row is re-checked, never downloaded again. Parsed here only (fetch and find_external both need it).
_FILED = re.compile(r"filed as (.+?) but Navidrome|^Navidrome never indexed (.+); file is in the library$")


def filed_path(reason: str | None) -> str | None:
    """The library-relative path a row's reason says was filed, from either shape; None for any other reason."""
    m = _FILED.search(reason or "")
    return (m.group(1) or m.group(2)) if m else None


def never_indexed(rel) -> str:
    """The `failed` reason after the re-check limit; filed_path reads it back."""
    return f"Navidrome never indexed {rel}; file is in the library"


_loose = loose                    # identity owns "is this the same text" (accents ignored, "&" is "and")


def _ext_pk(ext_id: str) -> int:
    return int(ext_id[4:])          # "ext-<rowid>"


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
    tier: str | None = None             # the comment's #tier:<t>, cached

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> "Crate":
        return cls(r["playlist_id"], r["name"], bool(r["enabled"]), r["source"], json.loads(r["devices"]),
                   r["created_at"], r["updated_at"], r["last_reconciled_at"], r["tier"])


class CrateStore:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL") if self.path != ":memory:" else None
        self.db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Add columns introduced after a DB was created (CREATE IF NOT EXISTS does not alter)."""
        have = {r[1] for r in self.db.execute("PRAGMA table_info(external_wanted)")}
        for col, typ in (("playlist_id", "TEXT"), ("position", "INTEGER"), ("tier", "TEXT NOT NULL DEFAULT 'crate'"),
                         ("asked_artist", "TEXT"), ("asked_title", "TEXT")):
            if col not in have:
                self.db.execute(f"ALTER TABLE external_wanted ADD COLUMN {col} {typ}")
        if "tier" not in {r[1] for r in self.db.execute("PRAGMA table_info(crates)")}:
            self.db.execute("ALTER TABLE crates ADD COLUMN tier TEXT")
        self.db.commit()

    # --- crates
    def get(self, playlist_id: str) -> Crate | None:
        r = self.db.execute("SELECT * FROM crates WHERE playlist_id=?", (playlist_id,)).fetchone()
        return Crate.from_row(r) if r else None

    def all(self, enabled_only: bool = False) -> list[Crate]:
        q = "SELECT * FROM crates" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY name"
        return [Crate.from_row(r) for r in self.db.execute(q)]

    def set_enabled(self, playlist_id: str, name: str, enabled: bool, source: str = "app") -> Crate:
        """Write the flag directly. Only tests use it: the comment owns the flag (D21), so production code caches
        it through set_attrs, and the next reconcile overwrites whatever this wrote."""
        now = time.time()
        self.db.execute(
            "INSERT INTO crates(playlist_id,name,enabled,source,created_at,updated_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(playlist_id) DO UPDATE SET name=excluded.name, enabled=excluded.enabled, "
            "source=excluded.source, updated_at=excluded.updated_at",
            (playlist_id, name, int(enabled), source, now, now))
        self.log(playlist_id, None, "crate_on" if enabled else "crate_off", source)
        self.db.commit()
        return self.get(playlist_id)  # type: ignore[return-value]

    def set_attrs(self, playlist_id: str, name: str, crate: bool, tier: str | None) -> tuple[bool, str | None] | None:
        """Cache what the playlist's comment says (source 'comment'). Returns the OLD (crate, tier) when either
        changed, None otherwise. A playlist that is neither a crate nor tiered gets no row until it is one."""
        if tier is not None:
            check_tier(tier)
        c = self.get(playlist_id)
        old = (c.enabled, c.tier) if c else (False, None)
        if (crate, tier) == old:
            if c and c.name != name:
                self.db.execute("UPDATE crates SET name=? WHERE playlist_id=?", (name, playlist_id))
                self.db.commit()
            return None
        now = time.time()
        self.db.execute(
            "INSERT INTO crates(playlist_id,name,enabled,source,tier,created_at,updated_at) VALUES(?,?,?,'comment',?,?,?) "
            "ON CONFLICT(playlist_id) DO UPDATE SET name=excluded.name, enabled=excluded.enabled, "
            "source=excluded.source, tier=excluded.tier, updated_at=excluded.updated_at",
            (playlist_id, name, int(crate), tier, now, now))
        if crate != old[0]:
            self.log(playlist_id, None, "crate_on" if crate else "crate_off", "comment")
        if tier != old[1]:
            self.log(playlist_id, None, "tier", f"{old[1] or 'none'} → {tier or 'none'}")
        self.db.commit()
        return old

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
        out = {s: 0 for s in STATUSES if s not in ("removed", "review")}   # review is for imported wanted rows only
        for r in self.db.execute("SELECT status, COUNT(*) n FROM crate_tracks WHERE playlist_id=? AND status!='removed' GROUP BY status", (playlist_id,)):
            out[r["status"]] = r["n"]
        out["total"] = sum(out.values())
        return out

    def _crate_wanted(self, where: str, params: tuple = ()) -> list[dict]:
        """Crate rows grouped per song (a song in several crates is one entry with `crates` listed)."""
        out: dict[str, dict] = {}
        for r in self.db.execute(
                "SELECT t.*, c.name AS crate_name FROM crate_tracks t JOIN crates c USING(playlist_id) "
                f"WHERE c.enabled=1 AND {where} ORDER BY c.name, t.position", params):
            d = dict(r); name = d.pop("crate_name")
            out.setdefault(d["song_id"], {**d, "crates": [], "tier": DEFAULT_TIER})["crates"].append(name)   # a crate is crate
        return list(out.values())

    def wanted(self) -> list[dict]:
        """Every track across enabled crates that still needs a file, plus external rows — the sourcing queue.
        Rows in progress (`sourcing`, `verify`) are listed too, so none is invisible; the web client shows them
        with their status and reason and offers no Preview/Approve for them."""
        live = "('needs_source','failed','sourcing','verify')"
        ext = self.db.execute(f"SELECT * FROM external_wanted WHERE status IN {live} ORDER BY id")
        rows = self._crate_wanted(f"t.status IN {live}") + [self._ext_row(r) for r in ext]
        checks = dict(self.db.execute("SELECT song_id, result FROM verifications").fetchall())   # parse only rows shown
        previews = dict(self.db.execute("SELECT song_id, result FROM previews").fetchall())
        for row in rows:
            row["verify"] = json.loads(checks[row["song_id"]]) if row["song_id"] in checks else None
            row["preview"] = json.loads(previews[row["song_id"]]) if row["song_id"] in previews else None
            row["approval"] = self.approval(row["song_id"])
            row["filed"] = filed_path(row.get("reason")) is not None   # in the library already: re-check, never download
        return rows

    def verify_ids(self, updated_before: float | None = None) -> list[str]:
        """Wanted ids (crate songs in enabled crates, then `ext-N`) whose file is filed but not yet seen by
        Navidrome: the worker re-checks these without downloading again. With `updated_before`, only rows last
        updated before that time (the worker's re-check throttle: each re-check rewrites the reason)."""
        cut = float("inf") if updated_before is None else updated_before
        crate = [r[0] for r in self.db.execute(
            "SELECT DISTINCT t.song_id FROM crate_tracks t JOIN crates c USING(playlist_id) "
            "WHERE c.enabled=1 AND t.status='verify' AND t.updated_at <= ? ORDER BY t.song_id", (cut,))]
        ext = [f"ext-{r[0]}" for r in self.db.execute(
            "SELECT id FROM external_wanted WHERE status='verify' AND updated_at <= ? ORDER BY id", (cut,))]
        return crate + ext

    def find_wanted(self, song_id: str) -> dict | None:
        """One wanted-shaped row for this id whatever its status."""
        if song_id.startswith("ext-"):
            return self.external(song_id)
        return (self._crate_wanted("t.song_id=? AND t.status!='removed'", (song_id,)) or [None])[0]

    def set_wanted_status(self, song_id: str, status: str, reason: str | None = None) -> None:
        """Status for a wanted id: the external row, or every live row of that song in an enabled crate."""
        if song_id.startswith("ext-"):
            self.set_external_status(song_id, status, reason)
        else:
            for (pl,) in self.db.execute(
                    "SELECT t.playlist_id FROM crate_tracks t JOIN crates c USING(playlist_id) "
                    "WHERE c.enabled=1 AND t.song_id=? AND t.status!='removed' ORDER BY c.name", (song_id,)).fetchall():
                self.set_track_status(pl, song_id, status, reason)
        self.commit()

    def set_wanted_names(self, wanted_id: str, artist: str, title: str) -> bool:
        """Copy the names Navidrome shows for the filed song onto the wanted row; True when they changed.

        An external row keeps the names it was first asked for in asked_artist/asked_title, so re-seeding the
        same Spotify playlist still finds it (find_external). A crate row's names are that song's live rows."""
        old = self.find_wanted(wanted_id)
        if old is None or ((old.get("artist") or ""), old["title"]) == (artist, title):
            return False
        now = time.time()
        if wanted_id.startswith("ext-"):
            self.db.execute("UPDATE external_wanted SET asked_artist=COALESCE(asked_artist, artist), "
                            "asked_title=COALESCE(asked_title, title), artist=?, title=?, updated_at=? WHERE id=?",
                            (artist, title, now, _ext_pk(wanted_id)))
        else:
            self.db.execute("UPDATE crate_tracks SET artist=?, title=?, updated_at=? WHERE song_id=? AND status!='removed'",
                            (artist, title, now, wanted_id))
        self.log(None, wanted_id, "renamed", f"{old.get('artist') or ''} – {old['title']} → {artist} – {title}")
        self.commit()
        return True

    def set_verification(self, song_id: str, result: dict) -> None:
        """Keep the last download check for a wanted id (crate or external), replacing the previous one."""
        self.db.execute("INSERT INTO verifications(song_id, result, ts) VALUES(?,?,?) ON CONFLICT(song_id) DO UPDATE "
                        "SET result=excluded.result, ts=excluded.ts", (song_id, json.dumps(result), time.time()))
        self.commit()

    def verification(self, song_id: str) -> dict | None:
        r = self.db.execute("SELECT result FROM verifications WHERE song_id=?", (song_id,)).fetchone()
        return json.loads(r[0]) if r else None

    def set_preview(self, wanted_id: str, result: dict) -> None:
        """Keep the last search-and-rank result for a wanted id, replacing the previous one."""
        self.db.execute("INSERT INTO previews(song_id, result, ts) VALUES(?,?,?) ON CONFLICT(song_id) DO UPDATE "
                        "SET result=excluded.result, ts=excluded.ts", (wanted_id, json.dumps(result), time.time()))
        self.commit()

    def preview(self, wanted_id: str) -> dict | None:
        r = self.db.execute("SELECT result FROM previews WHERE song_id=?", (wanted_id,)).fetchone()
        return json.loads(r[0]) if r else None

    # --- approvals (D23): the only thing that lets the worker download
    @staticmethod
    def _approval_row(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["candidate"] = json.loads(d["candidate"]) if d["candidate"] else None
        return d

    def approve(self, wanted_id: str, approved_by: str, candidate: dict | None, tier: str) -> int:
        """Record an approval and return its id. An earlier unused one for the same row is superseded, so at
        most one is pending per row. The event names the file, never the peer."""
        now = time.time()
        cur = self.db.execute("INSERT INTO approvals(wanted_id, approved_by, candidate, tier, ts) VALUES(?,?,?,?,?)",
                              (wanted_id, approved_by, json.dumps(candidate) if candidate else None, tier, now))
        new = cur.lastrowid
        self.db.execute("UPDATE approvals SET used_at=?, result=? WHERE wanted_id=? AND used_at IS NULL AND id!=?",
                        (now, f"superseded by #{new}", wanted_id, new))
        detail = f"{approved_by} at {tier}" + (f": {candidate.get('basename') or ''}" if candidate else "")
        self.log(None, wanted_id, "approved", detail)
        self.db.commit()
        return new

    def pending_approvals(self) -> list[dict]:
        return [self._approval_row(r) for r in self.db.execute("SELECT * FROM approvals WHERE used_at IS NULL ORDER BY id")]

    def claim_approval(self, approval_id: int) -> bool:
        """Take an approval for download: True only for the caller that finds it still unused (the conditional
        UPDATE is the claim, so a stale snapshot, a superseded approval or a second worker gets False)."""
        cur = self.db.execute("UPDATE approvals SET used_at=?, result='started' WHERE id=? AND used_at IS NULL",
                              (time.time(), approval_id))
        self.db.commit()
        return cur.rowcount == 1

    def recover_interrupted(self) -> list[str]:
        """After a worker (re)start: an approval still `started` belongs to a fetch that was killed (SIGTERM on
        `docker compose stop`), so its record says so (used_at kept: it was spent) and its row, if still
        `sourcing`, becomes `failed` so it shows in the queue to approve again. A `verify` row keeps its status:
        its file is in the library and the re-check finds it. Returns the wanted ids, in approval order."""
        why = "interrupted: worker restarted"
        ids = []
        for aid, wanted_id in self.db.execute("SELECT id, wanted_id FROM approvals WHERE result='started' ORDER BY id").fetchall():
            self.db.execute("UPDATE approvals SET result=? WHERE id=?", (why, aid))
            row = self.find_wanted(wanted_id)
            if row is not None and row["status"] == "sourcing":
                self.set_wanted_status(wanted_id, "failed", why)
            self.log(None, wanted_id, "interrupted", f"approval #{aid}")
            ids.append(wanted_id)
        self.db.commit()
        return ids

    def mark_approval_used(self, approval_id: int, result: str) -> None:
        self.db.execute("UPDATE approvals SET used_at=?, result=? WHERE id=?", (time.time(), result, approval_id))
        self.db.commit()

    def approval(self, wanted_id: str) -> dict | None:
        """The latest approval for a wanted id, used or not."""
        r = self.db.execute("SELECT * FROM approvals WHERE wanted_id=? ORDER BY id DESC LIMIT 1", (wanted_id,)).fetchone()
        return self._approval_row(r) if r else None

    # --- external wanted (not in Navidrome at all; seeded from Spotify etc.)
    def find_external(self, artist: str, title: str) -> dict | None:
        """A live (not failed) external row for the same lead artist/title, ignoring case and punctuation. A row
        renamed from Navidrome (set_wanted_names) also matches the names it was first asked for. A failed row
        whose file was filed (filed_path) counts as live: re-seeding must not queue a second download of it."""
        def k(a, t):                     # lead artists: an old "Chic feat. Nile Rodgers" row is a "Chic" ask
            return _loose(lead_artist(a)) + "|" + _loose(t)
        key = k(artist, title)
        for r in self.db.execute("SELECT * FROM external_wanted"):
            if r["status"] == "failed" and filed_path(r["reason"]) is None:
                continue
            asked = k(r["asked_artist"], r["asked_title"]) if r["asked_title"] is not None else None
            if key in (k(r["artist"], r["title"]), asked):
                return self._ext_row(r)
        return None

    def add_external_wanted(self, artist: str, title: str, album: str | None = None, duration_s: float | None = None,
                            year: int | None = None, source: str | None = None,
                            playlist_id: str | None = None, position: int | None = None, tier: str | None = None,
                            default_tier: str = DEFAULT_TIER) -> str:
        """Returns the existing id when the same artist/title is already queued (re-running a seed is a no-op);
        a playlist position or a tier, when given, is (re)recorded on that row. A new row without a tier gets
        default_tier (crate; imports pass medium, D15)."""
        check_tier(tier or check_tier(default_tier))
        existing = self.find_external(artist, title)
        if existing:
            if playlist_id is not None:
                self.db.execute("UPDATE external_wanted SET playlist_id=?, position=?, updated_at=? WHERE id=?",
                                (playlist_id, position, time.time(), _ext_pk(existing["song_id"])))
            if tier is not None:
                self.set_external_tier(existing["song_id"], tier)
            return existing["song_id"]
        return self._insert_external(artist, title, album, duration_s, year, source, playlist_id, position, tier or default_tier)

    def set_external_tier(self, ext_id: str, tier: str) -> None:
        """Change the tier an external row is sourced at; logged when it changes."""
        old = self.external(ext_id)["tier"]
        if check_tier(tier) != old:
            self.db.execute("UPDATE external_wanted SET tier=?, updated_at=? WHERE id=?", (tier, time.time(), _ext_pk(ext_id)))
            self.log(None, ext_id, "tier", f"{old} → {tier}")

    def _insert_external(self, artist, title, album, duration_s, year, source, playlist_id, position, tier) -> str:
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO external_wanted(artist,title,album,year,duration,source,playlist_id,position,tier,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (artist, title, album, year, int(duration_s) if duration_s else None, source, playlist_id, position, tier, now, now))
        self.log(None, f"ext-{cur.lastrowid}", "wanted", f"{artist} — {title}")
        return f"ext-{cur.lastrowid}"

    def imported(self, playlist_id: str) -> set[str]:
        return {r[0] for r in self.db.execute("SELECT song_id FROM imported_entries WHERE playlist_id=?", (playlist_id,))}

    def mark_imported(self, playlist_id: str, song_ids) -> None:
        self.db.executemany("INSERT OR IGNORE INTO imported_entries(playlist_id, song_id) VALUES(?,?)",
                            [(playlist_id, s) for s in song_ids])

    def external_for_playlist(self, playlist_id: str) -> list[dict]:
        return [self._ext_row(r) for r in self.db.execute(
            "SELECT * FROM external_wanted WHERE playlist_id=? ORDER BY position, id", (playlist_id,))]

    def external_ids_at_tier(self, tier: str) -> list[str]:
        return [self._ext_row(r)["song_id"] for r in self.db.execute(
            "SELECT * FROM external_wanted WHERE tier=? ORDER BY id", (check_tier(tier),))]

    def external_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM external_wanted").fetchone()[0]

    def external(self, ext_id: str) -> dict | None:
        r = self.db.execute("SELECT * FROM external_wanted WHERE id=?", (_ext_pk(ext_id),)).fetchone()
        return self._ext_row(r) if r else None

    def set_external_status(self, ext_id: str, status: str, reason: str | None = None) -> None:
        assert status in STATUSES, status
        self.db.execute("UPDATE external_wanted SET status=?, reason=?, updated_at=? WHERE id=?",
                        (status, reason, time.time(), _ext_pk(ext_id)))
        self.log(None, ext_id, "status", status)

    @staticmethod
    def _ext_row(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["song_id"] = f"ext-{d.pop('id')}"
        d["crates"], d["external"] = [], True
        return d

    # --- settings
    def stream_tier(self) -> str:
        """The web client's stream tier (spec §1 "Stream", D19); "server" (Navidrome's player profile decides) until one is chosen."""
        r = self.db.execute("SELECT value FROM settings WHERE key='stream_tier'").fetchone()
        return r[0] if r else STREAM_DEFAULT

    def set_stream_tier(self, tier: str) -> None:
        self.db.execute("INSERT INTO settings(key, value) VALUES('stream_tier', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (check_stream(tier),))
        self.db.commit()

    # --- events
    def log(self, playlist_id: str | None, song_id: str | None, kind: str, detail: str | None = None) -> None:
        self.db.execute("INSERT INTO events(ts,playlist_id,song_id,kind,detail) VALUES(?,?,?,?,?)",
                        (time.time(), playlist_id, song_id, kind, detail))

    def log_once(self, playlist_id: str | None, kind: str, detail: str) -> None:
        """Log unless the latest `kind` event for this playlist says the same: reconcile runs every few minutes,
        and a standing problem must not bury the rest of the log."""
        last = self.db.execute("SELECT detail FROM events WHERE playlist_id IS ? AND kind=? ORDER BY id DESC LIMIT 1",
                               (playlist_id, kind)).fetchone()
        if not last or last["detail"] != detail:
            self.log(playlist_id, None, kind, detail)

    def events(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))]

    def commit(self) -> None:
        self.db.commit()
