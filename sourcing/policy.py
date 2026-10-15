"""Quality policy: what counts as acceptable / preferred for a crate file.

Mirrors the spec's "preferred + whitelist/blacklist filetypes/bitrates". Four tiers (spec §1, D9):
low / medium / high trade quality for arrival time when sourcing something to listen to; crate is
the policy for files that go on real systems (lossless preferred, 320 kbps floor), unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QualityPolicy:
    name: str = "crate"
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
    # Speed vs quality (spec §1): 0 = quality only (crate), 1 = arrival time only.
    speed_weight: float = 0.0
    # An estimated arrival of this many seconds scores 50 of 100 on speed.
    arrival_budget_s: float = 60.0
    # Our own download cap, bytes/s (0 = none): a fast peer can't beat it.
    download_cap_Bps: int = 0

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


_LISTENING = dict(allow=["flac", "wav", "aiff", "alac", "m4a", "mp3", "ogg", "opus"], deny=["wma", "ra", "mid"])

# One setting, four values (spec §1, D9). Low/medium/high are for listening; crate is today's policy.
TIERS: dict[str, QualityPolicy] = {
    "low": QualityPolicy(name="low", min_lossy_bitrate=32, speed_weight=0.8, arrival_budget_s=60, **_LISTENING),
    "medium": QualityPolicy(name="medium", min_lossy_bitrate=64, speed_weight=0.6, arrival_budget_s=60, **_LISTENING),
    "high": QualityPolicy(name="high", min_lossy_bitrate=128, speed_weight=0.35, arrival_budget_s=300, **_LISTENING),
    "crate": QualityPolicy(),
}
DEFAULT_POLICY = TIERS["crate"]
