"""SQLite state for crates. Navidrome owns *playlists*, and each playlist's comment owns whether it is a crate
and its tier (D21, spec fact #6: `#crate`, `#tier:<t>`, read by crates.attrs); the `crates` table only caches
those, and reconcile rebuilds it from the comments. We own *what we know about each track's provisioning*.

Tables
  crates        one row per playlist that is or was a crate or tiered: the cached flag and tier
  crate_tracks  per (tiered playlist, song): last-seen library facts + provisioning status (the name predates
                tiers: every playlist with an effective tier has rows, not only crates)
  events        append-only log so the UI can show "what did the reconciler do"
  external_wanted  tracks wanted that aren't in Navidrome at all (seeded from Spotify etc.)
  settings      small key/value settings (the web client's stream tier)
  verifications the last download check per wanted id
  approvals     who allowed which download (D23); the worker consumes the unused ones
  previews      the last search-and-rank result per wanted id, so the Wanted tab can show the pick
  replacements  copy replacements (sourcing.replace): old and new song and path, recorded before the first step,
                and the step reached, so a crash at any step is resumed by the worker, never forgotten
  proposals     questions about one playlist slot (crates.proposals, D23): "replace X with Y in P at n?". Not
                approvals: an approval licenses a download the worker consumes; a proposal's yes edits one slot
                and downloads nothing, so no reader of approvals can mistake one for the other
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from sourcing.identity import lead_artist, loose
from sourcing.policy import DEFAULT_TIER, STREAM_DEFAULT, check_stream, check_tier, max_tier

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
  library_song_id TEXT,                           -- the Navidrome song filed for this row
  provisional INTEGER NOT NULL DEFAULT 0,         -- 1: this row's file is (or is being fetched as) play-now's fast
                                                  -- low copy, never its final file; the upgrade waits for approval
  created_at  REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS imported_entries (     -- every song import-playlist ever added to a playlist,
  playlist_id TEXT NOT NULL, song_id TEXT NOT NULL, -- so a track Michael removes by hand is never re-added
  PRIMARY KEY (playlist_id, song_id)
);
CREATE TABLE IF NOT EXISTS imported_playlists (   -- playlists import-playlist made or adopted (D33; was #imported)
  playlist_id TEXT PRIMARY KEY, name TEXT,        -- name: as last imported (for `imported list` only)
  source TEXT,                                    -- the import's source text, or 'migrated' (N2-03)
  imported_at REAL                                -- first recorded
);
CREATE TABLE IF NOT EXISTS import_order (         -- every row of a playlist's last real import, Spotify order (N4)
  playlist_id TEXT NOT NULL, position INTEGER NOT NULL,   -- Row.position (1-based)
  song_id TEXT,                                   -- the Navidrome song the row matched, or NULL
  wanted_id TEXT,                                 -- the ext-N row it queued (missing / ambiguous), or NULL
  PRIMARY KEY (playlist_id, position)
);
CREATE TABLE IF NOT EXISTS placements (           -- one per (wanted row, playlist), ever (N4, M9 §1; crates.placement)
  wanted_id TEXT NOT NULL, playlist_id TEXT NOT NULL,
  song_id TEXT,                                   -- the song placed (or tried)
  state TEXT NOT NULL,                            -- open | writing (edit sent, not yet confirmed) | done | given_up
  attempts INTEGER NOT NULL DEFAULT 0,            -- counted failures toward crates.placement.PLACE_LIMIT
  detail TEXT, updated_at REAL NOT NULL,
  PRIMARY KEY (wanted_id, playlist_id)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS verifications (        -- the last download check per wanted id (spec §3a): JSON of
  song_id TEXT PRIMARY KEY, result TEXT NOT NULL, -- ok, tier, problems, warnings, measurements, file
  ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (            -- one row per "yes, download this" (D23); at most one unused per wanted id
  id INTEGER PRIMARY KEY, wanted_id TEXT NOT NULL, approved_by TEXT NOT NULL,  -- michael | policy:<name> | agent:<id>
  candidate TEXT, tier TEXT NOT NULL, ts REAL NOT NULL, used_at REAL, result TEXT,
  purpose TEXT NOT NULL DEFAULT 'download');      -- download | play-now (D20: one fast provisional copy at `tier`)
CREATE TABLE IF NOT EXISTS previews (song_id TEXT PRIMARY KEY, result TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS replacements (         -- one per copy replacement (sourcing.replace)
  id INTEGER PRIMARY KEY, wanted_id TEXT NOT NULL,
  old_song_id TEXT NOT NULL, new_song_id TEXT NOT NULL,
  old_path TEXT NOT NULL, new_path TEXT NOT NULL,  -- library-relative; recorded before the first step
  reference TEXT,                                  -- JSON {path, size, mtime_ns}: the file verify compared
  state TEXT NOT NULL,                             -- repoint | trash | scan | done | blocked
  detail TEXT, trash_path TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS proposals (            -- one question per playlist slot (crates.proposals)
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL,      -- version_swap | unproven_copy
  playlist_id TEXT NOT NULL, position INTEGER NOT NULL,   -- 0-based index in getPlaylist when proposed
  old_song_id TEXT NOT NULL, new_song_id TEXT NOT NULL,
  summary TEXT NOT NULL,                           -- what Michael reads: playlist, slot, both titles and lengths
  wanted_id TEXT,                                  -- unproven_copy: the row that is `review` until answered
  new_path TEXT,                                   -- the new song's library path when proposed (a decline names it)
  old_name TEXT, new_name TEXT,                    -- "Artist – Title" when proposed: results name songs, not ids
  created_at REAL NOT NULL,
  decided_by TEXT, decided_at REAL,                -- michael | policy:<name> | agent:<id> (as approvals)
  decision TEXT, result TEXT);                     -- accepted | declined | stale; result: what happened
"""

