"""Reconcile: rebuild the cache of which playlists are crates (and their tiers) from the playlists' own
comments, and decide per track whether the library file is crate-worthy or must be sourced.

The playlist's comment owns the crate flag and the tier (D21, spec fact #6): `#crate` and `#tier:<t>`, read and
written only through crates.attrs, so Michael's own text survives byte for byte. crates.db caches them; when the
cache and a comment disagree, the comment wins and an `attrs` event records both. The setters (set_crate,
set_tier) write the comment first, read it back, and only then refresh the cache: a failed write or a crash in
between leaves the owner right and the cache rebuildable by the next run(), never the reverse. Clients that can
rename a playlist but not edit its comment (most phone apps) can mark it by name ("… [crate]" / "🎛 …"); such a
crate is turned off only by renaming it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sourcing.policy import DEFAULT_POLICY, DEFAULT_TIER, QualityPolicy, check_tier
from sourcing.scorer import Wanted
from subsonic.client import Playlist, Song, SubsonicClient
from . import attrs
from .store import CrateStore, filed_path

# Name markers, for clients that can rename a playlist but not edit its comment
# (most phone apps). "Disco Edits [crate]" or "🎛 Disco Edits" both count.
NAME_MARKERS = ("[crate]", "🎛")


class NameMarked(Exception):
    """The playlist's *name* carries a crate marker ([crate] / 🎛): only renaming it turns the crate off."""


class CommentNotKept(Exception):
    """The comment read back after our write does not say what we wrote (another client edited it in between,
    or Navidrome stored it differently). The cache is left alone."""


def has_crate_tag(comment: str | None) -> bool:
    return attrs.parse(comment).crate


def has_name_marker(name: str | None) -> bool:
    n = (name or "").strip().lower()
    return any(n.startswith(m) or n.endswith(m) for m in NAME_MARKERS)


def is_marked(name: str | None, comment: str | None) -> bool:
    """A playlist is marked as a crate from *outside this app* by comment or by name."""
    return has_crate_tag(comment) or has_name_marker(name)


def with_crate_tag(comment: str | None, on: bool) -> str:
    return attrs.write(comment, crate=on)


def judge(song: Song, policy: QualityPolicy = DEFAULT_POLICY) -> tuple[str, str]:
    """Is the file Navidrome has good enough for a crate? Uses only what Subsonic tells us
    (suffix, bitRate, samplingRate, bitDepth) — the deep check (fake-FLAC, duration) runs
    in sourcing.verify once we have the bytes."""
    ext = (song.suffix or "").lower()
    if not ext:
        return "needs_source", "library entry has no file suffix"
    rank = policy.format_rank(ext)
    if rank is None:
        return "needs_source", f".{ext} not allowed by crate policy"
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
    if rank > 0:
        # Acceptable lossy (e.g. 320 mp3) but a better format is preferred → keep the file usable,
        # still queue an upgrade. That is what "preferred vs allowed" means in the policy.
        return "needs_source", f".{ext} {song.bit_rate} kbps acceptable; lossless preferred"
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

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _onoff(b: bool) -> str:
    return "on" if b else "off"


