"""One wanted track, end to end: search → score → (approved) download → verify → file → rescan → ok.

    needs_source ──search/score──▶ (print pick, stop)            without approve
    needs_source ─▶ sourcing ─▶ verify ─▶ ok                      approve, all good
                                 │          └─▶ verify + reason    filed, but Navidrome didn't find it
                                 └─▶ failed                        bad file / download timed out
    needs_source (unchanged) when no acceptable candidate — retried next time

Crate rows (song already in Navidrome, just not good enough) also get the playlist entry
swapped to the new song in every crate that holds it, then reconciled so the new row is `ok`
and the old one `removed`. External rows (seeded from Spotify) just need the file in the library.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from crates.reconcile import Reconciler
from crates.store import CrateStore
from subsonic.client import SubsonicClient
from .organize import file_into
from .policy import DEFAULT_POLICY, QualityPolicy
from .scorer import Candidate, Wanted, explain, rank
from .slskd_client import SlskdClient
from .verify import verify


@dataclass
class FetchResult:
    status: str
    reason: str
    pick: Candidate | None = None
    filed: Path | None = None
    new_song_id: str | None = None
    explain: str = ""


def _norm(s: str | None) -> str:
    return re.sub(r"[^\w]+", "", (s or "").casefold())


def fetch(wanted_id: str, *, store: CrateStore, slskd: SlskdClient, navidrome: SubsonicClient,
          reconciler: Reconciler, music_root: Path, downloads_root: Path, approve: bool,
          policy: QualityPolicy = DEFAULT_POLICY, download_timeout_s: float = 600, poll_s: float = 1.0,
          scan_timeout_s: float = 120) -> FetchResult:
    row = next((w for w in store.wanted() if w["song_id"] == wanted_id), None)
    if row is None:
        return FetchResult("missing", f"{wanted_id} is not in the wanted queue")
    external = bool(row.get("external"))

    def set_status(status: str, reason: str | None = None) -> None:
        if external:
            store.set_external_status(wanted_id, status, reason)
        else:
            for crate in store.all(enabled_only=True):
                if wanted_id in store.track_status_map(crate.playlist_id):
                    store.set_track_status(crate.playlist_id, wanted_id, status, reason)
        store.commit()

    wanted = Wanted(row["artist"], row["title"], row.get("album"), row.get("duration"), row.get("year"))
    # crate_tracks doesn't keep the track number; Navidrome's own record has it (and nothing for external rows)
    track = row.get("track") if external else navidrome.song(wanted_id).track
    sid = slskd.search(f"{wanted.artist} {wanted.title}")
    slskd.wait_search(sid, poll_s=poll_s, max_s=30)
    cands = rank(slskd.search_responses(sid), wanted, policy)
    slskd.delete_search(sid)
    text = explain(cands)
    best = next((c for c in cands if not c.rejected), None)
    if best is None:
        return FetchResult("needs_source", "no acceptable candidate", None, explain=text)
    if not approve:
        return FetchResult("needs_source", "pick printed; re-run with --approve to download", best, explain=text)

    set_status("sourcing", f"downloading from {best.username}")
    slskd.enqueue(best.username, [{"filename": best.filename, "size": best.size}])
    landed = Path(downloads_root) / best.username / best.basename
    t0 = time.time()
    while True:
        states = [t.get("state", "") for t in (slskd.downloads(best.username) or []) if t.get("filename") == best.filename]
        if any(s.startswith("Completed, Succeeded") for s in states) and landed.exists():
            break
        ended = [s for s in states if s.startswith("Completed") and not s.startswith("Completed, Succeeded")]
        if ended or time.time() - t0 > download_timeout_s:
            why = f"download ended: {ended[0]}" if ended else "download timed out"
            set_status("failed", why)
            return FetchResult("failed", why, best, explain=text)
        time.sleep(poll_s)

    set_status("verify", "checking the file")
    vd = verify(landed, wanted.duration_s)
    if not vd.ok:
        why = "; ".join(vd.problems)
        set_status("failed", why)
        return FetchResult("failed", why, best, explain=text)

    filed = file_into(landed, Path(music_root), artist=wanted.artist, title=wanted.title,
                      album=wanted.album, year=wanted.year, track=track)

    navidrome.start_scan()
    t0 = time.time()
    while navidrome.scan_status().get("scanning") and time.time() - t0 < scan_timeout_s:
        time.sleep(poll_s)
    ext = filed.suffix.lstrip(".").lower()
    new = next((s for s in navidrome.search_songs(wanted.title, count=50)
                if (s.suffix or "") == ext and _norm(s.title) == _norm(wanted.title)
                and _norm(s.artist) == _norm(wanted.artist)), None)
    if new is None:
        why = f"filed as {filed.relative_to(music_root)} but Navidrome has not picked it up yet"
        set_status("verify", why)
        return FetchResult("verify", why, best, filed, explain=text)

    if external:
        set_status("ok", f"filed as {filed.relative_to(music_root)}")
        return FetchResult("ok", "filed and visible in Navidrome", best, filed, new.id, text)

    for crate in store.all(enabled_only=True):
        pl = navidrome.playlist(crate.playlist_id)
        ids = [e.id for e in pl.entries]
        if wanted_id not in ids:
            continue
        idx = ids.index(wanted_id)
        tail = ids[idx + 1:]
        # Subsonic removes by index and only appends, so drop old + tail, then re-add new + tail in order.
        navidrome.update_playlist(pl.id, remove_indexes=list(range(idx, len(ids))))
        navidrome.update_playlist(pl.id, add_song_ids=[new.id] + tail)
        reconciler.reconcile_playlist(navidrome.playlist(pl.id))
    store.commit()
    return FetchResult("ok", "filed, swapped into every crate, reconciled", best, filed, new.id, text)
