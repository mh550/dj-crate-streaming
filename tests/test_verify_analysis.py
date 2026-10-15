"""M5 (spec §3a): decoded checks — cutoff, fingerprints, the ffmpeg parser, and tier-aware verdicts."""
import math
import shutil

import pytest

from sourcing import verify as V
from tests.helpers import FIXTURES, make_audio

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")
EDGES = [11, 13, 15, 16, 17, 18, 19, 20]


# ---- estimate_cutoff: a lowpass is a cliff, music falls off smoothly ----

def test_cutoff_smooth_music_reaches_the_top_edge():
    # a library FLAC (Herb Alpert, 1979): steps of 2-7 dB, no cliff, quiet at the top
    levels = dict(zip(EDGES, [-29.7, -33.7, -38.8, -42.2, -45.9, -50.1, -55.0, -62.3]))
    assert V.estimate_cutoff(-16.1, levels) == 20


def test_cutoff_at_the_cliff_of_a_128k_mp3():
    levels = dict(zip(EDGES, [-4.8, -6.7, -10.4, -15.0, -62.7, -64.7, -66.4, -68.4]))
    assert V.estimate_cutoff(0.0, levels) == 16


def test_cutoff_empty_first_band_is_zero_and_inf_is_empty():
    levels = dict(zip(EDGES, [-120.0] + [-math.inf] * 7))
    assert V.estimate_cutoff(-20.0, levels) == 0
    assert V.estimate_cutoff(-math.inf, dict(zip(EDGES, [-math.inf] * 8))) == 0   # digital silence: no crash


# ---- fingerprints ----

def test_fingerprint_ber_same_shifted_and_different():
    import random
    rnd = random.Random(1)
    a = [rnd.getrandbits(32) for _ in range(300)]
    assert V.fingerprint_ber(a, a) == 0
    assert V.fingerprint_ber(a, a[7:]) == 0                     # same audio starting later
    b = [rnd.getrandbits(32) for _ in range(300)]
    assert V.fingerprint_ber(a, b) > 0.4
    assert V.fingerprint_ber(a, a[:5]) == 1.0                   # too little overlap to say


# ---- the parser, against a captured live ffmpeg run (4 s silence + 128k-mp3 noise as FLAC, 8 bands) ----

def test_parse_ffmpeg_captured_run():
    m = V.parse_ffmpeg((FIXTURES / "ffmpeg_analysis.sample.txt").read_text(), EDGES)
    assert m["errors"] == []
    assert m["full_db"] == pytest.approx(-21.65, abs=0.01)
    assert [round(m["bands_db"][e], 1) for e in EDGES] == [-26.4, -28.3, -32.0, -36.6, -84.3, -86.3, -88.0, -90.0]
    assert m["peak_db"] == pytest.approx(-9.31, abs=0.01) and m["flat_factor"] == 0
    assert m["bits_used"] == 16 and m["samples"] == 529200
    assert m["silences"] == [(0.0, 4.0)]


def test_parse_ffmpeg_errors_and_open_silence():
    text = ("[flac @ 0x1] [error] invalid sync code\n"
            "[silencedetect @ 0x2] [info] silence_start: 290.5\n"
            "[Parsed_astats_1 @ 0x3] [info] RMS level dB: -inf\n")
    m = V.parse_ffmpeg(text, [])
    assert m["errors"] == ["invalid sync code"]
    assert m["silences"] == [(290.5, None)]                     # silence ran to the end of the file
    assert m["full_db"] == -math.inf


# ---- verify with a tier, on generated audio ----

@pytest.fixture(scope="module")
def audio(tmp_path_factory):
    d = tmp_path_factory.mktemp("audio")
    return {"true": make_audio(d / "true.flac"),
            "fake": make_audio(d / "fake.flac", via_mp3_kbps=128)}


@needs_ffmpeg
def test_true_flac_passes_crate_with_measurements(audio):
    v = V.verify(audio["true"], 8, tier="crate")
    assert v.ok, (v.problems, v.warnings)
    m = v.measurements
    assert m["cutoff_khz"] == 20 and m["bits_used"] == 16 and abs(m["decoded_s"] - 8) < 0.01
    assert m["codec"] == "flac" and m["sample_rate"] == 44100


@needs_ffmpeg
def test_mp3_as_flac_fails_crate_but_only_warns_at_low(audio):
    v = V.verify(audio["fake"], 8, tier="crate")
    assert not v.ok and v.measurements["cutoff_khz"] == 16
    assert any("cutoff" in p and "16 kHz" in p for p in v.problems), v.problems
    low = V.verify(audio["fake"], 8, tier="low")
    assert low.ok and any("cutoff" in w for w in low.warnings)


@needs_ffmpeg
def test_no_tier_keeps_todays_header_only_behaviour(audio):
    v = V.verify(audio["fake"], 8)
    assert v.ok and v.warnings == [] and "cutoff_khz" not in v.measurements


@needs_ffmpeg
def test_unopenable_file_is_one_hard_integrity_problem(tmp_path):
    p = tmp_path / "junk.mp3"
    p.write_bytes(b"\x00not audio" * 500)
    v = V.verify(p, None, tier="low")
    assert not v.ok and v.problems and all(isinstance(x, str) for x in v.problems)


def test_without_ffmpeg_a_tiered_verify_warns_it_skipped(tmp_path, monkeypatch):
    from tests.helpers import make_flac
    p = make_flac(tmp_path / "c.flac", total=44100 * 300, pad_bytes=300 * 900_000 // 8)
    monkeypatch.setattr(V.shutil, "which", lambda name: None)
    v = V.verify(p, 300, tier="crate")
    assert v.ok and any("skipped" in w for w in v.warnings)


def test_unknown_tier_is_an_error(tmp_path):
    from tests.helpers import make_flac
    with pytest.raises(ValueError):
        V.verify(make_flac(tmp_path / "d.flac"), None, tier="ultra")
