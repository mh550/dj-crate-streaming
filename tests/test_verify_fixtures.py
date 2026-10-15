"""M5 step 2 (spec §3a): the fixture set end to end, all generated here with ffmpeg from seeded noise."""
import shutil
import subprocess

import pytest

from sourcing.verify import verify
from tests.helpers import make_audio

pytestmark = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("fpcalc")), reason="ffmpeg/fpcalc not on PATH")


def convert(src, dst, *args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), *args, str(dst)], check=True)
    return dst


@pytest.fixture(scope="module")
def f(tmp_path_factory):
    d = tmp_path_factory.mktemp("fx")
    true = make_audio(d / "true.flac")
    cut = d / "truncated.flac"
    cut.write_bytes(true.read_bytes()[: true.stat().st_size * 6 // 10])     # STREAMINFO still says 8 s
    return {
        "true": true,
        "fake": make_audio(d / "fake.flac", via_mp3_kbps=128),
        "pad24": convert(true, d / "pad24.flac", "-sample_fmt", "s32", "-bits_per_raw_sample", "24"),
        "true24": make_audio(d / "true24.flac", sample_fmt="s32", bits=24),
        "hires": make_audio(d / "hires.flac", rate=96000, sample_fmt="s32", bits=24),
        "upsampled": convert(true, d / "up96.flac", "-ar", "96000", "-sample_fmt", "s32", "-bits_per_raw_sample", "24"),
        "truncated": cut,
        "silence": make_audio(d / "silence.flac", lead_silence=4),
        "clipped": make_audio(d / "clipped.flac", af="volume=20dB"),
        "mp3": convert(true, d / "low.mp3", "-b:a", "128k"),
        "other": make_audio(d / "other.flac", seed=7, color="pink"),
        "long_true": make_audio(d / "long.flac", seconds=20),
        "long_mp3": convert(d / "long.flac", d / "long.mp3", "-b:a", "128k"),
        "long_other": make_audio(d / "long_other.flac", seconds=20, seed=9, color="brown"),
    }


def test_true_16_and_24_bit_flac_pass_crate(f):
    for name in ("true", "true24"):
        v = verify(f[name], 8, tier="crate")
        assert v.ok and not v.warnings, (name, v.problems, v.warnings)
    assert verify(f["true24"], 8, tier="crate").measurements["bits_used"] == 24


def test_mp3_decoded_to_flac_is_a_transcode(f):
    v = verify(f["fake"], 8, tier="crate")
    assert not v.ok and v.measurements["cutoff_khz"] == 16
    assert "likely came from ≤128 kbps" in v.problems[0]


def test_16_bit_padded_to_24_is_fake_for_crate_and_a_warning_below(f):
    v = verify(f["pad24"], 8, tier="crate")
    assert not v.ok and v.measurements["bits_used"] == 16
    assert any("padded from 16-bit" in p for p in v.problems)
    h = verify(f["pad24"], 8, tier="high")
    assert h.ok and any("padded" in w for w in h.warnings)


def test_real_hires_passes_and_upsampled_hires_is_fake(f):
    v = verify(f["hires"], 8, tier="crate")
    assert v.ok, (v.problems, v.warnings)
    assert v.measurements["cutoff_khz"] == 24
    u = verify(f["upsampled"], 8, tier="crate")
    assert not u.ok and any("upsampled" in p for p in u.problems)


def test_truncated_copy_is_hard_in_every_tier(f):
    for tier in ("low", "crate"):
        v = verify(f["truncated"], 8, tier=tier)
        assert not v.ok, tier
        assert any("truncated" in p or "flac -t" in p for p in v.problems), v.problems
    assert verify(f["truncated"], 8, tier="low").measurements["decoded_s"] < 6


def test_leading_silence_is_a_warning(f):
    v = verify(f["silence"], 12, tier="crate")
    assert v.ok and v.measurements["silence_start_s"] == 4.0
    assert any("silence at the start" in w for w in v.warnings)


def test_low_flac_bitrate_with_a_full_spectrum_is_only_a_warning(f):
    # 4 s of digital silence compresses to nothing: 425 kbps, under the header rule's 500, yet full band.
    # The measured spectrum outranks the header guess; without a tier the old hard rule stands.
    v = verify(f["silence"], 12, tier="crate")
    assert v.ok and any("full spectrum" in w for w in v.warnings), v.warnings
    assert not verify(f["silence"], 12).ok


def test_clipping_is_a_warning(f):
    v = verify(f["clipped"], 8, tier="crate")
    assert v.ok and any("clipped" in w for w in v.warnings)
    assert v.measurements["peak_db"] >= -0.1


def test_a_128k_mp3_is_fine_at_low_and_not_a_claimed_320(f):
    v = verify(f["mp3"], 8, tier="low")
    assert v.ok and not v.warnings, v.warnings      # it doesn't claim to be more than it is
    assert v.measurements["codec"] == "mp3" and v.measurements["cutoff_khz"] <= 17


def test_duration_is_hard_in_every_tier(f):
    v = verify(f["mp3"], 30, tier="low")
    assert not v.ok and "duration" in v.problems[0]


def test_reference_fingerprint_same_vs_different_recording(f):
    same = verify(f["long_mp3"], 20, tier="low", reference=f["long_true"])
    assert same.ok and same.measurements["fingerprint_ber"] < 0.1
    wrong = verify(f["long_other"], 20, tier="low", reference=f["long_true"])
    assert not wrong.ok and wrong.measurements["fingerprint_ber"] > 0.2
    assert "different recording" in wrong.problems[0]
