"""deploy/policy.toml: the tiers move out of code with the same values, and a typo fails loudly at load (M7 Task 3)."""
import dataclasses
from pathlib import Path

import pytest

from sourcing.policy import TIERS, QualityPolicy, load_policy

ROOT = Path(__file__).resolve().parent.parent


def _listening(**kw) -> QualityPolicy:
    # The pre-M7 code, copied literally: D17 (the floors) is open, so no number may move with the file.
    return QualityPolicy(allow=["flac", "wav", "aiff", "alac", "m4a", "mp3", "ogg", "opus"], deny=["wma", "ra", "mid"],
                         download_cap_Bps=1_000_000, strict_verify=False, **kw)


def test_policy_file_reproduces_todays_tiers():
    expected = {
        "low": _listening(name="low", min_lossy_bitrate=32, speed_weight=0.8, arrival_budget_s=60),
        "medium": _listening(name="medium", min_lossy_bitrate=64, speed_weight=0.6, arrival_budget_s=60),
        "high": _listening(name="high", min_lossy_bitrate=128, speed_weight=0.35, arrival_budget_s=300),
        "crate": QualityPolicy(),
    }
    got = {k: dataclasses.replace(v, prefer_versions=(), accept_versions=()) for k, v in TIERS.items()}
    assert got == expected
    assert list(TIERS) == ["low", "medium", "high", "crate"]


def test_versions_per_tier():
    assert TIERS["crate"].prefer_versions == ("extended", "club", "original")
    assert TIERS["crate"].accept_versions == ("extended", "club")
    assert TIERS["medium"].accept_versions == ("extended",)
    assert TIERS["medium"].prefer_versions == ()


def _write(tmp_path, text):
    p = tmp_path / "policy.toml"
    p.write_text(text, encoding="utf-8")
    return p


GOOD = """
[tiers.crate]
allow = ["flac"]
deny = ["wma"]
min_lossy_bitrate = 320
speed_weight = 0
arrival_budget_s = 60
download_cap_Bps = 0
strict_verify = true
"""


def test_loader_reads_a_minimal_file(tmp_path):
    [(name, pol)] = load_policy(_write(tmp_path, GOOD)).items()
    assert (name, pol.name, pol.allow, pol.deny, pol.strict_verify) == ("crate", "crate", ["flac"], ["wma"], True)
    assert pol.prefer_versions == () and pol.accept_versions == ()


def test_loader_rejects_unknown_keys_and_words(tmp_path):
    p = _write(tmp_path, GOOD.replace("min_lossy_bitrate", "min_lossy"))
    with pytest.raises(ValueError, match="min_lossy") as e:
        load_policy(p)
    assert "policy.toml" in str(e.value)

    p = _write(tmp_path, GOOD + '[versions.crate]\nprefer = ["twelve"]\n')
    with pytest.raises(ValueError, match="twelve"):
        load_policy(p)

    p = _write(tmp_path, GOOD + '[versions.party]\nprefer = ["extended"]\n')
    with pytest.raises(ValueError, match="party"):
        load_policy(p)

    p = _write(tmp_path, GOOD + '[versions.crate]\npreffer = ["extended"]\n')
    with pytest.raises(ValueError, match="preffer"):
        load_policy(p)


def test_loader_rejects_a_missing_or_mistyped_key(tmp_path):
    with pytest.raises(ValueError, match="strict_verify"):
        load_policy(_write(tmp_path, GOOD.replace("strict_verify = true\n", "")))
    with pytest.raises(ValueError, match="min_lossy_bitrate"):
        load_policy(_write(tmp_path, GOOD.replace("min_lossy_bitrate = 320", 'min_lossy_bitrate = "320"')))
    with pytest.raises(ValueError, match="allow"):
        load_policy(_write(tmp_path, GOOD.replace('allow = ["flac"]', 'allow = "flac"')))


def test_loader_rejects_a_broken_file(tmp_path):
    with pytest.raises(ValueError, match="policy.toml"):
        load_policy(_write(tmp_path, "[tiers.crate\n"))


def test_dockerfile_ships_the_policy_file():
    assert "COPY deploy/policy.toml deploy/policy.toml" in (ROOT / "Dockerfile").read_text()
