"""Reconcile: decide per track of each crate whether the library file is good enough or must be sourced, and keep
the record of which playlists are crates.

OWNER (2026-10-17 pivot, `owner="app"`, the default): the crates app owns the crate flag. Michael chooses which
playlists to keep synced in the crates web client; crates.db holds the answer and nothing is written to a playlist
comment or name. There are no listening tiers: a crate is judged at the one DJ-quality rule (deploy/policy.toml).
`owner="comment"` is the earlier design (D21, below), kept so its code and tests still run; nothing selects it
in production.

Fact #7: a track's tier is derived, never stored: the highest effective tier of the tiered playlists holding it
(crate > high > medium > low, deploy/policy.toml order). Each song is judged once, at that tier.

D21 (`owner="comment"`): the playlist's comment owns the crate flag and the tier (spec fact #6): `#crate` and `#tier:<t>`, read and
written only through crates.attrs, so Michael's own text survives byte for byte. crates.db caches them; when the
cache and a comment disagree, the comment wins and an `attrs` event records both. The setters (set_crate,
set_tier) write the comment first, read it back, and only then refresh the cache: a failed write or a crash in
between leaves the owner right and the cache rebuildable by the next run(), never the reverse. Clients that can
rename a playlist but not edit its comment (most phone apps) can mark it by name ("… [crate]" / "🎛 …"); such a
crate is turned off only by renaming it.

Two processes reconcile (the crates service on Michael's edits, the worker every WORKER_RECONCILE_S), so run(), the
setters and reconcile_playlist hold an flock on <crates.db dir>/reconcile.lock; after `lock_timeout_s` a caller
gets ReconcileBusy (the web client answers 503, the worker skips that run) having written nothing.
"""
from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from sourcing.policy import DEFAULT_POLICY, DEFAULT_TIER, TIERS, QualityPolicy, check_tier, max_tier
from sourcing.scorer import Wanted
from subsonic.client import Playlist, Song, SubsonicClient, SubsonicError
from . import attrs
from .store import CrateStore, held_reason, in_flight

# Name markers, for clients that can rename a playlist but not edit its comment
# (most phone apps). "Disco Edits [crate]" or "🎛 Disco Edits" both count.
NAME_MARKERS = ("[crate]", "🎛")

# More known playlists than this missing from one getPlaylists is not Michael deleting them (D43): nothing is dropped.
VANISH_LIMIT = 3


def default_owner() -> str:
    """Who owns the crate flag: "app" (crates.db; the default) or "comment" (D21), from $CRATES_OWNER."""
    owner = os.environ.get("CRATES_OWNER") or "app"
    if owner not in ("app", "comment"):
        raise ValueError(f"unknown CRATES_OWNER {owner!r} (app or comment)")
    return owner


class NameMarked(Exception):
    """The playlist's *name* carries a crate marker ([crate] / 🎛): only renaming it turns the crate off."""


class CommentNotKept(Exception):
    """The comment read back after our write does not say what we wrote (another client edited it in between,
    or Navidrome stored it differently). The cache is left alone."""


class ReconcileBusy(Exception):
    """Another process (or request) holds the reconcile lock past the timeout; nothing was written. Try again."""


@contextmanager
def hold_reconcile_lock(path: str | Path, timeout_s: float):
    """An exclusive flock on `path` for the block, waited for up to `timeout_s` seconds, else ReconcileBusy. The file
    is opened read-only (flock needs no write access), so the crates and worker containers can share it whichever
    user created it."""
    fd = os.open(path, os.O_RDONLY | os.O_CREAT, 0o644)
    try:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ReconcileBusy(f"another reconcile holds {path} (waited {timeout_s:g} s); try again") from None
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)                                     # closing releases the lock


def write_comment(client: SubsonicClient, pl: Playlist, new: str) -> Playlist:
    """The one comment writer: send ``new``, read the playlist back, raise CommentNotKept unless it holds exactly
    ``new``. Returns the playlist as read back. An update_playlist error propagates. Also used by the migration."""
    client.update_playlist(pl.id, comment=new)
    back = client.playlist(pl.id)
    if (back.comment or "") != new:
        raise CommentNotKept(f"{pl.name}: wrote comment {new!r} but Navidrome now has {back.comment or ''!r}; "
                             "nothing changed here, try again")
    return back


