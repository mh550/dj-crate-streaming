"""Post-download verification: is this file really what we asked for? (spec §3a)

Header checks (stdlib, no decoding):
  - FLAC STREAMINFO parse → sample rate, bit depth, channels, total samples → duration
  - "fake lossless" heuristic → implied kbps far below real FLAC
  - ffprobe, when on PATH, for any other format

With a tier, the file is also decoded once by ffmpeg (what careful Soulseek users do by hand with Spek,
`flac -t` and a listen): integrity, the spectral cutoff (a lossy source shows as a cliff in band energy),
bits actually used (16-bit padded to 24), fake hi-res, truncation, silence at the ends, clipping, and an
`fpcalc` fingerprint against a reference copy. The tier decides which findings are hard `problems`
(every tier: the file is broken, short or the wrong song; crate also: it isn't the quality it claims)
and which are `warnings`. Calibration notes: docs/plans/2026-10-15-m5-download-validation.md.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import struct
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .policy import DEFAULT_TIER, TIERS, check_tier

TEXT = {"text": True, "encoding": "utf-8", "errors": "replace"}   # ffmpeg echoes tags in whatever code page they're in


@dataclass
class AudioInfo:
    duration_s: float | None
    sample_rate: int | None
    bit_depth: int | None
    channels: int | None
    codec: str | None
    source: str
    duration_exact: bool = True     # False when ffprobe estimated it from the bitrate (VBR mp3 without a Xing header)


def flac_streaminfo(path: Path) -> AudioInfo | None:
    with path.open("rb") as f:
        if f.read(4) != b"fLaC":
            return None
        while True:
            hdr = f.read(4)
            if len(hdr) < 4:
                return None
            last = hdr[0] & 0x80
            btype = hdr[0] & 0x7F
            length = int.from_bytes(hdr[1:4], "big")
            block = f.read(length)
            if btype == 0 and length >= 34:
                # STREAMINFO: 16+16 block sizes, 24+24 frame sizes, then 20 bits sr, 3 bits ch-1, 5 bits bps-1, 36 bits samples
                bits = int.from_bytes(block[10:18], "big")
                sr = bits >> 44
                ch = ((bits >> 41) & 0x7) + 1
                bps = ((bits >> 36) & 0x1F) + 1
                total = bits & ((1 << 36) - 1)
                return AudioInfo(total / sr if sr and total else None, sr, bps, ch, "flac", "flac-streaminfo")
            if last:
                return None


def ffprobe(path: Path) -> AudioInfo | None:
    if not shutil.which("ffprobe"):
        return None
    try:
        run = subprocess.run(["ffprobe", "-v", "warning", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                             stdin=subprocess.DEVNULL, capture_output=True, timeout=30, **TEXT)
        d = json.loads(run.stdout)
        a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), {})
        dur = float(d.get("format", {}).get("duration") or a.get("duration") or 0) or None
        bits = a.get("bits_per_raw_sample") or a.get("bits_per_sample")
        return AudioInfo(dur, int(a["sample_rate"]) if a.get("sample_rate") else None, int(bits) if bits else None,
                         a.get("channels"), a.get("codec_name"), "ffprobe",
                         "Estimating duration from bitrate" not in run.stderr)
    except Exception:
        return None


def probe(path: Path) -> AudioInfo | None:
    if path.suffix.lower() == ".flac":
        info = flac_streaminfo(path)
        if info:
            return info
    return ffprobe(path)


@dataclass
class Verdict:
    ok: bool
    problems: list[str]
    info: AudioInfo | None
    warnings: list[str] = field(default_factory=list)
    measurements: dict = field(default_factory=dict)

    def as_dict(self, tier: str | None) -> dict:
        """The record `fetch` keeps per wanted row and `cli verify --json` prints (JSON-safe)."""
        return {"ok": self.ok, "tier": tier, "problems": self.problems, "warnings": self.warnings,
                "measurements": self.measurements}


# ---- decoded analysis ----

BAND_EDGES_KHZ = (11, 13, 15, 16, 17, 18, 19, 20)       # + 22, 24 above 48 kHz
CLIFF_DB = 15.0          # a step this big between adjacent edges is an encoder's lowpass; music falls 2-7 dB
EMPTY_DB = 90.0          # a band this far under the full band holds nothing
SILENCE = "silencedetect=n=-60dB:d=3"
LOSSLESS_CODECS = {"flac", "alac", "ape", "wavpack", "tta"}   # ffprobe codec names (policy.LOSSLESS holds extensions)


def band_edges(sample_rate: int | None) -> list[int]:
    edges = list(BAND_EDGES_KHZ) + ([22, 24] if (sample_rate or 0) > 48000 else [])
    return [e for e in edges if e * 1000 < (sample_rate or 44100) / 2 - 500]


def estimate_cutoff(full_db: float, bands_db: dict) -> float | None:
    """Highest band edge (kHz) with real energy above it: stop at the first empty band or at the first cliff
    (≥ CLIFF_DB down from the previous edge). 0 = nothing above the first edge; None = no bands measured."""
    if not bands_db:
        return None
    cutoff, prev = 0, None
    for edge in sorted(bands_db):
        level = bands_db[edge]
        if level == -math.inf or full_db - level >= EMPTY_DB or (prev is not None and prev - level >= CLIFF_DB):
            break
        cutoff, prev = edge, level
    return cutoff


def full_band(m: dict) -> bool:
    """The measured spectrum reaches the top band edge (no lowpass anywhere)."""
    return bool(m.get("bands_db")) and m.get("cutoff_khz") == max(m["bands_db"])


def fingerprint_ber(a: list[int], b: list[int], max_shift: int = 80, min_overlap: int = 20) -> float:
    """Bit-error rate of two chromaprint raw fingerprints at their best alignment (one item ≈ 0.124 s, so
    ±80 ≈ ±10 s covers a vinyl rip vs a CD rip). 0 = identical, ~0.5 = unrelated, 1.0 = too short to say."""
    best = 1.0
    for shift in range(-max_shift, max_shift + 1):
        i, j = max(shift, 0), max(-shift, 0)
        n = min(len(a) - i, len(b) - j)
        if n >= min_overlap:
            best = min(best, sum(((a[i + k] ^ b[j + k]) & 0xFFFFFFFF).bit_count() for k in range(n)) / (32 * n))
    return best


_ASTATS = re.compile(r"^\[Parsed_astats_(\d+) @ [^\]]*\] \[info\] ([^:]+): (\S+)", re.M)


def parse_ffmpeg(stderr: str, edges: list[int]) -> dict:
    """Read one `analyse` run (`-loglevel level+info`). The first astats is the full band; the rest are the
    band branches in `edges` order (ffmpeg numbers filters in graph order, but prints them out of order)."""
    stats: dict[int, dict[str, str]] = {}
    for idx, key, val in _ASTATS.findall(stderr):
        stats.setdefault(int(idx), {})[key] = val
    order = [stats[k] for k in sorted(stats)]
    num = lambda d, k: float(d[k]) if k in d else None    # float() reads "-inf"
    full = order[0] if order else {}
    silences: list[tuple[float, float | None]] = []
    for kind, t in re.findall(r"\[silencedetect @ [^\]]*\] \[info\] silence_(start|end): (\S+)", stderr):
        if kind == "start":
            silences.append((float(t), None))
        elif silences:
            silences[-1] = (silences[-1][0], float(t))
    bits = full.get("Bit depth", "").split("/")
    complete = len(order) == len(edges) + 1          # else a band branch printed nothing: don't shift the rest
    return {
        "errors": re.findall(r"^(?:\[[^\]]*\] )?\[(?:error|fatal)\] (.*)$", stderr, re.M),
        "full_db": num(full, "RMS level dB"),
        "bands_db": {e: num(d, "RMS level dB") for e, d in zip(edges, order[1:])} if complete else {},
        "complete": complete,
        "flac_t": None,
        "peak_db": num(full, "Peak level dB"),
        "flat_factor": num(full, "Flat factor"),
        "bits_used": int(bits[1]) if len(bits) > 1 else None,
        "samples": int(float(full["Number of samples"])) if "Number of samples" in full else None,
        "silences": silences,
    }


MAX_DECODE_NOISE = 10    # fewer ffmpeg errors than this, with the audio all there, is a junk frame or a tag: a warning


def analyse(path: Path, sample_rate: int | None, duration_s: float | None = None) -> dict:
    """One ffmpeg decode: full band (astats + silencedetect) and one brick-wall highpass per band edge, each
    band ending in a null sink; plus `flac -t` (the MD5 of the decoded audio) for FLAC. The timeout grows with
    length × rate (≈20 ms per second of 44.1 kHz audio on this box), never under 10 minutes."""
    timeout = max(600.0, 60 + 2 * (duration_s or 0) * max(1.0, (sample_rate or 44100) / 44100))
    edges = band_edges(sample_rate)
    n = len(edges) + 1
    chains = [f"[x0]astats=measure_perchannel=none,{SILENCE}[o0]"]
    for i, e in enumerate(edges, 1):
        chains.append(f"[x{i}]firequalizer=gain='if(gte(f,{e * 1000}),0,-120)':delay=0.02:accuracy=20,"
                      f"astats=measure_perchannel=none[o{i}]")
    graph = f"asplit={n}" + "".join(f"[x{i}]" for i in range(n)) + ";" + ";".join(chains)
    # Every band is its own null output. ffmpeg 7.1 (the image's Debian 13 build) panics with "Assertion
    # best_input >= 0 failed" when a firequalizer branch ends in anullsink: its delay flushes after the input ends.
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-nostats", "-loglevel", "level+info", "-i", str(path),
           "-filter_complex", graph]
    for i in range(n):
        cmd += ["-map", f"[o{i}]", "-f", "null", "-"]
    run = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, **TEXT)
    m = parse_ffmpeg(run.stderr, edges)
    if run.returncode and not m["errors"]:
        m["errors"] = [run.stderr.strip().splitlines()[-1] if run.stderr.strip() else f"ffmpeg exit {run.returncode}"]
    if path.suffix.lower() == ".flac" and shutil.which("flac"):
        t = subprocess.run(["flac", "-t", "-s", str(path)], stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, **TEXT)
        if t.returncode:
            m["flac_t"] = (t.stderr.strip().splitlines() or ["failed"])[-1].strip()
    return m


FINGERPRINT_S = 120          # the default window; a copy upgrade fingerprints the whole file (cap below)
FINGERPRINT_MAX_S = 900


def fingerprint(path: Path, length: int = FINGERPRINT_S) -> list[int] | None:
    run = subprocess.run(["fpcalc", "-raw", "-json", "-length", str(length), str(path)], stdin=subprocess.DEVNULL,
                         capture_output=True, timeout=300, **TEXT)
    try:
        return json.loads(run.stdout)["fingerprint"]
    except (ValueError, KeyError):
        return None


# ---- the verdict ----

HARD_EVERY_TIER = {"missing", "unreadable", "integrity", "duration", "truncated", "recording"}
HARD_WHEN_STRICT = {"transcode", "fake_24bit", "fake_hires", "implied_kbps", "sample_rate"}   # policy.strict_verify


def verify(path: Path, expected_duration_s: float | None = None, tier: str | None = None, reference: Path | None = None,
           tolerance_s: float | None = None, min_lossless_kbps: int | None = None, recording_id: str | None = None,
           lookup: Callable[[Path], list[dict]] | None = None, intent: str | None = None,
           listed_length_s: float | None = None) -> Verdict:
    """Header checks always; with a `tier`, the decoded checks too (module docstring). The tier's policy sets the
    thresholds and how strict it is. Without a tier: header checks only, judged like crate (pre-M5 behaviour).
    With a tier and a `lookup` (AcoustID), the file's recording is looked up and compared with `recording_id`.
    `intent` (M7) says what the download is for: "copy" is a better copy of the owned recording, so it should be
    compared with that copy (`reference`); "version" is another version of the song, which has no reference to
    match (its fingerprint is not expected to), so the recording check is the AcoustID lookup alone."""
    if intent == "version" and reference is not None:
        raise ValueError("a new version has no reference copy")
    policy = TIERS[check_tier(tier or DEFAULT_TIER)]
    tolerance_s = policy.duration_tolerance_s if tolerance_s is None else tolerance_s
    min_lossless_kbps = policy.min_lossless_kbps if min_lossless_kbps is None else min_lossless_kbps
    path = Path(path)
    reference = Path(reference) if reference is not None else None
    hard = HARD_EVERY_TIER | (HARD_WHEN_STRICT if policy.strict_verify else set())
    findings: list[tuple[str, str]] = []
    m: dict = {}

    def verdict(info: AudioInfo | None) -> Verdict:
        problems, warnings = [], []
        for check, msg in findings:
            if check == "implied_kbps" and full_band(m):     # the measured spectrum outranks the size guess
                check, msg = "low_kbps", f"{msg}, but the full spectrum is there: quiet or simple material"
            (problems if check in hard else warnings).append(msg)
        if intent == "copy":
            # M8 deletes the old copy when this is True, so it implies ok: the fingerprint matched over the overlap
            # (a truncated prefix matches perfectly, hence the length test against the reference), the reference is
            # a different file, and nothing else is wrong with the download. The length compared is the *decoded*
            # one: a truncated FLAC keeps its STREAMINFO length and a VBR MP3's header length is an estimate, so a
            # skipped decode (no ffmpeg, a timeout) can never prove the download whole.
            ref_s, decoded_s = m.get("reference_duration_s"), m.get("decoded_s")
            m["replaceable"] = bool(
                not problems and m.get("reference_compared") and m.get("fingerprint_ber", 1.0) <= MAX_SAME_BER
                and ref_s and decoded_s and abs(decoded_s - ref_s) <= tolerance_s
                and reference is not None and m.get("reference") and not _same_file(path, reference))
            if not problems and m.get("reference_compared") and not decoded_s:
                warnings.append("not replaceable: the decoded length was not measured (decoded checks skipped), "
                                "so the download may be a truncated prefix of the reference")
        return Verdict(not problems, problems, info, warnings, finite(m))

    if not path.exists():
        findings.append(("missing", "file missing"))
        return verdict(None)
    info = probe(path)
    if not info:
        findings.append(("unreadable", "could not read audio header (no ffprobe and not FLAC?)"))
        return verdict(None)
    m.update(codec=info.codec, sample_rate=info.sample_rate, bit_depth=info.bit_depth, duration_s=info.duration_s)
    if intent is not None:
        m["intent"] = intent
    if intent == "copy":     # M8 deletes the old copy only when a fingerprint comparison actually passed
        m["reference_compared"], m["replaceable"] = False, False
    def check_length(length: float | None) -> None:
        if expected_duration_s and length and abs(length - expected_duration_s) > tolerance_s:
            findings.insert(0, ("duration", f"duration {length:.0f}s vs expected {expected_duration_s:.0f}s "
                                            f"(Δ{abs(length - expected_duration_s):.0f}s)"))

    def check_listing(length: float | None) -> None:
        """A new version has no expected length, but the peer listed one for this very file: what arrived must be
        close to it (not the candidate vouching for itself: it is the peer's listing against our own measurement)."""
        if intent == "version" and listed_length_s and length and abs(length - listed_length_s) > max(10, 0.05 * listed_length_s):
            findings.insert(0, ("duration", f"arrived length differs from the peer's listing ({length:.0f}s vs "
                                            f"{listed_length_s:.0f}s listed)"))

    if tier is None or info.duration_exact:      # else the decoded length decides, below
        check_length(info.duration_s)
        check_listing(info.duration_s)
    if info.duration_s:
        kbps = path.stat().st_size * 8 / info.duration_s / 1000
        m["kbps"] = round(kbps)
        if info.codec == "flac" and kbps < min_lossless_kbps:
            findings.append(("implied_kbps", f"FLAC at {kbps:.0f} kbps looks like a lossy transcode"))
    if info.sample_rate and info.sample_rate < 44100:
        findings.append(("sample_rate", f"low sample rate {info.sample_rate}"))
    if tier is None:
        return verdict(info)

    if not shutil.which("ffmpeg"):
        findings.append(("skipped", "ffmpeg not on PATH: decoded checks skipped (integrity, cutoff, bit depth, "
                                    "truncation, silence, clipping)"))
    else:
        try:
            _decoded_checks(info, analyse(path, info.sample_rate, info.duration_s), findings, m)
        except subprocess.TimeoutExpired as e:
            findings.append(("skipped", f"decoded checks timed out after {e.timeout:.0f}s and were skipped"))
    if not info.duration_exact:
        check_length(m.get("decoded_s") or info.duration_s)
        check_listing(m.get("decoded_s") or info.duration_s)
    if reference is not None:
        _recording_check(path, reference, findings, m, whole=intent == "copy")
    elif intent == "copy":
        findings.append(("reference", "copy upgrade without a reference: the recording was not compared"))
    if lookup is not None:
        _acoustid_check(path, lookup, recording_id, findings, m)
    return verdict(info)


def finite(v):
    """JSON has no -inf/NaN (astats says -inf for silence): None instead, inside dicts too."""
    if isinstance(v, dict):
        return {k: finite(x) for k, x in v.items()}
    return None if isinstance(v, float) and not math.isfinite(v) else v


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.samefile(b)
    except OSError:
        return a.resolve() == b.resolve()


MAX_SAME_BER = 0.20      # same audio is under this, a different recording well over


def _recording_check(path: Path, reference: Path, findings: list, m: dict, whole: bool = False) -> None:
    """Fingerprint both files and compare. `whole` (a copy upgrade) fingerprints their full length, so two edits
    that share an intro cannot pass as one recording, and sets `reference_compared` / `replaceable`."""
    if not shutil.which("fpcalc"):
        findings.append(("skipped", "fpcalc not on PATH: recording check skipped"))
        return
    length = FINGERPRINT_S
    if whole:
        # Which file was compared, as it was then: M8 trashes exactly this file, and only if it is unchanged, not
        # whatever Navidrome resolves for the song later.
        try:
            st = reference.stat()
            m["reference"] = {"path": str(reference.resolve()), "size": st.st_size, "mtime_ns": st.st_mtime_ns}
        except OSError:
            m["reference"] = None
        mine, theirs = probe(path), probe(reference)
        m["reference_duration_s"] = theirs.duration_s if theirs else None
        secs = [i.duration_s for i in (mine, theirs) if i and i.duration_s]
        length = min(FINGERPRINT_MAX_S, math.ceil(max(secs))) if secs else FINGERPRINT_S
    try:
        a, b = fingerprint(path, length), fingerprint(reference, length)
    except subprocess.TimeoutExpired:
        a = b = None
    if not (a and b):
        findings.append(("skipped", "fpcalc could not fingerprint one of the files: recording check skipped"))
        return
    m["fingerprint_ber"] = ber = round(fingerprint_ber(a, b), 3)
    if whole:
        m["reference_compared"] = True
    if ber > MAX_SAME_BER:
        findings.append(("recording", f"different recording from {reference.name} "
                                      f"(fingerprint bit-error rate {ber:.2f}; same audio is under {MAX_SAME_BER:.2f})"))


def _acoustid_check(path: Path, lookup: Callable[[Path], list[dict]], recording_id: str | None,
                    findings: list, m: dict) -> None:
    """A failed lookup (no network, bad key, no fpcalc) is only a warning; a *disagreement* with the recording
    Navidrome knows is the hard `recording` finding. Nothing known (no recording_id) or nothing found never fails."""
    try:
        recs = lookup(path)
    except Exception as e:
        m["acoustid"] = {"error": f"{type(e).__name__}: {e}"}
        findings.append(("acoustid", f"AcoustID lookup failed: {type(e).__name__}: {e}"))
        return
    top = recs[0] if recs else {}
    m["acoustid"] = {"recording_id": top.get("id"), "title": top.get("title"), "score": top.get("score"),
                     "ids": [r["id"] for r in recs]}
    if not recs:
        findings.append(("acoustid", "fingerprint not in AcoustID"))
    elif recording_id is not None and recording_id not in m["acoustid"]["ids"]:
        findings.append(("recording", f"AcoustID says this is {top.get('title')} ({top['id']}), "
                                      f"not recording {recording_id}"))


def _decoded_checks(info: AudioInfo, a: dict, findings: list, m: dict) -> None:
    # Integrity. `flac -t` is the authority for FLAC (it checks the MD5 of the audio). ffmpeg also logs metadata
    # it can't parse (a webp cover, an odd ID3 frame) and skipped junk frames as [error]: a handful with the
    # audio all there is a warning; lost audio shows up as truncation below.
    errs = "; ".join(a["errors"][:3])
    if a["flac_t"]:
        findings.append(("integrity", f"flac -t: {a['flac_t']}"))
    if a["samples"] is None or a["full_db"] is None:
        findings.append(("integrity", "could not decode" + (f": {errs}" if errs else " any audio")))
        return
    if len(a["errors"]) >= MAX_DECODE_NOISE:
        findings.append(("integrity", f"{len(a['errors'])} decode errors: {errs}"))
    elif errs:
        findings.append(("decode_noise", f"ffmpeg reported: {errs}"))
    if a["full_db"] == -math.inf:
        findings.append(("integrity", "no signal: the file is digital silence"))
    sr = info.sample_rate or 44100
    m["decoded_s"] = decoded = round(a["samples"] / sr, 2)
    if info.duration_exact and info.duration_s and info.duration_s - decoded > 1.0:
        findings.append(("truncated", f"truncated: the header says {info.duration_s:.1f}s, only {decoded:.1f}s decodes"))
    if not a["complete"]:
        findings.append(("skipped", "the band analysis came back incomplete: cutoff checks skipped"))
    m["bands_db"] = {e: round(v, 1) for e, v in a["bands_db"].items()}
    m["cutoff_khz"] = cutoff = estimate_cutoff(a["full_db"], a["bands_db"])
    codec = info.codec or ""
    claims_lossless = codec in LOSSLESS_CODECS or codec.startswith("pcm_")
    if cutoff is not None:                                   # the spectral rules need measured bands
        claim = "lossless" if claims_lossless else f"{m.get('kbps')} kbps"
        if claims_lossless or (m.get("kbps") or 0) >= 315:
            if cutoff <= 16:
                where = f"cutoff ≈{cutoff} kHz (energy stops above {cutoff} kHz)" if cutoff else "nothing above 11 kHz"
                findings.append(("transcode", f"{where} for a {claim} file: "
                                              f"lossless or 320 kbps reaches 19–20 kHz, so this likely came from ≤128 kbps"))
            elif cutoff <= 18 and max(a["bands_db"]) >= 19:
                findings.append(("maybe_lossy", f"cutoff ≈{cutoff} kHz for a {claim} file: may come from a ≤192 kbps "
                                                f"source (old or lo-fi recordings can lack highs too)"))
        if sr > 48000 and cutoff <= 22:
            findings.append(("fake_hires", f"{sr} Hz but nothing above ≈{max(cutoff, 20)} kHz: likely upsampled from 44.1/48 kHz"))
    m["bits_used"] = a["bits_used"]
    if claims_lossless and (info.bit_depth or 0) > 16 and a["bits_used"] and a["bits_used"] <= 16:
        findings.append(("fake_24bit", f"{info.bit_depth}-bit file uses only {a['bits_used']} bits: padded from 16-bit"))
    m["peak_db"], m["flat_factor"] = a["peak_db"], a["flat_factor"]
    if a["peak_db"] is not None and a["peak_db"] >= -0.1 and (a["flat_factor"] or 0) >= 1.0:
        findings.append(("clipping", f"clipped: peak {a['peak_db']:.2f} dBFS, flat factor {a['flat_factor']:.1f}"))
    for start, end in a["silences"]:
        if start <= 0.05:
            m["silence_start_s"] = round((end if end is not None else decoded) - start, 1)
            findings.append(("silence", f"{m['silence_start_s']}s of silence at the start"))
        elif end is None or end >= decoded - 0.05:
            m["silence_end_s"] = round(decoded - start, 1)
            findings.append(("silence", f"{m['silence_end_s']}s of silence at the end"))