REPLACEMENT_OPEN = ("repoint", "trash", "scan")
APPROVAL_PURPOSES = ("download", "play-now")       # play-now (D20): one fast provisional copy, scored at its tier    # the worker advances these; done and blocked are final

PROPOSAL_KINDS = ("version_swap", "unproven_copy")
DECISIONS = ("accepted", "declined", "stale")
DECIDERS = re.compile(r"michael|(?:policy|agent):\S+")     # the approver vocabulary (approvals.approved_by)



class ProposalDecided(ValueError):
    """The proposal is answered already (maybe by another process meanwhile); nothing was recorded."""


class PlayNowRefused(ValueError):
    """A play-now approval was not recorded: the row already has an approval waiting or being fetched (a double
    tap, a second device, another process). Nothing was written."""


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


# One open request per song (D20 ruling): a playlist row whose song is play-now's provisional copy, while that copy's
# upgrade (the external row) is in flight, is held in `review` with this reason. Not in flight itself: every reconcile
# judges it again, and once the external row is done the row gets its own verdict.
_HELD = re.compile(r"^upgrade in flight as (ext-\d+)$")


def held_reason(ext_id: str) -> str:
    return f"upgrade in flight as {ext_id}"


def held_by(reason: str | None) -> str | None:
    """The external row a held playlist row waits for (held_reason), else None."""
    m = _HELD.match(reason or "")
    return m.group(1) if m else None


def in_flight(status: str, reason: str | None) -> bool:
    """A row reconcile must not touch, whatever its tier or verdict: a download under way (`sourcing`), a filed file
    Navidrome has not indexed (`verify`, or `failed` with a filed path), a question for Michael (`review`, except a
    row held for an upgrade in flight: held_reason). Its playlist losing its tier does not remove it either: fetch
    must still reach it to finish."""
    return (status in ("sourcing", "verify") or (status == "review" and held_by(reason) is None)
            or (status == "failed" and filed_path(reason) is not None))


# A `review` row is a question. Copy replacement (sourcing.replace / fetch) and proposals leave rows in `review` with
# one of these reasons when a better copy was filed but did not replace the old one; approving such a row is a fresh
# download attempt. Any other review reason (import-playlist's "ambiguous …": several library versions fit) waits
# for a pick between versions that already exist, and a download would not answer it.
RETRYABLE_REVIEW = re.compile(r"kept beside |declined replacement #\d+|replacement #\d+ not made:|filed beside ")


def retryable_review(reason: str | None) -> bool:
    """True when a `review` row's reason is one a replacement left, i.e. approving the row may download again.
    web/app.js repeats this test (RETRYABLE_REVIEW there) to decide which review rows offer Preview/Approve."""
    return bool(RETRYABLE_REVIEW.match(reason or ""))


def pick_token(candidate: dict) -> str:
    """An opaque name for a ranked candidate (D18): the web client sees this, never the peer, and approving by it
    resolves the full candidate from the preview kept server-side."""
    key = "\0".join(str(candidate.get(k) or "") for k in ("username", "filename", "size"))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# What leaves the server never names a Soulseek peer or a local absolute path (the containers' mounts): row responses
# go through public(), which drops every `username` key and every reference's `path`, and cuts the directories off
# any absolute path inside a string (a path in an error text keeps its basename). Relative library paths stay.
_ABS = re.compile(r"(?<![\w.:/\\])/(?:[^\s/'\"]+/)+")


def public(v):
    """`v` (a wanted row, an approval, a preview) as the HTTP API may show it; see _ABS."""
    if isinstance(v, str):
        return _ABS.sub("", v)
    if isinstance(v, dict):
        out = {k: public(x) for k, x in v.items() if k != "username"}
        if isinstance(out.get("reference"), dict):
            out["reference"].pop("path", None)
        return out
    if isinstance(v, list):
        return [public(x) for x in v]
    return v


def never_indexed(rel) -> str:
    """The `failed` reason after the re-check limit; filed_path reads it back."""
    return f"Navidrome never indexed {rel}; file is in the library"


_loose = loose                    # identity owns "is this the same text" (accents ignored, "&" is "and")

# A playlist is tiered when its comment makes it a crate or gives it a #tier: (the cache of both, D21).
TIERED = "(c.enabled=1 OR c.tier IS NOT NULL)"
# The rows fetch and the worker work on: those of tiered playlists, and in-flight ones whatever their playlist.
REACHABLE = f"({TIERED} OR in_flight(t.status, t.reason))"


def effective_tier(enabled: bool, tier: str | None) -> str | None:
    """A playlist's sourcing tier: crate when flagged, else its #tier:, else none (mirrors attrs.Attrs.effective)."""
    return DEFAULT_TIER if enabled else tier


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

    @property
    def effective(self) -> str | None:
        return effective_tier(self.enabled, self.tier)

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> "Crate":
        return cls(r["playlist_id"], r["name"], bool(r["enabled"]), r["source"], json.loads(r["devices"]),
                   r["created_at"], r["updated_at"], r["last_reconciled_at"], r["tier"])


