"""The identity picker's data (M9 §5a, R7): the proposal rows Michael decides on, and his taps.

`identity_backfill propose` writes `<identity_dir>/identity-proposal.json`; this module reads it and serves the rows
whose ids wait for Michael (`search`, `ambiguous`, `none` with candidates, and `conflict`/`error`, which can only be
skipped). A tap is recorded in `<identity_dir>/identity-choices.json` (one entry per path, the latest tap wins) and
logged as an `identity_pick` event. That file is the only one this module writes; a body's `path` is only ever a key
among the proposal's rows, never opened. Nothing here writes a tag: `identity_backfill apply --choices` does that,
run by Michael (plan docs/plans/2026-10-21-r7-identity-picker.md).
"""
from __future__ import annotations

import datetime
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from scripts.identity_backfill import (CHOICE_ACTIONS, CHOICES, PROPOSAL, _canon, _navidrome_ids, choice_problem,
                                       write_atomic)
from sourcing.identity import loose

PICKER = ("search", "ambiguous", "none", "conflict", "error")    # the order the rows come in
SKIP_ONLY = ("conflict", "error")
MB_RECORDING = "https://musicbrainz.org/recording/"
# an absolute path: quoted as Python quotes it ('…', or "…" when the name holds a '), or bare after a space
_ABS_PATH = re.compile(r"""'(/[^']*)'|"(/[^"]*)"|(?<![^\s(=])(/[^\s'"/][^\s'"]*)""")
_PATH_START = r"""(?<![^\s'"(=])"""                           # where a path may begin: not inside "AC/DC" or 3:13/3:15
_ROW_TYPES = {"file": dict, "write": dict, "candidates": list, "candidate_details": list}


class Refused(Exception):
    """A request the picker answers with this HTTP status and message (the service turns it into an ApiError)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def load_proposal(identity_dir: Path) -> dict:
    try:
        doc = json.loads((identity_dir / PROPOSAL).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refused(404, "no identity proposal yet: run identity_backfill propose") from None
    except (OSError, ValueError) as e:
        raise Refused(503, f"{PROPOSAL} cannot be read ({type(e).__name__}): run identity_backfill propose again") from None
    if not (isinstance(doc, dict) and isinstance(doc.get("proposals"), list)
            and all(_well_formed(r) for r in doc["proposals"])):
        raise Refused(503, f"{PROPOSAL} is not a proposal: run identity_backfill propose again")
    return doc


def _well_formed(row) -> bool:
    """A row whose fields the picker reads have their types (a missing field is fine)."""
    if not isinstance(row, dict):
        return False
    return all(field not in row or isinstance(row[field], kind) for field, kind in _ROW_TYPES.items())


def load_choices(identity_dir: Path) -> dict:
    """{"created", "choices": {path: entry}}; empty when there is none yet. A file that cannot be read is a 503 and
    is never overwritten: Michael's earlier taps are in it."""
    try:
        doc = json.loads((identity_dir / CHOICES).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"choices": {}}
    except (OSError, ValueError) as e:
        raise Refused(503, f"{CHOICES} cannot be read ({type(e).__name__}): fix or move it; it is kept as it is") from None
    if not (isinstance(doc, dict) and isinstance(doc.get("choices"), dict)
            and all(isinstance(c, dict) for c in doc["choices"].values())):
        raise Refused(503, f"{CHOICES} is not a choices file: fix or move it; it is kept as it is")
    return doc


def picker_rows(doc: dict) -> dict[str, dict]:
    """path → row, for the rows that offer Michael something to decide (a `none` row needs candidates). A row
    skipped in the proposal JSON is left out: that skip is final (`apply`), so a tap on it could do nothing. So is a
    path the proposal holds twice: `apply --choices` refuses it (which row was tapped?)."""
    held = Counter(r.get("path") for r in doc["proposals"])
    return {r["path"]: r for r in doc["proposals"]
            if isinstance(r.get("path"), str) and held[r["path"]] == 1 and r.get("cls") in PICKER
            and not r.get("skip") and (r["cls"] != "none" or r.get("candidates"))}


def _suggested(row: dict, details: list[dict]) -> str | None:
    """The only candidate with a release named like the file's album (Q8, D47), else None. Every release when the
    row has them (`releases`), else the first one (a proposal from before R7)."""
    album = loose(str((row.get("file") or {}).get("album") or ""))
    if not album or row["cls"] not in ("ambiguous", "none"):
        return None
    hits = [d.get("id") for d in details
            if any(isinstance(x, str) and loose(x) == album
                   for x in (d["releases"] if isinstance(d.get("releases"), list) else [d.get("release")]))]
    return hits[0] if len(hits) == 1 else None


def _choice_view(row: dict, entry: dict | None) -> dict | None:
    if entry is None:
        return None
    return {k: entry.get(k) for k in ("action", "mbid", "at", "decided_by")} | {"stale": bool(choice_problem(row, entry))}


def _scrub(why: str, root: str) -> str:
    """`why` without absolute paths: an exception's text can hold one (the file's, or a cache file's). A path in the
    library loses the root; any other keeps only its name."""
    if root.rstrip("/"):
        why = re.sub(_PATH_START + re.escape(root.rstrip("/") + "/"), "", why)

    def name(m):
        quote = "'" if m.group(1) is not None else '"' if m.group(2) is not None else ""
        path = next(g for g in m.groups() if g is not None)
        return f"{quote}…/{path.rstrip('/').rsplit('/', 1)[-1]}{quote}"
    return _ABS_PATH.sub(name, why)


