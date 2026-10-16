"""Fill in the library's MusicBrainz recording and work ids, by proposal and review (M7, Task 8: `propose`).

    docker compose exec -T worker python -m scripts.identity_backfill propose [--limit N]
        → /data/identity/identity-proposal.json + identity-backfill-report.md   (= /srv/docker/crates/identity/)
    Michael reads the report: accepts classes, marks single rows "skip": true, or picks an ambiguous row's
    candidate with "choose": "<mbid>" in the JSON
    … `apply` writes the accepted id fields (write_minimal, empty fields only) → Navidrome scan → id/playlist check
    … `revert <log>` empties what apply wrote, where the value is still ours

Why: the file's tags own which recording a file is, but only ~98 of ~860 files carry a recording id. Navidrome
keys a song on it after a retag plus a move (the M2 playlist breakage), and M8's same-version test trusts it: two
files with one recording id are copies, and M8 deletes the worse one. So a wrong id is worse than none, and every
doubt here resolves to "not proposed".

Why not beets: measured (M7 plan, fact 5), beets applied the 403 s "(Get Down in the 90's-mix)" recording to the
412 s "(Original 12'' Version)" at 96.8% similarity. A recording here fits a file only when the lead artists are
equal, the base titles and version labels (`identity.parse_title`) agree, a label-bearing MusicBrainz
disambiguation ("clean", "12\" version") is one the file's title carries too, it is not a video, and the lengths
agree ±4 s; a recording without a length never fits (M6). MusicBrainz duplicates one recording at the same length
often (~35% of searches): those rows are `ambiguous` with their candidates, never resolved by guessing.
Tie-breaks are only the file's own ISRC and album, and a confident (score ≥ 0.8) AcoustID top result.

The file's existing ids are read raw (`read_ids`), not only through mediafile: an MP3 may carry its recording id
in `TXXX:MusicBrainz Track Id`, which Navidrome reads and mediafile does not. Such a file is never re-proposed.

`propose` never opens a library file for writing (a test pins every file's sha256), and refuses an --out inside
the library. It runs in the worker (fact 7): that container has fpcalc, mediafile and /srv/music, and keeps every
/srv/music writer in one place. MusicBrainz answers are cached in `mb-cache.jsonl` next to the proposal, so a
killed ~45 min run resumes where it stopped (one `MusicBrainz` client per run: its spacing and retry live there).
AcoustID is used only when ACOUSTID_KEY is set; the key is never printed or logged.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sourcing import acoustid
from sourcing.identity import Copy, lead_artist, loose, parse_title, version_groups
from sourcing.musicbrainz import MusicBrainz, Recording

AUDIO = (".flac", ".mp3", ".m4a", ".wav")
TOL_S = 4.0
MIN_ACOUSTID_SCORE = 0.8
CLASSES = ("confirmed", "isrc", "acoustid", "search", "ambiguous", "conflict", "none", "error")
ACCEPT = frozenset({"confirmed", "isrc", "acoustid"})        # the default; `search` waits for Michael (ruling a)
ID_FIELDS = ("mb_trackid", "mb_workid", "acoustid_id")
PROPOSAL = "identity-proposal.json"
REPORT = "identity-backfill-report.md"
CACHE = "mb-cache.jsonl"

_MBID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_ISRC = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$")
# Lucene operators. mb.search quotes each term as a phrase and escapes \ and "; the rest become spaces, which
# MusicBrainz's tokeniser treats alike, so no title can turn into a query error (a 400) or an operator.
_LUCENE = re.compile(r'[+\-!(){}\[\]^"~*?:\\/|]')
# Where taggers store each id, casefolded: Vorbis keys, ID3 TXXX descriptions, MP4 freeform names (without the
# "----:com.apple.iTunes:" prefix), ASF names. The ID3 UFID frame is read separately.
_ID_NAMES = {
    "mb_trackid": {"musicbrainz_trackid", "musicbrainz track id", "musicbrainz/track id"},
    "mb_workid": {"musicbrainz_workid", "musicbrainz work id", "musicbrainz/work id"},
    "acoustid_id": {"acoustid_id", "acoustid id", "acoustid/id"},
}
_LEAD = "lead artist"


@dataclass
class FileFacts:
    path: str                       # relative to music_root, posix
    artist: str
    title: str
    album: str
    length_s: float
    mb_trackid: str
    mb_workid: str
    acoustid_id: str
    isrc: str
    version_tag: str
    size: int
    mtime_ns: int
    abspath: str = field(default="", repr=False)              # for the fingerprint; not part of the proposal
    id_note: str = ""                                          # the file carries several values for one id field

    def tags(self) -> dict:
        """What `apply` re-checks before it writes (the row's "file")."""
        return {k: getattr(self, k) for k in ("artist", "title", "album", "length_s", "isrc", "version_tag",
                                              "mb_trackid", "mb_workid", "acoustid_id")}


@dataclass
class Proposal:
    path: str
    cls: str                        # one of CLASSES
    write: dict[str, str]           # ⊆ {"mb_trackid", "mb_workid", "acoustid_id"}; only fields empty in the file
    recording: str = ""
    title: str = ""
    length_s: float | None = None
    why: str = ""
    candidates: list[str] = field(default_factory=list)       # ids Michael may "choose" from (ambiguous, review)
    accept: bool = False            # default from the class: True for confirmed, isrc, acoustid
    size: int = 0
    mtime_ns: int = 0
    skip: bool = False              # Michael sets this in the JSON to keep one row out of `apply`
    file: dict = field(default_factory=dict)                   # the file's tags when proposed (FileFacts.tags)
    candidate_details: list[dict] = field(default_factory=list)


# ── reading (read-only) ─────────────────────────────────────────────────────────────────────────────────────────

def _texts(v) -> list[str]:
    out = []
    for x in v if isinstance(v, list) else [v]:
        x = x.decode("utf-8", errors="replace") if isinstance(x, bytes) else str(getattr(x, "value", x))
        out += [y.strip() for y in x.split("\x00") if y.strip()]
    return out


def read_ids(path: Path, mg=None) -> dict[str, list[str]]:
    """Every value of each id field the file carries, wherever a tagger put it: {field: [distinct values]}.

    mediafile reads one storage style per field (an MP3's recording id only from UFID), but Navidrome also reads
    `TXXX:MusicBrainz Track Id`; a file whose id lives there already has one. `apply` re-checks with this too."""
    import mutagen
    import mutagen.id3
    if mg is None:
        mg = mutagen.File(str(path))
    found: dict[str, list[str]] = {k: [] for k in ID_FIELDS}

    def add(key: str, values: list[str]) -> None:
        for v in values:
            if v and v.casefold() not in {x.casefold() for x in found[key]}:
                found[key].append(v)
    tags = getattr(mg, "tags", None)
    if tags is None:
        return found
    if isinstance(tags, mutagen.id3.ID3):
        for fr in tags.getall("UFID"):
            if fr.owner == "http://musicbrainz.org":
                add("mb_trackid", _texts(fr.data))
        named = [(fr.desc, list(fr.text)) for fr in tags.getall("TXXX")]
    else:
        named = [(str(k), tags[k]) for k in tags.keys()]
    for name, value in named:
        name = name.casefold().removeprefix("----:com.apple.itunes:")
        for key, names in _ID_NAMES.items():
            if name in names:
                add(key, _texts(value))
    return found


def _version_tag(mg) -> str:
    """The raw VERSION (Vorbis, MP4 freeform) or TIT3 (ID3) text; identity decides whether it is a label."""
    import mutagen.id3
    tags = getattr(mg, "tags", None)
    if tags is None:
        return ""
    if isinstance(tags, mutagen.id3.ID3):
        frames = tags.getall("TIT3")
        return str(frames[0].text[0]) if frames and frames[0].text else ""
    for k in list(tags.keys()):
        if isinstance(k, str) and (k.upper() == "VERSION" or k.upper().endswith(":VERSION")):
            v = _texts(tags[k])
            return v[0] if v else ""
    return ""


def read_facts(music_root: Path, path: Path) -> FileFacts:
    """A file's identity tags, read with mediafile and mutagen (both open the file read-only)."""
    from mediafile import MediaFile                          # the worker image installs it; tests reach Debian's
    st = path.stat()
    m = MediaFile(str(path))
    ids = read_ids(path, m.mgfile)
    many = [f"{k}: {', '.join(v)}" for k, v in ids.items() if len(v) > 1]
    s = lambda v: str(v or "").strip()                       # noqa: E731
    return FileFacts(path=path.relative_to(music_root).as_posix(), artist=s(m.artist), title=s(m.title),
                     album=s(m.album), length_s=float(m.length or 0.0),
                     mb_trackid=next(iter(ids["mb_trackid"]), ""), mb_workid=next(iter(ids["mb_workid"]), ""),
                     acoustid_id=next(iter(ids["acoustid_id"]), ""), isrc=s(m.isrc),
                     version_tag=s(_version_tag(m.mgfile)), size=st.st_size, mtime_ns=st.st_mtime_ns,
                     abspath=str(path), id_note="; ".join(many))


# ── deciding ────────────────────────────────────────────────────────────────────────────────────────────────────

def search_text(s: str) -> str:
    """`s` with Lucene's operator characters as spaces, for a MusicBrainz search term."""
    return " ".join(_LUCENE.sub(" ", s or "").split())


def _isrc(raw: str) -> str:
    """The file's first ISRC in canonical form, or "" when it is not one (a junk value must not reach a URL)."""
    first = re.split(r"[;,/\s]+", raw.strip())[0] if raw.strip() else ""
    code = first.replace("-", "").upper()
    return code if _ISRC.match(code) else ""


def _len(s: float | None) -> str:
    if s is None:
        return "?"
    s = round(s)
    return f"{s // 60}:{s % 60:02d}"


def _disambiguation_label(d: str):
    """The version label a MusicBrainz disambiguation names ("clean", "12\" version", "radio edit"), or None."""
    if not d:
        return None
    t = parse_title(f"x ({d})")
    return t if t.kinds else None


def _misfit(f: FileFacts, t, r: Recording) -> str:
    """Why the recording is not this file's version, or "" when it is. The lead artist is checked last, so a
    result of exactly _LEAD-prefixed text means everything else agreed (a near miss worth a person's look)."""
    if r.video:
        return "a video recording"
    if r.length_s is None:
        return "MusicBrainz has no length for it"
    if not f.length_s or abs(r.length_s - f.length_s) > TOL_S:
        return f"length {_len(r.length_s)} vs file {_len(f.length_s)}"
    rt = parse_title(r.title, r.artist)
    if not loose(t.base) or loose(rt.base) != loose(t.base):
        return f"title {r.title!r}"
    if rt.key != t.key:
        return f"version {r.title!r} vs file {f.title!r}"
    d = _disambiguation_label(r.disambiguation)
    if d is not None:
        by = {b for b in d.by.split("|") if b}
        if not t.kinds or d.kinds - t.kinds or not by <= set(t.by.split("|")):
            return f"MusicBrainz names it {r.disambiguation!r}, the file's title does not"
    lead = loose(lead_artist(f.artist))
    if not lead or lead != loose(lead_artist(r.artist)):
        return f"{_LEAD}: credited {r.artist!r}, file {f.artist!r}"
    return ""


def _tie_break(fit: list[Recording], tests) -> tuple[Recording | None, str]:
    """One recording when `fit` has one, or when the tests (in order) narrow it to one; each test narrows only when
    some candidates pass it. Otherwise None: MusicBrainz duplicates stay ambiguous."""
    if len(fit) == 1:
        return fit[0], ""
    for name, test in tests:
        passed = [r for r in fit if test(r)]
        if len(passed) == 1:
            return passed[0], f"; tie broken by {name}"
        if passed:
            fit = passed
    return None, ""


def _same_album(f: FileFacts):
    album = loose(f.album)
    return lambda r: bool(album) and any(loose(x) == album for x in r.releases)


def _detail(r: Recording) -> dict:
    return {"id": r.id, "title": r.title, "length_s": r.length_s, "artist": r.artist,
            "release": r.releases[0] if r.releases else "", "disambiguation": r.disambiguation}


def _set_pick(p: Proposal, r: Recording) -> None:
    p.recording, p.title, p.length_s = r.id, r.title, r.length_s


def _work(p: Proposal, f: FileFacts, works: tuple[str, ...]) -> None:
    if f.mb_workid:
        return
    if len(works) == 1:
        p.write["mb_workid"] = works[0]
    elif works:
        p.why += f"; {len(works)} works, none proposed"


def _confirm(p: Proposal, f: FileFacts, t, mb) -> None:
    """Step 1: the file's own recording id is checked, never replaced; only a missing work id is proposed."""
    rid = f.mb_trackid
    p.recording = rid
    if f.id_note and "mb_trackid" in f.id_note:
        p.cls, p.why = "conflict", f"the file carries more than one recording id ({f.id_note})"
        return
    if not _MBID.match(rid):
        p.cls, p.why = "conflict", f"the file's recording id {rid!r} is not a MusicBrainz id"
        return
    r = mb.recording(rid)
    if r is None:
        p.cls, p.why = "conflict", "recording id not in MusicBrainz"
        return
    _set_pick(p, r)
    merged = f"; MusicBrainz merged it into {r.id}" if r.id.casefold() != rid.casefold() else ""
    p.recording = rid
    miss = _misfit(f, t, r)
    if miss:
        p.cls, p.why = "conflict", f"the file's id does not fit: {miss}{merged}"
        return
    p.cls, p.why = "confirmed", f"MusicBrainz {_len(r.length_s)} vs file {_len(f.length_s)}{merged}"
    _work(p, f, r.work_ids)


def _acoustid(p: Proposal, f: FileFacts, lookup, fit_ids: list[str]) -> None:
    """Step 4: a confident fingerprint may single out one fitting recording; it never adds one that did not fit.
    Only results scoring ≥ 0.8 count, and a search pick must be in the top result (AcoustID merges similar audio,
    so a weak or lower result is no evidence)."""
    try:
        found = lookup(Path(f.abspath) if f.abspath else Path(f.path))
    except Exception as e:                                   # fpcalc, network, a bad key: noted, class unchanged
        p.why += f"; AcoustID lookup failed ({type(e).__name__}: {e})"
        return
    found = sorted(found, key=lambda a: a.get("score") or 0, reverse=True)
    sure = [a for a in found if (a.get("score") or 0) >= MIN_ACOUSTID_SCORE]
    if not sure:
        p.why += "; AcoustID: no confident match" + (f" (best score {found[0].get('score')})" if found else "")
        return
    top = [a for a in sure if a.get("acoustid") == sure[0].get("acoustid")]
    if p.cls == "search":
        hit = next((a for a in top if a["id"] == p.recording), None)
        if hit is not None:
            p.cls = "acoustid"
            p.why += "; AcoustID's top result agrees"
            if hit.get("acoustid") and not f.acoustid_id:
                p.write["acoustid_id"] = hit["acoustid"]
        else:
            p.cls, p.write = "conflict", {}
            p.candidates = [a["id"] for a in top]
            p.why += f"; AcoustID's top result is {', '.join(p.candidates)}, not the search pick"
    elif p.cls == "ambiguous":
        hit = [a for a in sure if a["id"] in fit_ids]
        hit_ids = list(dict.fromkeys(a["id"] for a in hit))
        if len(hit_ids) == 1:
            p.cls = "acoustid"
            p.why += "; a confident AcoustID result picks one of them"
            p.recording = hit_ids[0]
            if hit[0].get("acoustid") and not f.acoustid_id:
                p.write["acoustid_id"] = hit[0]["acoustid"]
        else:
            p.why += f"; confident AcoustID results match {len(hit_ids)} of them"
    else:
        ids = list(dict.fromkeys(a["id"] for a in sure))
        p.why += f"; AcoustID suggests {', '.join(ids[:3])} (not checked against the title; nothing proposed)"


def _classify(f: FileFacts, mb, lookup, p: Proposal) -> None:
    t = parse_title(f.title, f.artist, f.version_tag)
    if f.mb_trackid:
        _confirm(p, f, t, mb)
        return
    notes: list[str] = [f"several ids in the file ({f.id_note})"] if f.id_note else []
    picked: dict[str, Recording] = {}
    near: dict[str, Recording] = {}                          # fit except the lead artist: for review, never applied

    def sort(recs: list[Recording]) -> list[Recording]:
        fit = []
        for r in recs:
            miss = _misfit(f, t, r)
            if not miss:
                fit.append(r)
            elif miss.startswith(_LEAD):
                near.setdefault(r.id, r)
        return fit

    isrc = _isrc(f.isrc)
    if f.isrc and not isrc:
        notes.append(f"ISRC {f.isrc!r} is not one; not looked up")
    if isrc:                                                 # step 2
        recs = mb.isrc(isrc)
        fit = sort(recs)
        r, how = _tie_break(fit, [("album", _same_album(f))])
        if r is not None:
            p.cls = "isrc"
            _set_pick(p, r)
            p.why = "; ".join(notes + [f"ISRC {isrc}: {len(fit)} of {len(recs)} recordings fit" + how])
            p.write["mb_trackid"] = r.id
            _work(p, f, r.work_ids)
            return
        notes.append(f"ISRC {isrc}: {len(fit)} of {len(recs)} recordings fit")

    artist_q, title_q = search_text(lead_artist(f.artist)), search_text(t.base)
    fit_ids: list[str] = []
    if not artist_q or not title_q:
        p.cls = "none"
        notes.append("no artist or title to search for")
    else:                                                    # step 3
        recs = mb.search(artist_q, title_q)
        fit = sort(recs)
        fit_ids = [r.id for r in fit]
        picked = {r.id: r for r in fit}
        tests = [("the file's ISRC", lambda r: bool(isrc) and isrc in r.isrcs), ("album", _same_album(f))]
        r, how = _tie_break(fit, tests)
        said = f"search: {len(fit)} of {len(recs)} results fit"
        if r is not None:
            p.cls = "search"
            _set_pick(p, r)
            notes.append(said + how)
        elif fit:
            p.cls, p.candidates = "ambiguous", fit_ids
            p.candidate_details = [_detail(x) for x in fit]
            notes.append(said + " at " + ", ".join(_len(x.length_s) for x in fit))
        else:
            p.cls = "none"
            notes.append(said)
    if p.cls == "none" and near:
        p.candidates = list(near)
        p.candidate_details = [_detail(x) for x in near.values()]
        notes.append(f"{len(near)} recording(s) fit except the {_LEAD} (credited "
                     + ", ".join(sorted({repr(x.artist) for x in near.values()})) + "): for review only")
    p.why = "; ".join(notes)

    if lookup is not None:                                   # step 4
        _acoustid(p, f, lookup, fit_ids)
    if p.cls in ("search", "acoustid"):                      # steps 5 and 6
        r = picked[p.recording]
        _set_pick(p, r)
        full = mb.recording(r.id)
        if full is not None and full.id.casefold() != r.id.casefold():
            miss = _misfit(f, t, full)
            if miss:
                p.cls, p.write = "conflict", {}
                p.why += f"; MusicBrainz merged {r.id} into {full.id}, which does not fit: {miss}"
                return
            p.why += f"; MusicBrainz merged {r.id} into {full.id}"
            _set_pick(p, full)
        p.write["mb_trackid"] = p.recording
        _work(p, f, full.work_ids if full else ())


def classify(f: FileFacts, mb: MusicBrainz, lookup=None) -> Proposal:
    """One file's proposal. Any exception is this file's `error`; the run goes on."""
    p = Proposal(path=f.path, cls="none", write={}, size=f.size, mtime_ns=f.mtime_ns, file=f.tags())
    try:
        _classify(f, mb, lookup, p)
    except Exception as e:
        p = Proposal(path=f.path, cls="error", write={}, why=f"{type(e).__name__}: {e}", size=f.size,
                     mtime_ns=f.mtime_ns, file=f.tags())
    if p.cls in ("conflict", "ambiguous", "none", "error"):
        p.write = {}
    p.accept = p.cls in ACCEPT
    return p


# ── the run ─────────────────────────────────────────────────────────────────────────────────────────────────────

def audio_files(music_root: Path) -> list[Path]:
    return sorted(p for p in music_root.rglob("*")
                  if p.suffix.lower() in AUDIO and p.is_file() and p.relative_to(music_root).parts[0] != "_playlists")


def check_out_dir(music_root: Path, out_dir: Path) -> None:
    """The proposal never lands in the library: Navidrome would scan it, and the library stays read-only here."""
    if Path(out_dir).resolve().is_relative_to(Path(music_root).resolve()):
        raise ValueError(f"--out {out_dir} is inside the library {music_root}; choose a directory outside it")


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def propose(music_root: Path, out_dir: Path, mb: MusicBrainz, *, lookup=None, limit: int | None = None,
            log=print, every: int = 50) -> list[Proposal]:
    """Classify every audio file under music_root (not _playlists/) and write the proposal and the report."""
    music_root, out_dir = Path(music_root), Path(out_dir)
    check_out_dir(music_root, out_dir)
    paths = audio_files(music_root)[:limit]
    proposals: list[Proposal] = []
    facts: list[FileFacts] = []
    counts: Counter = Counter()
    start = time.monotonic()
    for i, path in enumerate(paths, 1):
        try:
            f = read_facts(music_root, path)
        except Exception as e:                               # unreadable or vanished: an error row, the run goes on
            try:
                st = path.stat()
                size, mtime = st.st_size, st.st_mtime_ns
            except OSError:
                size = mtime = 0
            f = FileFacts(path.relative_to(music_root).as_posix(), "", "", "", 0.0, "", "", "", "", "", size, mtime)
            p = Proposal(path=f.path, cls="error", write={}, why=f"unreadable: {type(e).__name__}: {e}",
                         size=size, mtime_ns=mtime, file=f.tags())
        else:
            p = classify(f, mb, lookup)
        facts.append(f)
        proposals.append(p)
        counts[p.cls] += 1
        if i % every == 0 or i == len(paths):
            spent = time.monotonic() - start
            log(f"{i}/{len(paths)} files, {spent:.0f} s, ~{spent / i * (len(paths) - i) / 60:.0f} min left: "
                + " ".join(f"{c}={counts[c]}" for c in CLASSES if counts[c]))
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = {"created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "music_root": str(music_root), "counts": {c: counts[c] for c in CLASSES},
           "proposals": [asdict(p) for p in proposals]}
    _write_atomic(out_dir / PROPOSAL, json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    write_report(proposals, facts, out_dir / REPORT)
    return proposals


# ── the report (read on a phone: bullet blocks, no wide tables) ────────────────────────────────────────────────

MEANING = {
    "confirmed": "The file already has a recording id. MusicBrainz agrees on the artist, title, version label and "
                 "length (±4 s). Only a missing work id is proposed. Accepted by default.",
    "isrc": "The file's own ISRC leads to exactly one recording with the same lead artist, title, version label "
            "and length (±4 s). Accepted by default.",
    "acoustid": "A confident audio fingerprint (score ≥ 0.8) agrees with the one fitting recording, or singles "
                "one out of several. Accepted by default.",
    "search": "An artist + title search found exactly one recording with the same lead artist, title, version "
              "label and length (±4 s), or a tie broken by the file's ISRC or album. **Not accepted by default.**",
    "ambiguous": "Several recordings fit equally (MusicBrainz duplicates of one recording). Nothing is proposed. "
                 "To pick one, set `\"choose\": \"<mbid>\"` on the row in the JSON (only a listed candidate counts).",
    "conflict": "The evidence disagrees: an existing id that does not fit the file, two different ids in one file, "
                "or AcoustID against the search. Nothing is written; worth a look, because M8 trusts recording ids.",
    "none": "Nothing fits. Nothing is written. Rows with candidates fit on everything except the lead artist: "
            "a person can still `\"choose\"` one.",
    "error": "A lookup failed (MusicBrainz error, unreadable or vanished file). Re-run `propose`: the cache keeps "
             "what was already answered.",
}


def _md(s) -> str:
    return str(s if s is not None else "").replace("\n", " ").replace("|", "\\|")


def _link(kind: str, mbid: str) -> str:
    return f"[{mbid[:8]}](https://musicbrainz.org/{kind}/{mbid})" if mbid else ""


def _row(p: Proposal, f: FileFacts | None) -> list[str]:
    who = f"{f.artist} – {f.title}" if f and (f.artist or f.title) else p.path
    out = [f"- **{_md(who)}** ({_len(f.length_s) if f else '?'})", f"  - file: `{p.path}`"]
    if p.recording:
        bits = [f"{_md(p.title)} {_link('recording', p.recording)}".strip(), _len(p.length_s)]
        if "mb_workid" in p.write:
            bits.append(f"work {_link('work', p.write['mb_workid'])}")
        elif f and f.mb_workid:
            bits.append(f"has work {_link('work', f.mb_workid)}")
        if "acoustid_id" in p.write:
            bits.append(f"AcoustID {p.write['acoustid_id'][:8]}")
        out.append(f"  - {'writes' if p.write else 'recording'}: " + " · ".join(bits))
    if p.why:
        out.append(f"  - why: {_md(p.why)}")
    details = {d["id"]: d for d in p.candidate_details}
    if p.candidates:
        out.append("  - candidates:")
        for c in p.candidates:
            d = details.get(c, {})
            bits = [_link("recording", c), _len(d.get("length_s"))] if d else [_link("recording", c)]
            bits += [_md(x) for x in (d.get("title"), d.get("artist"), d.get("release")) if x]
            if d.get("disambiguation"):
                bits.append(f"({_md(d['disambiguation'])})")
            out.append("    - " + " · ".join(bits))
    return out


def write_report(proposals: list[Proposal], facts: list[FileFacts], path: Path) -> None:
    by_path = {f.path: f for f in facts}
    counts = Counter(p.cls for p in proposals)
    out = ["# Identity backfill: proposed MusicBrainz ids", "",
           "## What this is", "",
           "For every audio file in the library, a proposed MusicBrainz recording id (`mb_trackid`), work id "
           "(`mb_workid`) and AcoustID id (`acoustid_id`), each only where the file has none. Nothing has been "
           "written: this report and `identity-proposal.json` are the proposal. A recording is proposed only when "
           "it agrees with the file on lead artist, title, version label and length (±4 s).", "",
           "Then `apply` writes the accepted rows: only the id fields, only empty ones, never over a value. "
           "`revert` undoes it. By default `apply` takes the classes accepted below (confirmed, isrc, acoustid).",
           "",
           "- To choose classes: `apply --classes confirmed,isrc,acoustid,search identity-proposal.json`.",
           "- To keep one row out: set `\"skip\": true` on it in the JSON.",
           "- To pick a candidate on an ambiguous row: set `\"choose\": \"<mbid>\"` on it in the JSON. Only one of "
           "that row's listed candidates counts.", "",
           "## Counts", "", "| Class | Files |", "|---|---:|"]
    out += [f"| {c} | {counts[c]} |" for c in CLASSES]
    out.append(f"| **all** | {len(proposals)} |")

    for c in CLASSES:
        rows = [p for p in proposals if p.cls == c]
        if not rows:
            continue
        out += ["", f"## {c} ({len(rows)})", "", MEANING[c], ""]
        for p in rows:
            out += _row(p, by_path.get(p.path))

    # Copies of one version: identity's same-version test over the current tags (M8's input; read-only).
    usable = [f for f in facts if f.length_s > 0 and loose(lead_artist(f.artist))
              and loose(parse_title(f.title, f.artist).base)]
    copies = [Copy(f.artist, f.title, f.length_s, f.mb_trackid, f.mb_workid, f.version_tag) for f in usable]
    groups = version_groups(copies)
    out += ["", "## Copies of one version", "",
            f"{len(groups)} groups, {sum(map(len, groups))} files: by `identity.same_version` over the files' "
            "current tags (same recording id, or same lead artist, title, version label and length ±4 s), these "
            "are copies of one version. They are for M8 (keep the better copy) and need no action now. Files "
            "without an artist, title or length are left out."]
    if groups:
        out.append("")
    for g in groups:
        first = usable[g[0]]
        out.append(f"- **{_md(first.artist)} – {_md(first.title)}**")
        out += [f"  - `{usable[i].path}` ({_len(usable[i].length_s)})" for i in g]

    # Version labels: what parse_title read, and what it did not (vocabulary gaps).
    kinds: Counter = Counter()
    unread: Counter = Counter()
    copy_notes = labelled = 0
    for f in facts:
        t = parse_title(f.title, f.artist, f.version_tag)
        kinds.update(t.kinds)
        labelled += bool(t.kinds)
        copy_notes += bool(t.copy_note)
        if t.base.endswith((")", "]")):
            unread[f.title] += 1
    out += ["", "## Version labels identity reads", "",
            f"{labelled} of {len(facts)} titles carry a version label; {copy_notes} carry a copy marker "
            "(remaster, feat., album version) that does not change the version."]
    out += [""] * bool(kinds) + [f"- {k}: {n}" for k, n in sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))]
    if unread:
        out += ["", f"Titles whose trailing parenthetical was **not** read as a label ({len(unread)}). A version "
                "word here means a gap in identity's vocabulary:", ""]
        out += [f"- {_md(t)}" + (f" (×{n})" if n > 1 else "") for t, n in sorted(unread.items())]
    else:
        out += ["", "No title ends in a parenthetical that identity left unread."]
    _write_atomic(Path(path), "\n".join(out) + "\n")


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _redacting(lookup, key: str):
    """The AcoustID lookup with the key cut out of any error message (the why goes into the JSON and report)."""
    def run(path):
        try:
            return lookup(path)
        except Exception as e:
            raise RuntimeError(f"{type(e).__name__}: {str(e).replace(key, '<ACOUSTID_KEY>')}") from None
    return run


