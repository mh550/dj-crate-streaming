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
  `in flight`, ...), as is a row without a planned file, and one whose own tier rejects its planned file goes per
  track (the plan is made at the first row's tier; S2-R1). A planned file its fetch did not file (an error, a failed
  check) and a POST slskd refused are cancelled and forgotten (remove=true), so nothing lands unfiled later. Each
  approval is marked used with its row's outcome; one being run refuses a second approve_request.

Switching (S2-05b): trouble with a planned file switches the rest of that folder's unfiled rows, the failed one
included, to another folder. The triggers: a transfer fetch says another peer may fix (`FetchResult.again`, S1-06:
fetch does not retry in planned mode; a planned transfer that timed out too, S2-R1), a peer that has started none of
its files `start_timeout_s` after the enqueue (`ALBUM_START_TIMEOUT_S`; then every folder of that peer), one verify
finding of the "not what it claims" kind (`DISTRUST`), or `MAX_FOLDER_FAILURES` failed rows in one folder (an
ordinary finding alone fails only its row, whose approval waits for the job's end: a later switch of its folder takes
it along). On a switch the folder's records of
rows not yet filed are cancelled and forgotten (remove=true), and the moved rows are planned again over the first
search's responses (cached with the plan) plus one fresh album search (when slskd answers), without the failed
folders, the release the job has been filing first (the planned files' lengths), one row being enough; rows already
filed stay. The cache keeps the failed folders and is marked stale, so approving the request again plans afresh
without them (S2-R1). One `switch` event per failed folder: `folder 1 distrusted: transcode (<basename>); 8 rows →
folder 2`.

The caps (S2-05c): a row gets its planned folder, one switched folder and one per-track fetch (an ordinary fetch,
`exclude` = every failed folder's peer, so neither its pick nor S1-06's retry is one of theirs); a row no folder
covers goes per track from the start, with the same exclusion. Each row's attempts are kept in order: its own
failure in a folder (`folder 1: transcode (<basename>)` for a distrust finding, else `folder 2: <fetch's reason>`),
or the folder's cause when it moved along (`folder 1: no transfer started within 600 s`). A row with attempts whose
per-track fetch files nothing fails with all of them: `folder 1: transcode (<basename>); folder 2: download ended:
Completed, Errored; per track: no acceptable candidate from another peer`, which is its approval's outcome too
(`failed: …`). The request's status follows its rows (`failed` none ok, `partly` some, store.request_status).

Playlists (S2-07): a `playlist` request (sourcing.requests.add_playlist) is approved in one go too. Its open rows
sharing `identity.loose` artist and album, MIN_GROUP_ROWS or more, are each one album job as above (`groups`): its own
search `"<artist> <album>"`, plan cached as `req-<id>:<group_key>` (`req-7:algreen/imstillinlovewithyou`) and events
`#<id> <artist> — <album>: …`;
lengths come from the rows' `duration` (a playlist has no release). Its other rows get ordinary `download` approvals
(per track, the worker's usual fetch).
"""
from __future__ import annotations

import contextlib
import time

from crates.store import filed_path, public, retryable_review
from . import album
from .identity import loose
from .fetch import (FetchResult, error_outcome, fetch, forget_finished, forget_new, in_library, new_file,
                    planned_candidate, search, to_download)
from .policy import DEFAULT_POLICY, TIERS
from .scorer import split_remote
from .slskd_client import SlskdError, transfer_files

ALBUM_PLAN_MAX_AGE_S = 3600          # an older cached plan is made again before the enqueue (peers come and go)
ALBUM_START_TIMEOUT_S = 600          # a peer that has started none of the job's files by then: its folders switch
DISTRUST = {"transcode", "fake_24bit", "fake_hires", "recording"}    # one such finding distrusts the whole folder
MAX_FOLDER_FAILURES = 2              # this many failed rows in one folder distrust it too
MIN_GROUP_ROWS = 3                   # a playlist's rows of one album go as an album job from this many (S2-07)
NOT_STARTED = ("Requested", "Queued", "Initializing")              # slskd states before a transfer starts


def preview_key(request_id: int, key: str | None = None) -> str:
    """The cached plan of the request (an album) or of one of its album groups (a playlist, `key`)."""
    return f"req-{request_id}" + (f":{key}" if key is not None else "")


def group_key(row: dict) -> str | None:
    """A playlist row's album group: `<loose artist>/<loose album>`; None without an album."""
    return f"{loose(row.get('artist'))}/{loose(row['album'])}" if loose(row.get("album")) else None


def open_rows(req: dict) -> list[dict]:
    """The rows an approval of the request covers: not `ok`, not `removed`, no file of theirs filed already, and not
    a question no download answers (a `review` row waiting for a pick: the library may have it; S3-03 review)."""
    return [r for r in req["rows"] if r["status"] not in ("ok", "removed") and filed_path(r.get("reason")) is None
            and (r["status"] != "review" or retryable_review(r.get("reason")))]


def groups(req: dict) -> list[dict]:
    """The request's album jobs, each {"key", "artist", "album", "rows"} (open rows). An album or track request is one,
    key None. A playlist request has one per album with MIN_GROUP_ROWS or more open rows (S2-07), in playlist order;
    its other open rows go per track (`per_track`)."""
    if req["kind"] != "playlist":
        return [{"key": None, "artist": req["artist"], "album": req["album"], "rows": open_rows(req)}]
    rows = _playlist_open(req)
    by: dict[str, list[dict]] = {}
    for r in rows:
        if group_key(r) is not None:
            by.setdefault(group_key(r), []).append(r)
    return [{"key": k, "artist": g[0]["artist"], "album": g[0]["album"], "rows": g}
            for k, g in by.items() if len(g) >= MIN_GROUP_ROWS]


def _playlist_open(req: dict) -> list[dict]:
    """A playlist request's open rows (open_rows: without the import's questions, an ambiguous `review` row)."""
    return open_rows(req)


def per_track(req: dict) -> list[dict]:
    """A playlist request's open rows in no album group: approved as ordinary downloads."""
    grouped = {r["song_id"] for g in groups(req) for r in g["rows"]}
    return [r for r in _playlist_open(req) if r["song_id"] not in grouped]


def approvable(req: dict) -> list[dict]:
    """The rows approve_request approves: its album groups' rows, then (a playlist) the per-track ones."""
    return [r for g in groups(req) for r in g["rows"]] + (per_track(req) if req["kind"] == "playlist" else [])


def _scope(store, request_id: int, key: str | None) -> dict:
    """The request as one album job sees it: itself (key None), or a playlist's album group `key` (every row of that
    album, the first one's artist and album spelling)."""
    req = _request(store, request_id)
    if key is None:
        return req
    rows = [r for r in req["rows"] if group_key(r) == key]
    return {**req, "artist": rows[0]["artist"] if rows else None, "album": rows[0]["album"] if rows else None,
            "rows": rows, "group": key}


def _tag(scope: dict) -> str:
    """How events name the job: `#12`, or `#12 Al Green — I'm Still in Love With You:` for a playlist's group."""
    return f"#{scope['id']}" + (f" {scope['artist']} — {scope['album']}:" if scope.get("group") else "")


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
    return search(slskd, " ".join(x for x in (req["artist"], req["album"]) if x), poll_s)


def plan_request(store, slskd, request_id: int, policy=None, *, poll_s: float = 1.0, group: str | None = None,
                 lock=contextlib.nullcontext()) -> dict:
    """Search the album once, plan its open rows, cache the plan (`req-<id>`) and return what a client may see:
    folder labels, coverage, row → basename, the per-track rows. One `plan` event. Nothing is enqueued. The cache
    also keeps, server side only, `at`, `assign` and the search's `responses` (a switch plans over them again).
    A playlist request plans each album group so (`group`: that one only) and returns {"request_id", "albums": [each
    group's plan, with its artist and album], "per_track": [its rows in no group]}.
    `lock` (the service's) is held for the store's reads and writes, never during a search (S3-03); the folders a
    job (another process) failed meanwhile are read again after it, and stay out and failed."""
    with lock:
        req = _request(store, request_id)
        if req["kind"] == "playlist" and group is None:
            keys, singles = [g["key"] for g in groups(req)], per_track(req)
    if req["kind"] == "playlist" and group is None:
        return public({"request_id": request_id,
                       "albums": [plan_request(store, slskd, request_id, policy, poll_s=poll_s, group=k, lock=lock)
                                  for k in keys],
                       "per_track": [{"id": r["song_id"], "title": r["title"]} for r in singles]})
    with lock:
        req = _scope(store, request_id, group)
    responses = _search(slskd, req, poll_s)
    with lock:
        return _plan(store, request_id, group, policy, responses)


def _plan(store, request_id: int, group: str | None, policy, responses: list[dict]) -> dict:
    """plan_request's plan over the search's `responses`, cached; the caller holds the lock."""
    req = _scope(store, request_id, group)
    rows = _playlist_open(req) if group else open_rows(req)      # a group plans the rows approve_request approves
    policy = policy or (TIERS[rows[0]["tier"]] if rows else DEFAULT_POLICY)
    failed = _failed(store.preview(preview_key(request_id, group)))
    plan = album.plan_album(responses, rows, policy=policy, exclude=failed)
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
             "text": album.describe(plan)} | ({"artist": req["artist"], "album": req["album"]} if group else {})
    store.log(None, None, "plan", f"{_tag(req)} {summary(plan) or 'nothing to plan'}")
    store.set_preview(preview_key(request_id, group),     # commits the event; `at`, `assign`, `responses`: server side
                      shown | {"at": time.time(), "assign": assign, "responses": responses,
                               "failed": sorted(failed)})
    return public(shown)


def shown(store, req: dict) -> dict | None:
    """The request's cached plan as the API shows it (S3-03): {"folders": [{"label", "coverage", "rows": [{"id",
    "file"}]}], "perTrack": [row ids], "ts"}, `ts` when it was made (None once a folder failed: the job plans again);
    folder labels and basenames, never a peer. A playlist's: {"albums": [each album group's, with its "artist" and
    "album"], "perTrack": its rows in no group}. None while the request, or one of its album groups, has none cached."""
    if req["kind"] != "playlist":
        return _shown(store.preview(preview_key(req["id"])))
    albums = []
    for g in groups(req):
        plan = _shown(store.preview(preview_key(req["id"], g["key"])))
        if plan is None:
            return None
        albums.append({"artist": g["artist"], "album": g["album"]} | plan)
    return {"albums": albums, "perTrack": [r["song_id"] for r in per_track(req)]}


def _shown(cache: dict | None) -> dict | None:
    if cache is None:
        return None
    return public({"folders": [{"label": f["label"], "coverage": f["covers"],
                                "rows": [{"id": r["id"], "file": r["basename"]} for r in f["rows"]]}
                               for f in cache["folders"]],
                   "perTrack": [r["id"] for r in cache["per_track"]], "ts": cache.get("at") or None})


def _failed(cache: dict | None) -> set[tuple[str, str]]:
    """The folders (peer, directory) earlier runs of the job failed (a switch's cause): never planned again."""
    return {(p, d) for p, d in (cache or {}).get("failed") or []}


def approve_request(store, request_id: int, approved_by: str = "michael") -> list[int]:
    """Michael's approval of the whole request (D7): one `album` approval per open row with its planned file (from
    the cached plan; None without one: the job plans first, or the row goes per track). Returns the approval ids.
    A playlist request: `album` approvals for its album groups' rows, `download` approvals for the rest (S2-07)."""
    req = _request(store, request_id)
    busy = [r["song_id"] for r in req["rows"]          # a row the running job has not reached yet is `needs_source`
            if r["status"] in ("sourcing", "verify") or (r.get("approval") or {}).get("result") == "started"]
    if busy:
        raise ValueError(f"request #{request_id}: {', '.join(busy)} in flight; approve it again once that has ended")
    ids = []
    for g in groups(req):
        cache = store.preview(preview_key(request_id, g["key"])) or {}
        assign = cache.get("assign") or {} if cache.get("at") else {}    # stale (a folder failed): the job plans
        ids += [store.approve(r["song_id"], approved_by, (assign.get(r["song_id"]) or {}).get("candidate"), r["tier"],
                              purpose="album") for r in g["rows"]]
    if req["kind"] == "playlist":
        ids += [store.approve(r["song_id"], approved_by, None, r["tier"]) for r in per_track(req)]
    return ids


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


def run(request_id: int, approvals: list[dict], **kw) -> list[tuple[dict, str]]:
    """Run one request's `album` approvals (see the module docstring); a playlist request's per album group, each as
    its own job. `kw` is _run's. Returns (approval, outcome) for each approval claimed here; a lost claim (superseded,
    or taken since the list was read) is skipped. Never raises once an approval is claimed: an error is its outcome."""
    store = kw["store"]
    if (store.request(request_id) or {}).get("kind") != "playlist":
        return _run(request_id, None, approvals, **kw)
    by: dict[str | None, list[dict]] = {}
    for a in approvals:
        by.setdefault(group_key(store.find_wanted(a["wanted_id"]) or {"album": None}), []).append(a)
    return [x for key, group in by.items()          # a row that left its album since (no album): per track
            for x in (_run(request_id, key, group, **kw) if key is not None else _plain(group, **kw))]


def _plain(approvals: list[dict], *, fetcher=fetch, plan_max_age_s=None, start_timeout_s=None,
           **common) -> list[tuple[dict, str]]:
    """Each approval claimed and fetched as an ordinary download (the worker's own way), no plan."""
    store, out = common["store"], []
    for a in approvals:
        if not store.claim_approval(a["id"]):
            continue
        try:
            outcome = fetcher(a["wanted_id"], approve=True, prefer=a["candidate"], **common).outcome
        except Exception as e:
            outcome = error_outcome(e)
        store.mark_approval_used(a["id"], outcome)
        out.append((a, outcome))
    return out


def _run(request_id: int, group: str | None, approvals: list[dict], *, fetcher=fetch,
         plan_max_age_s: float = ALBUM_PLAN_MAX_AGE_S, start_timeout_s: float = ALBUM_START_TIMEOUT_S,
         **common) -> list[tuple[dict, str]]:
    """One album job: the request's (group None) or a playlist's album group `group` (a group_key). `common` is fetch's keyword
    arguments (store, slskd, navidrome, ...)."""
    store, slskd = common["store"], common["slskd"]
    poll_s, sleep = common.get("poll_s", 1.0), common.get("sleep") or time.sleep
    claimed: list[dict] = []
    out: list[tuple[dict, str]] = []
    sent: list[tuple[str, set[str], set[str]]] = []   # each POST's (peer, its files, the record ids before it)
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
            return r, r.outcome
        except Exception as e:                     # fetch has failed the row (or kept it `verify`) already
            return None, error_outcome(e)

    try:
        claimed += [a for a in approvals if store.claim_approval(a["id"])]
        todo = []
        for a in claimed:                          # the library first (S1-07): linked, not downloaded
            row = store.find_wanted(a["wanted_id"])
            hit = (in_library(store, common["navidrome"], a["wanted_id"], row)
                   if to_download(row) and new_file(row) else None)
            if hit is not None:
                done(a, f"ok: in library ({hit.new_song_id})")
            else:
                todo.append(a)
        cache = store.preview(preview_key(request_id, group))
        if todo and (cache is None or time.time() - (cache.get("at") or 0) > plan_max_age_s):
            plan_request(store, slskd, request_id, poll_s=poll_s, group=group)
            cache = store.preview(preview_key(request_id, group))
        assign = (cache or {}).get("assign") or {}
        responses = (cache or {}).get("responses") or []
        labels = {_key(x["candidate"]): x["folder"] for x in assign.values()}
        plain: list[tuple[dict, dict | None]] = []     # (approval, prefer): fetched without a plan, by fetch's own
        planned: list[tuple[dict, dict]] = []          # rules (no file planned, or no download wanted any more)
        for a in todo:
            c = (assign.get(a["wanted_id"]) or {}).get("candidate")
            (planned.append((a, c)) if c is not None else plain.append((a, a["candidate"])))
        tried = {a["wanted_id"]: 1 for a, _ in planned}    # folders each row has been planned on
        attempts: dict[str, list[str]] = {}                # row → its failed folders: `folder 1: <why>`, in order
        failures: dict[tuple[str, str], list[str]] = {}    # folder → the basenames of its failed rows
        bad = _failed(cache)                               # failed folders (this run's, earlier runs'): never again
        stalled: set[str] = set()                          # peers that started nothing: none of their folders either
        while planned:
            moved: list[tuple[dict, dict]] = []            # this round's switched rows, with their failed folder's file
            why: dict[tuple[str, str], str] = {}           # this round's failed folders → the switch event's cause
            cause: dict[tuple[str, str], str] = {}         # → the attempt of a row moved along: `folder 1: <why>`
            by_peer: dict[str, list[tuple[dict, dict]]] = {}
            for a, c in planned:
                row = store.find_wanted(a["wanted_id"])
                if not to_download(row):
                    plain.append((a, a["candidate"]))
                elif planned_candidate(c, album.wanted(row), TIERS[row["tier"]]).rejected:
                    plain.append((a, None))        # its own tier rejects the file (the plan's is the first row's,
                else:                              # or the file changed since): never enqueued, per track
                    by_peer.setdefault(c["username"], []).append((a, c))
            for peer, items in by_peer.items():    # one POST per peer: every planned file of its folder(s)
                names, before = {c["filename"] for _, c in items}, None
                try:
                    before = forget_finished(slskd, peer, names)     # as fetch does (S1-04)
                    sent.append((peer, names, before))
                    slskd.enqueue(peer, [{"filename": c["filename"], "size": c["size"]} for _, c in items])
                except SlskdError as e:            # the rows stay as they were; Michael may approve again
                    if before is not None:         # the POST failed: slskd may have taken part of it
                        forget_new(slskd, peer, names, before)
                    for a, _ in items:
                        done(a, error_outcome(e))
                    continue
                if not _started(slskd, peer, names, before, start_timeout_s, poll_s, sleep):
                    forget_new(slskd, peer, names, before)
                    stalled.add(peer)
                    for key in dict.fromkeys(_key(c) for _, c in items):
                        bad.add(key)
                        why[key] = f"{labels[key]}: no transfer started within {start_timeout_s:g} s"
                        cause[key] = why[key]
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
                    forget_new(slskd, peer, {c["filename"]}, before)    # not filed: nothing of it may land later
                    if r is None or r.status != "failed":          # an error (not the folder's), nothing downloaded
                        done(a, outcome)
                        continue
                    fails = failures.setdefault(key, [])
                    fails.append(split_remote(c["filename"])[1])
                    distrust = next((k for k in r.kinds if k in DISTRUST), None)
                    own = f"{distrust} ({fails[-1]})" if distrust else r.reason
                    attempts.setdefault(a["wanted_id"], []).append(f"{labels[key]}: {own}")
                    if not (r.again or distrust or len(fails) >= MAX_FOLDER_FAILURES):
                        held[a["id"]] = (a, c, outcome)            # an ordinary finding: this row only, for now
                        continue
                    bad.add(key)
                    why[key] = (f"{labels[key]} distrusted: {own}" if distrust else
                                f"{labels[key]}: {r.reason} ({fails[-1]})" if r.again else
                                f"{labels[key]}: {len(fails)} failures ({', '.join(fails)})")
                    cause[key] = f"{labels[key]}: {own}" if distrust else why[key]
                    moved += take_held(key) + [(a, c)]
                    forget_new(slskd, peer, {c2["filename"] for a2, c2 in items                 # the folder's queued rest
                                          if _key(c2) == key and a2["wanted_id"] not in filed}, before)
            planned = []
            if not moved:
                break
            for a, c in moved:                     # a row moved along (not its own failure): its folder's cause
                if len(attempts.setdefault(a["wanted_id"], [])) < tried[a["wanted_id"]]:
                    attempts[a["wanted_id"]].append(cause[_key(c)])
            dest: dict[int, str] = {}              # approval id → the moved row's new folder label, or "per track"
            go = [(a, c) for a, c in moved if tried[a["wanted_id"]] < 2]
            for a, _ in moved:
                if tried[a["wanted_id"]] >= 2:     # its one switched folder is used: per track (S2-05c caps it)
                    plain.append((a, None))
                    dest[a["id"]] = "per track"
            if go:                                 # re-plan over the first search plus a fresh one, failed folders out
                req = _scope(store, request_id, group)
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
            for key, event in why.items():
                store.log(None, None, "switch", f"{_tag(_scope(store, request_id, group))} {event}; "
                          f"{_moves([dest[a['id']] for a, c in moved if _key(c) == key])}")
            store.commit()
        if bad - _failed(cache):                   # an approval again plans afresh, without them
            store.set_preview(preview_key(request_id, group), (cache or {}) | {"at": 0, "failed": sorted(bad)})
        def give_up(a: dict, last: list[str]) -> str:
            """Fail the row with every attempt in its reason; the approval's outcome says the same."""
            reason = "; ".join(attempts[a["wanted_id"]] + last)
            store.set_wanted_status(a["wanted_id"], "failed", reason)
            return f"failed: {reason}"

        for a, _, outcome in held.values():        # failed rows of folders that stayed trusted: final now
            done(a, give_up(a, []) if len(attempts[a["wanted_id"]]) > 1 else outcome)   # a switched one lists both
        held.clear()
        failed_peers = {peer for peer, _ in bad}   # a stalled peer's folders are among them
        for a, prefer in plain:                    # an ordinary fetch, never from a failed peer: the last attempt
            r, outcome = spend(lambda: fetcher(a["wanted_id"], approve=True, prefer=prefer, exclude=failed_peers,
                                               **common))
            row = store.find_wanted(a["wanted_id"])
            if attempts.get(a["wanted_id"]) and row and row["status"] in ("failed", "needs_source") \
                    and filed_path(row.get("reason")) is None:  # its folders failed, and so did this: every attempt
                outcome = give_up(a, [f"per track: {r.reason if r is not None else outcome}"])  # or the error
            done(a, outcome)
    except Exception as e:                         # e.g. a search: every claimed approval gets an outcome, and
        for peer, names, before in sent:           # nothing sent lands unfiled later (a filed file's record goes too)
            forget_new(slskd, peer, names, before)
        seen = {a["id"] for a, _ in out}
        for a in claimed:
            if a["id"] not in seen:
                done(a, held[a["id"]][2] if a["id"] in held else error_outcome(e))
    return out