def _view(row: dict, root: str, song_ids: dict[str, str], entry: dict | None) -> dict:
    cls = row["cls"]
    details = [d for d in row.get("candidate_details") or [] if isinstance(d, dict) and isinstance(d.get("id"), str)]
    why = _scrub(str(row.get("why") or ""), root)
    proposed = None
    if cls == "search":
        rid = str((row.get("write") or {}).get("mb_trackid") or "")      # what an Accept is checked against
        proposed = {"id": rid, "title": row.get("title"), "length_s": row.get("length_s"), "url": MB_RECORDING + rid}
    return {"path": row["path"], "cls": cls, "why": why, "file": row.get("file") or {},
            "songId": song_ids.get(row["path"]), "proposed": proposed,
            "candidates": [{k: d.get(k) for k in ("id", "title", "artist", "length_s", "release", "disambiguation")}
                           | {"url": MB_RECORDING + d["id"]} for d in details],
            "suggested": _suggested(row, details), "choice": _choice_view(row, entry)}


def listing(identity_dir: Path, navidrome_db: Path | None, cls: str | None = None) -> dict:
    """GET /api/identity: the picker rows in class order, then by path; `counts` before the class filter. A
    navidrome.db that cannot be read raises sqlite3.Error (the service's 503)."""
    if cls is not None and cls not in PICKER:
        raise Refused(400, f"class must be one of {', '.join(PICKER)}")
    doc = load_proposal(identity_dir)
    rows = picker_rows(doc)
    choices = load_choices(identity_dir)["choices"]
    song_ids = _navidrome_ids(navidrome_db) if navidrome_db else {}
    root = doc.get("music_root") if isinstance(doc.get("music_root"), str) else ""
    order = sorted(rows.values(), key=lambda r: (PICKER.index(r["cls"]), r["path"]))
    return {"created": doc.get("created"), "counts": {c: sum(r["cls"] == c for r in order) for c in PICKER},
            "rows": [_view(r, root, song_ids, choices.get(r["path"])) for r in order if cls in (None, r["cls"])]}


def _checked(row: dict, action, mbid) -> str | None:
    """The canonical mbid the tap records (None for a skip), or Refused with the plan's status."""
    cls = row["cls"]
    if action not in CHOICE_ACTIONS:
        raise Refused(400, "action must be accept, choose or skip")
    if action == "skip":
        return None
    if cls in SKIP_ONLY:
        raise Refused(409, f"{cls} rows can only be skipped")
    if action == "accept":
        if cls != "search":
            raise Refused(400, "accept is for search rows; choose a candidate")
        if not _canon(mbid):
            raise Refused(400, "accept needs the mbid of the recording the page showed")
        if _canon(mbid) != _canon((row.get("write") or {}).get("mb_trackid")):
            raise Refused(409, "the proposal changed since the page loaded; reload")
        return _canon(mbid)
    if cls == "search":
        raise Refused(400, "a search row is accepted or skipped (it has no candidates)")
    if mbid is None:
        raise Refused(400, "choose needs the mbid of one of the row's candidates")
    if not _canon(mbid) or _canon(mbid) not in {_canon(c) for c in row.get("candidates") or []}:
        raise Refused(400, f"{mbid} is not one of the row's candidates")
    return _canon(mbid)


def record(identity_dir: Path, body, store, navidrome_db: Path | None) -> dict:
    """POST /api/identity/choice: check the tap against the row, write the choices file, then log `identity_pick`
    and commit. The caller holds the service's write lock (one read-modify-write at a time)."""
    rows = picker_rows(load_proposal(identity_dir))
    choices = load_choices(identity_dir)
    if not isinstance(body, dict):
        raise Refused(400, "body must be a JSON object")
    path = body.get("path")
    row = rows.get(path) if isinstance(path, str) else None
    if row is None:
        raise Refused(400, f"not in the identity proposal: {path}")
    action = body.get("action")
    mbid = _checked(row, action, body.get("mbid"))
    entry = {"action": action, "mbid": mbid, "cls": row["cls"], "size": row.get("size"),
             "mtime_ns": row.get("mtime_ns"), "at": _now(), "decided_by": "michael"}
    problem = choice_problem(row, entry)
    if problem:                                             # _checked and choice_problem agree; never record a misfit
        raise Refused(400, f"{path}: {problem}")
    choices.setdefault("created", entry["at"])
    choices["choices"][path] = entry
    try:
        write_atomic(identity_dir / CHOICES, json.dumps(choices, ensure_ascii=False, indent=1) + "\n")
    except OSError as e:
        raise Refused(503, f"could not save the choice: {e.strerror or type(e).__name__}") from None
    try:
        song_id = _navidrome_ids(navidrome_db).get(path) if navidrome_db else None
    except sqlite3.Error:                                   # the event only names the song when it can
        song_id = None
    said = f"{action} {mbid}" if mbid else action
    try:
        store.log(None, song_id, "identity_pick", f"{row['cls']} {path}: {said}; decided_by=michael")
        store.commit()
    except sqlite3.Error as e:                              # crates.db busy: the choice stands, its event does not
        store.db.rollback()
        raise Refused(503, f"the choice is saved, but its identity_pick event could not be logged ({e}): "
                           "tap it again to log it") from None
    return {"path": path, "choice": _choice_view(row, entry)}
