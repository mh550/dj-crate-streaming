"""Quality policy: what counts as acceptable / preferred for a crate file.

Mirrors the spec's "preferred + whitelist/blacklist filetypes/bitrates". Four tiers (spec §1, D9):
low / medium / high trade quality for arrival time when sourcing something to listen to; crate is
the policy for files that go on real systems (lossless preferred, 320 kbps floor), unchanged.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from sourcing import identity


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
    # D16 version preferences (deploy/policy.toml): kinds favoured when picking a download, best first, and
    # other versions an import may accept in place of the one a playlist row asked for.
    prefer_versions: tuple[str, ...] = ()
    accept_versions: tuple[str, ...] = ()

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


# The tiers (spec §1, D9) and the version preferences (D16) are Michael's settings, so they live in
# deploy/policy.toml. Low/medium/high are for listening; crate is for files that go on real systems.
POLICY_FILE = Path(__file__).resolve().parent.parent / "deploy" / "policy.toml"

_TIER_KEYS = {"allow": list, "deny": list, "min_lossy_bitrate": int, "speed_weight": (int, float),
              "arrival_budget_s": (int, float), "download_cap_Bps": int, "strict_verify": bool}
_RANGES = {"speed_weight": (0, 1), "min_lossy_bitrate": (0, None), "download_cap_Bps": (0, None),
           "arrival_budget_s": (0, None)}
_VERSION_KEYS = {"prefer": "prefer_versions", "accept": "accept_versions"}


def _bad(path: Path, where: str, why: str) -> ValueError:
    return ValueError(f"{path}: {where}: {why}")


def _typed(path: Path, where: str, key: str, value, want) -> None:
    ok = isinstance(value, want) and not (isinstance(value, bool) and want is not bool)
    if not ok:
        names = want.__name__ if isinstance(want, type) else "number"
        raise _bad(path, f"{where}.{key}", f"expected {names}, got {value!r}")
    if key not in _RANGES:
        return
    lo, hi = _RANGES[key]
    if value < lo or (hi is not None and value > hi) or (key == "arrival_budget_s" and value <= 0):
        raise _bad(path, f"{where}.{key}", f"{value!r} out of range ({'> 0' if key == 'arrival_budget_s' else f'{lo} to {hi}' if hi is not None else f'>= {lo}'})")


def require_tiers(path: Path, tiers: dict[str, QualityPolicy], names) -> None:
    """The code names some tiers (default, import, stream presets): a file without one stops the start."""
    for name in names:
        if name not in tiers:
            raise _bad(Path(path), f"[tiers.{name}]", "missing, but the code uses this tier")


def load_policy(path: Path) -> dict[str, QualityPolicy]:
    """Read [tiers.<name>] (in file order) and merge [versions.<name>] into the same tier.

    Raises ValueError naming the file and the key for anything unexpected: a typo in Michael's file must stop
    the start, not quietly fall back to a default.
    """
    path = Path(path)
    try:
        with path.open("rb") as f:
            doc = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ValueError(f"{path}: cannot read: {e}") from e
    for top in doc:
        if top not in ("tiers", "versions"):
            raise _bad(path, top, "unknown section (expected tiers, versions)")
    tiers, versions = doc.get("tiers", {}), doc.get("versions", {})
    out: dict[str, QualityPolicy] = {}
    for name, table in tiers.items():
        where = f"[tiers.{name}]"
        if not isinstance(table, dict):
            raise _bad(path, where, "expected a table")
        for key in table:
            if key not in _TIER_KEYS:
                raise _bad(path, f"{where}.{key}", f"unknown key (expected {', '.join(_TIER_KEYS)})")
        for key, want in _TIER_KEYS.items():
            if key not in table:
                raise _bad(path, f"{where}.{key}", "missing")
            _typed(path, where, key, table[key], want)
        for key in ("allow", "deny"):
            if not all(isinstance(x, str) for x in table[key]):
                raise _bad(path, f"{where}.{key}", f"expected a list of strings, got {table[key]!r}")
        out[name] = QualityPolicy(name=name, **table)
    for name, table in versions.items():
        where = f"[versions.{name}]"
        if name not in out:
            raise _bad(path, where, f"no [tiers.{name}] to attach it to")
        if not isinstance(table, dict):
            raise _bad(path, where, "expected a table")
        for key in table:
            if key not in _VERSION_KEYS:
                raise _bad(path, f"{where}.{key}", f"unknown key (expected {', '.join(_VERSION_KEYS)})")
            words = table[key]
            if not isinstance(words, list) or not all(isinstance(w, str) for w in words):
                raise _bad(path, f"{where}.{key}", f"expected a list of words, got {words!r}")
            for w in words:
                if w not in identity.KINDS:
                    raise _bad(path, f"{where}.{key}", f"unknown version word {w!r} (one of {', '.join(identity.KINDS)})")
            setattr(out[name], _VERSION_KEYS[key], tuple(words))
    return out


TIERS: dict[str, QualityPolicy] = load_policy(POLICY_FILE)
DEFAULT_TIER = "crate"
IMPORT_TIER = "medium"      # D15 (Michael, 2026-10-15): new rows from import-playlist / seed-spotify, unless --tier
DEFAULT_POLICY = TIERS[DEFAULT_TIER]

# D19: a sourcing tier only says which file we keep; stream quality belongs to the client. "server" sends no
# format and no maxBitRate, so Navidrome's per-player transcoding profile decides. The opus presets and
# "crate" (original bytes) stay as explicit overrides: (Subsonic format, maxBitRate kbps).
STREAM: dict[str, tuple[str | None, int | None]] = {
    "server": (None, None), "low": ("opus", 64), "medium": ("opus", 96), "high": ("opus", 160), "crate": ("raw", None)}
STREAM_DEFAULT = "server"

require_tiers(POLICY_FILE, TIERS, [DEFAULT_TIER, IMPORT_TIER, *(k for k in STREAM if k != "server")])


def check_tier(name: str) -> str:
    if name not in TIERS:
        raise ValueError(f"unknown tier {name!r} (one of {', '.join(TIERS)})")
    return name


def check_stream(name: str) -> str:
    if name not in STREAM:
        raise ValueError(f"unknown stream {name!r} (one of {', '.join(STREAM)})")
    return name


def tier_rank(name: str) -> int:
    """Position in deploy/policy.toml's tier order (low < medium < high < crate); ValueError for an unknown tier."""
    try:
        return list(TIERS).index(name)
    except ValueError:
        raise ValueError(f"unknown tier {name!r} (one of {', '.join(TIERS)})") from None


def max_tier(*names: str | None) -> str | None:
    """The highest of the given tiers, ignoring None; None when there are none. A track's target is the max
    over the playlists that hold it."""
    named = [n for n in names if n is not None]
    return max(named, key=tier_rank) if named else None
