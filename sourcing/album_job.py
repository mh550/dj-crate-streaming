"""The album job (spec S2-05, plan `docs/plans/2026-10-22-s2-album-requests.md` → "Album job"): an album request
approved as one, sourced album-first.

- `plan_request` searches `"<artist> <album>"` once, plans the request's open rows (sourcing.album.plan_album) and
  caches the plan as the preview `req-<id>` (`at`, the time; `assign`, each planned row's folder label and file).
  What it returns, and the `plan` event, name folders by label and files by basename: never a peer.
- `approve_request` is Michael's click (D7): one `album` approval per open row, the planned file as its candidate
  (None for a row going per track). Refused (ValueError) while a row is being fetched or filed.
- `run` is the worker's side (Worker._spend hands it a request's `album` approvals): claim them, link each row the
  library already has (fetch.in_library, S1-07: `ok`, nothing downloaded), plan again when the cached plan is older
  than `plan_max_age_s`, enqueue each peer's planned files in one POST, then run each row through fetch in planned
  mode (no search, no enqueue: it polls the transfer enqueued here). Only a row a fetch would download, whose planned
  file still passes at the row's own tier, is enqueued; any other is an ordinary fetch (which says `already ok`,
  `in flight`, ...), as is a row without a planned file. A planned file its fetch did not file (an error, a failed
  check) and a POST slskd refused are cancelled and forgotten (remove=true), so nothing lands unfiled later. Each
  approval is marked used with its row's outcome; one being run refuses a second approve_request.

Switching (S2-05b): trouble with a planned file switches the rest of that folder's unfiled rows, the failed one
included, to another folder. The triggers: a transfer fetch says another peer may fix (`FetchResult.again`, S1-06:
fetch does not retry in planned mode), a peer that has started none of its files `start_timeout_s` after the enqueue
(`ALBUM_START_TIMEOUT_S`; then every folder of that peer), one verify finding of the "not what it claims" kind
(`DISTRUST`), or `MAX_FOLDER_FAILURES` failed rows in one folder (an ordinary finding alone fails only its row, whose
approval waits for the job's end: a later switch of its folder takes it along). On a switch the folder's records of
rows not yet filed are cancelled and forgotten (remove=true), and the moved rows are planned again over the first
search's responses (cached with the plan) plus one fresh album search (when slskd answers), without the failed
folders, the release the job has been filing first (the planned files' lengths), one row being enough; rows already
filed stay. One `switch` event per failed folder: `folder 1 distrusted: transcode (<basename>); 8 rows → folder 2`.
A row gets one switched folder; a row with none left (or none found) goes per track, as an ordinary fetch.

S2-05c (the per-row attempt cap) builds on this.
"""
from __future__ import annotations

import time

from crates.store import filed_path, public, retryable_review
from . import album
from .fetch import FetchResult, copy_of, fetch, in_library, planned_candidate
from .policy import DEFAULT_POLICY, TIERS
from .scorer import split_remote
from .slskd_client import SlskdError, transfer_files

ALBUM_PLAN_MAX_AGE_S = 3600          # an older cached plan is made again before the enqueue (peers come and go)
ALBUM_START_TIMEOUT_S = 600          # a peer that has started none of the job's files by then: its folders switch
DISTRUST = {"transcode", "fake_24bit", "fake_hires", "recording"}    # one such finding distrusts the whole folder
MAX_FOLDER_FAILURES = 2              # this many failed rows in one folder distrust it too
NOT_STARTED = ("Requested", "Queued", "Initializing")              # slskd states before a transfer starts


def preview_key(request_id: int) -> str:
    return f"req-{request_id}"


def open_rows(req: dict) -> list[dict]:
    """The rows an approval of the request covers: not `ok`, not `removed`, no file of theirs filed already."""
    return [r for r in req["rows"] if r["status"] not in ("ok", "removed") and filed_path(r.get("reason")) is None]


