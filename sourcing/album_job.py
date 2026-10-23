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

S2-05b (switching folders on trouble) and S2-05c (the per-row attempt cap) build on this.
"""
from __future__ import annotations

import time

from crates.store import filed_path, public, retryable_review
from . import album
from .fetch import FetchResult, copy_of, fetch, in_library, planned_candidate
from .policy import DEFAULT_POLICY, TIERS
from .slskd_client import SlskdError, transfer_files

ALBUM_PLAN_MAX_AGE_S = 3600          # an older cached plan is made again before the enqueue (peers come and go)


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


def plan_request(store, slskd, request_id: int, policy=None, *, poll_s: float = 1.0) -> dict:
    """Search the album once, plan its open rows, cache the plan (`req-<id>`) and return what a client may see:
    folder labels, coverage, row → basename, the per-track rows. One `plan` event. Nothing is enqueued."""
    req = _request(store, request_id)
    rows = open_rows(req)
    policy = policy or (TIERS[rows[0]["tier"]] if rows else DEFAULT_POLICY)
    sid = slskd.search(" ".join(x for x in (req["artist"], req["album"]) if x))
    try:
        st = slskd.wait_search(sid, poll_s=poll_s, max_s=30)
        responses = slskd.search_responses(sid, expect=st.get("responseCount") or 0, poll_s=poll_s)
    finally:
        slskd.delete_search(sid)
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
    store.set_preview(preview_key(request_id), shown | {"at": time.time(), "assign": assign})     # commits the event
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


def run(request_id: int, approvals: list[dict], *, fetcher=fetch, plan_max_age_s: float = ALBUM_PLAN_MAX_AGE_S,
        **common) -> list[tuple[dict, str]]:
    """Run one request's `album` approvals (see the module docstring). `common` is fetch's keyword arguments (store,
    slskd, navidrome, ...). Returns (approval, outcome) for each approval claimed here; a lost claim (superseded,
    or taken since the list was read) is skipped. Never raises once an approval is claimed: an error is its outcome."""
    store, slskd = common["store"], common["slskd"]
    claimed: list[dict] = []
    out: list[tuple[dict, str]] = []

    def done(a: dict, outcome: str) -> None:
        store.mark_approval_used(a["id"], outcome)
        out.append((a, outcome))

    def spend(a: dict, call) -> FetchResult | None:
        try:
            r = call()
            outcome = r.approval_result or f"{r.status}: {r.reason}"
        except Exception as e:                     # fetch has failed the row (or kept it `verify`) already
            r, outcome = None, f"error: {type(e).__name__}: {e}"
        done(a, outcome)
        return r

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
            plan_request(store, slskd, request_id, poll_s=common.get("poll_s", 1.0))
            cache = store.preview(preview_key(request_id))
        assign = (cache or {}).get("assign") or {}
        by_peer: dict[str, list[tuple[dict, dict]]] = {}
        plain = []                                 # rows fetched without a plan: by its own rules (no file planned,
        for a in todo:                             # or no download wanted any more: ok, in flight, filed...)
            row = store.find_wanted(a["wanted_id"])
            c = (assign.get(a["wanted_id"]) or {}).get("candidate")
            if c is None or not _to_download(row):
                plain.append(a)
            elif planned_candidate(c, album.wanted(row), TIERS[row["tier"]]).rejected:
                spend(a, lambda: fetcher(a["wanted_id"], approve=True, planned=True, prefer=c, enqueued=set(),
                                         **common))         # scored again at the row's tier: never enqueued
            else:
                by_peer.setdefault(c["username"], []).append((a, c))
        for peer, items in by_peer.items():        # one POST per peer: every planned file of its folder(s)
            names, before = {c["filename"] for _, c in items}, None
            try:
                listed = [t for t in transfer_files(slskd.downloads(peer)) if t.get("id")]
                for t in listed:                   # earlier attempts' final records go, as fetch does (S1-04)
                    if t.get("filename") in names and str(t.get("state", "")).startswith("Completed"):
                        slskd.remove_download(peer, t["id"])
                before = {t["id"] for t in listed}
                slskd.enqueue(peer, [{"filename": c["filename"], "size": c["size"]} for _, c in items])
            except SlskdError as e:                # the rows stay as they were; Michael may approve again
                if before is not None:             # the POST failed: slskd may have taken part of it
                    _forget(slskd, peer, names, before)
                for a, _ in items:
                    done(a, f"error: {type(e).__name__}: {e}")
                continue
            for a, c in items:
                r = spend(a, lambda: fetcher(a["wanted_id"], approve=True, planned=True, prefer=c, enqueued=before,
                                             **common))
                if r is None or r.filed is None:   # not filed (raised, refused, failed): nothing may land later
                    _forget(slskd, peer, {c["filename"]}, before)
        for a in plain:                            # an ordinary fetch (S2-05c caps the per-track one)
            spend(a, lambda: fetcher(a["wanted_id"], approve=True, prefer=a["candidate"], **common))
    except Exception as e:                         # e.g. the re-plan's search: every claimed approval gets an outcome
        seen = {a["id"] for a, _ in out}
        for a in claimed:
            if a["id"] not in seen:
                done(a, f"error: {type(e).__name__}: {e}")
    return out
