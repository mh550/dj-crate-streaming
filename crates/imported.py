"""One-time move of the `#imported` comment marker into crates.db `imported_playlists` (N2-03, D33/D37).

Before D33 a playlist comment said "made by import-playlist" with the token `#imported`; now the crates.db row does,
and import-playlist reads only the row. This records every playlist of ours whose comment still carries the token,
then strips the token through the one comment writer (send, read back). The row is committed before the comment
changes, so the playlist is never foreign to import-playlist in between; a failed write leaves the row, and a re-run
finishes the strip. Another user's playlist is listed and never written; `x#imported` is not the token.
The `imported` event holds the old comment verbatim: it is the reverse log.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from sourcing.import_playlist import _MARKER_TOKEN, is_imported
from subsonic.client import SubsonicClient
from .reconcile import CommentNotKept, write_comment
from .store import CrateStore

SOURCE = "migrated"
_SP = r"[^\S\r\n]*"                                  # whitespace within a line (spaces, tabs, NBSP; not CR/LF)
_TOKEN_AND_SPACES = re.compile(rf"(?:{_SP}{_MARKER_TOKEN.pattern})+{_SP}", re.IGNORECASE)   # a run of tokens
_EDGE_SPACES = re.compile(rf"^{_SP}|{_SP}$")


@dataclass(frozen=True)
class Step:
    playlist_id: str
    name: str
    owner: str | None
    old: str                 # the whole comment, as planned against
    new: str | None          # the comment to write; None when skipped
    action: str              # "record + strip" | "strip" (row already there) | "skip" (another user's)


def strip_marker(comment: str) -> str:
    """Each run of whole `#imported` tokens, with the whitespace around it, becomes one space; a line that lost a
    token drops the whitespace left at its start or end (a CRLF line keeps its CR). Other lines stay byte for byte.
    A bare marker becomes ""."""
    out = []
    for line in comment.split("\n"):
        body, cr = (line[:-1], "\r") if line.endswith("\r") else (line, "")
        new, n = _TOKEN_AND_SPACES.subn(" ", body)
        out.append(_EDGE_SPACES.sub("", new) + cr if n else line)
    return "\n".join(out)


def plan(client: SubsonicClient, store: CrateStore) -> list[Step]:
    out = []
    for p in client.playlists():
        old = p.comment or ""
        if not is_imported(old):
            continue
        if p.owner != client.user:
            out.append(Step(p.id, p.name, p.owner, old, None, "skip"))
        else:
            action = "strip" if store.is_playlist_imported(p.id) else "record + strip"
            out.append(Step(p.id, p.name, p.owner, old, strip_marker(old), action))
    return out


def report(steps: list[Step]) -> str:
    if not steps:
        return "nothing to migrate"
    lines = []
    for s in steps:
        if s.action == "skip":
            lines.append(f"skipped: owned by {s.owner or '?'}: {s.name} ({s.playlist_id})")
        else:
            lines.append(f"would {s.action}: {s.name} ({s.playlist_id}): "
                         f"{json.dumps(s.old, ensure_ascii=False)}  →  {json.dumps(s.new, ensure_ascii=False)}")
    return "\n".join(lines)


def apply(client: SubsonicClient, store: CrateStore, steps: list[Step]) -> tuple[list[str], list[str]]:
    """Record, commit, then strip, per playlist. Returns (names migrated, one failure line per playlist not
    finished, naming it); a failure does not stop the others. A comment changed since the plan is refused before
    anything is recorded."""
    done, failed = [], []
    for s in steps:
        if s.action == "skip":
            continue
        try:
            pl = client.playlist(s.playlist_id)
            if (pl.comment or "") != s.old:
                failed.append(f"{s.name} ({s.playlist_id}): comment changed since the plan; run again")
                continue
            if s.action == "record + strip":
                store.mark_playlist_imported(s.playlist_id, s.name, SOURCE,
                                             detail=f"migrated from comment {json.dumps(s.old, ensure_ascii=False)}")
                store.commit()
            write_comment(client, pl, s.new)
            done.append(s.name)
        except CommentNotKept as e:                  # its message starts with the name already
            failed.append(f"({s.playlist_id}) {e}")
        except Exception as e:                       # a SubsonicError, a gone playlist: report, go on
            failed.append(f"{s.name} ({s.playlist_id}): {e}")
    return done, failed


def list_lines(store: CrateStore) -> list[str]:
    """`imported list`: one line per row (id, name, source, first recorded), or "no imported playlists"."""
    return [f"{r['playlist_id']}  {r['name']}  {r['source']}  "
            f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(r['imported_at']))}"
            for r in store.imported_playlists()] or ["no imported playlists"]
