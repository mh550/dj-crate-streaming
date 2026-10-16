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

    noise=True also drops words that only blur a name match (feat, remaster, album version, explicit, clean, hq,
    hd): it is the scorer's name test, not a version test. Versions come from `parse_title`, where clean/explicit
    are labels. "original mix" is a version label (D16), so it stays."""
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

# 12"/7" spellings seen in the library: 12" 12'' 12' 12” 12 Inch, 7in; also typographic quotes and "12-Inch".
# Matched on the raw text (quotes matter).
_INCH = r"(?:\s*(?:\"|”|“|″|''|'|’|‘)|[\s-]*in(?:ch(?:es)?)?\b)"
_TWELVE = re.compile(r"(?<![\w.])12" + _INCH, re.I)
_SEVEN = re.compile(r"(?<![\w.])7" + _INCH, re.I)

# Vocabulary on words(): earlier alternatives win at the same position ("re edit" before "edit").
_TOKENS = (
    ("original", r"original (?:mix|version)|original"),
    ("extended", r"extended|long version"),
    ("reedit", r"re ?edit|revision"),
    ("edit", r"single version|single edit|short version|radio|edit"),
    ("club", r"club"), ("dub", r"dub"), ("live", r"live"), ("demo", r"demo"),
    ("instrumental", r"instrumental|inst"),
    ("acappella", r"a cappella|acappella|acapella|a capella"),
    ("remix", r"remix|rmx|rework|bootleg|refix"),
    ("alt", r"alternate|alt take|take|medley"),       # the take number stays in the credit: take 21 ≠ take 22
)
_TOKEN = re.compile(r"\b(?:" + "|".join(f"(?P<{k}>{p})" for k, p in _TOKENS) + r")\b")
# Words that say which mix without naming it; they stay in the credit and add "alt" (mono ≠ stereo). A clean
# edit mutes lyrics at the same length, so clean/explicit/dirty are versions, never copies (an explicit file must
# not be "upgraded" to a clean one).
_KEPT = re.compile(r"\b(?:mono|stereo|clean|explicit|dirty)\b")
# Not part of a credit: filler, and a whole remaster phrase beside a label ("Live - 2011 Remaster"). A bare year,
# "album" or "single" is kept: "Live 1977" ≠ "Live 1979", "Single Mix" ≠ "Album Mix".
_REMASTER = r"(?:\d{4} )?(?:digital(?:ly)? )?remaster(?:ed)?(?: \d{4})?"
_FILLER = re.compile(r"\b(?:" + _REMASTER + r"|mix|version|by)\b")

_FEAT = re.compile(r"^(?:feat|ft|featuring)\b")      # not "with": "(With Strings)" is an arrangement
# A whole decoration that only says which copy: "2011 Remaster", "Remastered Version",
# "Remastered 2001/Rudy Van Gelder Edition", "Album Version", "Bonus Track".
_COPY = re.compile(r"^(?:(?:\d{4} )?(?:digital(?:ly)? )?remaster(?:ed)?(?: version| \d{4}(?: [a-z0-9 ]+ edition)?)?"
                   r"|album version|bonus track)$")

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
    if _KEPT.search(w):
        kinds.add("alt")
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
    # "(feat. The Live Band)" credits people; a copy phrase may not hide a label ("Remastered 2009 Mono Edition")
    if _FEAT.match(w) or (_COPY.match(w) and not _TOKEN.search(w) and not _KEPT.search(w)):
        return _COPY_NOTE, frozenset(), ""
    kinds, by = _label(dec)                              # "(Live - 2011 Remaster)" is live
    return ("label", kinds, by) if kinds else None


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
    by: str = ""                    # loose credits, "|"-joined in reading order ("tommoulton")
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
        elif loose(parts[-1]) == lead and _classify(parts[-1]) is None:     # artist "Live": "Song - Live"
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
        head, _, tail = dec.partition(" - ")
        feat_tail = bool(tail) and bool(_FEAT.match(words(head)))
        tc = _classify(tail) if feat_tail else None
        if feat_tail and tc is None:                     # "(feat. X - Acoustic)": an unknown tail stays in the base
            break
        if tc is not None:                               # "(feat. X - Dub Mix)": the credit, then the label
            dec, c = head.strip(), (_COPY_NOTE, frozenset(), "")
            if tc[0] == _COPY_NOTE:
                notes.insert(0, tail.strip())
            else:
                labels.insert(0, tail.strip())
                kinds |= tc[1]
                bys.insert(0, tc[2])
        if c[0] == _COPY_NOTE:
            notes.insert(0, dec)
        else:
            labels.insert(0, dec)
            kinds |= c[1]
            bys.insert(0, c[2])
        t = rest

    tag = (version_tag or "").strip()
    c = _classify(tag) if tag else None
    # A year or "PMEDIA" in VERSION is not a label (fact 2); the title's own label is not counted twice.
    if c is not None and c[0] == "label" and loose(tag) not in {loose(x) for x in labels}:
        kinds |= c[1]
        bys.append(c[2])
        labels.append(tag)
    return Title(base=t, label=", ".join(labels), kinds=frozenset(kinds), by="|".join(b for b in bys if b),
                 copy_note=", ".join(notes))


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
    """Two copies of one recording? Recording ids decide when both have one. Otherwise: the same lead artist, the
    same base title and label, lengths known and within tol_s; a work id only ever *rejects* (two works are two
    songs), because sharing one says "same song", not "same version". Every doubt is "different": M8 deletes a copy
    on True, while a missed match only leaves a duplicate. A fingerprint check is the caller's."""
    if a.recording_id and b.recording_id:
        return a.recording_id.casefold() == b.recording_id.casefold()
    if a.work_id and b.work_id and a.work_id.casefold() != b.work_id.casefold():
        return False
    if loose(lead_artist(a.artist)) != loose(lead_artist(b.artist)):
        return False
    ta = parse_title(a.title, a.artist, a.version_tag)
    tb = parse_title(b.title, b.artist, b.version_tag)
    if loose(ta.base) != loose(tb.base) or ta.key != tb.key or a.length_s is None or b.length_s is None:
        return False
    return abs(a.length_s - b.length_s) <= tol_s


def version_groups(copies: list[Copy], tol_s: float = 4.0) -> list[list[int]]:
    """Indices of copies that are one version, groups of two or more, each sorted, in order of first index.

    Copies are bucketed by song key, merged where they share a recording id (the only way two song keys can be one
    version), and walked by length; a copy joins the first group whose every member it is `same_version` with. So
    each group is pairwise same-version: a chain 300/303/306 s never makes 300 and 306 one version, and
    disagreeing recording or work ids never share a group."""
    parent = list(range(len(copies)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    first: dict[str, int] = {}
    for i, c in enumerate(copies):
        for k in (song_key(c.artist, c.title), "rec:" + c.recording_id.casefold() if c.recording_id else ""):
            if k:
                parent[root(i)] = root(first.setdefault(k, i))
    buckets: dict[int, list[int]] = {}
    for i in range(len(copies)):
        buckets.setdefault(root(i), []).append(i)
    groups: list[list[int]] = []
    for members in buckets.values():
        members.sort(key=lambda i: (copies[i].length_s is None, copies[i].length_s or 0.0))
        found: list[list[int]] = []
        for i in members:
            g = next((g for g in found if all(same_version(copies[j], copies[i], tol_s) for j in g)), None)
            if g is None:
                found.append([i])
            else:
                g.append(i)
        groups += [sorted(g) for g in found if len(g) > 1]
    return sorted(groups)
