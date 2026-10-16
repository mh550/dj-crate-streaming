"""One wanted track, end to end: search → score → (approved) download → verify → beet import → rescan → ok.

    needs_source ──search/score──▶ (print pick, stop)                       without approve
    needs_source ─▶ sourcing ─▶ verify ─▶ beet import ─▶ rescan ─▶ ok         approve, all good
                                 │          │                 └─▶ verify     filed, Navidrome hasn't indexed it yet
                                 │          └─▶ failed                        beets imported nothing (file kept in staging)
                                 └─▶ failed                                   bad file / download timed out / exception
    needs_source (unchanged) when no acceptable candidate — retried next time

Filing is beets' job (D18): the verified download moves to its own `<downloads>/.staging/<id>-<ts>/`
folder and BeetsFiler imports it from there, so beets never sees slskd's folders or the library's
originals. Navidrome's names for the filed song then go back onto the wanted row (`renamed` event),
because they are what the library now calls it. Soulseek peer names never reach a reason or an event.

`prefer` (an approval's candidate, D18) makes the download that exact file while it is still offered and
unrejected; otherwise the top-ranked one is used, and a `pick` event says which of the two happened.

Re-running `fetch` on a `verify` row skips the download and just re-checks Navidrome for the
filed path kept in the reason, searching by the filed file's own artist/title tags (what Navidrome indexed);
each miss is counted in the reason as `(check N)`, and the RECHECK_LIMIT-th fails the row with "Navidrome
never indexed <path>; file is in the library", so it does not wait unseen forever. A `sourcing` row older
than the download timeout is treated as abandoned and retried; a fresh one is reported as in flight. Any exception after the row enters
`sourcing` marks it `failed` with the exception text before propagating, so nothing is ever stuck, except
once beets has filed the file: from then on the row is `verify` with the filed path in its reason (set right
after filing, and again with the exception text), because the library file is the one copy of that version
and a retry would download and file a second one.

Crate rows (song already in Navidrome, just not good enough) also get the playlist entry swapped
to the new song in every crate that holds it, in one updatePlaylist call per crate, then
reconciled so the new row is `ok` and the old one `removed`. External rows (seeded from Spotify)
just need the file in the library.
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from crates.reconcile import Reconciler
from crates.store import CrateStore
from scripts.export_playlists import open_ro
from subsonic.client import SubsonicClient
from .filer import BeetsFiler, FilingError
from .policy import DEFAULT_TIER, TIERS, QualityPolicy, check_tier
from .scorer import Candidate, Wanted, explain, rank
from .slskd_client import SlskdClient, transfer_files
from .verify import verify

_FILED = re.compile(r"filed as (.+?) but Navidrome")   # the filed path rides in the reason until a jobs table exists (M4)
_CHECK = re.compile(r"\(check (\d+)\)$")                # how many re-checks have not found it, also in the reason
RECHECK_LIMIT = 12      # re-checks without Navidrome finding the file before the row fails, so Michael sees it


def _file_names(path: Path) -> tuple[str, str] | None:
    """(artist, title) from the filed file's own tags, which are what Navidrome indexes; None when unreadable or
    untitled. mediafile is imported lazily: the worker image installs it, and without it the caller falls back."""
    try:
        from mediafile import MediaFile
        mf = MediaFile(str(path))
    except Exception:                          # ImportError, or a file mediafile cannot read
        return None
    title = (mf.title or "").strip()
    return ((mf.artist or "").strip(), title) if title else None


@dataclass
class FetchResult:
    status: str
    reason: str
    pick: Candidate | None = None
    filed: Path | None = None
    new_song_id: str | None = None
    explain: str = ""


def _find_landed(downloads_root: Path, best: Candidate) -> Path | None:
    """slskd writes <downloads>/<remote parent folder>/<basename>; fall back to a walk by name+size."""
    guess = downloads_root / best.folder / best.basename
    if guess.exists():
        return guess
    for p in downloads_root.rglob(best.basename):
        if p.is_file() and (not best.size or p.stat().st_size == best.size):
            return p
    return None


def _library_file(navidrome_db: Path | None, song_id: str, music_root: Path) -> tuple[Path | None, str]:
    """The file Navidrome has for `song_id` (Navidrome 0.64 stores library-relative paths), read from its
    database read-only, and why there is none when there isn't."""
    if navidrome_db is None or not Path(navidrome_db).is_file():
        return None, f"no reference: navidrome.db not at {navidrome_db}"
    try:
        con = open_ro(navidrome_db)
        try:
            row = con.execute("SELECT path FROM media_file WHERE id = ?", (song_id,)).fetchone()
        finally:
            con.close()
    except sqlite3.Error as e:                 # locked, not a database, schema changed: verify without a reference
        return None, f"no reference: navidrome.db unreadable ({type(e).__name__})"
    if row is None:
        return None, f"no reference: {song_id} not in navidrome.db"
    ref = music_root / row[0]
    if not ref.is_file():
        return None, f"no reference: {row[0]} missing on disk"
    return ref, ""


