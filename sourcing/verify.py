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


@dataclass
class AudioInfo:
    duration_s: float | None
    sample_rate: int | None
    bit_depth: int | None
    channels: int | None
    codec: str | None
    source: str


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
        out = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                             stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30).stdout
        d = json.loads(out)
        a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), {})
        dur = float(d.get("format", {}).get("duration") or a.get("duration") or 0) or None
        bits = a.get("bits_per_raw_sample") or a.get("bits_per_sample")
        return AudioInfo(dur, int(a["sample_rate"]) if a.get("sample_rate") else None, int(bits) if bits else None,
                         a.get("channels"), a.get("codec_name"), "ffprobe")
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


# ---- decoded analysis ----

BAND_EDGES_KHZ = (11, 13, 15, 16, 17, 18, 19, 20)       # + 22, 24 above 48 kHz
CLIFF_DB = 15.0          # a step this big between adjacent edges is an encoder's lowpass; music falls 2-7 dB
EMPTY_DB = 90.0          # a band this far under the full band holds nothing
SILENCE = "silencedetect=n=-60dB:d=3"
LOSSLESS_CODECS = {"flac", "alac", "ape", "wavpack", "tta"}


def band_edges(sample_rate: int | None) -> list[int]:
    edges = list(BAND_EDGES_KHZ) + ([22, 24] if (sample_rate or 0) > 48000 else [])
    return [e for e in edges if e * 1000 < (sample_rate or 44100) / 2 - 500]


def estimate_cutoff(full_db: float, bands_db: dict) -> float:
    """Highest band edge (kHz) with real energy above it: stop at the first empty band or at the first cliff
    (≥ CLIFF_DB down from the previous edge). 0 = nothing above the first edge."""
    cutoff, prev = 0, None
    for edge in sorted(bands_db):
        level = bands_db[edge]
        if level == -math.inf or full_db - level >= EMPTY_DB or (prev is not None and prev - level >= CLIFF_DB):
            break
        cutoff, prev = edge, level
    return cutoff


def fingerprint_ber(a: list[int], b: list[int], max_shift: int = 80, min_overlap: int = 20) -> float:
    """Bit-error rate of two chromaprint raw fingerprints at their best alignment (one item ≈ 0.124 s, so
    ±80 ≈ ±10 s covers a vinyl rip vs a CD rip). 0 = identical, ~0.5 = unrelated, 1.0 = too short to say."""
    best = 1.0
    for shift in range(-max_shift, max_shift + 1):
        pairs = list(zip(a[max(shift, 0):], b[max(-shift, 0):]))
        if len(pairs) >= min_overlap:
            best = min(best, sum(bin((x ^ y) & 0xFFFFFFFF).count("1") for x, y in pairs) / (32 * len(pairs)))
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
    return {
        "errors": re.findall(r"^(?:\[[^\]]*\] )?\[(?:error|fatal)\] (.*)$", stderr, re.M),
        "full_db": num(full, "RMS level dB"),
        "bands_db": {e: num(d, "RMS level dB") for e, d in zip(edges, order[1:])},
        "peak_db": num(full, "Peak level dB"),
        "flat_factor": num(full, "Flat factor"),
        "bits_used": int(bits[1]) if len(bits) > 1 else None,
        "samples": int(float(full["Number of samples"])) if "Number of samples" in full else None,
        "silences": silences,
    }


def analyse(path: Path, sample_rate: int | None) -> dict:
    """One ffmpeg decode: full band (astats + silencedetect) and one brick-wall highpass per band edge."""
    edges = band_edges(sample_rate)
    n = len(edges) + 1
    chains = [f"[x0]astats=measure_perchannel=none,{SILENCE}[o0]"]
    for i, e in enumerate(edges, 1):
        chains.append(f"[x{i}]firequalizer=gain='if(gte(f,{e * 1000}),0,-120)':delay=0.02:accuracy=20,"
                      f"astats=measure_perchannel=none[o{i}]")
    graph = f"asplit={n}" + "".join(f"[x{i}]" for i in range(n)) + ";" + ";".join(chains)
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-nostats", "-loglevel", "level+info", "-i", str(path), "-filter_complex", graph]
    for i in range(n):
        cmd += ["-map", f"[o{i}]", "-f", "null", "-"]
    run = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600)
    m = parse_ffmpeg(run.stderr, edges)
    if run.returncode and not m["errors"]:
        m["errors"] = [run.stderr.strip().splitlines()[-1] if run.stderr.strip() else f"ffmpeg exit {run.returncode}"]
    if path.suffix.lower() == ".flac" and shutil.which("flac"):
        t = subprocess.run(["flac", "-t", "-s", str(path)], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600)
        if t.returncode:
            m["errors"].append("flac -t: " + (t.stderr.strip().splitlines() or ["failed"])[-1].strip())
    return m


def fingerprint(path: Path) -> list[int] | None:
    run = subprocess.run(["fpcalc", "-raw", "-json", "-length", "120", str(path)], stdin=subprocess.DEVNULL,
                         capture_output=True, text=True, timeout=300)
    try:
        return json.loads(run.stdout)["fingerprint"]
    except (ValueError, KeyError):
        return None


# ---- the verdict ----

HARD_EVERY_TIER = {"missing", "unreadable", "integrity", "duration", "truncated", "recording"}
HARD_FOR_CRATE = {"transcode", "fake_24bit", "fake_hires", "implied_kbps", "sample_rate"}