def summary(plan: album.AlbumPlan) -> str:
    """`folder 1: 8 of 9; 1 row per track`: the plan event's text (labels as album.describe numbers them)."""
    parts = [f"folder {n}: {len(f.rows)} of {plan.total}"
             for n, f in enumerate((f for f in (plan.primary, plan.secondary) if f), 1)]
    if plan.per_track:
        n = len(plan.per_track)
        parts.append(f"{n} row{'s' if n != 1 else ''} per track")
    return "; ".join(parts)


def _request(store, request_id: int) -> dict:
    req = store.request(request_id)
    if req is None:
        raise ValueError(f"no request #{request_id}")
    return req


def _search(slskd, req: dict, poll_s: float) -> list[dict]:
    """One search for `"<artist> <album>"`: its responses."""
    sid = slskd.search(" ".join(x for x in (req["artist"], req["album"]) if x))
    try:
        st = slskd.wait_search(sid, poll_s=poll_s, max_s=30)
        return slskd.search_responses(sid, expect=st.get("responseCount") or 0, poll_s=poll_s)
    finally:
        slskd.delete_search(sid)


def plan_request(store, slskd, request_id: int, policy=None, *, poll_s: float = 1.0) -> dict:
    """Search the album once, plan its open rows, cache the plan (`req-<id>`) and return what a client may see:
    folder labels, coverage, row → basename, the per-track rows. One `plan` event. Nothing is enqueued. The cache
    also keeps, server side only, `at`, `assign` and the search's `responses` (a switch plans over them again)."""
    req = _request(store, request_id)
    rows = open_rows(req)
    policy = policy or (TIERS[rows[0]["tier"]] if rows else DEFAULT_POLICY)
    responses = _search(slskd, req, poll_s)
    plan = album.plan_album(responses, rows, policy=policy)
    folders, assign = [], {}
    for n, (role, f) in enumerate(((r, f) for r, f in (("primary", plan.primary), ("secondary", plan.secondary)) if f), 1):
        label = f"folder {n}"
        folders.append({"label": label, "role": role, "covers": f"{len(f.rows)} of {plan.total}",
                        "rows": [{"id": row["song_id"], "track_no": row.get("track_no"), "title": row["title"],
                                  "basename": c.basename} for row, c in f.rows]})
        assign |= {row["song_id"]: {"folder": label, "candidate": c.as_dict()} for row, c in f.rows}
    shown = {"request_id": request_id, "folders": folders,
             "per_track": [{"id": r["song_id"], "track_no": r.get("track_no"), "title": r["title"]}
                           for r in plan.per_track],
             "text": album.describe(plan)}
    store.log(None, None, "plan", f"#{request_id} {summary(plan) or 'nothing to plan'}")
    store.set_preview(preview_key(request_id),            # commits the event; `at`, `assign`, `responses`: server side
                      shown | {"at": time.time(), "assign": assign, "responses": responses})
    return public(shown)


def approve_request(store, request_id: int, approved_by: str = "michael") -> list[int]:
    """Michael's approval of the whole request (D7): one `album` approval per open row with its planned file (from
    the cached plan; None without one: the job plans first, or the row goes per track). Returns the approval ids."""
    req = _request(store, request_id)
    busy = [r["song_id"] for r in req["rows"]          # a row the running job has not reached yet is `needs_source`
            if r["status"] in ("sourcing", "verify") or (r.get("approval") or {}).get("result") == "started"]
    if busy:
        raise ValueError(f"request #{request_id}: {', '.join(busy)} in flight; approve it again once that has ended")
    assign = (store.preview(preview_key(request_id)) or {}).get("assign") or {}
    return [store.approve(r["song_id"], approved_by, (assign.get(r["song_id"]) or {}).get("candidate"), r["tier"],
                          purpose="album") for r in open_rows(req)]


def _to_download(row: dict | None) -> bool:
    """A row an approved fetch would download (not ok, removed, in flight, filed, or a question no download answers)."""
    return row is not None and filed_path(row.get("reason")) is None and (
        row["status"] in ("needs_source", "failed") or (row["status"] == "review" and retryable_review(row.get("reason"))))


