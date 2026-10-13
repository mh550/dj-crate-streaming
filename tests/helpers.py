"""Shared test helpers (plain functions, no pytest fixtures)."""
import json
import struct
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def load_responses() -> list[dict]:
    """The slskd-shaped search responses fixture; [0]["files"][0] is vinylhead77's Good Times FLAC."""
    return json.loads((FIXTURES / "search_responses.sample.json").read_text())


def make_flac(path: Path, sr=44100, bps=16, ch=2, total=44100 * 300, pad_bytes=0) -> Path:
    """Minimal FLAC: marker + STREAMINFO block (last) with a fake sample count; no frames.
    `pad_bytes` of zeros stand in for the audio so size-based checks (fake-lossless) work."""
    bits = (sr << 44) | ((ch - 1) << 41) | ((bps - 1) << 36) | total
    si = struct.pack(">HH", 4096, 4096) + b"\x00\x00\x00" * 2 + bits.to_bytes(8, "big") + b"\x00" * 16
    hdr = bytes([0x80 | 0]) + len(si).to_bytes(3, "big")
    path.write_bytes(b"fLaC" + hdr + si + b"\x00" * pad_bytes)
    return path
