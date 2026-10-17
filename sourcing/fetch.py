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

Re-running `fetch` on a `verify` row (or on a row failed as "Navidrome never indexed <path>", see
filed_path) skips the download and just re-checks Navidrome for the
filed path kept in the reason, searching by the filed file's own artist/title tags (what Navidrome indexed);
each miss is counted in the reason as `(check N)`, and the RECHECK_LIMIT-th fails the row with "Navidrome
never indexed <path>; file is in the library", so it does not wait unseen forever. A `sourcing` row older
than the download timeout is treated as abandoned and retried; a fresh one is reported as in flight. Any exception after the row enters
`sourcing` marks it `failed` with the exception text before propagating, so nothing is ever stuck, except
once beets has filed the file: from then on the row is `verify` with the filed path in its reason (set right
after filing, and again with the exception text), because the library file is the one copy of that version
and a retry would download and file a second one.

A copy upgrade (`copy_of`: a playlist row, whose song is already in Navidrome but not good enough for its derived
tier) replaces the old copy only with proof (sourcing.replace): the verification stored for this download says
`replaceable` is True and names the old file it compared, that file is unchanged, and identity calls the two one
version. Then the new song takes the old one's place in *every* playlist that holds it (not only tiered ones), the
reconciled rows say so (new `ok`, old `removed`), and the old file goes to the trash once no playlist entry refers
to it; a step that cannot finish now is resumed by the worker. Without proof both copies stay, no playlist is
touched, and the row becomes `review` ("kept beside <old>: not proven the same recording (<why>)"). A request
withdrawn mid-download (no tiered playlist holds the old song any more) is filed, nothing is replaced, and the row
becomes `review` ("filed beside <old>; request withdrawn, both copies kept").
A new version is never a replacement (D23). External rows (seeded from Spotify) just need the file in the library;
when the filed song is another version of a song a tiered playlist holds, and that tier prefers it, Michael is asked
(crates.proposals.version_swaps), as he is about each slot of a copy kept beside the old one (unproven_copy). Asking
never fails the fetch.

Play-now (D20): Michael's tap is an approval for one fast copy; the worker fetches it with `score_tier="low"` (ranked
and verified at low; the row keeps its tier) and `provisional=True`, which the external row records as it enters
`sourcing`. Once Navidrome lists the file the row names that song (`library_song_id`, `provisional` 1) and goes back
to `needs_source` as the upgrade ("provisional low copy filed as <rel>; upgrade at <tier> waits for approval", an
`upgrade_queued` event). The upgrade is then an ordinary copy upgrade of the provisional song, approved by Michael:
with proof it replaces the provisional file (trash), else both are kept and the row asks.

    filed, Navidrome lists it ─┬─ provisional (play-now) ────────────────────▶ needs_source: the upgrade, queued
                               ├─ not a copy upgrade ───────────────────────▶ ok
                               ├─ withdrawn (no tiered playlist holds it) ──▶ review, both copies kept
                               ├─ proven ─▶ replacement: repoint ─▶ trash ─▶ scan ─▶ done (else the worker resumes)
                               └─ not proven ─▶ review "kept beside …" (both copies stay)
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import time
from dataclasses import dataclass, replace
from pathlib import Path

from crates import proposals
from crates.reconcile import Reconciler, judge
from crates.store import CrateStore, filed_path, never_indexed, retryable_review
from scripts.export_playlists import open_ro
from subsonic.client import SubsonicClient, SubsonicError
from .filer import BeetsFiler, FilingError
from .identity import parse_filename, parse_title
from .policy import TIERS, QualityPolicy, check_tier
from . import replace as replacement
from .scorer import Candidate, Wanted, explain, rank
from .slskd_client import SlskdClient, transfer_files
from .verify import verify

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
    approval_result: str = ""      # set when an approval must record something other than "<status>: <reason>"


def _find_landed(downloads_root: Path, best: Candidate) -> Path | None:
    """slskd writes <downloads>/<remote parent folder>/<basename>; fall back to a walk by name+size."""
    guess = downloads_root / best.folder / best.basename
    if guess.exists():
        return guess
    for p in downloads_root.rglob(best.basename):
        if p.is_file() and (not best.size or p.stat().st_size == best.size):
            return p
    return None


