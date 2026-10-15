"""The tag fixes behind what Amperfy shows (spec §3 backfill), as pure functions on a dict of tags.

`clean(fields)` returns (changed fields only, names of the rules that fired). Rules, in order:

  junk         "100 - Smokey Robinson - Why You Wanna See My Bad Side.mp3" as title (and artist)
  split        no artist tag and exactly one " - " in the title: "September - Ostavi Trag"
  sockseek     "Artist - 'Title' (Album)"; the album is taken only when the file has none
  prefix       "Pepe Link - Vem Menina" by Pepe Link
  remaster     " - Remastered 1999", " - 2012 Remaster" … → title; the suffix goes to comments as "version: …"
  compilation  a file under Compilations/ gets albumartist = artist, comp off (Michael's folders are
               not Various-Artists albums)

Left alone on purpose: " - Live" (a different recording; D14 default), mixes, edits, demos,
"Title - Artist" suffixes (could be a featured artist or a label: not ours to guess).
Running `clean` on its own output changes nothing.
"""
from __future__ import annotations

import re

PLACEHOLDERS = {"", "[unknown artist]", "unknown artist", "[unknown album]", "unknown album"}
_JUNK = re.compile(r"^\d+\s*-\s*(?P<artist>.+?)\s+-\s+(?P<title>.+?)(\.(mp3|flac|m4a|wav))+$", re.I)
_SOCK = re.compile(r"^(?P<artist>.+?) - '(?P<title>.+)' \((?P<album>.+)\)$")
_REMASTER = re.compile(r"^(?P<title>.*?)\s+-\s+(?P<version>(\d{4}\s+)?(digital(ly)?\s+)?remaster(ed)?(\s+(version|\d{4}))?)\s*$", re.I)


def _blank(s: str | None) -> bool:
    return (s or "").strip().casefold() in PLACEHOLDERS


def _same(a: str, b: str) -> bool:
    return re.sub(r"\W+", "", a.casefold()) == re.sub(r"\W+", "", b.casefold())


def clean(fields: dict) -> tuple[dict, list[str]]:
    f, rules = dict(fields), []

    def fire(rule: str, **changes) -> None:
        f.update(changes)
        rules.append(rule)

    title, artist = f.get("title") or "", f.get("artist") or ""
    m = _JUNK.match(title)
    if m and (_blank(artist) or artist == title):
        fire("junk", artist=m["artist"].strip(), title=m["title"].strip())
    elif _blank(artist) and title.count(" - ") == 1:
        a, t = title.split(" - ")
        fire("split", artist=a.strip(), title=t.strip())
    elif (m := _SOCK.match(title)) and (_blank(artist) or _same(m["artist"], artist)):
        changes = {"title": m["title"].strip()}
        if _blank(f.get("album")):
            changes["album"] = m["album"].strip()
        fire("sockseek", **changes)
    elif artist and title.casefold().startswith(artist.casefold() + " - "):
        fire("prefix", title=title[len(artist) + 3:].strip())

    if m := _REMASTER.match(f["title"] or ""):
        comments = f.get("comments") or ""
        fire("remaster", title=m["title"].strip(),
             comments=(comments + "\n" if comments else "") + f"version: {m['version'].strip()}")

    if f.get("in_compilations"):
        changes = {}
        if not _blank(f.get("artist")) and f.get("albumartist") != f["artist"]:
            changes["albumartist"] = f["artist"]
        if f.get("comp"):
            changes["comp"] = False
        if changes:
            fire("compilation", **changes)

    return {k: v for k, v in f.items() if fields.get(k) != v}, rules