def verify(path: Path, expected_duration_s: float | None = None, tier: str | None = None, reference: Path | None = None,
           tolerance_s: float = 4.0, min_lossless_kbps: int = 500) -> Verdict:
    """Header checks always; with a `tier`, the decoded checks too (module docstring). Without a tier every
    finding is hard, which is the pre-M5 behaviour `fetch` relied on."""
    if tier is not None:
        from .policy import check_tier
        check_tier(tier)
    path = Path(path)
    findings: list[tuple[str, str]] = []
    m: dict = {}

    def verdict(info: AudioInfo | None) -> Verdict:
        hard = HARD_EVERY_TIER | HARD_FOR_CRATE if tier in (None, "crate") else HARD_EVERY_TIER
        problems = [msg for check, msg in findings if check in hard]
        return Verdict(not problems, problems, info, [msg for check, msg in findings if check not in hard], m)

    if not path.exists():
        findings.append(("missing", "file missing"))
        return verdict(None)
    info = probe(path)
    if not info:
        findings.append(("unreadable", "could not read audio header (no ffprobe and not FLAC?)"))
        return verdict(None)
    m.update(codec=info.codec, sample_rate=info.sample_rate, bit_depth=info.bit_depth, duration_s=info.duration_s)
    if info.duration_s:
        m["kbps"] = round(path.stat().st_size * 8 / info.duration_s / 1000)
    if expected_duration_s and info.duration_s:
        d = abs(info.duration_s - expected_duration_s)
        if d > tolerance_s:
            findings.append(("duration", f"duration {info.duration_s:.0f}s vs expected {expected_duration_s:.0f}s (Δ{d:.0f}s)"))
    if info.codec == "flac" and info.duration_s:
        kbps = path.stat().st_size * 8 / info.duration_s / 1000
        if kbps < min_lossless_kbps:
            findings.append(("implied_kbps", f"FLAC at {kbps:.0f} kbps looks like a lossy transcode"))
    if info.sample_rate and info.sample_rate < 44100:
        findings.append(("sample_rate", f"low sample rate {info.sample_rate}"))
    if tier is None:
        return verdict(info)

    if not shutil.which("ffmpeg"):
        findings.append(("skipped", "ffmpeg not on PATH: decoded checks skipped (integrity, cutoff, bit depth, "
                                    "truncation, silence, clipping)"))
    else:
        _decoded_checks(path, info, analyse(path, info.sample_rate), findings, m)
        if m.get("bands_db") and m["cutoff_khz"] == max(m["bands_db"]):   # the measured spectrum outranks the
            findings[:] = [("low_kbps", f"{msg}, but the full spectrum is there: quiet or simple material")
                           if check == "implied_kbps" else (check, msg) for check, msg in findings]   # size guess
    if reference is not None:
        if not shutil.which("fpcalc"):
            findings.append(("skipped", "fpcalc not on PATH: recording check skipped"))
        else:
            a, b = fingerprint(path), fingerprint(Path(reference))
            if a and b:
                m["fingerprint_ber"] = ber = round(fingerprint_ber(a, b), 3)
                if ber > 0.20:
                    findings.append(("recording", f"different recording from {Path(reference).name} "
                                                  f"(fingerprint bit-error rate {ber:.2f}; same audio is under 0.20)"))
            else:
                findings.append(("skipped", "fpcalc could not fingerprint one of the files: recording check skipped"))
    return verdict(info)


def _decoded_checks(path: Path, info: AudioInfo, a: dict, findings: list, m: dict) -> None:
    if a["errors"]:
        findings.append(("integrity", "decode errors: " + "; ".join(a["errors"][:3])))
    if a["samples"] is None or a["full_db"] is None:
        if not a["errors"]:
            findings.append(("integrity", "ffmpeg decoded no audio"))
        return
    sr = info.sample_rate or 44100
    m["decoded_s"] = decoded = round(a["samples"] / sr, 2)
    if info.duration_s and info.duration_s - decoded > 1.0:
        findings.append(("truncated", f"truncated: the header says {info.duration_s:.1f}s, only {decoded:.1f}s decodes"))
    m["bands_db"] = {e: round(v, 1) for e, v in a["bands_db"].items()}
    m["cutoff_khz"] = cutoff = estimate_cutoff(a["full_db"], a["bands_db"])
    top = max(a["bands_db"]) if a["bands_db"] else 0
    claims_lossless = (info.codec or "") in LOSSLESS_CODECS or (info.codec or "").startswith("pcm_")
    claims_hq = claims_lossless or (m.get("kbps") or 0) >= 315
    claim = "lossless" if claims_lossless else f"{m.get('kbps')} kbps"
    if claims_hq and cutoff <= 16:
        findings.append(("transcode", f"cutoff ≈{cutoff} kHz (energy stops above {cutoff} kHz) for a {claim} file: "
                                      f"lossless or 320 kbps reaches 19–20 kHz, so this likely came from ≤128 kbps"))
    elif claims_hq and cutoff <= 18 and top >= 19:
        findings.append(("maybe_lossy", f"cutoff ≈{cutoff} kHz for a {claim} file: may come from a ≤192 kbps source "
                                        f"(old or lo-fi recordings can lack highs too)"))
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
