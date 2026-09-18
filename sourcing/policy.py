"""Quality policy: what counts as acceptable / preferred for a crate file.

Mirrors the spec's "preferred + whitelist/blacklist filetypes/bitrates, separately
for stream vs crate". Only the crate side matters for sourcing.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QualityPolicy:
    # Ordered preference; earlier = better. Extensions lowercase, no dot.
    preferred: list[str] = field(default_factory=lambda: ["flac", "wav", "aiff", "alac", "m4a", "mp3", "ogg", "opus"])
    allow: list[str] = field(default_factory=lambda: ["flac", "wav", "aiff", "alac", "m4a", "mp3"])
    deny: list[str] = field(default_factory=lambda: ["wma", "ra", "mid", "opus"])
    # Lossy floor (kbps). Files below are rejected outright.
    min_lossy_bitrate: int = 320
    # Lossless sanity: reject "FLAC" files whose size/duration implies a transcode.
    min_lossless_kbps: int = 500
    # Sample-rate / bit-depth we consider acceptable for lossless.
    accept_sample_rates: tuple[int, ...] = (44100, 48000, 88200, 96000, 176400, 192000)
    accept_bit_depths: tuple[int, ...] = (16, 24)
    # Duration tolerance vs. known track length, seconds.
    duration_tolerance_s: float = 4.0

    LOSSLESS = {"flac", "wav", "aiff", "aif", "alac", "ape", "wv"}

    def format_rank(self, ext: str) -> int | None:
        ext = ext.lower().lstrip(".")
        if ext in self.deny or ext not in self.allow:
            return None
        try:
            return self.preferred.index(ext)
        except ValueError:
            return len(self.preferred)

    def is_lossless(self, ext: str) -> bool:
        return ext.lower().lstrip(".") in self.LOSSLESS


DEFAULT_POLICY = QualityPolicy()
