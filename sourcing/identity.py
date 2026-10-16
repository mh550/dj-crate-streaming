"""What counts as the same song, the same version and the same copy: decided here and nowhere else.

    Song     lead artist + base title (the MusicBrainz work when both sides carry one)
    Version  a recording: radio edit, 12"/extended, club, dub, live, remix by X… (recording id when known)
    Copy     a file; copies of one version differ only in quality (a remaster is a copy, not a version)

The invariants this serves: a version has at most one copy, so a better copy *replaces* the old one; several
versions of a song coexist, so a new version is never a replacement. Replacement trusts `same_version`, which is
why every doubt resolves to "different version": a false "same" would trash a legitimate 12".

Which version a file is lives in its tags: the recording id, else the title. The title is the label's source
because the version tag (`VERSION`/`TIT3`) in this library holds years and rip-group names (M7 plan, fact 2);
it counts only when it parses as a label. Labels come only from *trailing* decorations (" - X", "(X)", "[X]")
that contain a vocabulary word, so "Peace and Love Dub" or "Mary Jane (All Night Long)" stay song names.
Which versions make one song is derived here and never stored. See docs/specs/2026-10-16-ownership-and-identity.md
Part 2. Stdlib only: sourcing.policy imports this module.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

KINDS = ("edit", "extended", "club", "dub", "instrumental", "acappella", "live", "remix", "reedit", "demo", "alt",
         "original")
NEUTRAL = frozenset({"original"})          # counts for preferences, not for the version key


# ── folding ─────────────────────────────────────────────────────────────────────────────────────────────────────

_NOISE = re.compile(r"\b(?:\d{4} remaster(?:ed)?|remaster(?:ed)?|album version|feat|ft|featuring|explicit|clean|hq|hd)\b")


def words(s: str | None, *, noise: bool = False) -> str:
    """Accent-, case- and punctuation-free words; "&" is "and" on both sides alike.

    noise=True also drops copy and credit words (feat, remaster, album version, explicit…): they never change
    which recording a name means. "original mix" is a version label (D16), so it stays."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold().replace("&", " and ")
    s = "".join(c if c.isalnum() else " " for c in s)          # letters of any script stay; "_" goes
    if noise:
        s = _NOISE.sub(" ", s)
    return " ".join(s.split())


def loose(s: str | None) -> str:
    """`words` without the spaces: the comparison key for "is this the same text"."""
    return words(s).replace(" ", "")


_LEAD_SPLIT = re.compile(r"\s+•\s+|;|\s+(?:feat|ft)\.|\s+featuring\s", re.I)


def lead_artist(artist: str | None) -> str:
    """The first credited artist: "Chic feat. Nile Rodgers" is Chic's song. "&" and "," stay (band names)."""
    return _LEAD_SPLIT.split(artist or "", maxsplit=1)[0].strip()


# ── version labels ──────────────────────────────────────────────────────────────────────────────────────────────

# 12"/7" spellings seen in the library: 12" 12'' 12' 12” 12 Inch, 7in. Matched on the raw text (quotes matter).
_INCH = r"\s*(?:\"|”|″|''|'|in\b|inch(?:es)?\b)"
_TWELVE = re.compile(r"(?<![\w.])12" + _INCH, re.I)
_SEVEN = re.compile(r"(?<![\w.])7" + _INCH, re.I)

# Vocabulary on words(): earlier alternatives win at the same position ("re edit" before "edit").
_TOKENS = (
    ("original", r"original (?:mix|version)|original"),
    ("extended", r"extended|long version"),
    ("reedit", r"re ?edit"),
    ("edit", r"single version|single edit|short version|radio|edit"),
    ("club", r"club"), ("dub", r"dub"), ("live", r"live"), ("demo", r"demo"),
    ("instrumental", r"instrumental|inst"),
    ("acappella", r"a cappella|acappella|acapella|a capella"),
    ("remix", r"remix|rmx|rework"),
    ("alt", r"alternate|alt take|take \d+|medley"),
)
_TOKEN = re.compile(r"\b(?:" + "|".join(f"(?P<{k}>{p})" for k, p in _TOKENS) + r")\b")
# Not part of a credit: filler, years, and copy words that may sit beside a label ("Live - 2011 Remaster").
_FILLER = re.compile(r"\b(?:mix|version|single|by|\d{4}|remaster(?:ed)?|digital(?:ly)?|explicit|clean|album)\b")