def _new_file(row: dict | None) -> bool:
    """A row the library may already have (fetch's S1-07 rule): an external row that is not a copy, still to fetch."""
    return _to_download(row) and bool(row.get("external")) and copy_of(row) is None


def _forget(slskd, peer: str, names: set[str], before: set[str]) -> None:
    """Best effort: cancel and forget (remove=true) the job's records of `names`, so none lands unfiled later."""
    try:
        for t in transfer_files(slskd.downloads(peer)):
            if t.get("filename") in names and t.get("id") and t["id"] not in before:
                slskd.remove_download(peer, t["id"])
    except SlskdError:
        pass




def _started(slskd, peer: str, names: set[str], before: set[str], timeout_s: float, poll_s: float, sleep) -> bool:
    """Whether one of the job's records of `names` at `peer` is past queued (in progress, or ended) within
    `timeout_s` of the enqueue. slskd unreachable meanwhile counts as not started yet."""
    t0 = time.time()
    while True:
        try:
            states = [str(t.get("state") or "") for t in transfer_files(slskd.downloads(peer))
                      if t.get("filename") in names and t.get("id") not in before]
        except SlskdError:
            states = []
        if any(s and not s.startswith(NOT_STARTED) for s in states):
            return True
        if time.time() - t0 >= timeout_s:
            return False
        sleep(poll_s)


def _merge(first: list[dict], fresh: list[dict]) -> list[dict]:
    """The first search's responses with a fresh search's: a peer's fresh response replaces its earlier one."""
    peers = {r.get("username") for r in fresh}
    return [r for r in first if r.get("username") not in peers] + fresh


def _key(c: dict) -> tuple[str, str]:
    """A planned file's folder: (peer, directory), as sourcing.album groups them."""
    return c["username"], album.folder_of(c["filename"])


def _moves(dest: list[str]) -> str:
    """Where a switched folder's rows went: `8 rows → folder 2`, `7 rows → folder 2, 1 row → folder 3; 1 row per
    track`."""
    n_rows = lambda n: f"{n} row{'s' if n != 1 else ''}"
    counts: dict[str, int] = {}
    for d in dest:
        counts[d] = counts.get(d, 0) + 1
    folders = ", ".join(f"{n_rows(n)} → {d}" for d, n in counts.items() if d != "per track")
    per = counts.get("per track")
    return "; ".join(x for x in (folders, per and f"{n_rows(per)} per track") if x)


