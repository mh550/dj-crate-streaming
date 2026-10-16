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
    # Downloaded-file check (spec §3a): a file that isn't the quality it claims (transcode, padded bits,
    # upsampled) is rejected (True, crate) or accepted with a warning (False, the listening tiers).
    strict_verify: bool = True

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


# Our own download speed through the VPN, bytes/s. Peers *report* upload speeds up to 61 MB/s (live, M4),
# which made a 28 MB FLAC look as quick as a 5 MB file. 1 MB/s is an assumption until a real download measures it.
OUR_DOWNLOAD_CAP_BPS = 1_000_000

def _listening(**kw) -> QualityPolicy:
    return QualityPolicy(allow=["flac", "wav", "aiff", "alac", "m4a", "mp3", "ogg", "opus"], deny=["wma", "ra", "mid"],
                         download_cap_Bps=OUR_DOWNLOAD_CAP_BPS, strict_verify=False, **kw)   # fresh lists per tier

# One setting, four values (spec §1, D9). Low/medium/high are for listening; crate is today's policy.
TIERS: dict[str, QualityPolicy] = {
    "low": _listening(name="low", min_lossy_bitrate=32, speed_weight=0.8, arrival_budget_s=60),
    "medium": _listening(name="medium", min_lossy_bitrate=64, speed_weight=0.6, arrival_budget_s=60),
    "high": _listening(name="high", min_lossy_bitrate=128, speed_weight=0.35, arrival_budget_s=300),
    "crate": QualityPolicy(),
}
DEFAULT_TIER = "crate"
IMPORT_TIER = "medium"      # D15 (Michael, 2026-10-15): new rows from import-playlist / seed-spotify, unless --tier
DEFAULT_POLICY = TIERS[DEFAULT_TIER]

# D19: a sourcing tier only says which file we keep; stream quality belongs to the client. "server" sends no
# format and no maxBitRate, so Navidrome's per-player transcoding profile decides. The opus presets and
# "crate" (original bytes) stay as explicit overrides: (Subsonic format, maxBitRate kbps).
STREAM: dict[str, tuple[str | None, int | None]] = {
    "server": (None, None), "low": ("opus", 64), "medium": ("opus", 96), "high": ("opus", 160), "crate": ("raw", None)}
STREAM_DEFAULT = "server"


def check_tier(name: str) -> str:
    if name not in TIERS:
        raise ValueError(f"unknown tier {name!r} (one of {', '.join(TIERS)})")
    return name


def check_stream(name: str) -> str:
    if name not in STREAM:
        raise ValueError(f"unknown stream {name!r} (one of {', '.join(STREAM)})")
    return name
