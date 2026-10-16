"""Reconcile: make our crate state match Navidrome's playlists, and decide per track
whether the library file is crate-worthy or must be sourced.

This is deliberately *read-only against Navidrome* except for one optional thing:
mirroring the crate flag into the playlist comment (`#crate`) so any Subsonic client
shows it. Toggling from another client works two ways: edit the comment (where the
client allows it) or rename the playlist with a marker ("… [crate]" / "🎛 …"), which
every client can do. The store wins when the two disagree on a toggle made here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sourcing.policy import QualityPolicy, DEFAULT_POLICY
from sourcing.scorer import Wanted
from subsonic.client import Playlist, Song, SubsonicClient
from . import attrs
from .store import CrateStore, filed_path

# Name markers, for clients that can rename a playlist but not edit its comment
# (most phone apps). "Disco Edits [crate]" or "🎛 Disco Edits" both count.
NAME_MARKERS = ("[crate]", "🎛")


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
    toggled_from_comment: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


class Reconciler:
    def __init__(self, client: SubsonicClient, store: CrateStore, policy: QualityPolicy = DEFAULT_POLICY,
                 mirror_tag: bool = True):
        self.client, self.store, self.policy, self.mirror_tag = client, store, policy, mirror_tag

    # --- toggling
    def set_crate(self, playlist_id: str, enabled: bool) -> dict:
        pl = self.client.playlist(playlist_id)
        self.store.set_enabled(pl.id, pl.name, enabled, source="app")
        if self.mirror_tag and has_crate_tag(pl.comment) != enabled:
            try:
                self.client.update_playlist(pl.id, comment=with_crate_tag(pl.comment, enabled))
            except Exception as e:   # mirroring is best-effort
                self.store.log(pl.id, None, "mirror_failed", str(e))
        if enabled:
            self.reconcile_playlist(pl)
        else:
            for t in self.store.tracks(pl.id):
                self.store.set_track_status(pl.id, t["song_id"], "removed", "crate disabled")
        self.store.commit()
        return self.crate_view(pl)

    # --- reconcile
    def run(self) -> ReconcileReport:
        rep = ReconcileReport()
        playlists = self.client.playlists()
        rep.crates_seen = len(playlists)
        known = {c.playlist_id: c for c in self.store.all()}
        for p in playlists:
            c = known.get(p.id)
            tagged = is_marked(p.name, p.comment)
            # A #crate comment or a name marker added outside this app turns the crate on; removing
            # it turns it off — but only if that is how it got enabled (don't fight an in-app toggle).
            if tagged and not (c and c.enabled):
                self.store.set_enabled(p.id, p.name, True, source="comment")
                rep.toggled_from_comment.append(p.name)
                c = self.store.get(p.id)
            elif not tagged and c and c.enabled and c.source == "comment":
                self.store.set_enabled(p.id, p.name, False, source="comment")
                rep.toggled_from_comment.append(p.name)
                c = self.store.get(p.id)
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
        return {"id": pl.id, "name": pl.name, "songCount": pl.song_count, "duration": pl.duration,
                "comment": pl.comment or "", "crate": bool(c and c.enabled),
                "crateSource": c.source if c else None, "devices": c.devices if c else [],
                "summary": self.store.summary(pl.id) if c and c.enabled else None,
                "lastReconciledAt": c.last_reconciled_at if c else None}

    def wanted(self) -> list[Wanted]:
        return [Wanted(t["artist"] or "", t["title"] or "", t["album"], t["duration"], t["year"]) for t in self.store.wanted()]