def has_crate_tag(comment: str | None) -> bool:
    return attrs.parse(comment).crate


def has_name_marker(name: str | None) -> bool:
    n = (name or "").strip().lower()
    return any(n.startswith(m) or n.endswith(m) for m in NAME_MARKERS)


def is_marked(name: str | None, comment: str | None) -> bool:
    """A playlist is marked as a crate from *outside this app* by comment or by name."""
    return has_crate_tag(comment) or has_name_marker(name)


def effective_tier(name: str | None, comment: str | None) -> str | None:
    """A playlist's sourcing tier from its own name and comment: crate when the comment or a name marker says so,
    else its #tier:, else none. The one reading of it (reconcile's cache, import-playlist's matching)."""
    a = attrs.parse(comment)
    return DEFAULT_TIER if a.crate or has_name_marker(name) else a.tier


def with_crate_tag(comment: str | None, on: bool) -> str:
    return attrs.write(comment, crate=on)


def judge(song: Song, policy: QualityPolicy = DEFAULT_POLICY) -> tuple[str, str]:
    """Is the file Navidrome has good enough for this tier? Uses only what Subsonic tells us
    (suffix, bitRate, samplingRate, bitDepth) — the deep check (fake-FLAC, duration) runs
    in sourcing.verify once we have the bytes.

    A strict tier (crate) wants the preferred format and sane lossless. A listening tier (strict_verify false) keeps
    one file that Navidrome transcodes for streaming, so it asks for an upgrade only below its floor: a format it
    does not allow, or a lossy file under min_lossy_bitrate. "Lossless preferred" is never a reason there."""
    ext = (song.suffix or "").lower()
    if not ext:
        return "needs_source", "library entry has no file suffix"
    rank = policy.format_rank(ext)
    if rank is None:
        return "needs_source", f".{ext} not allowed by {policy.name} policy"
    if not policy.strict_verify:
        if policy.is_lossless(ext):
            return "ok", f".{ext} lossless"
        if (song.bit_rate or 0) < policy.min_lossy_bitrate:
            return "needs_source", f".{ext} {song.bit_rate or '?'} kbps below {policy.name}'s {policy.min_lossy_bitrate} floor"
        return "ok", f".{ext} {song.bit_rate} kbps"
    if policy.is_lossless(ext):
        if song.sample_rate and song.sample_rate not in policy.accept_sample_rates:
            return "needs_source", f"odd sample rate {song.sample_rate}"
        if song.bit_depth and song.bit_depth not in policy.accept_bit_depths:
            return "needs_source", f"odd bit depth {song.bit_depth}"
        if song.bit_rate and song.duration and song.bit_rate < policy.min_lossless_kbps:
            return "needs_source", f"lossless at {song.bit_rate} kbps looks like a transcode"
        return "ok", f".{ext} lossless"
    if (song.bit_rate or 0) < policy.min_lossy_bitrate:
        return "needs_source", f".{ext} {song.bit_rate or '?'} kbps below {policy.min_lossy_bitrate} floor"
    # 2026-10-17: a lossy file at or above the floor is DJ quality and is kept. "Lossless preferred" only steers
    # the scorer when a download is chosen; it never queues an upgrade by itself (it would flag every mp3).
    return "ok", f".{ext} {song.bit_rate} kbps"


def song_facts(s: Song) -> dict:
    return {"title": s.title, "artist": s.artist, "album": s.album, "year": s.year, "duration": s.duration,
            "suffix": s.suffix, "bit_rate": s.bit_rate, "sample_rate": s.sample_rate, "bit_depth": s.bit_depth, "path": s.path}


@dataclass
class ReconcileReport:
    crates_seen: int = 0
    crates_enabled: int = 0
    tracks_ok: int = 0
    tracks_needing_source: int = 0
    tracks_removed: int = 0
    toggled_from_comment: list[str] = field(default_factory=list)   # crates turned on/off by a comment or name
    errors: list[str] = field(default_factory=list)
    attr_changes: list[str] = field(default_factory=list)   # "<name>: crate off→on (comment wins)"
    problems: list[str] = field(default_factory=list)       # attrs problems: "<name>: unknown tier …"
    external_tiers: list[str] = field(default_factory=list) # "ext-7: medium → high" (derive_external_tiers)
    playlists_gone: list[str] = field(default_factory=list) # "<name>: playlist no longer exists …; 3 rows dropped"

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _onoff(b: bool) -> str:
    return "on" if b else "off"