class Reconciler:
    def __init__(self, client: SubsonicClient, store: CrateStore, policy: QualityPolicy = DEFAULT_POLICY):
        self.client, self.store, self.policy = client, store, policy

    # --- setters: the comment first, then the cache
    def set_crate(self, playlist_id: str, enabled: bool) -> dict:
        pl = self.client.playlist(playlist_id)
        if not enabled and has_name_marker(pl.name):
            raise NameMarked(f"{pl.name!r} is a crate by its name: rename it (drop \"[crate]\" / \"🎛\") to turn it off")
        return self._write_attrs(pl, crate=enabled)

    def set_tier(self, playlist_id: str, tier: str | None) -> dict:
        """`None` clears `#tier:`; `"crate"` sets the crate flag; any other tier keeps the flag as it is."""
        if tier is not None:
            check_tier(tier)
        return self._write_attrs(self.client.playlist(playlist_id), tier=tier)

    def _write_attrs(self, pl: Playlist, **change) -> dict:
        new = attrs.write(pl.comment, **change)
        if new != (pl.comment or ""):
            self.client.update_playlist(pl.id, comment=new)      # an exception propagates: the cache is untouched
            back = self.client.playlist(pl.id)
            if (back.comment or "") != new:
                raise CommentNotKept(f"{pl.name}: wrote comment {new!r} but Navidrome now has {back.comment or ''!r}; "
                                     "nothing changed here, try again")
            pl = back
        self.refresh_cache(pl)
        # Until derived tiers (M8 Task 5): today's per-playlist reconcile of the crate's tracks.
        if (c := self.store.get(pl.id)) and c.enabled:
            self.reconcile_playlist(pl)
        else:
            for t in self.store.tracks(pl.id):
                self.store.set_track_status(pl.id, t["song_id"], "removed", "crate disabled")
        self.store.commit()
        return self.crate_view(pl)

    def refresh_cache(self, pl: Playlist) -> list[str]:
        """cache := what the comment (or a name marker) says. Returns the changes as text, empty when none."""
        a = attrs.parse(pl.comment)
        crate = a.crate or has_name_marker(pl.name)
        old = self.store.set_attrs(pl.id, pl.name, crate, a.tier)
        if old is None:
            return []
        out = []
        if old[0] != crate:
            out.append(f"{pl.name}: crate {_onoff(old[0])}→{_onoff(crate)}")
        if old[1] != a.tier:
            out.append(f"{pl.name}: tier {old[1] or 'none'}→{a.tier or 'none'}")
        return out

    @staticmethod
    def _disagrees(pl: Playlist, cached) -> bool:
        a = attrs.parse(pl.comment)
        return (a.crate or has_name_marker(pl.name), a.tier) != ((cached.enabled, cached.tier) if cached else (False, None))

    # --- reconcile
    def run(self) -> ReconcileReport:
        rep = ReconcileReport()
        playlists = self.client.playlists()
        rep.crates_seen = len(playlists)
        known = {c.playlist_id: c for c in self.store.all()}
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
            if not (c and c.enabled):
                continue
            rep.crates_enabled += 1
            try:
                full = self.client.playlist(p.id)
            except Exception as e:
                rep.errors.append(f"{p.name}: {e}")
                continue
            ok, need, gone = self.reconcile_playlist(full)
            rep.tracks_ok += ok; rep.tracks_needing_source += need; rep.tracks_removed += gone
        # Crates whose playlist vanished from Navidrome.
        present = {p.id for p in playlists}
        for pid, c in known.items():
            if c.enabled and pid not in present:
                rep.errors.append(f"{c.name}: playlist no longer exists in Navidrome")
        self.store.commit()
        return rep

    def reconcile_playlist(self, pl: Playlist) -> tuple[int, int, int]:
        """Returns (ok, needs_source, removed) counts."""
        prev = self.store.track_status_map(pl.id)
        seen: set[str] = set()
        ok = need = 0
        for pos, s in enumerate(pl.entries):
            seen.add(s.id)
            status, reason = judge(s, self.policy)
            old = prev.get(s.id)
            # Don't clobber an in-flight sourcing job with a fresh "needs_source" verdict; nor a failed
            # never-indexed row, whose file is already in the library (it is re-checked, never downloaded twice).
            if old and status == "needs_source" and (
                    old["status"] in ("sourcing", "verify")
                    or (old["status"] == "failed" and filed_path(old["reason"]))):
                status, reason = old["status"], old["reason"]
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
        return {"id": pl.id, "name": pl.name, "songCount": pl.song_count, "duration": pl.duration,
                "comment": pl.comment or "", "crate": crate,
                "tier": DEFAULT_TIER if crate else (c.tier if c else None),     # effective, from the cache
                "tierTag": attrs.parse(pl.comment).tier, "crateByName": has_name_marker(pl.name),
                "crateSource": c.source if c else None, "devices": c.devices if c else [],
                "summary": self.store.summary(pl.id) if c and c.enabled else None,
                "lastReconciledAt": c.last_reconciled_at if c else None}

    def wanted(self) -> list[Wanted]:
        return [Wanted(t["artist"] or "", t["title"] or "", t["album"], t["duration"], t["year"]) for t in self.store.wanted()]