_FEAT = re.compile(r"^(?:feat|ft|featuring|with)\b")
_COPY = re.compile(r"^(?:(?:\d{4} )?(?:digital(?:ly)? )?remaster(?:ed)?\b.*|album version|explicit(?: version)?"
                   r"|clean(?: version)?|bonus track)$")

_COPY_NOTE = "copy"


def _label(dec: str) -> tuple[frozenset[str], str]:
    """The kinds and credit one decoration names; no kinds means it is not a label."""
    kinds: set[str] = set()
    raw = dec
    if _TWELVE.search(raw):
        kinds.add("extended")
    if _SEVEN.search(raw):
        kinds.add("edit")
    raw = _SEVEN.sub(" ", _TWELVE.sub(" ", raw))
    w = words(raw)
    if kinds:                                            # a 12" single is the 12": "single" adds nothing
        w = re.sub(r"\bsingle\b", " ", w)

    def hit(m: re.Match) -> str:
        kinds.add(m.lastgroup)
        return " "
    w = _TOKEN.sub(hit, w)
    named_mix = bool(re.search(r"\bmix\b", w))
    named_version = bool(re.search(r"\bversion\b", w))
    by = loose(_FILLER.sub(" ", w))
    if not kinds and named_mix:                          # "Tom Moulton Mix", a bare "Mix"
        kinds.add("remix")
    elif not kinds and named_version and by:             # "Disco Version", "Sax Version"
        kinds.add("alt")
    if kinds == {"edit"} and by:                         # "Dominique Torti's Wild Style Edit"
        kinds = {"reedit"}
    return frozenset(kinds), by if kinds else ""


def _classify(dec: str) -> tuple[str, frozenset[str], str] | None:
    """(_COPY_NOTE, …) for a copy marker, ("label", kinds, by) for a label, None to stop peeling."""
    w = words(dec)
    if _FEAT.match(w):                                   # "(feat. The Live Band)" credits people, not a version
        return _COPY_NOTE, frozenset(), ""
    kinds, by = _label(dec)
    if kinds:                                            # before the remaster test: "(Live - 2011 Remaster)" is live
        return "label", kinds, by
    if _COPY.match(w):
        return _COPY_NOTE, frozenset(), ""
    return None


def _opener(t: str) -> int:
    """Index of the bracket that opens t's final ")"/"]", or -1 when unbalanced."""
    pairs, stack = {")": "(", "]": "["}, []
    for i in range(len(t) - 1, -1, -1):
        c = t[i]
        if c in pairs:
            stack.append(pairs[c])
        elif c in "([":
            if not stack or stack.pop() != c:
                return -1
            if not stack:
                return i
    return -1


def _peel(t: str) -> tuple[str, str] | None:
    """Split off t's last decoration: (rest, decoration as written), or None when there is none."""
    if t.endswith((")", "]")):
        start = _opener(t)
        if start <= 0:                                   # unbalanced, or the whole title: never a decoration
            return None
        return re.sub(r"\s+-$", "", t[:start].rstrip()), t[start + 1:-1].strip()   # " - (Daft Punk Remix)" is one
    i = t.rfind(" - ")
    if i <= 0:
        return None
    return t[:i].rstrip(), t[i + 3:].strip()


_JUNK = (re.compile(r"(?:\.(?:mp3|flac|m4a|wav))+$", re.I),     # file names used as titles
         re.compile(r"^\d{1,3}\s*-\s*(?=\D)"))                    # "100 - Smokey Robinson - …", not "1-2-3"


@dataclass(frozen=True)
class Title:
    base: str                       # the title without decorations, as written
    label: str = ""                 # label decorations as written, ", "-joined in reading order
    kinds: frozenset[str] = field(default_factory=frozenset)
    by: str = ""                    # loose credit ("tommoulton")
    copy_note: str = ""             # copy-marker decorations as written ("Remastered 2011", "feat. X")

    @property
    def key(self) -> tuple[tuple[str, ...], str]:
        """What makes two titles one version: the kinds that matter, and who made it."""
        return tuple(sorted(self.kinds - NEUTRAL)), self.by