def copy_of(row: dict) -> str | None:
    """The song a download would be a better copy of: a playlist row's own song; an external row's library song
    while the row is not `ok` (play-now's provisional copy, Task 11); else None (a new file, not a copy)."""
    if not row.get("external"):
        return row["song_id"]
    lib = row.get("library_song_id")
    return lib if lib and row.get("status") != "ok" else None


def _owned(wanted: Wanted, navidrome: SubsonicClient, song_id: str | None) -> Wanted:
    """What `rank` judges candidates against. A copy upgrade must keep the owned file's own version, label
    included: Navidrome's title for the song, not the row's name, which a Spotify import may have written without
    the label (then the version guard would be vacuous). Only the title changes, so the search query still uses the
    row's name. When Navidrome cannot say, the row's title stands. `song_id` None: not a copy, nothing to keep."""
    if song_id is None:
        return wanted
    try:
        title = navidrome.song(song_id).title
    except (SubsonicError, OSError, ValueError):
        return wanted
    return replace(wanted, title=title) if title else wanted


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
          navidrome_db: Path | None = None, lookup=None, prefer: dict | None = None,
          trash_root: Path | None = None, score_tier: str | None = None, provisional: bool = False,
          sleep=None) -> FetchResult:
    """`score_tier` ranks and verifies at that tier's policy and leaves the row's tier alone (unlike `tier`, which
    re-tiers an external row). `provisional` (play-now, D20; external rows without a library song) files the copy
    as provisional: see the module docstring. `sleep` (default time.sleep) waits each poll of the download and of
    the scan; the worker passes one that also beats its heartbeat, so a long download doesn't look like a dead worker."""
    sleep = sleep or time.sleep
    music_root, downloads_root = Path(music_root), Path(downloads_root)
    row = store.find_wanted(wanted_id)
    if row is None:
        return FetchResult("missing", f"{wanted_id} is not in any enabled crate or the external queue")
    external = bool(row.get("external"))
    copy_id = copy_of(row)                 # the owned song this download would replace, None for a new file
    if score_tier is not None:
        check_tier(score_tier)
    if tier is not None and check_tier(tier) != row["tier"]:     # fact #7: a playlist row's tier is derived
        if not external:
            return FetchResult("refused", f"{wanted_id}: its tier comes from its playlists ({row['tier']})")
        store.set_external_tier(wanted_id, tier); store.commit()
        row["tier"] = tier
    if approve:      # before any search: e.g. inside the crates container the file would land where we can't file it
        missing = [str(d) for d in (music_root, downloads_root) if not (d.is_dir() or d.parent.is_dir())]
        if missing:
            return FetchResult("refused", f"not downloading: {', '.join(missing)} not here (run --approve where the "
                               "library and slskd's downloads are mounted)")
        if filer is None:
            return FetchResult("refused", "no beets filer configured (run --approve in the worker)")
    at = score_tier or row["tier"]         # what this download is ranked and verified at
    policy = policy or TIERS[at]

    def set_status(status: str, reason: str | None = None) -> None:
        store.set_wanted_status(wanted_id, status, reason)

    def fail(why: str, best: Candidate | None, text: str) -> FetchResult:
        set_status("failed", why)
        return FetchResult("failed", why, best, explain=text)

    wanted = Wanted(row.get("artist") or "", row["title"], row.get("album"), row.get("duration"), row.get("year"),
                    copy=copy_id is not None)

    def locate_in_navidrome(filed: Path, query: str | None = None):
        navidrome.start_scan()
        t0 = time.time()
        while navidrome.scan_status().get("scanning") and time.time() - t0 < scan_timeout_s:
            sleep(poll_s)
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
                return fail(never_indexed(rel), best, text)
            why = f"filed as {rel} but Navidrome has not picked it up yet" + (f" (check {check})" if check else "")
            set_status("verify", why)
            return FetchResult("verify", why, best, filed, explain=text)
        store.set_wanted_names(wanted_id, new.artist or "", new.title)      # what the library calls it now
        rel = filed.relative_to(music_root).as_posix()
        done = f"filed as {rel}"
        if copy_id is None and external and (store.external(wanted_id) or {}).get("provisional"):
            # A fast copy that already meets the row's tier is the row's file, but only when it was verified at
            # least as strictly as that tier (a crate's checks never ran at low), and reconcile's judge passes it
            # at that tier (its floor and formats; verify checks no lossy floor).
            policy_at = reconciler.policy_for(row["tier"]) if reconciler is not None else TIERS[row["tier"]]
            verified_at = (store.verification(wanted_id) or {}).get("tier")
            strict_enough = verified_at in TIERS and TIERS[verified_at].strict_verify >= policy_at.strict_verify
            if strict_enough and judge(new, policy_at)[0] == "ok":
                store.set_external_song(wanted_id, new.id, False)
                done = f"filed as {rel}; provisional copy already meets {row['tier']}"
        if copy_id is None and external and (store.external(wanted_id) or {}).get("provisional"):
            # Play-now's fast copy (the row says so from the moment its download started, so a re-check after a
            # worker restart reads it too): it plays now, but it is not the row's file at its tier. The row stays
            # queued as the upgrade, a copy of this song (copy_of), which waits for Michael's approval. It is never
            # put in a playlist or proposed for a slot: only the upgrade may take a slot, through a replacement.
            store.set_external_song(wanted_id, new.id, True)
            set_status("needs_source", f"provisional low copy filed as {rel}; upgrade at {row['tier']} waits for approval")
            store.log(None, wanted_id, "upgrade_queued",
                      f"{rel} is a provisional low copy; upgrade at {row['tier']} waits for approval")
            store.commit()
            return FetchResult("ok", "filed (provisional); upgrade queued", best, filed, new.id, text)
        if copy_id is None:
            if external:
                store.set_library_song(wanted_id, new.id)
            set_status("ok", done)
            if external:                 # another version of a song a tiered playlist holds: ask, never swap (D23)
                ask(lambda: proposals.version_swaps(store, navidrome_db, new.id), rel)
            return FetchResult("ok", "filed and visible in Navidrome", best, filed, new.id, text)
        if not external and not store.playlists_holding([copy_id]):
            # Its playlist stopped being tiered (or dropped the song) mid-download: the request is withdrawn, so
            # nothing is replaced and both copies stay on disk, which Michael is asked about (`review`, which also
            # ends the re-checks: a `verify` row would be re-checked forever).
            old_rel = _old_rel(copy_id)
            set_status("review", f"filed beside {old_rel}; request withdrawn, both copies kept (the new copy is {rel})")
            store.log(None, wanted_id, "kept_both", f"{rel} beside {old_rel}: request withdrawn")
            store.commit()
            return FetchResult("ok", "filed; request withdrawn, both copies kept", best, filed, new.id, text)
        return replace_copy(filed, rel, new.id, best, text)

    def _old_rel(song_id: str) -> str:
        """The old copy's library path for a reason: navidrome.db's, else the verification's reference."""
        try:
            if navidrome_db is not None and Path(navidrome_db).is_file():
                found = replacement.song_path(navidrome_db, song_id)
                if found:
                    return found
        except sqlite3.Error:
            pass
        return (store.verification(wanted_id) or {}).get("reference") or f"song {song_id}"

    def ask(make, rel: str) -> None:
        """Create proposals (crates.proposals) about the filed file `rel` (library-relative, which is what the event
        names). Asking is a side effect of the filing: a failure is an event, never the fetch's outcome."""
        if navidrome_db is None or not Path(navidrome_db).is_file():
            store.log(None, wanted_id, "proposal", f"not asked about {rel}: navidrome.db is not available")
        else:
            try:
                make()
            except Exception as e:
                store.log(None, wanted_id, "proposal", f"not asked about {rel}: {type(e).__name__}: {e}")
        store.commit()

    def keep_both(old_rel: str, rel: str, why: str, filed: Path, new_id: str, best, text: str) -> FetchResult:
        """No proof the two are one recording: both copies stay, no playlist is touched, Michael is asked about
        each slot of the old song in a tiered playlist (proposals.unproven_copy)."""
        set_status("review", f"kept beside {old_rel}: not proven the same recording ({why}); the new copy is {rel}")
        store.log(None, wanted_id, "kept_both", f"{rel} beside {old_rel}: {why}")
        store.commit()
        ask(lambda: proposals.unproven_copy(store, navidrome_db, copy_id, new_id, why, wanted_id), rel)
        return FetchResult("ok", f"filed; kept both ({why})", best, filed, new_id, text)

    def replace_copy(filed: Path, rel: str, new_id: str, best, text: str) -> FetchResult:
        """The copy upgrade's end: a replacement with proof, else keep both. Both the first call and a re-check read
        the *stored* verification, so a re-check decides the same way."""
        ctx = replacement.Ctx(store=store, navidrome=navidrome, navidrome_db=navidrome_db, music_root=music_root,
                              trash_root=trash_root, forget=filer.forget if filer is not None else None,
                              reconciler=reconciler)
        job = replacement.open_for(store, copy_id)
        if job is None:
            v = store.verification(wanted_id)
            ref = ((v or {}).get("measurements") or {}).get("reference")
            why = replacement.why_not(v)                 # first: an unlicensed download reads nothing more
            old_rel = (v or {}).get("reference") or f"song {copy_id}"
            try:
                if navidrome_db is None or not Path(navidrome_db).is_file():
                    why = why or "no navidrome.db to find the old copy in"
                elif (found := replacement.song_path(navidrome_db, copy_id)) is None:
                    why = why or "the old copy is not in navidrome.db"
                else:
                    old_rel = found
                if why is None and new_id == copy_id:
                    why = "Navidrome gave the new copy the old song's id"
                if why is None and trash_root is None:
                    why = "no trash configured"
                if why is None and not (music_root / old_rel).exists():
                    why = f"the old copy {old_rel} is not on disk"
                if why is None:
                    why = replacement.proof(ctx, copy_id, new_id, old_rel, rel, ref)
            except sqlite3.Error as e:                   # locked, not a database, another schema: no proof
                why = why or f"navidrome.db unreadable ({type(e).__name__})"
            if why is not None:
                return keep_both(old_rel, rel, why, filed, new_id, best, text)
            job = {"id": replacement.start(store, wanted_id=wanted_id, old_song_id=copy_id, new_song_id=new_id,
                                           old_path=old_rel, new_path=rel, reference=ref)}
        try:
            replacement.advance(job["id"], ctx)
            err = ""
        except Exception as e:                            # the job keeps its state: the worker resumes it
            err = f"{type(e).__name__}: {e}"
            store.log(None, wanted_id, "replace", f"#{job['id']} interrupted: {err}")
        j = store.replacement(job["id"])
        detail = "; ".join(x for x in (j["detail"], err) if x)
        if j["state"] == "done":
            where = f"old copy in the trash: {j['trash_path']}" if j["trash_path"] else "old copy already gone"
            return FetchResult("ok", f"filed; replaced the old copy in every playlist ({where})", best, filed, new_id,
                               text)
        what = "blocked" if j["state"] == "blocked" else "continues in the worker"
        # The old song's rows still live (a playlist still holds it) wait for the job; reconcile leaves `review` alone
        # and no second download is offered for them. An external row the repoint settled (`ok`, naming the new
        # song, replace._settle) is done whatever the later steps wait for.
        if not (external and (store.external(wanted_id) or {}).get("status") == "ok"):
            set_status("review", f"replacement #{j['id']} {j['state']}: {detail}")
        return FetchResult("ok", f"filed; replacement #{j['id']} {what} ({detail})", best, filed, new_id, text)

    status = row.get("status")
    if status == "removed":              # an upgrade row a tiered playlist's row superseded (one request per song)
        return FetchResult("removed", f"{wanted_id} is closed ({row.get('reason')}); nothing searched")
    if status == "ok":
        return FetchResult("ok", "already ok; nothing to do")
    if status == "review" and not retryable_review(row.get("reason")):     # import-playlist: several versions fit
        return FetchResult("review", f"needs a pick first ({row.get('reason')}); nothing searched")
    # A replacement's review (kept beside / declined / not made / filed beside) falls through: approving it is a
    # fresh download attempt, and the row becomes `sourcing` like any other.
    reason = row.get("reason") or ""
    rel = filed_path(reason)
    if status == "verify" or (status == "failed" and rel is not None):    # filed already: re-check, never download
        if not approve:       # a preview (the crates container: no library mounted) touches neither row nor Navidrome
            return FetchResult(status, f"already filed as {rel or '?'}; the worker re-checks it")
        if rel is not None and (music_root / rel).exists():
            filed = music_root / rel
            names = _file_names(filed)            # Navidrome indexed the file's tags, not the row's (Spotify) names
            c = _CHECK.search(reason)             # a never-indexed row starts counting again at 1
            r = finish(filed, None, "", query=" ".join(names) if names else None,
                       check=(int(c.group(1)) if c else 0) + 1)
            r.approval_result = f"recheck: already filed as {rel}"
            return r
        if status == "failed":                    # the file is gone: say so now, a later approval may fetch again
            return fail(f"filed as {rel} earlier, but it is no longer in the library", None, "")
        return fail(f"verify row without a filed path (reason was: {row.get('reason')!r})", None, "")
    if status == "sourcing" and time.time() - (row.get("updated_at") or 0) < download_timeout_s:
        return FetchResult("sourcing", "in flight (started less than the download timeout ago)")

    sid = slskd.search(f"{wanted.artist} {wanted.title}".strip())
    try:
        slskd.wait_search(sid, poll_s=poll_s, max_s=30)
        cands = rank(slskd.search_responses(sid), _owned(wanted, navidrome, copy_id), policy)
    finally:
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

    # What this download is for, which tells verify what to compare it with (M7): a copy upgrade (copy_of) is
    # compared with the old file (the reference), an external row that gets another version is a new version (no
    # reference, and no expected length: a version's length differs from the row's, and the candidate's own listed
    # length would be it vouching for itself), anything else is checked as before.
    intent, expected = None, wanted.duration_s
    if copy_id is not None:
        intent = "copy"
    else:
        got = parse_filename(best.basename, wanted.artist)        # read as the scorer read it
        if got.key != parse_title(wanted.title, wanted.artist).key:
            intent, expected = "version", None
            store.log(None, wanted_id, "pick", f"another version ({got.label or "no label"}) of {wanted.title}: {best.basename}")

    if external and copy_id is None:          # what this download is for, recorded before it starts (D20)
        store.set_provisional(wanted_id, provisional)
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
                sleep(poll_s)
                continue
            return fail(why, best, text)

        ref, rid = None, None
        if copy_id is not None:               # a copy upgrade: the old copy is the recording we must match
            ref, reason = _library_file(navidrome_db, copy_id, music_root)
            if ref is None:
                store.log(None, wanted_id, "reference", reason)
                store.commit()                # the verifier decodes for minutes: hold no write transaction meanwhile
            rid = navidrome.song(copy_id).music_brainz_id or None
        extra = {"recording_id": rid, "lookup": lookup} if lookup is not None else {}    # see header_only in tests
        if intent == "version" and best.length_s:        # the peer's listing of this file, checked against what arrived
            extra["listed_length_s"] = best.length_s
        set_status("sourcing", f"checking {best.basename}")      # committed: the web's progress strip shows the phase
        vd = verifier(landed, expected, tier=at, reference=ref, intent=intent, **extra)   # still `sourcing`: not ours yet
        store.set_verification(wanted_id, vd.as_dict(at) | {"file": landed.name,
                               "reference": _rel(ref).as_posix() if ref is not None else None})
        if not vd.ok:
            landed.unlink(missing_ok=True)                      # our own download, not library material
            return fail("; ".join(vd.problems), best, text)

        staging = downloads_root / ".staging" / f"{wanted_id}-{int(time.time())}"   # beets only ever sees this
        staging.mkdir(parents=True, exist_ok=True)
        shutil.move(landed, staging / landed.name)
        log = staging.with_suffix(".log")
        def imported(it) -> None:
            """Called by the filer as soon as beets has filed the file, before MusicBrainz is asked or `beet
            write` runs: from here a stop (SIGTERM, Ctrl-C) leaves a `verify` row with the path, never a
            `sourcing` row that recovery would fail and a re-approval would file a second time."""
            nonlocal item
            item = it
            set_status("verify", f"filed as {_rel(it.path)} but Navidrome has not picked it up yet")   # commits

        try:
            item = filer.file(staging, log, names={"artist": wanted.artist, "title": wanted.title}, on_imported=imported)
        except FilingError as e:
            item = e.item or item                                # beets filed it (a failed write), or `imported` already saw it
            raise
        if item is not None and item.filled:
            store.log(None, wanted_id, "tagged", f"filled {', '.join(item.filled)} from the wanted row")
        if item is None:                                         # e.g. a duplicate beets skipped: keep the file
            return fail(f"beets did not import {landed.name}; it is still in {staging}", best, text)
        store.log(None, wanted_id, "filed",
                  f"beets {'matched' if item.matched else 'as-is'}: {item.path.relative_to(music_root)}"
                  + (f" ({item.note})" if item.note else ""))
        # The row has said `verify` with the path since `imported` (a kill during the scan wait included), so a
        # re-check finds the file instead of a retry filing a second copy.
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
