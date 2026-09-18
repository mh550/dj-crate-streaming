"""Post-download verification: is this file really what we asked for?

Stdlib-only checks that don't need ffmpeg:
  - FLAC STREAMINFO parse → sample rate, bit depth, channels, total samples → duration
  - "fake lossless" heuristic → implied kbps far below real FLAC
If ffprobe is on PATH we also use it for any format. AcoustID fingerprinting is a
TODO (needs `fpcalc` from chromaprint) — that's the definitive identity check.
"""
from __future__ import annotations

import json
import shutil
import struct
import subprocess
from dataclasses import dataclass
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
                             capture_output=True, text=True, timeout=30).stdout
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


def verify(path: Path, expected_duration_s: float | None = None, tolerance_s: float = 4.0, min_lossless_kbps: int = 500) -> Verdict:
    problems: list[str] = []
    if not path.exists():
        return Verdict(False, ["file missing"], None)
    info = probe(path)
    if not info:
        return Verdict(False, ["could not read audio header (no ffprobe and not FLAC?)"], None)
    if expected_duration_s and info.duration_s:
        d = abs(info.duration_s - expected_duration_s)
        if d > tolerance_s:
            problems.append(f"duration {info.duration_s:.0f}s vs expected {expected_duration_s:.0f}s (Δ{d:.0f}s)")
    if info.codec == "flac" and info.duration_s:
        kbps = path.stat().st_size * 8 / info.duration_s / 1000
        if kbps < min_lossless_kbps:
            problems.append(f"FLAC at {kbps:.0f} kbps looks like a lossy transcode")
    if info.sample_rate and info.sample_rate < 44100:
        problems.append(f"low sample rate {info.sample_rate}")
    return Verdict(not problems, problems, info)
