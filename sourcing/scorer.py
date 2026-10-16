"""Score slskd search results for a wanted track when the peers are *unknown*.

Input shapes follow slskd's `GET /api/v0/searches/{id}/responses`:

    [{"username": "...", "hasFreeUploadSlot": true, "queueLength": 0, "uploadSpeed": 1234567,
      "fileCount": 3, "lockedFileCount": 0,
      "files": [{"filename": "@@share\\Music\\Chic\\Risqué (1979)\\03 - Good Times.flac",
                 "size": 32112345, "extension": "flac", "bitRate": 1015, "sampleRate": 44100,
                 "bitDepth": 16, "length": 501, "isLocked": false, "code": 1}]}]

The scorer is pure and deterministic so it can be unit-tested against fixtures and
tuned without a live Soulseek connection. Each candidate gets a breakdown so the
CLI (and later the control app) can explain *why* a file was chosen.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher

from .policy import QualityPolicy, DEFAULT_POLICY


def split_remote(filename: str) -> tuple[str, str]:
    """A Soulseek remote path (either slash) → (immediate parent folder, basename).
    slskd lands downloads at <downloads>/<parent folder>/<basename>, so both sides use this."""
    parts = re.split(r"[\\/]", filename)
    return (parts[-2] if len(parts) > 1 else ""), parts[-1]


@dataclass
class Wanted:
    artist: str
    title: str
    album: str | None = None
    duration_s: float | None = None   # from Spotify/MusicBrainz metadata if known
    year: int | None = None


@dataclass
class Candidate:
    username: str
    filename: str
    size: int
    extension: str
    bit_rate: int | None
    sample_rate: int | None
    bit_depth: int | None
    length_s: int | None
    is_locked: bool
    has_free_slot: bool
    queue_length: int
    upload_speed: int
    file_count: int = 1
    score: float = 0.0
    rejected: str | None = None
    reasons: list[str] = field(default_factory=list)

    @property
    def basename(self) -> str:
        return split_remote(self.filename)[1]

    @property
    def folder(self) -> str:
        return split_remote(self.filename)[0]

    def as_dict(self) -> dict:
        """JSON-ready for the API and the approvals table; the basename is what the UI shows in place of the remote path."""
        return asdict(self) | {"basename": self.basename}


# ---------- text normalization ----------

_NOISE = re.compile(r"\b(feat|ft|featuring|remaster(?:ed)?|\d{4} remaster|album version|original mix|explicit|clean|hq|hd)\b", re.I)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[_\-\.]+", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = _NOISE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


_TRACKNO = re.compile(r"^\s*(?:[a-d]\d|\d{1,2})\s*[-._ ]+\s*", re.I)


def strip_trackno(s: str) -> str:
    return _TRACKNO.sub("", s)


def ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


# ---------- name matching (soularr-style: several passes, take the best) ----------

def name_match(c: Candidate, w: Wanted) -> tuple[float, str]:
    """0..1 similarity between the file (name + folder) and the wanted track."""
    base = strip_trackno(norm(re.sub(r"\.[^.]+$", "", c.basename)))
    folder = norm(c.folder)
    artist, title = norm(w.artist), norm(w.title)

    artist_in_path = 1.0 if artist and (artist in folder or artist in base or artist in norm(c.filename)) else 0.0
    title_only = ratio(base, title)
    title_in_name = 1.0 if title and title in base else 0.0
    artist_title = ratio(base, f"{artist} {title}")
    if not artist_in_path:
        # A title-only filename can belong to any song with that name; never let it score as a confident match.
        artist_title *= 0.85
    passes = {
        "artist - title": artist_title,
        "title + artist in path": (0.5 * title_only + 0.5 * artist_in_path) if title_only >= 0.6 else 0.0,
        "title in name + artist in path": (0.6 * title_in_name + 0.4 * artist_in_path) if title_in_name else 0.0,
    }
    score = max(passes.values())
    best = max(passes, key=passes.get)
    return score, best


# ---------- scoring ----------

UNKNOWN_SPEED_Bps = 50_000          # a peer that reports no upload speed is assumed slow


def estimated_arrival_s(c: Candidate, cap_Bps: int = 0) -> float:
    """Seconds until the file would be here: size over the slower of the peer and our own cap, plus a
    rough wait when the peer has no free slot (30 s, and 20 s per upload queued ahead of us).
    A listing without a size can't be estimated: infinity, so it earns no speed points."""
    if c.size <= 0:
        return float("inf")
    speed = c.upload_speed or UNKNOWN_SPEED_Bps
    if cap_Bps:
        speed = min(speed, cap_Bps)
    wait = 0 if c.has_free_slot else 30 + 20 * c.queue_length
    return c.size / speed + wait