def fetch(wanted_id: str, *, store: CrateStore, slskd: SlskdClient, navidrome: SubsonicClient,
          reconciler: Reconciler, music_root: Path, downloads_root: Path, approve: bool,
          tier: str | None = None, policy: QualityPolicy | None = None, download_timeout_s: float = 600, poll_s: float = 1.0,
          scan_timeout_s: float = 120, verifier=verify, filer: BeetsFiler | None = None,
          navidrome_db: Path | None = None, lookup=None, prefer: dict | None = None) -> FetchResult:
    music_root, downloads_root = Path(music_root), Path(downloads_root)
    row = store.find_wanted(wanted_id)
    if row is None:
        return FetchResult("missing", f"{wanted_id} is not in any enabled crate or the external queue")
    external = bool(row.get("external"))
    if tier is not None and check_tier(tier) != row["tier"]:     # spec §1: a crate track is sourced at crate
        if not external:
            return FetchResult("refused", f"{wanted_id} is in a crate, and a crate track is sourced at tier {DEFAULT_TIER}")
        store.set_external_tier(wanted_id, tier); store.commit()
        row["tier"] = tier
    if approve:      # before any search: e.g. inside the crates container the file would land where we can't file it
        missing = [str(d) for d in (music_root, downloads_root) if not (d.is_dir() or d.parent.is_dir())]
        if missing:
            return FetchResult("refused", f"not downloading: {', '.join(missing)} not here (run --approve where the "
                               "library and slskd's downloads are mounted)")
        if filer is None:
            return FetchResult("refused", "no beets filer configured (run --approve in the worker)")
    policy = policy or TIERS[row["tier"]]

    def set_status(status: str, reason: str | None = None) -> None:
        store.set_wanted_status(wanted_id, status, reason)

    def fail(why: str, best: Candidate | None, text: str) -> FetchResult:
        set_status("failed", why)
        return FetchResult("failed", why, best, explain=text)

    wanted = Wanted(row.get("artist") or "", row["title"], row.get("album"), row.get("duration"), row.get("year"))

    def locate_in_navidrome(filed: Path, query: str | None = None):
        navidrome.start_scan()
        t0 = time.time()
        while navidrome.scan_status().get("scanning") and time.time() - t0 < scan_timeout_s:
            time.sleep(poll_s)
        ext, size, rel = filed.suffix.lstrip(".").lower(), filed.stat().st_size, filed.relative_to(music_root).as_posix()
        query = query if query is not None else f"{wanted.artist} {wanted.title}"
        hits = [s for s in navidrome.search_songs(query.strip(), count=50)
                if (s.suffix or "").lower() == ext and s.size == size]   # size is the key: tags may differ, and
        # Navidrome's Subsonic `path` is synthesised from tags, so it only serves as a tie-break
        return next((s for s in hits if (s.path or "").endswith(rel)), hits[0] if hits else None)

    def _rel(p: Path) -> Path:
        return p.relative_to(music_root) if p.is_relative_to(music_root) else p

    def finish(filed: Path, best: Candidate | None, text: str, query: str | None = None,
               check: int = 0) -> FetchResult:
        """`check` counts re-checks (0 straight after filing); the RECHECK_LIMIT-th miss fails the row."""
        new = locate_in_navidrome(filed, query)
        if new is None:
            rel = filed.relative_to(music_root)
            if check >= RECHECK_LIMIT:
                return fail(f"Navidrome never indexed {rel}; file is in the library", best, text)
            why = f"filed as {rel} but Navidrome has not picked it up yet" + (f" (check {check})" if check else "")
            set_status("verify", why)
            return FetchResult("verify", why, best, filed, explain=text)
        store.set_wanted_names(wanted_id, new.artist or "", new.title)      # what the library calls it now
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
    if status == "review":                                       # import-playlist: several library versions fit
        return FetchResult("review", f"needs a pick first ({row.get('reason')}); nothing searched")
    if status == "verify":
        reason = row.get("reason") or ""
        m = _FILED.search(reason)
        if m and (music_root / m.group(1)).exists():
            filed = music_root / m.group(1)
            names = _file_names(filed)            # Navidrome indexed the file's tags, not the row's (Spotify) names
            c = _CHECK.search(reason)
            return finish(filed, None, "", query=" ".join(names) if names else None,
                          check=(int(c.group(1)) if c else 0) + 1)
        return fail(f"verify row without a filed path (reason was: {row.get('reason')!r})", None, "")
    if status == "sourcing" and time.time() - (row.get("updated_at") or 0) < download_timeout_s:
        return FetchResult("sourcing", "in flight (started less than the download timeout ago)")

    sid = slskd.search(f"{wanted.artist} {wanted.title}".strip())
    slskd.wait_search(sid, poll_s=poll_s, max_s=30)
    cands = rank(slskd.search_responses(sid), wanted, policy)
    slskd.delete_search(sid)
    text = explain(cands, peers=False)
    best = next((c for c in cands if not c.rejected), None)
    if best is None:
        return FetchResult("needs_source", "no acceptable candidate", None, explain=text)
    if not approve:
        return FetchResult("needs_source", "pick printed; re-run with --approve to download", best, explain=text)
    if prefer:       # the candidate Michael approved (D18): honoured while the peer still offers that file
        same = next((c for c in cands if not c.rejected and c.username == prefer.get("username")
                     and c.filename == prefer.get("filename")), None)
        if same is not None:
            best = same
        store.log(None, wanted_id, "pick", f"approved candidate still offered: {best.basename}" if same is not None
                  else f"approved candidate no longer offered; using the top-ranked {best.basename}")

    set_status("sourcing", f"downloading {best.basename}")
    item = None                                                  # the library file, once beets has filed it
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
            elif state.startswith("Completed"):
                why = f"download ended: {state}"
            elif time.time() - t0 > download_timeout_s:
                why = "download timed out"
            else:
                time.sleep(poll_s)
                continue
            return fail(why, best, text)

        ref, rid = None, None
        if not external:                      # a crate upgrade: the old copy is the recording we must match
            ref, reason = _library_file(navidrome_db, wanted_id, music_root)
            if ref is None:
                store.log(None, wanted_id, "reference", reason)
                store.commit()                # the verifier decodes for minutes: hold no write transaction meanwhile
            rid = navidrome.song(wanted_id).music_brainz_id or None
        extra = {"recording_id": rid, "lookup": lookup} if lookup is not None else {}    # see header_only in tests
        vd = verifier(landed, wanted.duration_s, tier=row["tier"], reference=ref, **extra)   # still `sourcing`: not ours yet
        store.set_verification(wanted_id, vd.as_dict(row["tier"]) | {"file": landed.name})
        if not vd.ok:
            landed.unlink(missing_ok=True)                      # our own download, not library material
            return fail("; ".join(vd.problems), best, text)

        staging = downloads_root / ".staging" / f"{wanted_id}-{int(time.time())}"   # beets only ever sees this
        staging.mkdir(parents=True, exist_ok=True)
        shutil.move(landed, staging / landed.name)
        log = staging.with_suffix(".log")
        try:
            item = filer.file(staging, log, names={"artist": wanted.artist, "title": wanted.title})
        except FilingError as e:
            item = e.item                                        # set when beets had already filed it (a failed write)
            raise
        if item is not None and item.filled:
            store.log(None, wanted_id, "tagged", f"filled {', '.join(item.filled)} from the wanted row")
        if item is None:                                         # e.g. a duplicate beets skipped: keep the file
            return fail(f"beets did not import {landed.name}; it is still in {staging}", best, text)
        store.log(None, wanted_id, "filed",
                  f"beets {'matched' if item.matched else 'as-is'}: {item.path.relative_to(music_root)}"
                  + (f" ({item.note})" if item.note else ""))
        # From here the file is in the library: the row says where before anything else can go wrong (a kill
        # during the scan wait included), so a re-check finds it instead of a retry filing a second copy.
        set_status("verify", f"filed as {_rel(item.path)} but Navidrome has not picked it up yet")
        log.unlink(missing_ok=True)
        try:
            staging.rmdir()
        except OSError:                                          # beets left something behind: harmless, keep it
            pass
        return finish(item.path, best, text, query=f"{item.artist} {item.title}")
    except Exception as e:                                       # never leave a row stuck in sourcing
        if item is not None:                                     # filed: keep the path, so a re-check (not a retry) follows
            set_status("verify", f"filed as {_rel(item.path)} but Navidrome has not picked it up yet "
                                 f"({type(e).__name__}: {e})")
        else:
            set_status("failed", f"{type(e).__name__}: {e}")
        raise