def parse_title(title: str | None, artist: str | None = None, version_tag: str | None = None) -> Title:
    """Split a title into its song name, its version label and its copy markers (M7 plan, Task 1)."""
    t = (title or "").strip()
    for _ in range(3):                                   # junk stacks: "04 - 122 - X - Y.mp3.mp3"
        for p in _JUNK:
            t = p.sub("", t).strip()
    lead = loose(lead_artist(artist))
    parts = t.split(" - ")
    if lead and len(parts) > 1:                          # "Pepe Link - Vem Menina", "… - Jennifer Lara"
        if loose(parts[0]) == lead:
            t = " - ".join(parts[1:]).strip()
        elif loose(parts[-1]) == lead:
            t = " - ".join(parts[:-1]).strip()

    labels: list[str] = []
    notes: list[str] = []
    bys: list[str] = []
    kinds: set[str] = set()
    while (p := _peel(t)) is not None:
        rest, dec = p
        c = _classify(dec) if rest else None
        if c is None:
            break
        if c[0] == _COPY_NOTE:
            notes.insert(0, dec)
        else:
            labels.insert(0, dec)
            kinds |= c[1]
            bys.insert(0, c[2])
        t = rest

    tag = (version_tag or "").strip()
    c = _classify(tag) if tag else None
    if c is not None and c[0] == "label":                # a year or "PMEDIA" in VERSION is not a label (fact 2)
        kinds |= c[1]
        bys.append(c[2])
        if loose(tag) not in {loose(x) for x in labels}:
            labels.append(tag)
    return Title(base=t, label=", ".join(labels), kinds=frozenset(kinds), by="".join(bys), copy_note=", ".join(notes))


def song_key(artist: str | None, title: str | None) -> str:
    """Which versions make one song, when no work id says so: lead artist + base title."""
    return f"{loose(lead_artist(artist))}|{loose(parse_title(title, artist).base)}"


# ── same version ────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Copy:
    artist: str
    title: str
    length_s: float | None
    recording_id: str = ""
    work_id: str = ""
    version_tag: str = ""


def same_version(a: Copy, b: Copy, tol_s: float = 4.0) -> bool:
    """Two copies of one recording? Recording ids decide when both have one; otherwise the same lead artist, song,
    label and length (±tol_s). Unknown length is "not shown to be the same". A fingerprint check is the caller's."""
    if a.recording_id and b.recording_id:
        return a.recording_id.casefold() == b.recording_id.casefold()
    if loose(lead_artist(a.artist)) != loose(lead_artist(b.artist)):
        return False
    ta = parse_title(a.title, a.artist, a.version_tag)
    tb = parse_title(b.title, b.artist, b.version_tag)
    if a.work_id and b.work_id:
        if a.work_id.casefold() != b.work_id.casefold():
            return False
    elif loose(ta.base) != loose(tb.base):
        return False
    if ta.key != tb.key or a.length_s is None or b.length_s is None:
        return False
    return abs(a.length_s - b.length_s) <= tol_s


def version_groups(copies: list[Copy], tol_s: float = 4.0) -> list[list[int]]:
    """Indices of copies that are one version, groups of two or more, each sorted, in order of first index.

    Copies are bucketed by (lead artist, base, key) and walked by length; a copy joins the current group only when
    it is `same_version` as every member, so a chain 300/303/306 s never makes 300 and 306 one version, and
    disagreeing recording or work ids split a group."""
    buckets: dict[tuple, list[int]] = {}
    for i, c in enumerate(copies):
        t = parse_title(c.title, c.artist, c.version_tag)
        buckets.setdefault((loose(lead_artist(c.artist)), loose(t.base), t.key), []).append(i)
    groups: list[list[int]] = []
    for members in buckets.values():
        members.sort(key=lambda i: (copies[i].length_s is None, copies[i].length_s or 0.0))
        cur: list[int] = []
        for i in members:
            if cur and all(same_version(copies[j], copies[i], tol_s) for j in cur):
                cur.append(i)
                continue
            if len(cur) > 1:
                groups.append(sorted(cur))
            cur = [i]
        if len(cur) > 1:
            groups.append(sorted(cur))
    return sorted(groups)