def score_candidate(c: Candidate, w: Wanted, policy: QualityPolicy = DEFAULT_POLICY) -> Candidate:
    """Fills c.score / c.rejected / c.reasons. Score is roughly 0..100."""
    c.reasons.clear()
    ext = c.extension.lower().lstrip(".") or c.basename.rsplit(".", 1)[-1].lower()
    rank = policy.format_rank(ext)
    if rank is None:
        c.rejected = f"format .{ext} not allowed"; c.score = 0; return c
    if c.is_locked:
        c.rejected = "locked file"; c.score = 0; return c

    lossless = policy.is_lossless(ext)
    # Lossy floor.
    if not lossless and (c.bit_rate or 0) < policy.min_lossy_bitrate:
        c.rejected = f"lossy below {policy.min_lossy_bitrate} kbps ({c.bit_rate})"; c.score = 0; return c

    # --- name match (dominant: 0..45)
    nm, how = name_match(c, w)
    if nm < 0.55:
        c.rejected = f"name match too weak ({nm:.2f} via {how})"; c.score = 0; return c
    s = 45 * nm
    c.reasons.append(f"name {nm:.2f} ({how})")

    # --- format preference (0..20)
    fmt = max(0.0, 20 - 5 * rank)
    s += fmt
    c.reasons.append(f"format .{ext} +{fmt:.0f}")

    # --- lossless sanity: implied bitrate from size/length; catch fake FLACs (0..10 / reject)
    if lossless and c.length_s:
        implied_kbps = c.size * 8 / c.length_s / 1000
        if implied_kbps < policy.min_lossless_kbps:
            c.rejected = f"suspicious lossless: {implied_kbps:.0f} kbps implied (likely transcode)"; c.score = 0; return c
        s += 6
        c.reasons.append(f"lossless plausible ({implied_kbps:.0f} kbps)")
        if c.sample_rate and c.sample_rate not in policy.accept_sample_rates:
            s -= 5; c.reasons.append(f"odd sample rate {c.sample_rate}")
        if c.bit_depth and c.bit_depth not in policy.accept_bit_depths:
            s -= 5; c.reasons.append(f"odd bit depth {c.bit_depth}")
        if c.bit_depth == 24 or (c.sample_rate or 0) > 48000:
            s += 2; c.reasons.append("hi-res")

    # --- duration vs known length (−15..+15)
    if w.duration_s and c.length_s:
        d = abs(c.length_s - w.duration_s)
        if d <= policy.duration_tolerance_s:
            s += 15; c.reasons.append(f"duration match (Δ{d:.0f}s)")
        elif d <= 20:
            s += 3; c.reasons.append(f"duration close (Δ{d:.0f}s) — different edit?")
        else:
            s -= 15; c.reasons.append(f"duration off (Δ{d:.0f}s) — probably a different version")
    elif w.duration_s and not c.length_s:
        c.reasons.append("no length reported")

    # --- album / year hints (0..6)
    if w.album and norm(w.album) in norm(c.folder):
        s += 4; c.reasons.append("album folder matches")
    if w.year and str(w.year) in c.folder:
        s += 2; c.reasons.append("year in folder")

    # --- peer reliability (−10..+10)
    if c.has_free_slot:
        s += 5; c.reasons.append("free slot")
    else:
        s -= 3; c.reasons.append("no free slot")
    if c.queue_length > 50:
        s -= 7; c.reasons.append(f"long queue ({c.queue_length})")
    elif c.queue_length > 10:
        s -= 3; c.reasons.append(f"queue {c.queue_length}")
    if c.upload_speed >= 2_000_000:
        s += 5; c.reasons.append("fast peer")
    elif c.upload_speed and c.upload_speed < 200_000:
        s -= 3; c.reasons.append("slow peer")
    # A peer sharing the whole album folder is more likely a real rip than a stray file.
    if c.file_count >= 4:
        s += 2; c.reasons.append(f"peer has {c.file_count} matching files (album?)")

    # --- speed (listening tiers): blend in how soon the file would arrive
    if policy.speed_weight:
        t = estimated_arrival_s(c, policy.download_cap_Bps)
        speed = 100 * policy.arrival_budget_s / (policy.arrival_budget_s + t)
        c.reasons.append("arrival unknown" if math.isinf(t) else f"arrival ~{t:.0f} s")
        s = (1 - policy.speed_weight) * s + policy.speed_weight * speed

    c.score = round(s, 1)
    return c


def parse_responses(responses: list[dict]) -> list[Candidate]:
    out: list[Candidate] = []
    for r in responses:
        for f in r.get("files", []):
            out.append(Candidate(
                username=r.get("username", "?"),
                filename=f.get("filename", ""),
                size=int(f.get("size") or 0),
                extension=(f.get("extension") or f.get("filename", "").rsplit(".", 1)[-1] or "").lower(),
                bit_rate=f.get("bitRate"),
                sample_rate=f.get("sampleRate"),
                bit_depth=f.get("bitDepth"),
                length_s=f.get("length"),
                is_locked=bool(f.get("isLocked", False)),
                has_free_slot=bool(r.get("hasFreeUploadSlot", False)),
                queue_length=int(r.get("queueLength") or 0),
                upload_speed=int(r.get("uploadSpeed") or 0),
                file_count=int(r.get("fileCount") or len(r.get("files", []))),
            ))
    return out


def rank(responses: list[dict], wanted: Wanted, policy: QualityPolicy = DEFAULT_POLICY) -> list[Candidate]:
    cands = [score_candidate(c, wanted, policy) for c in parse_responses(responses)]
    return sorted(cands, key=lambda c: (c.rejected is not None, -c.score))


def explain(cands: list[Candidate], limit: int = 10, peers: bool = True) -> str:
    """Ranked, one candidate per block. peers=False labels each p1, p2, ... in rank order instead of naming
    the Soulseek user, for text that reaches events, logs or the web client."""
    lines = []
    for i, c in enumerate(cands[:limit], 1):
        head = f"{c.score:6.1f}  {(c.username if peers else f'p{i}'):<18} {c.basename[:60]}"
        lines.append(head + (f"   ✗ {c.rejected}" if c.rejected else ""))
        if not c.rejected:
            lines.append("         " + "; ".join(c.reasons))
    return "\n".join(lines)
