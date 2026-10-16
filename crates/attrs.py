"""Playlist attributes that live in the playlist's own comment (D21): ``#crate`` and ``#tier:<t>``.

The comment is Michael's free text, edited in Navidrome and Amperfy, so the contract is narrow: ``parse``
never raises on anything he types (an unknown tier is a problem to show him), and ``write`` adds or removes
only our tokens, so every other byte of the comment (emoji, newlines, tabs, accents) survives. Pure: no
Subsonic, no store. crates.db only caches what this module reads out of the comment.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sourcing.policy import DEFAULT_TIER, TIERS, check_tier, tier_rank

CRATE_TAG = "#crate"
TIER_PREFIX = "#tier:"

# Whitespace-delimited, case-insensitive: "#crates", "x#crate" and "#crate," are not tokens.
_TOKEN = re.compile(r"(?<!\S)#(?:crate|tier:\S*)(?!\S)", re.IGNORECASE)


@dataclass(frozen=True)
class Attrs:
    crate: bool
    tier: str | None                    # a valid non-crate tier from #tier:, else None
    problems: tuple[str, ...] = ()

    @property
    def effective(self) -> str | None:
        """The tier the playlist is sourced at: crate when flagged, else its #tier:, else none."""
        return DEFAULT_TIER if self.crate else self.tier


def _is_crate(token: str) -> bool:
    return token.lower() in (CRATE_TAG, TIER_PREFIX + DEFAULT_TIER)


def _is_tier(token: str) -> bool:
    return token.lower().startswith(TIER_PREFIX)


def parse(comment: str | None) -> Attrs:
    crate, tiers, problems = False, [], []
    for m in _TOKEN.finditer(comment or ""):
        tok = m.group()
        if _is_crate(tok):
            crate = True
        elif _is_tier(tok):
            name = tok[len(TIER_PREFIX):].lower()
            if name in TIERS:
                tiers.append(name)
            else:
                problems.append(f"unknown tier {name!r} in {tok} (one of {', '.join(TIERS)})")
    tier = max(tiers, key=tier_rank) if tiers else None
    if len(set(tiers)) > 1:
        problems.append(f"several #tier: tags ({', '.join(tiers)}); using {tier}")
    return Attrs(crate, tier, tuple(problems))


UNSET: object = object()


def _remove(comment: str, drop) -> str:
    """Remove the tokens ``drop(token)`` accepts, each with one adjacent space or tab (the one before it,
    else the one after it). Newlines are never touched. Last token first, so earlier spans stay valid."""
    spans = [m.span() for m in _TOKEN.finditer(comment) if drop(m.group())]
    for start, end in reversed(spans):
        if start > 0 and comment[start - 1] in " \t":
            start -= 1
        elif end < len(comment) and comment[end] in " \t":
            end += 1
        comment = comment[:start] + comment[end:]
    return comment


def _append(comment: str, token: str) -> str:
    return comment + ("" if not comment or comment[-1].isspace() else " ") + token


def write(comment: str | None, *, crate: bool | None = None, tier: str | None | object = UNSET) -> str:
    """Return ``comment`` with the crate flag and/or tier set; nothing but our tokens changes.

    ``crate=False`` removes every crate token (``#crate``, ``#tier:crate``). ``tier="<t>"`` replaces every
    ``#tier:`` token with ``#tier:<t>``; tier ``"crate"`` means ``crate=True``; ``tier=None`` removes every
    ``#tier:`` token. An unknown tier raises ValueError (it is never written); an unknown tier already in the
    comment is left alone unless ``tier=`` is given.
    """
    c = comment or ""
    if tier is not UNSET and tier is not None:
        check_tier(tier)
        if tier == DEFAULT_TIER:
            crate = True
    if tier is not UNSET:
        keep = (lambda t: not _is_tier(t) or _is_crate(t)) if tier == DEFAULT_TIER else (lambda t: not _is_tier(t))
        c = _remove(c, lambda t: not keep(t))
        if tier is not None and tier != DEFAULT_TIER:
            c = _append(c, TIER_PREFIX + tier)
    if crate is True and not parse(c).crate:
        c = _append(c, CRATE_TAG)
    elif crate is False:
        c = _remove(c, _is_crate)
    return c