def main(argv: list[str] | None = None, *, opener=None, sleep=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("propose", help="write the proposal and the report; reads the library, writes nothing to it")
    pp.add_argument("--music", type=Path, default=Path(os.environ.get("MUSIC_ROOT") or "/srv/music"))
    pp.add_argument("--out", type=Path, default=Path("/data/identity"))
    pp.add_argument("--limit", type=int, default=None)
    a = ap.parse_args(argv)
    try:
        check_out_dir(a.music, a.out)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    kw = {k: v for k, v in (("opener", opener), ("sleep", sleep)) if v is not None}
    mb = MusicBrainz(cache=a.out / CACHE, **kw)              # one client per run (tests inject opener/sleep)
    key = (os.environ.get("ACOUSTID_KEY") or "").strip()
    lookup = _redacting(acoustid.make_lookup(key), key) if key else None
    print(f"AcoustID {'on' if lookup else 'off (no ACOUSTID_KEY)'}; cache {a.out / CACHE}", flush=True)
    props = propose(a.music, a.out, mb, lookup=lookup, limit=a.limit, log=lambda s: print(s, flush=True))
    n = Counter(p.cls for p in props)
    print(" ".join(f"{c}={n[c]}" for c in CLASSES if n[c]) + f" → {a.out / REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