_BESIDE_DB = object()


class Reconciler:
    def __init__(self, client: SubsonicClient, store: CrateStore, policy: QualityPolicy = DEFAULT_POLICY,
                 lock_path: str | Path | None | object = _BESIDE_DB, lock_timeout_s: float = 60,
                 owner: str | None = None):
        """`lock_path` defaults to reconcile.lock beside the store's database; an in-memory store has no lock.
        `owner` is "app" (crates.db owns the crate flag) or "comment" (D21); default: $CRATES_OWNER, else "app"."""
        self.client, self.store, self.policy = client, store, policy
        self.owner = owner or default_owner()
        if self.owner not in ("app", "comment"):
            raise ValueError(f"unknown owner {self.owner!r} (app or comment)")
        if lock_path is _BESIDE_DB:
            lock_path = None if store.path == ":memory:" else Path(store.path).parent / "reconcile.lock"
        self.lock_path, self.lock_timeout_s = lock_path, lock_timeout_s
        self._tlock, self._depth = threading.RLock(), 0

    @contextmanager
    def _locked(self):
        """The cross-process reconcile lock, re-entrant within this reconciler (a setter re-judges through
        reconcile_playlist; flock would block on its own second fd)."""
        with self._tlock:
            outer = self._depth == 0 and self.lock_path is not None
            held = hold_reconcile_lock(self.lock_path, self.lock_timeout_s) if outer else None
            if held is not None:
                held.__enter__()
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
                if held is not None:
                    held.__exit__(None, None, None)

    # --- setters: the comment first, then the cache
    def set_crate(self, playlist_id: str, enabled: bool) -> dict:
        pl = self.client.playlist(playlist_id)
        if self.owner == "app":
            return self._set_crate_app(pl, enabled)
        if not enabled and has_name_marker(pl.name):
            raise NameMarked(f"{pl.name!r} is a crate by its name: rename it (drop \"[crate]\" / \"🎛\") to turn it off")
        return self._write_attrs(pl, crate=enabled)

    def set_tier(self, playlist_id: str, tier: str | None) -> dict:
        """`None` clears `#tier:`; `"crate"` sets the crate flag; any other tier keeps the flag as it is."""
        if self.owner == "app":
            raise ValueError("tiers are retired: every download is DJ quality (mark crates with the crate switch)")
        if tier is not None:
            check_tier(tier)
        return self._write_attrs(self.client.playlist(playlist_id), tier=tier)

    def _set_crate_app(self, pl: Playlist, enabled: bool) -> dict:
        """owner="app": the flag goes into crates.db only (source 'app'); the playlist itself is never edited."""
        with self._locked():
            self.store.set_enabled(pl.id, pl.name, enabled, source="app")
            self.reconcile_playlist(pl)
            self.store.derive_external_tiers()
            self.store.commit()
            return self.crate_view(pl)

    def _write_attrs(self, pl: Playlist, **change) -> dict:
        with self._locked():                                     # busy: ReconcileBusy before anything is written
            return self._write_attrs_locked(pl, **change)

    def _write_attrs_locked(self, pl: Playlist, **change) -> dict:
        new = attrs.write(pl.comment, **change)
        if new != (pl.comment or ""):
            pl = write_comment(self.client, pl, new)             # an exception propagates: the cache is untouched
        self.refresh_cache(pl)
        # The playlist's tier moved, so every song it holds (or held) may have a new derived tier: judge this
        # playlist, then those songs' other tiered playlists, so none keeps asking at the old tier until the next run.
        songs = {t["song_id"] for t in self.store.tracks(pl.id)} | {s.id for s in pl.entries}
        self.reconcile_playlist(pl)
        for pid in sorted(self.store.playlists_holding(songs) - {pl.id}):
            try:
                self.reconcile_playlist(self.client.playlist(pid))
            except (SubsonicError, OSError) as e:                # the comment is written; the next run() catches up
                self.store.log(pid, None, "reconcile", f"not re-judged after {pl.name}'s tier changed: {e}")
        self.store.derive_external_tiers()
        self.store.commit()
        return self.crate_view(pl)

    def refresh_cache(self, pl: Playlist) -> list[str]:
        """cache := what the comment (or a name marker) says. Returns the changes as text, empty when none.
        owner="app": the cache is the truth, so only the playlist's name is refreshed."""
        if self.owner == "app":
            self.store.set_name(pl.id, pl.name)
            return []
        a = attrs.parse(pl.comment)
        crate = effective_tier(pl.name, pl.comment) == DEFAULT_TIER
        old = self.store.set_attrs(pl.id, pl.name, crate, a.tier)
        if old is None:
            return []
        out = []
        if old[0] != crate:
            out.append(f"{pl.name}: crate {_onoff(old[0])}→{_onoff(crate)}")
        if old[1] != a.tier:
            out.append(f"{pl.name}: tier {old[1] or 'none'}→{a.tier or 'none'}")
        return out

    def _disagrees(self, pl: Playlist, cached) -> bool:
        if self.owner == "app":
            return False
        a = attrs.parse(pl.comment)
        crate = effective_tier(pl.name, pl.comment) == DEFAULT_TIER
        return (crate, a.tier) != ((cached.enabled, cached.tier) if cached else (False, None))

    # --- reconcile
    def run(self) -> ReconcileReport:
        """1. the cache from every comment; 2. read each tiered playlist; 3. derive each song's tier (the max over
        the tiered playlists holding it); 4. judge each song at it, per (playlist, song) row; 5. rows of playlists
        no longer tiered are removed; 6. external rows take their playlist's tier."""
        with self._locked():
            return self._run()

    def _run(self) -> ReconcileReport:
        rep = ReconcileReport()
        playlists = self.client.playlists()
        rep.crates_seen = len(playlists)
        known = {c.playlist_id: c for c in self.store.all()}
        tiered: list[Playlist] = []
        derived: dict[str, str | None] = {}
        for p in playlists:
            was = known.get(p.id)
            if self._disagrees(p, was):
                # getPlaylists is a snapshot: a setter may have written the comment since. Act on a fresh read only.
                try:
                    p = self.client.playlist(p.id)
                except Exception as e:
                    rep.errors.append(f"{p.name}: {e}")
                    continue
            probs = [f"{p.name}: {x}" for x in attrs.parse(p.comment).problems]
            rep.problems += probs
            self.store.note_problems(p.id, "attrs_problem", probs)
            changes = self.refresh_cache(p)
            c = self.store.get(p.id)
            if changes and was is not None:
                self.store.log(p.id, None, "attrs",
                               f"{p.name}: cache said crate={_onoff(was.enabled)} tier={was.tier or 'none'}; comment says "
                               f"crate={_onoff(c.enabled)} tier={c.tier or 'none'} (comment wins)")
                rep.attr_changes += [f"{x} (comment wins)" for x in changes]
            if bool(was and was.enabled) != bool(c and c.enabled):
                rep.toggled_from_comment.append(p.name)
            tier = c.effective if c else None
            if tier is None:
                continue
            rep.crates_enabled += c.enabled
            try:
                full = self.client.playlist(p.id)
            except Exception as e:
                rep.errors.append(f"{p.name}: {e}")
                held = [t["song_id"] for t in self.store.tracks(p.id)]    # unread: its last known songs still count
            else:
                tiered.append(full)
                held = [s.id for s in full.entries]
            for sid in held:
                derived[sid] = max_tier(derived.get(sid), tier)
        for full in tiered:
            ok, need, gone = self._judge_playlist(full, derived)
            rep.tracks_ok += ok; rep.tracks_needing_source += need; rep.tracks_removed += gone
        present = {p.id for p in playlists}
        for c in self.store.all():
            if c.effective is None and c.playlist_id in present:
                rep.tracks_removed += self._untier(c.playlist_id)
        self.store.commit()
        self._forget_vanished(rep, present, known)
        rep.external_tiers = self.store.derive_external_tiers()
        self.store.commit()
        return rep

    def _forget_vanished(self, rep: ReconcileReport, present: set[str], known: dict) -> None:
        """Playlists crates.db knows (a `crates` or `imported_playlists` row) that getPlaylists did not list lose
        their rows (CrateStore.forget_playlist, D43), each confirmed gone by getPlaylist's error 70. An empty listing,
        or more than VANISH_LIMIT missing at once among those worth guarding (tiered or imported: an untiered row is
        a switched-off crate, or one already cleared while its downloads finish), looks like the wrong Navidrome or
        user, not deletions: nothing is dropped. An event and a reverse-log line are written only by a run that
        changes something, so a playlist whose rows wait for a download is listed in rep.playlists_gone every run
        but logged once."""
        imported = {r["playlist_id"]: r["name"] for r in self.store.imported_playlists()}
        names = {pid: name or pid for pid, name in {**imported, **{pid: c.name for pid, c in known.items()}}.items()}
        missing = sorted((pid for pid in names if pid not in present), key=lambda pid: (names[pid], pid))
        guarded = [names[pid] for pid in missing if pid in imported or known[pid].effective is not None]
        if missing and not present:
            rep.errors.append(f"getPlaylists listed no playlist; nothing dropped "
                              f"({len(missing)} known: {', '.join(names[pid] for pid in missing)})")
            return
        if len(guarded) > VANISH_LIMIT:
            rep.errors.append(f"{len(guarded)} known playlists missing from Navidrome at once "
                              f"({', '.join(guarded)}); nothing dropped")
            return
        for pid in missing:
            name = names[pid]
            try:
                self.client.playlist(pid)
                why = "reads it"
            except SubsonicError as e:
                why = None if e.code == 70 else f"says {e}"
            except Exception as e:                      # anything else is not "gone" either
                why = f"says {e}"
            if why:
                rep.errors.append(f"{name}: missing from getPlaylists but getPlaylist {why}; kept")
                continue
            try:
                out = self.store.forget_playlist(pid)
                n = len(out["dropped"])
                line = f"{name}: playlist no longer exists in Navidrome; {n} row{'' if n == 1 else 's'} dropped" \
                    + (f", {out['kept']} in flight kept" if out["kept"] else "")
                if any(out[k] for k in ("dropped", "crate", "imported_entries", "imported_playlist", "wanted_removed",
                                        "problems")):
                    self._log_forgotten(pid, name, out)
                    c = out["crate"]                     # a tiered row's flag and tier (a cleared one was logged)
                    self.store.log(pid, None, "playlist_gone", line + (
                        f"; was crate={_onoff(bool(c['enabled']))} tier={c['tier'] or 'none'}"
                        if c and (c["enabled"] or c["tier"] is not None) else ""))
                    self.store.commit()
            except OSError as e:                         # no reverse log, no delete
                self.store.db.rollback()
                rep.errors.append(f"{name}: playlist no longer exists in Navidrome; kept: reverse log not written ({e})")
                continue
            except Exception:                            # nothing half-done waits for someone else's commit
                self.store.db.rollback()
                raise
            rep.playlists_gone.append(line)
            rep.tracks_removed += out["live"]

    def _log_forgotten(self, pid: str, name: str, out: dict) -> None:
        """One JSON line per forget_playlist that changed something, beside crates.db (none for an in-memory
        store): every row as it was, so each can be put back. A playlist whose rows waited has several lines (the
        first one holds its `crates` row before it was cleared): replay them newest first. A line whose commit then
        failed describes a forget that did not happen; replaying it only re-inserts rows that are still there."""
        if self.store.path == ":memory:":
            return
        line = json.dumps({"ts": time.time(), "playlist_id": pid, "name": name, "forgotten": out}, ensure_ascii=False)
        with open(Path(self.store.path).parent / "playlists-gone.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

    def policy_for(self, tier: str) -> QualityPolicy:
        """The crate tier is this reconciler's policy (a test or service may pass its own); the others are policy.toml's."""
        return self.policy if tier == DEFAULT_TIER else TIERS[tier]

    def _untier(self, playlist_id: str) -> int:
        """A playlist with no effective tier has no rows: each live one becomes `removed`, except in-flight ones,
        which fetch still has to finish (a later run removes them once finished). Returns how many."""
        live = [t for t in self.store.tracks(playlist_id) if not in_flight(t["status"], t["reason"])]
        for t in live:
            self.store.set_track_status(playlist_id, t["song_id"], "removed", "playlist no longer tiered")
        return len(live)

    def reconcile_playlist(self, pl: Playlist) -> tuple[int, int, int]:
        """One playlist, each song judged at its derived tier: the max of this playlist's tier and the tiers of the
        other tiered playlists holding it (store.song_tier). An untiered playlist loses its rows. Returns (ok,
        needs_source, removed) counts."""
        with self._locked():
            return self._reconcile_playlist(pl)

    def _reconcile_playlist(self, pl: Playlist) -> tuple[int, int, int]:
        own = self.store.playlist_tier(pl.id)
        if own is None:
            gone = self._untier(pl.id)
            self.store.commit()
            return 0, 0, gone
        return self._judge_playlist(pl, {s.id: max_tier(own, self.store.song_tier(s.id)) for s in pl.entries})

    def _judge_playlist(self, pl: Playlist, derived: dict[str, str | None]) -> tuple[int, int, int]:
        prev = self.store.track_status_map(pl.id)
        seen: set[str] = set()
        ok = need = 0
        for pos, s in enumerate(pl.entries):
            seen.add(s.id)
            policy = self.policy_for(derived[s.id])
            status, reason = judge(s, policy)
            if status == "ok" and policy.strict_verify and self.store.is_provisional(s.id):
                # Play-now's fast copy was verified at low only: a strict tier's checks never ran on it, so the
                # tags passing judge do not make it this tier's file.
                status, reason = "needs_source", f"provisional copy (verified at low only); {policy.name} needs its own download"
            old = prev.get(s.id)
            # One open request per song: a play-now provisional copy's upgrade (an external row) gives way to this
            # row, unless it is in flight; then this row is held until it finishes (no second download meanwhile).
            up = self.store.upgrade_row(s.id)
            if up is not None and not self.store.upgrade_busy(up):
                self.store.supersede_upgrade(up["song_id"])
                up = None
            # An in-flight row keeps its status and reason whatever the verdict: a download under way or a filed
            # file Navidrome has not indexed yet (re-checked, never downloaded twice), or a question for Michael.
            if old and in_flight(old["status"], old["reason"]):
                status, reason = old["status"], old["reason"]
            elif up is not None and status != "ok":
                status, reason = "review", held_reason(up["song_id"])
            self.store.upsert_track(pl.id, s.id, pos, song_facts(s), status, reason)
            if not old or old["status"] != status:
                self.store.log(pl.id, s.id, "status", f"{status}: {reason}")
            ok += status == "ok"; need += status != "ok"
        gone = 0
        for sid, t in prev.items():
            if sid not in seen and t["status"] != "removed":
                self.store.set_track_status(pl.id, sid, "removed", "no longer in playlist")
                gone += 1
        self.store.mark_reconciled(pl.id)
        self.store.commit()
        return ok, need, gone

    # --- views for the API/UI
    def crate_view(self, pl: Playlist) -> dict:
        c = self.store.get(pl.id)
        crate = bool(c and c.enabled)
        tier = DEFAULT_TIER if crate else (c.tier if c else None)         # effective, from the cache
        return {"id": pl.id, "name": pl.name, "songCount": pl.song_count, "duration": pl.duration,
                "comment": pl.comment or "", "crate": crate,
                "tier": tier,
                "tierTag": attrs.parse(pl.comment).tier, "crateByName": has_name_marker(pl.name),
                "crateSource": c.source if c else None, "devices": c.devices if c else [],
                "summary": self.store.summary(pl.id) if tier else None,      # any tiered playlist, not only crates
                "lastReconciledAt": c.last_reconciled_at if c else None}

    def wanted(self) -> list[Wanted]:
        return [Wanted(t["artist"] or "", t["title"] or "", t["album"], t["duration"], t["year"]) for t in self.store.wanted()]