class CrateStore:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.create_function("in_flight", 2, in_flight, deterministic=True)     # one rule for Python and SQL
        self.db.execute("PRAGMA journal_mode=WAL") if self.path != ":memory:" else None
        self.db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Add columns introduced after a DB was created (CREATE IF NOT EXISTS does not alter)."""
        have = {r[1] for r in self.db.execute("PRAGMA table_info(external_wanted)")}
        for col, typ in (("playlist_id", "TEXT"), ("position", "INTEGER"), ("tier", "TEXT NOT NULL DEFAULT 'crate'"),
                         ("asked_artist", "TEXT"), ("asked_title", "TEXT"), ("library_song_id", "TEXT"),
                         ("provisional", "INTEGER NOT NULL DEFAULT 0")):
            if col not in have:
                self.db.execute(f"ALTER TABLE external_wanted ADD COLUMN {col} {typ}")
        if "purpose" not in {r[1] for r in self.db.execute("PRAGMA table_info(approvals)")}:
            self.db.execute("ALTER TABLE approvals ADD COLUMN purpose TEXT NOT NULL DEFAULT 'download'")
        if "tier" not in {r[1] for r in self.db.execute("PRAGMA table_info(crates)")}:
            self.db.execute("ALTER TABLE crates ADD COLUMN tier TEXT")
        have = {r[1] for r in self.db.execute("PRAGMA table_info(proposals)")}
        for col in ("old_name", "new_name"):
            if col not in have:
                self.db.execute(f"ALTER TABLE proposals ADD COLUMN {col} TEXT")
        self.db.commit()

    # --- crates
    def get(self, playlist_id: str) -> Crate | None:
        r = self.db.execute("SELECT * FROM crates WHERE playlist_id=?", (playlist_id,)).fetchone()
        return Crate.from_row(r) if r else None

    def all(self, enabled_only: bool = False) -> list[Crate]:
        q = "SELECT * FROM crates" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY name"
        return [Crate.from_row(r) for r in self.db.execute(q)]

    def tiered(self) -> list[Crate]:
        """Playlists with an effective tier (crates and #tier: playlists), by name."""
        return [Crate.from_row(r) for r in self.db.execute(f"SELECT * FROM crates c WHERE {TIERED} ORDER BY name")]

    def playlist_tier(self, playlist_id: str | None) -> str | None:
        """The cached effective tier of a playlist; None for an untiered or unknown one."""
        c = self.get(playlist_id) if playlist_id else None
        return c.effective if c else None

    def song_tier(self, song_id: str) -> str | None:
        """Fact #7: the tier a song's file must reach, the highest effective tier of the tiered playlists holding it
        (a live row); None when no tiered playlist holds it."""
        return max_tier(*(effective_tier(bool(e), t) for e, t in self.db.execute(
            "SELECT c.enabled, c.tier FROM crate_tracks t JOIN crates c USING(playlist_id) "
            f"WHERE t.song_id=? AND t.status!='removed' AND {TIERED}", (song_id,))))

    def playlists_holding(self, song_ids) -> set[str]:
        """Tiered playlists with a live row for any of these songs."""
        ids = list(song_ids)
        if not ids:
            return set()
        return {r[0] for r in self.db.execute(
            "SELECT DISTINCT t.playlist_id FROM crate_tracks t JOIN crates c USING(playlist_id) "
            f"WHERE t.status!='removed' AND {TIERED} AND t.song_id IN ({','.join('?' * len(ids))})", ids)}

    def set_enabled(self, playlist_id: str, name: str, enabled: bool, source: str = "app") -> Crate:
        """Write the flag directly: the crates app's own switch (owner="app"). Under the earlier owner="comment"
        design (D21) only tests used it, since the next reconcile overwrote it from the comment."""
        now = time.time()
        self.db.execute(
            "INSERT INTO crates(playlist_id,name,enabled,source,created_at,updated_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(playlist_id) DO UPDATE SET name=excluded.name, enabled=excluded.enabled, "
            "source=excluded.source, updated_at=excluded.updated_at",
            (playlist_id, name, int(enabled), source, now, now))
        self.log(playlist_id, None, "crate_on" if enabled else "crate_off", source)
        self.db.commit()
        return self.get(playlist_id)  # type: ignore[return-value]

    def set_name(self, playlist_id: str, name: str) -> None:
        """Refresh the stored name of a playlist that already has a row (a rename in Navidrome); no row, no change."""
        c = self.get(playlist_id)
        if c and c.name != name:
            self.db.execute("UPDATE crates SET name=? WHERE playlist_id=?", (name, playlist_id))
            self.db.commit()

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
        # `review` rows count too (so the counts add up to the total) but, as before, the key appears only when there
        # is one: the GROUP BY below adds it.
        out = {s: 0 for s in STATUSES if s not in ("removed", "review")}
        for r in self.db.execute("SELECT status, COUNT(*) n FROM crate_tracks WHERE playlist_id=? AND status!='removed' GROUP BY status", (playlist_id,)):
            out[r["status"]] = r["n"]
        out["total"] = sum(out.values())
        return out

    def _crate_wanted(self, where: str, params: tuple = ()) -> list[dict]:
        """Tiered-playlist rows (and in-flight ones, see in_flight) grouped per song: `playlists` names their
        playlists, `crates` the crates among them, and `tier` is the song's derived tier (song_tier); an in-flight
        row no tiered playlist holds any more says crate (its download was chosen already; the tier only names it)."""
        out: dict[str, dict] = {}
        for r in self.db.execute(
                "SELECT t.*, c.name AS crate_name, c.enabled AS crate_on FROM crate_tracks t JOIN crates c "
                f"USING(playlist_id) WHERE {REACHABLE} AND {where} ORDER BY c.name, t.position", params):
            d = dict(r); name, on = d.pop("crate_name"), d.pop("crate_on")
            w = out.setdefault(d["song_id"], {**d, "crates": [], "playlists": [],
                                              "tier": self.song_tier(d["song_id"]) or DEFAULT_TIER})
            w["playlists"].append(name)
            if on:
                w["crates"].append(name)
        return list(out.values())

    def wanted(self) -> list[dict]:
        """Every track across tiered playlists that still needs a file, plus external rows — the sourcing queue.
        Rows in progress (`sourcing`, `verify`) and questions (`review`) are listed too, so none is invisible; the
        web client shows them with their status and reason, and offers Preview/Approve for a `review` row only when
        retryable_review says approving it may download again."""
        live = "('needs_source','failed','sourcing','verify','review')"
        ext = self.db.execute(f"SELECT * FROM external_wanted WHERE status IN {live} ORDER BY id")
        rows = self._crate_wanted(f"t.status IN {live}") + [self._ext_row(r) for r in ext]
        checks = dict(self.db.execute("SELECT song_id, result FROM verifications").fetchall())   # parse only rows shown
        previews = dict(self.db.execute("SELECT song_id, result FROM previews").fetchall())
        for row in rows:
            self._decorate(row, checks.get(row["song_id"]), previews.get(row["song_id"]))
        return rows

    def _decorate(self, row: dict, check: str | None, preview: str | None) -> dict:
        row["verify"] = json.loads(check) if check else None
        row["preview"] = json.loads(preview) if preview else None
        row["approval"] = self.approval(row["song_id"])
        row["filed"] = filed_path(row.get("reason")) is not None   # in the library already: re-check, never download
        return row

    def wanted_row(self, wanted_id: str) -> dict | None:
        """One row shaped like a wanted() entry (its last verification, preview and approval), whatever its status;
        None when unknown. The web client polls it after play-now until `library_song_id` names a song to play."""
        row = self.find_wanted(wanted_id)
        if row is None:
            return None
        one = "SELECT result FROM {} WHERE song_id=?"
        check = self.db.execute(one.format("verifications"), (wanted_id,)).fetchone()
        preview = self.db.execute(one.format("previews"), (wanted_id,)).fetchone()
        return self._decorate(row, check[0] if check else None, preview[0] if preview else None)

    def verify_ids(self, updated_before: float | None = None) -> list[str]:
        """Wanted ids (songs with a `verify` row in any playlist, then `ext-N`) whose file is filed but not yet seen by
        Navidrome: the worker re-checks these without downloading again. With `updated_before`, only rows last
        updated before that time (the worker's re-check throttle: each re-check rewrites the reason), except a play-now
        copy waiting to be listed: Michael pressed play, so it is re-checked on every tick."""
        cut = float("inf") if updated_before is None else updated_before
        crate = [r[0] for r in self.db.execute(
            "SELECT DISTINCT t.song_id FROM crate_tracks t JOIN crates c USING(playlist_id) "
            "WHERE t.status='verify' AND t.updated_at <= ? ORDER BY t.song_id", (cut,))]   # in flight: any playlist
        ext = [f"ext-{r[0]}" for r in self.db.execute(           # a play-now copy (provisional, no song yet) every tick
            "SELECT id FROM external_wanted WHERE status='verify' AND (updated_at <= ? "
            "OR (provisional=1 AND library_song_id IS NULL)) ORDER BY id", (cut,))]
        return crate + ext

    def find_wanted(self, song_id: str) -> dict | None:
        """One wanted-shaped row for this id whatever its status."""
        if song_id.startswith("ext-"):
            return self.external(song_id)
        return (self._crate_wanted("t.song_id=? AND t.status!='removed'", (song_id,)) or [None])[0]

    def set_wanted_status(self, song_id: str, status: str, reason: str | None = None) -> None:
        """Status for a wanted id: the external row, or every live row of that song in a tiered playlist, and its
        in-flight rows in any playlist (a crate turned off mid-download still gets its download's outcome)."""
        if song_id.startswith("ext-"):
            self.set_external_status(song_id, status, reason)
        else:
            for (pl,) in self.db.execute(
                    "SELECT t.playlist_id FROM crate_tracks t JOIN crates c USING(playlist_id) "
                    f"WHERE {REACHABLE} AND t.song_id=? AND t.status!='removed' ORDER BY c.name", (song_id,)).fetchall():
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

    def approve(self, wanted_id: str, approved_by: str, candidate: dict | None, tier: str,
                purpose: str = "download") -> int:
        """Record an approval and return its id. An earlier unused one for the same row is superseded, so at
        most one is pending per row. The event names the file, never the peer.

        A `play-now` approval (D20) never supersedes: it is recorded only while the row has no approval waiting or
        being fetched (`started`), and the check is part of the INSERT, so a double tap, a second device or another
        process on the same crates.db records one approval, never two (PlayNowRefused, nothing written)."""
        assert purpose in APPROVAL_PURPOSES, purpose
        now = time.time()
        args = (wanted_id, approved_by, json.dumps(candidate) if candidate else None, tier, now, purpose)
        if purpose == "play-now":
            cur = self.db.execute(
                "INSERT INTO approvals(wanted_id, approved_by, candidate, tier, ts, purpose) SELECT ?,?,?,?,?,? "
                "WHERE NOT EXISTS (SELECT 1 FROM approvals WHERE wanted_id=? AND (used_at IS NULL OR result='started'))",
                args + (wanted_id,))
            if cur.rowcount != 1:      # nothing inserted. End the write transaction the INSERT opened, or this
                self.db.commit()       # connection keeps crates.db's write lock; commit as approve always does
                raise PlayNowRefused(f"{wanted_id} has an approval waiting or being fetched already")
        else:
            cur = self.db.execute("INSERT INTO approvals(wanted_id, approved_by, candidate, tier, ts, purpose) "
                                  "VALUES(?,?,?,?,?,?)", args)
        new = cur.lastrowid
        self.db.execute("UPDATE approvals SET used_at=?, result=? WHERE wanted_id=? AND used_at IS NULL AND id!=?",
                        (now, f"superseded by #{new}", wanted_id, new))
        detail = f"{approved_by} at {tier}" + (" (play now)" if purpose == "play-now" else "") \
            + (f": {candidate.get('basename') or ''}" if candidate else "")
        self.log(None, wanted_id, "approved", detail)
        self.db.commit()
        return new

    def pending_approvals(self) -> list[dict]:
        """Unused approvals, play-now first (Michael is waiting to hear it), then in the order they were given."""
        return [self._approval_row(r) for r in self.db.execute(
            "SELECT * FROM approvals WHERE used_at IS NULL ORDER BY purpose='play-now' DESC, id")]

    def has_play_now(self) -> bool:
        """An unused play-now approval exists: the sleeping worker wakes for it."""
        return self.db.execute("SELECT 1 FROM approvals WHERE used_at IS NULL AND purpose='play-now' LIMIT 1"
                               ).fetchone() is not None

    def approval_in_progress(self, wanted_id: str) -> dict | None:
        """The approval of this row the worker has to act on: unused, or claimed and still being fetched."""
        r = self.db.execute("SELECT * FROM approvals WHERE wanted_id=? AND (used_at IS NULL OR result='started') "
                            "ORDER BY id DESC LIMIT 1", (wanted_id,)).fetchone()
        return self._approval_row(r) if r else None

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

    def mark_playlist_imported(self, playlist_id: str, name: str, source: str, detail: str | None = None) -> bool:
        """Record that import-playlist made (or adopted) this playlist (D33). The first record's source and time
        stay; a later call only refreshes the name. True when the row is new (then one `imported` event). The
        caller commits, like mark_imported."""
        new = not self.is_playlist_imported(playlist_id)
        self.db.execute("INSERT INTO imported_playlists(playlist_id, name, source, imported_at) VALUES(?,?,?,?) "
                        "ON CONFLICT(playlist_id) DO UPDATE SET name=excluded.name",
                        (playlist_id, name, source, time.time()))
        if new:
            self.log(playlist_id, None, "imported", detail or f"made by import-playlist: {source}")
        return new

    def forget_playlist(self, playlist_id: str) -> dict:
        """Delete what crates.db holds for a playlist Navidrome no longer has (N3, D43); the caller commits. Rows a
        download still has to finish wait: `sourcing`/`verify` ones and one with an approval waiting or being fetched,
        in crate_tracks or external_wanted (a `review` question or a `failed` filed row never ends on its own, so it
        does not wait). Every other crate_tracks row is deleted. While some wait, the `crates` row stays (fetch
        reaches its rows through it) but loses its flag and tier, so nothing counts the playlist as tiered; once none
        waits, it goes with the import rows (import_order and placements too, N4) and the problems setting. Open
        wanted rows become `removed` and keep playlist_id/position/tier as history, except one another playlist's
        import_order still names (N4: that playlist still wants it). Returns every row it changed as it was before (the
        caller's reverse log) and `live`/`kept` counts; proposals and events are left alone."""
        pid = (playlist_id,)
        if not self.db.in_transaction:      # fetch and the web write from other processes: lock before the first read
            self.db.execute("BEGIN IMMEDIATE")
        waits =("(status IN ('sourcing','verify') OR (status!='removed' AND EXISTS (SELECT 1 FROM approvals a "
                 "WHERE a.wanted_id={} AND (a.used_at IS NULL OR a.result='started'))))")
        crate_waits = waits.format("crate_tracks.song_id")
        dropped = [dict(r) for r in self.db.execute(
            f"SELECT * FROM crate_tracks WHERE playlist_id=? AND NOT {crate_waits} ORDER BY position", pid)]
        self.db.execute(f"DELETE FROM crate_tracks WHERE playlist_id=? AND NOT {crate_waits}", pid)
        kept = self.db.execute("SELECT COUNT(*) FROM crate_tracks WHERE playlist_id=?", pid).fetchone()[0]
        wanted_removed = []
        ext_waits = waits.format("'ext-' || external_wanted.id")
        for r in self.db.execute(f"SELECT *, {ext_waits} AS waits FROM external_wanted WHERE playlist_id=? ORDER BY id",
                                 pid).fetchall():
            r = dict(r)
            if r.pop("waits"):
                kept += 1
            elif r["status"] not in ("ok", "removed") and not any(
                    o["playlist_id"] != playlist_id for o in self.import_order_for(f"ext-{r['id']}")):
                wanted_removed.append(r)
                self.set_external_status(f"ext-{r['id']}", "removed", "playlist deleted")
        crate = self.db.execute("SELECT * FROM crates WHERE playlist_id=?", pid).fetchone()
        out = {"dropped": dropped, "live": sum(t["status"] != "removed" for t in dropped), "kept": kept,
               "crate": dict(crate) if crate else None, "imported_entries": [], "imported_playlist": None,
               "wanted_removed": wanted_removed, "problems": None,
               "import_order": [], "placements": []}
        if kept:
            if crate and (crate["enabled"] or crate["tier"] is not None):
                self.db.execute("UPDATE crates SET enabled=0, tier=NULL, updated_at=? WHERE playlist_id=?",
                                (time.time(), playlist_id))
            else:
                out["crate"] = None                     # unchanged
            return out
        out["imported_entries"] = sorted(self.imported(playlist_id))
        r = self.db.execute("SELECT * FROM imported_playlists WHERE playlist_id=?", pid).fetchone()
        out["imported_playlist"] = dict(r) if r else None
        out["import_order"] = self.import_order(playlist_id)
        out["placements"] = [dict(r) for r in self.db.execute(
            "SELECT * FROM placements WHERE playlist_id=? ORDER BY wanted_id", pid)]
        for table in ("crates", "imported_entries", "imported_playlists", "import_order", "placements"):
            self.db.execute(f"DELETE FROM {table} WHERE playlist_id=?", pid)
        key = (f"problems:attrs_problem:{playlist_id}",)
        r = self.db.execute("SELECT value FROM settings WHERE key=?", key).fetchone()
        out["problems"] = r[0] if r else None             # note_problems' value (a JSON list) for that key
        self.db.execute("DELETE FROM settings WHERE key=?", key)
        return out

    def record_import_order(self, playlist_id: str, rows: list[tuple[int, str | None, str | None]]) -> None:
        """Replace the playlist's import_order with `rows` of (position, song_id, wanted_id): all or nothing (a
        savepoint). Inside the caller's transaction the caller commits; outside one, this commits."""
        self.db.execute("SAVEPOINT import_order")
        try:
            self.db.execute("DELETE FROM import_order WHERE playlist_id=?", (playlist_id,))
            self.db.executemany("INSERT INTO import_order(playlist_id, position, song_id, wanted_id) VALUES(?,?,?,?)",
                                [(playlist_id, *r) for r in rows])
        except BaseException:
            if self.db.in_transaction:          # a disk-full or I/O error may have rolled it all back already
                self.db.execute("ROLLBACK TO import_order")
                self.db.execute("RELEASE import_order")
            raise
        self.db.execute("RELEASE import_order")

    def import_order(self, playlist_id: str) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM import_order WHERE playlist_id=? ORDER BY position", (playlist_id,))]

    def import_order_for(self, wanted_id: str) -> list[dict]:
        """Every playlist slot that queued this wanted row (a track wanted by two playlists has a row in each)."""
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM import_order WHERE wanted_id=? ORDER BY playlist_id, position", (wanted_id,))]

    def due_placements(self) -> list[dict]:
        """The (wanted row, playlist) pairs placement still has to do, derived from state alone (N4): an import_order
        row names the wanted row; that row is `ok` with its library song and not provisional; the song is not in the
        playlist's imported_entries (added, or removed after, already); no `done`/`given_up` placement. One per pair
        (its smallest position), in (playlist, position) order, with the playlist's imported name."""
        return [dict(r) for r in self.db.execute(
            "SELECT o.wanted_id, o.playlist_id, e.library_song_id AS song_id, MIN(o.position) AS position, ip.name "
            "FROM import_order o JOIN external_wanted e ON o.wanted_id = 'ext-' || e.id "
            "LEFT JOIN imported_playlists ip ON ip.playlist_id = o.playlist_id "
            "WHERE e.status='ok' AND e.library_song_id IS NOT NULL AND e.provisional=0 "
            "AND NOT EXISTS (SELECT 1 FROM imported_entries i WHERE i.playlist_id=o.playlist_id "
            "AND i.song_id=e.library_song_id) "
            "AND NOT EXISTS (SELECT 1 FROM placements p WHERE p.wanted_id=o.wanted_id AND p.playlist_id=o.playlist_id "
            "AND p.state IN ('done','given_up')) "
            "GROUP BY o.playlist_id, o.wanted_id ORDER BY o.playlist_id, MIN(o.position)")]

    def placement(self, wanted_id: str, playlist_id: str) -> dict | None:
        r = self.db.execute("SELECT * FROM placements WHERE wanted_id=? AND playlist_id=?",
                            (wanted_id, playlist_id)).fetchone()
        return dict(r) if r else None

    def note_placement(self, wanted_id: str, playlist_id: str, state: str, detail: str | None, *,
                       song_id: str | None = None, count: bool = True, now: float | None = None) -> None:
        """Upsert a placement's state; `attempts += 1` only when `count` (a transient error is not counted). The
        caller commits."""
        assert state in ("open", "writing", "done", "given_up"), state
        self.db.execute(
            "INSERT INTO placements(wanted_id, playlist_id, song_id, state, attempts, detail, updated_at) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(wanted_id, playlist_id) DO UPDATE SET "
            "song_id=COALESCE(excluded.song_id, song_id), state=excluded.state, attempts=attempts+excluded.attempts, "
            "detail=excluded.detail, updated_at=excluded.updated_at",
            (wanted_id, playlist_id, song_id, state, int(count), detail, time.time() if now is None else now))

    def repoint_song(self, old: str, new: str) -> dict:
        """Every playlist now holds `new` instead of `old` (a copy replacement, the duplicate cleanup): import orders
        name `new`, a playlist that ever had `old` added has `new` added too (removed stays removed; the old row
        stays), and filed external rows (`ok`, not provisional) name it, so placement finds its neighbours and
        never inserts the old copy (review N4-05 I2). Rows still in flight are their own flow's. Returns the counts
        of rows changed; the caller commits."""
        n = {"import_order": self.db.execute("UPDATE import_order SET song_id=? WHERE song_id=?", (new, old)).rowcount}
        n["imported_entries"] = self.db.execute(
            "INSERT OR IGNORE INTO imported_entries(playlist_id, song_id) "
            "SELECT playlist_id, ? FROM imported_entries WHERE song_id=?", (new, old)).rowcount
        n["external_wanted"] = self.db.execute(
            "UPDATE external_wanted SET library_song_id=? WHERE library_song_id=? AND status='ok' AND provisional=0",
            (new, old)).rowcount
        return n

    def is_playlist_imported(self, playlist_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM imported_playlists WHERE playlist_id=?", (playlist_id,)).fetchone() is not None

    def imported_playlists(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM imported_playlists ORDER BY name, playlist_id")]

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

    def derive_external_tiers(self) -> list[str]:
        """An external row of a tiered playlist takes that playlist's effective tier (D15/D21: the comment owns it,
        so `--tier` on a re-run and Michael's tier menu both land here). Rows in flight (`sourcing`, `verify`) keep
        theirs: their download was chosen at it. A row of an untiered playlist, or of none, keeps its stored tier.
        Each change is a `tier` event (set_external_tier); returns them as "<ext id>: <old> → <new>"."""
        out = []
        for r in self.db.execute(
                "SELECT e.id, e.tier AS old, c.enabled, c.tier FROM external_wanted e JOIN crates c USING(playlist_id) "
                f"WHERE {TIERED} AND e.status NOT IN ('sourcing','verify') ORDER BY e.id").fetchall():
            new = effective_tier(bool(r["enabled"]), r["tier"])
            if new != r["old"]:
                self.set_external_tier(f"ext-{r['id']}", new)
                out.append(f"ext-{r['id']}: {r['old']} → {new}")
        if out:
            self.commit()
        return out

    def set_library_song(self, ext_id: str, song_id: str) -> None:
        """The Navidrome song an external row's download became (fetch, once Navidrome lists it)."""
        self.db.execute("UPDATE external_wanted SET library_song_id=?, updated_at=? WHERE id=?",
                        (song_id, time.time(), _ext_pk(ext_id)))

    def set_external_song(self, ext_id: str, song_id: str | None, provisional: bool) -> None:
        """The library song an external row has and whether it is play-now's provisional copy (D20). Provisional:
        it plays, but it is not the row's file at its tier, so the row stays queued for its upgrade."""
        self.db.execute("UPDATE external_wanted SET library_song_id=?, provisional=?, updated_at=? WHERE id=?",
                        (song_id, int(provisional), time.time(), _ext_pk(ext_id)))

    def set_provisional(self, ext_id: str, provisional: bool) -> None:
        """What the download starting now is for (fetch sets it as the row enters `sourcing`): a filed file that
        Navidrome lists later is then known to be provisional even across a worker restart."""
        self.db.execute("UPDATE external_wanted SET provisional=? WHERE id=?", (int(provisional), _ext_pk(ext_id)))

    def is_provisional(self, song_id: str) -> bool:
        """`song_id` is play-now's provisional copy for some external row (verified at low only, D20)."""
        return self.db.execute("SELECT 1 FROM external_wanted WHERE library_song_id=? AND provisional=1 LIMIT 1",
                               (song_id,)).fetchone() is not None

    def upgrade_row(self, song_id: str) -> dict | None:
        """The open external row whose library song is `song_id` (play-now's provisional copy, waiting for its
        upgrade), if any."""
        r = self.db.execute("SELECT * FROM external_wanted WHERE library_song_id=? AND status NOT IN ('ok','removed') "
                            "ORDER BY id LIMIT 1", (song_id,)).fetchone()
        return self._ext_row(r) if r else None

    def upgrade_busy(self, row: dict) -> bool:
        """An external upgrade row that must finish on its own: in flight (in_flight, `review` included) or holding
        an approval waiting or being fetched (Michael's yes is kept, never superseded)."""
        return in_flight(row["status"], row.get("reason")) or self.approval_in_progress(row["song_id"]) is not None

    SUPERSEDED = "superseded by the playlist row — its tier applies"

    def supersede_upgrade(self, ext_id: str) -> None:
        """Close an external upgrade row because a tiered playlist holds its song: that playlist row is the one
        request for a better file now (fetch refuses a `removed` row)."""
        self.set_external_status(ext_id, "removed", self.SUPERSEDED)

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

    # --- replacements (sourcing.replace): a copy replacement's steps, durable so a crash is resumed
    @staticmethod
    def _replacement_row(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["reference"] = json.loads(d["reference"]) if d["reference"] else None
        return d

    def add_replacement(self, *, wanted_id: str, old_song_id: str, new_song_id: str, old_path: str, new_path: str,
                        reference: dict | None) -> int:
        """Record a replacement in state `repoint` before its first step, and commit it."""
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO replacements(wanted_id, old_song_id, new_song_id, old_path, new_path, reference, state, "
            "created_at, updated_at) VALUES(?,?,?,?,?,?,'repoint',?,?)",
            (wanted_id, old_song_id, new_song_id, old_path, new_path, json.dumps(reference) if reference else None,
             now, now))
        self.log(None, old_song_id, "replace", f"#{cur.lastrowid} repoint: {old_path} → {new_path}")
        self.db.commit()
        return cur.lastrowid

    def replacement(self, job_id: int) -> dict | None:
        r = self.db.execute("SELECT * FROM replacements WHERE id=?", (job_id,)).fetchone()
        return self._replacement_row(r) if r else None

    def open_replacements(self) -> list[dict]:
        return [self._replacement_row(r) for r in self.db.execute(
            f"SELECT * FROM replacements WHERE state IN ({','.join('?' * len(REPLACEMENT_OPEN))}) ORDER BY id",
            REPLACEMENT_OPEN)]

    def song_in_use(self, song_id: str) -> str | None:
        """What still works with this library song, so its file must stay (the duplicate cleanup's trash asks): an
        external row filed as it that is not finished or holds an approval in progress, an approval in progress
        of the song's own wanted row, or an open replacement naming it. None when nothing does."""
        for (pk, status) in self.db.execute("SELECT id, status FROM external_wanted WHERE library_song_id=? ORDER BY id",
                                            (song_id,)).fetchall():
            if status not in ("ok", "removed") or self.approval_in_progress(f"ext-{pk}") is not None:
                return f"ext-{pk}"
        if self.approval_in_progress(song_id) is not None:
            return f"approval of {song_id}"
        job = next((j for j in self.open_replacements() if song_id in (j["old_song_id"], j["new_song_id"])), None)
        return f"replacement #{job['id']}" if job else None

    def set_replacement(self, job_id: int, state: str, detail: str | None = None, **cols) -> None:
        """Move a replacement to `state` (also `trash_path`, the one other column a step sets) and commit. A
        `replace` event is logged when the state or the detail changes, so a waiting step is logged once, not
        on every worker tick."""
        assert state in REPLACEMENT_OPEN + ("done", "blocked"), state
        assert set(cols) <= {"trash_path"}, cols
        old = self.replacement(job_id)
        sets = ", ".join(f"{c}=?" for c in ("state", "detail", "updated_at", *cols))
        self.db.execute(f"UPDATE replacements SET {sets} WHERE id=?",
                        (state, detail, time.time(), *cols.values(), job_id))
        if (old["state"], old["detail"]) != (state, detail):
            self.log(None, old["old_song_id"], "replace", f"#{job_id} {state}" + (f": {detail}" if detail else ""))
        self.db.commit()

    # --- proposals (crates.proposals): questions about one playlist slot, answered by Michael
    def add_proposal(self, *, kind: str, playlist_id: str, position: int, old_song_id: str, new_song_id: str,
                     summary: str, wanted_id: str | None = None, new_path: str | None = None,
                     old_name: str | None = None, new_name: str | None = None) -> int | None:
        """Record an open proposal and return its id; None, recording nothing, when the same question was asked
        before: the same kind, playlist, slot, old and new song in any state, or the same swap in that playlist
        declined at any slot (Michael said no to it; the slot moving does not make it a new question)."""
        assert kind in PROPOSAL_KINDS, kind
        asked = self.db.execute(
            "SELECT 1 FROM proposals WHERE kind=? AND playlist_id=? AND old_song_id=? AND new_song_id=? "
            "AND (position=? OR decision='declined') LIMIT 1",
            (kind, playlist_id, old_song_id, new_song_id, position)).fetchone()
        if asked:
            return None
        cur = self.db.execute(
            "INSERT INTO proposals(kind, playlist_id, position, old_song_id, new_song_id, summary, wanted_id, new_path, "
            "old_name, new_name, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (kind, playlist_id, position, old_song_id, new_song_id, summary, wanted_id, new_path, old_name, new_name,
             time.time()))
        self.log(playlist_id, old_song_id, "proposal", f"#{cur.lastrowid} {kind}: {summary}")
        self.db.commit()
        return cur.lastrowid

    def proposals(self, open_only: bool = True) -> list[dict]:
        q = "SELECT * FROM proposals" + (" WHERE decision IS NULL" if open_only else "") + " ORDER BY id"
        return [dict(r) for r in self.db.execute(q)]

    def proposal(self, proposal_id: int) -> dict | None:
        r = self.db.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
        return dict(r) if r else None

    def decide(self, proposal_id: int, decision: str, decided_by: str, result: str) -> None:
        """Answer an open proposal and log a `proposal` event. ValueError for a decider outside the approver
        vocabulary; ProposalDecided for a proposal that is unknown or answered already, by another process too
        (the conditional UPDATE is the check)."""
        assert decision in DECISIONS, decision
        if not DECIDERS.fullmatch(decided_by or ""):
            raise ValueError(f"decided_by {decided_by!r}: michael, policy:<name> or agent:<id>")
        cur = self.db.execute("UPDATE proposals SET decision=?, decided_by=?, decided_at=?, result=? "
                              "WHERE id=? AND decision IS NULL", (decision, decided_by, time.time(), result, proposal_id))
        if cur.rowcount != 1:                      # nothing was changed
            raise ProposalDecided(f"proposal #{proposal_id} is unknown or already answered")
        p = self.proposal(proposal_id)
        self.log(p["playlist_id"], p["old_song_id"], "proposal", f"#{proposal_id} {decision} by {decided_by}: {result}")
        self.db.commit()

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

    def note_problems(self, playlist_id: str, kind: str, details: list[str]) -> list[str]:
        """Log each problem that is not already among this playlist's current ones, and remember the current set
        (a settings row). Reconcile runs every few minutes: a standing problem is logged once, not every run, and
        logged again only if it went away and came back. Returns the newly logged ones."""
        key = f"problems:{kind}:{playlist_id}"
        r = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        before = set(json.loads(r["value"])) if r else set()
        new = [d for d in dict.fromkeys(details) if d not in before]
        for d in new:
            self.log(playlist_id, None, kind, d)
        if details:
            self.db.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (key, json.dumps(sorted(set(details)))))
        elif r:
            self.db.execute("DELETE FROM settings WHERE key=?", (key,))
        return new

    def events(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))]

    def commit(self) -> None:
        self.db.commit()
