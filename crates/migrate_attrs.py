"""One-time move of what only crates.db knows into playlist comments (M8 Task 4, D21).

From Task 3 on, the comment owns "is this playlist a crate" and its tier, and the first reconcile rebuilds
crates.db from comments. Today the live crate flag and the import tiers exist only in crates.db, so without this
migration that reconcile would switch the crate off and forget the tiers. The migration only ever ADDS tokens
(``#crate``, ``#tier:<t>``), through the same comment writer the setters use (write, read back, refuse on a
mismatch). It is a dry run unless asked to apply, and it refuses a playlist whose comment changed since the plan.

The old crate detection was a substring test; the new grammar ignores ``#crate.``, ``#crates`` and ``x#crate``.
``lookalikes`` lists those so Michael can decide; the migration never touches them.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sourcing.import_playlist import MARKER
from sourcing.policy import IMPORT_TIER, TIERS, max_tier
from subsonic.client import Playlist, SubsonicClient, SubsonicError
from . import attrs
from .reconcile import CommentNotKept, has_name_marker, is_marked, judge, write_comment
from .store import CrateStore


@dataclass(frozen=True)
class Change:
    playlist_id: str
    name: str
    old: str            # the whole comment, as planned against
    new: str            # the whole comment to write
    why: str


def plan(client: SubsonicClient, store: CrateStore) -> list[Change]:
    """What to add. An enabled crate in crates.db whose comment and name say nothing gets ``#crate``; an
    ``#imported`` playlist with no tier tag gets ``#tier:<t>``, the highest tier of its wanted rows, else the
    import tier (D15). Nothing is removed; disabled crates, readable tags and other playlists are left alone."""
    crates = {c.playlist_id for c in store.all(enabled_only=True)}
    out: list[Change] = []
    for p in client.playlists():
        old = p.comment or ""
        a = attrs.parse(old)
        if a.crate or has_name_marker(p.name):
            continue                                        # already a crate, by comment or by name
        if p.id in crates:
            out.append(Change(p.id, p.name, old, attrs.write(old, crate=True), "crates.db said crate"))
        elif MARKER in old and a.tier is None and not a.problems:     # an unreadable #tier: tag is never written over
            tier = max_tier(*(r["tier"] for r in store.external_for_playlist(p.id))) or IMPORT_TIER
            out.append(Change(p.id, p.name, old, attrs.write(old, tier=tier), f"imported at {tier} (D15)"))
    return out


def lookalikes(playlists: list[Playlist]) -> list[Playlist]:
    """Playlists whose comment or name contains ``#crate`` (any case, anywhere) but which the new grammar does
    not read as a crate: ``#crates``, ``#crate.``, ``x#crate``. The old substring test counted them."""
    return [p for p in playlists
            if "#crate" in f"{p.name or ''}\n{p.comment or ''}".lower() and not is_marked(p.name, p.comment)]


def _q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)               # one line, newlines visible as \n


def _would_queue(client: SubsonicClient, c: Change) -> str | None:
    """"<name> at <tier>: n of m tracks would be queued", for a change that gives a playlist a tier."""
    tier = attrs.parse(c.new).tier
    if tier is None:
        return None
    try:
        entries = client.playlist(c.playlist_id).entries
    except SubsonicError as e:
        return f"- {c.name} at {tier}: could not read the playlist ({e})"
    n = sum(judge(s, TIERS[tier])[0] != "ok" for s in entries)
    return f"- {c.name} at {tier}: {n} of {len(entries)} tracks would be queued"


def report(changes: list[Change], client: SubsonicClient, store: CrateStore) -> str:
    """Markdown for a phone: names, comments and counts only."""
    lines = ["# Playlist attributes: crates.db to comments", ""]
    if changes:
        lines += [f"## Changes ({len(changes)})", ""]
        lines += [f"- **{c.name}**: {_q(c.old)} → {_q(c.new)} ({c.why})" for c in changes]
        queued = [x for c in changes if (x := _would_queue(client, c))]
        if queued:
            lines += ["", "## Upgrades at the new tier", "",
                      "At the new tier, these tracks would be queued for an upgrade:", ""] + queued
    else:
        lines += ["Nothing to change: no comment needs a token added."]
    odd = lookalikes(client.playlists())
    if odd:
        planned = {c.playlist_id for c in changes}
        lines += ["", f"## Contains #crate but is not read as a crate ({len(odd)})", "",
                  "The old check was a substring test; these were crates then and are not now. "
                  "The migration leaves them alone. Fix the comment, or tell me to flag them.", ""]
        lines += [f"- **{p.name}**: comment {_q(p.comment or '')}"
                  + (" (crates.db says crate: #crate will be added)" if p.id in planned else "") for p in odd]
    lines += ["", f"Total: {len(changes)} to change, {len(odd)} to decide."]
    return "\n".join(lines)


def apply(client: SubsonicClient, changes: list[Change]) -> tuple[list[str], list[str]]:
    """Write each change. Returns (written names, refusals). A playlist whose comment is no longer ``old`` is
    refused (Michael edited it since the plan); a write Navidrome did not keep is refused too. One refusal does
    not stop the others."""
    written: list[str] = []
    refused: list[str] = []
    for c in changes:
        try:
            pl = client.playlist(c.playlist_id)
            if (pl.comment or "") != c.old:
                refused.append(f"{c.name}: comment changed since the plan ({_q(pl.comment or '')}); left alone")
                continue
            write_comment(client, pl, c.new)
        except (CommentNotKept, SubsonicError) as e:
            refused.append(f"{c.name}: {e}")
            continue
        written.append(c.name)
    return written, refused
