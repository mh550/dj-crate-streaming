"""One wanted track, end to end: search → score → (approved) download → verify → file → rescan → ok.

    needs_source ──search/score──▶ (print pick, stop)            without approve
    needs_source ─▶ sourcing ─▶ verify ─▶ ok                      approve, all good
                                 │          └─▶ verify + reason    filed, Navidrome hasn't indexed it yet
                                 └─▶ failed                        bad file / download timed out / exception
    needs_source (unchanged) when no acceptable candidate — retried next time

Re-running `fetch` on a `verify` row skips the download and just re-checks Navidrome for the
filed path kept in the reason; a `sourcing` row older than the download timeout is treated as
abandoned and retried; a fresh one is reported as in flight. Any exception after the row enters
`sourcing` marks it `failed` with the exception text before propagating, so nothing is ever stuck.

Crate rows (song already in Navidrome, just not good enough) also get the playlist entry swapped
to the new song in every crate that holds it, in one updatePlaylist call per crate, then
reconciled so the new row is `ok` and the old one `removed`. External rows (seeded from Spotify)
just need the file in the library.
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
from .slskd_client import SlskdClient, transfer_files
from .verify import verify

_FILED = re.compile(r"filed as (.+?) but Navidrome")


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


def _filed_reason(music_root: Path, filed: Path) -> str:
    return f"filed as {filed.relative_to(music_root)} but Navidrome has not picked it up yet"


def _find_landed(downloads_root: Path, best: Candidate) -> Path | None:
    """slskd writes <downloads>/<remote parent folder>/<basename>; fall back to a walk by name+size."""
    guess = downloads_root / best.folder / best.basename
    if guess.exists():
        return guess
    for p in downloads_root.rglob(best.basename):
        if p.is_file() and (not best.size or p.stat().st_size == best.size):
            return p
    return None


def fetch(wanted_id: str, *, store: CrateStore, slskd: SlskdClient, navidrome: SubsonicClient,
          reconciler: Reconciler, music_root: Path, downloads_root: Path, approve: bool,
          policy: QualityPolicy = DEFAULT_POLICY, download_timeout_s: float = 600, poll_s: float = 1.0,
          scan_timeout_s: float = 120) -> FetchResult:
    music_root, downloads_root = Path(music_root), Path(downloads_root)
    row = store.find_wanted(wanted_id)
    if row is None:
        return FetchResult("missing", f"{wanted_id} is not in any enabled crate or the external queue")
    external = bool(row.get("external"))

    def set_status(status: str, reason: str | None = None) -> None:
        if external:
            store.set_external_status(wanted_id, status, reason)
        else:
            for crate in store.all(enabled_only=True):
                cur = store.track_status_map(crate.playlist_id).get(wanted_id)
                if cur and cur["status"] != "removed":
                    store.set_track_status(crate.playlist_id, wanted_id, status, reason)
        store.commit()

    wanted = Wanted(row.get("artist") or "", row["title"], row.get("album"), row.get("duration"), row.get("year"))

    def locate_in_navidrome(filed: Path):
        navidrome.start_scan()
        t0 = time.time()
        while navidrome.scan_status().get("scanning") and time.time() - t0 < scan_timeout_s:
            time.sleep(poll_s)
        ext, size = filed.suffix.lstrip(".").lower(), filed.stat().st_size
        hits = [s for s in navidrome.search_songs(f"{wanted.artist} {wanted.title}".strip(), count=50)
                if (s.suffix or "").lower() == ext]
        return next((s for s in hits if s.size == size), None)            # size is the real key; tags may differ

    def finish(filed: Path, best: Candidate | None, text: str) -> FetchResult:
        new = locate_in_navidrome(filed)
        if new is None:
            why = _filed_reason(music_root, filed)
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
            # Subsonic removes by index and only appends: drop old+tail and re-add new+tail in ONE call,
            # which Navidrome applies atomically (remove first, then add).
            navidrome.update_playlist(pl.id, add_song_ids=[new.id] + ids[idx + 1:], remove_indexes=list(range(idx, len(ids))))
            reconciler.reconcile_playlist(navidrome.playlist(pl.id))
        store.commit()
        return FetchResult("ok", "filed, swapped into every crate, reconciled", best, filed, new.id, text)

    status = row.get("status")
    if status == "ok":
        return FetchResult("ok", "already ok; nothing to do")
    if status == "verify":
        m = _FILED.search(row.get("reason") or "")
        if m and (music_root / m.group(1)).exists():
            return finish(music_root / m.group(1), None, "")
        set_status("failed", f"verify row without a filed path (reason was: {row.get('reason')!r})")
        return FetchResult("failed", "verify row without a filed path", explain="")
    if status == "sourcing" and time.time() - (row.get("updated_at") or 0) < download_timeout_s:
        return FetchResult("sourcing", "in flight (started less than the download timeout ago)")

    sid = slskd.search(f"{wanted.artist} {wanted.title}".strip())
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
    try:
        # forget earlier attempts at the same file so their final state can't be mistaken for this one
        for t in transfer_files(slskd.downloads(best.username)):
            if t.get("filename") == best.filename and str(t.get("state", "")).startswith("Completed") and t.get("id"):
                slskd.remove_download(best.username, t["id"])
        slskd.enqueue(best.username, [{"filename": best.filename, "size": best.size}])
        t0 = time.time()
        while True:
            mine = [t for t in transfer_files(slskd.downloads(best.username)) if t.get("filename") == best.filename]
            state = str(mine[-1].get("state", "")) if mine else ""
            if state.startswith("Completed, Succeeded"):
                landed = _find_landed(downloads_root, best)
                if landed:
                    break
                why = f"slskd reports success but {best.basename} is not under {downloads_root}"
                set_status("failed", why)
                return FetchResult("failed", why, best, explain=text)
            if state.startswith("Completed") or time.time() - t0 > download_timeout_s:
                why = f"download ended: {state}" if state.startswith("Completed") else "download timed out"
                set_status("failed", why)
                return FetchResult("failed", why, best, explain=text)
            time.sleep(poll_s)

        set_status("verify", "checking the file")
        vd = verify(landed, wanted.duration_s)
        if not vd.ok:
            why = "; ".join(vd.problems)
            landed.unlink(missing_ok=True)                      # our own download, not library material
            set_status("failed", why)
            return FetchResult("failed", why, best, explain=text)

        track = row.get("track") if external else navidrome.song(wanted_id).track
        filed = file_into(landed, music_root, artist=wanted.artist, title=wanted.title,
                          album=wanted.album, year=wanted.year, track=track)
        return finish(filed, best, text)
    except Exception as e:                                       # never leave a row stuck in sourcing/verify
        set_status("failed", f"{type(e).__name__}: {e}")
        raise