def run(request_id: int, approvals: list[dict], *, fetcher=fetch, plan_max_age_s: float = ALBUM_PLAN_MAX_AGE_S,
        start_timeout_s: float = ALBUM_START_TIMEOUT_S, **common) -> list[tuple[dict, str]]:
    """Run one request's `album` approvals (see the module docstring). `common` is fetch's keyword arguments (store,
    slskd, navidrome, ...). Returns (approval, outcome) for each approval claimed here; a lost claim (superseded,
    or taken since the list was read) is skipped. Never raises once an approval is claimed: an error is its outcome."""
    store, slskd = common["store"], common["slskd"]
    poll_s, sleep = common.get("poll_s", 1.0), common.get("sleep") or time.sleep
    claimed: list[dict] = []
    out: list[tuple[dict, str]] = []
    held: dict[int, tuple[dict, dict, str]] = {}   # approval id → (approval, file, outcome): failed in a folder a
                                                   # later switch may still take it from; marked at the end
    def done(a: dict, outcome: str) -> None:
        store.mark_approval_used(a["id"], outcome)
        out.append((a, outcome))

    def take_held(key: tuple[str, str]) -> list[tuple[dict, dict]]:
        """The rows that failed in folder `key` before it failed as a whole: they switch too."""
        return [held.pop(i)[:2] for i in [i for i, (_, hc, _) in held.items() if _key(hc) == key]]

    def spend(call) -> tuple[FetchResult | None, str]:
        try:
            r = call()
            return r, r.approval_result or f"{r.status}: {r.reason}"
        except Exception as e:                     # fetch has failed the row (or kept it `verify`) already
            return None, f"error: {type(e).__name__}: {e}"

    try:
        claimed += [a for a in approvals if store.claim_approval(a["id"])]
        todo = []
        for a in claimed:                          # the library first (S1-07): linked, not downloaded
            row = store.find_wanted(a["wanted_id"])
            hit = in_library(store, common["navidrome"], a["wanted_id"], row) if _new_file(row) else None
            if hit is not None:
                done(a, f"ok: in library ({hit.new_song_id})")
            else:
                todo.append(a)
        cache = store.preview(preview_key(request_id))
        if todo and (cache is None or time.time() - (cache.get("at") or 0) > plan_max_age_s):
            plan_request(store, slskd, request_id, poll_s=poll_s)
            cache = store.preview(preview_key(request_id))
        assign = (cache or {}).get("assign") or {}
        responses = (cache or {}).get("responses") or []
        labels = {_key(x["candidate"]): x["folder"] for x in assign.values()}
        plain: list[tuple[dict, dict | None]] = []     # (approval, prefer): fetched without a plan, by fetch's own
        planned: list[tuple[dict, dict]] = []          # rules (no file planned, or no download wanted any more)
        for a in todo:
            c = (assign.get(a["wanted_id"]) or {}).get("candidate")
            (planned.append((a, c)) if c is not None else plain.append((a, a["candidate"])))
        tried = {a["wanted_id"]: 1 for a, _ in planned}    # folders each row has been planned on
        failures: dict[tuple[str, str], list[str]] = {}    # folder → the basenames of its failed rows
        bad: set[tuple[str, str]] = set()                  # failed folders: never planned again
        stalled: set[str] = set()                          # peers that started nothing: none of their folders either
        while planned:
            moved: list[tuple[dict, dict]] = []            # this round's switched rows, with their failed folder's file
            why: dict[tuple[str, str], str] = {}           # this round's failed folders → the switch event's cause
            by_peer: dict[str, list[tuple[dict, dict]]] = {}
            for a, c in planned:
                row = store.find_wanted(a["wanted_id"])
                if not _to_download(row):
                    plain.append((a, a["candidate"]))
                elif planned_candidate(c, album.wanted(row), TIERS[row["tier"]]).rejected:
                    done(a, spend(lambda: fetcher(a["wanted_id"], approve=True, planned=True, prefer=c,
                                                  enqueued=set(), **common))[1])    # scored again: never enqueued
                else:
                    by_peer.setdefault(c["username"], []).append((a, c))
            for peer, items in by_peer.items():    # one POST per peer: every planned file of its folder(s)
                names, before = {c["filename"] for _, c in items}, None
                try:
                    listed = [t for t in transfer_files(slskd.downloads(peer)) if t.get("id")]
                    for t in listed:               # earlier attempts' final records go, as fetch does (S1-04)
                        if t.get("filename") in names and str(t.get("state", "")).startswith("Completed"):
                            slskd.remove_download(peer, t["id"])
                    before = {t["id"] for t in listed}
                    slskd.enqueue(peer, [{"filename": c["filename"], "size": c["size"]} for _, c in items])
                except SlskdError as e:            # the rows stay as they were; Michael may approve again
                    if before is not None:         # the POST failed: slskd may have taken part of it
                        _forget(slskd, peer, names, before)
                    for a, _ in items:
                        done(a, f"error: {type(e).__name__}: {e}")
                    continue
                if not _started(slskd, peer, names, before, start_timeout_s, poll_s, sleep):
                    _forget(slskd, peer, names, before)
                    stalled.add(peer)
                    for key in dict.fromkeys(_key(c) for _, c in items):
                        bad.add(key)
                        why[key] = f"{labels[key]}: no transfer started within {start_timeout_s:g} s"
                        moved += take_held(key)
                    moved += items
                    continue
                filed: set[str] = set()
                for a, c in items:
                    key = _key(c)
                    if key in bad:                 # its folder failed earlier in this round (its records forgotten)
                        moved.append((a, c))
                        continue
                    r, outcome = spend(lambda: fetcher(a["wanted_id"], approve=True, planned=True, prefer=c,
                                                       enqueued=before, **common))
                    if r is not None and r.filed is not None:
                        filed.add(a["wanted_id"])
                        done(a, outcome)
                        continue
                    _forget(slskd, peer, {c["filename"]}, before)    # not filed: nothing of it may land later
                    if r is None or r.status != "failed":          # an error (not the folder's), nothing downloaded
                        done(a, outcome)
                        continue
                    fails = failures.setdefault(key, [])
                    fails.append(split_remote(c["filename"])[1])
                    distrust = next((k for k in r.kinds if k in DISTRUST), None)
                    if not (r.again or distrust or len(fails) >= MAX_FOLDER_FAILURES):
                        held[a["id"]] = (a, c, outcome)            # an ordinary finding: this row only, for now
                        continue
                    bad.add(key)
                    why[key] = (f"{labels[key]} distrusted: {distrust} ({fails[-1]})" if distrust else
                                f"{labels[key]}: {r.reason} ({fails[-1]})" if r.again else
                                f"{labels[key]}: {len(fails)} failures ({', '.join(fails)})")
                    moved += take_held(key) + [(a, c)]
                    _forget(slskd, peer, {c2["filename"] for a2, c2 in items                 # the folder's queued rest
                                          if _key(c2) == key and a2["wanted_id"] not in filed}, before)
            planned = []
            if not moved:
                break
            dest: dict[int, str] = {}              # approval id → the moved row's new folder label, or "per track"
            go = [(a, c) for a, c in moved if tried[a["wanted_id"]] < 2]
            for a, _ in moved:
                if tried[a["wanted_id"]] >= 2:     # its one switched folder is used: per track (S2-05c caps it)
                    plain.append((a, None))
                    dest[a["id"]] = "per track"
            if go:                                 # re-plan over the first search plus a fresh one, failed folders out
                req = _request(store, request_id)
                try:
                    responses = _merge(responses, _search(slskd, req, poll_s))
                except SlskdError:                 # slskd busy or away: the first search's folders still serve
                    pass
                rows = {r["song_id"]: r for r in req["rows"]}
                want = [rows[a["wanted_id"]] for a, _ in go if a["wanted_id"] in rows]
                exclude = bad | {(r.get("username"), album.folder_of(f.get("filename", ""))) for r in responses
                                 if r.get("username") in stalled for f in r.get("files", [])}
                like = {rows[w]["track_no"]: x["candidate"]["length_s"] for w, x in assign.items()   # the release
                        if w in rows and rows[w].get("track_no") and x["candidate"].get("length_s")}  # being filed
                plan = album.plan_album(responses, want, policy=TIERS[want[0]["tier"]] if want else DEFAULT_POLICY,
                                        exclude=exclude, like=like, min_rows=1)
                new = {row["song_id"]: cand for row, cand in plan.assignments()}
                for a, _ in go:
                    cand = new.get(a["wanted_id"])
                    if cand is None:               # no other folder has it
                        plain.append((a, None))
                        dest[a["id"]] = "per track"
                        continue
                    c = cand.as_dict()
                    labels.setdefault(_key(c), f"folder {len(set(labels.values())) + 1}")
                    tried[a["wanted_id"]] += 1
                    planned.append((a, c))
                    dest[a["id"]] = labels[_key(c)]
            for key, cause in why.items():
                store.log(None, None, "switch", f"#{request_id} {cause}; "
                          f"{_moves([dest[a['id']] for a, c in moved if _key(c) == key])}")
            store.commit()
        for a, _, outcome in held.values():        # failed rows of folders that stayed trusted: final now
            done(a, outcome)
        held.clear()
        for a, prefer in plain:                    # an ordinary fetch (S2-05c caps the per-track one)
            done(a, spend(lambda: fetcher(a["wanted_id"], approve=True, prefer=prefer, **common))[1])
    except Exception as e:                         # e.g. a search: every claimed approval gets an outcome
        seen = {a["id"] for a, _ in out}
        for a in claimed:
            if a["id"] not in seen:
                done(a, held[a["id"]][2] if a["id"] in held else f"error: {type(e).__name__}: {e}")
    return out
