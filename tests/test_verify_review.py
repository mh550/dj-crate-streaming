"""M5 Opus review fixes: what a real library throws at verify (webp covers, junk mp3 frames, cp1251 tags,
silence, timeouts), each found on Michael's files or reproduced from them."""
import json
import math
import shutil
import subprocess

import pytest

from sourcing import verify as V
from tests.helpers import convert, make_audio, make_flac

needs_tools = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("metaflac")), reason="ffmpeg/metaflac missing")


@pytest.fixture(scope="module")
def d(tmp_path_factory):
    return tmp_path_factory.mktemp("review")


@needs_tools
def test_a_webp_cover_is_not_an_integrity_failure(d):
    # 69 of 534 library FLAC pictures are webp; ffmpeg 6.1 logs "[error] Unknown attached picture mimetype"
    flac = make_audio(d / "cover.flac")
    webp = d / "cover.webp"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=16x16", "-frames:v", "1", str(webp)], check=True)
    subprocess.run(["metaflac", f"--import-picture-from=3|image/webp||16x16x24|{webp}", str(flac)], check=True)
    v = V.verify(flac, 8, tier="crate")
    assert v.ok, v.problems
    assert any("ffmpeg reported" in w and "webp" in w for w in v.warnings), v.warnings


@needs_tools
def test_a_few_junk_mp3_frames_are_a_warning_but_lost_audio_is_not(d):
    good = convert(make_audio(d / "src.flac", seconds=20), d / "good.mp3", "-b:a", "320k")
    raw = good.read_bytes()
    junk = d / "junk.mp3"
    junk.write_bytes(raw[: len(raw) // 2] + bytes(range(256)) * 4 + raw[len(raw) // 2:])     # one bad patch mid-file
    v = V.verify(junk, 20, tier="crate")
    assert v.ok, v.problems
    assert any("ffmpeg reported" in w for w in v.warnings), v.warnings


def test_many_decode_errors_or_a_failed_flac_t_stay_hard():
    base = {"samples": 44100 * 8, "full_db": -12.0, "bands_db": {20: -40.0}, "bits_used": 16, "peak_db": -3.0,
            "flat_factor": 0.0, "silences": [], "complete": True, "flac_t": None}
    info = V.AudioInfo(8.0, 44100, 16, 2, "mp3", "ffprobe")
    findings = []
    V._decoded_checks(info, dict(base, errors=["Header missing"] * 12), findings, {})
    assert any(c == "integrity" and "12 decode errors" in msg for c, msg in findings), findings
    findings = []
    V._decoded_checks(V.AudioInfo(8.0, 44100, 16, 2, "flac", "flac-streaminfo"), dict(base, errors=[], flac_t="state = FLAC__STREAM_DECODER_END_OF_STREAM"), findings, {})
    assert any(c == "integrity" and "flac -t" in msg for c, msg in findings), findings


@needs_tools
def test_a_cp1251_tag_does_not_crash(d):
    # Soulseek is full of ID3 tags in legacy code pages; ffmpeg echoes the raw bytes on stderr
    plain = convert(make_audio(d / "ru.flac"), d / "plain.mp3", "-b:a", "128k", "-id3v2_version", "0", "-write_id3v1", "0")
    text = b"\x03" + "Привет".encode("cp1251")                      # says UTF-8 (0x03), holds cp1251
    frame = b"TIT2" + len(text).to_bytes(4, "big") + b"\x00\x00" + text
    tag = b"ID3\x04\x00\x00" + bytes([(len(frame) >> s) & 0x7F for s in (21, 14, 7, 0)]) + frame
    bad = d / "cp1251.mp3"
    bad.write_bytes(tag + plain.read_bytes())
    v = V.verify(bad, 8, tier="low")
    assert v.ok, v.problems


@needs_tools
def test_digital_silence_is_hard_and_its_measurements_are_valid_json(d):
    silent = d / "silent.flac"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=8",
                    "-sample_fmt", "s16", str(silent)], check=True)
    v = V.verify(silent, 8, tier="low")
    assert not v.ok and any("no signal" in p for p in v.problems), v.problems
    json.dumps(v.as_dict("low"), allow_nan=False)                   # -inf would break /api/wanted for every row
    assert not any(isinstance(x, float) and not math.isfinite(x) for x in v.measurements.values())


def test_measurements_are_finite_on_every_path():
    assert V.finite({"peak_db": -math.inf, "bands_db": {20: -math.inf, 19: -3.0}}) == {"peak_db": None, "bands_db": {20: None, 19: -3.0}}


def test_no_measured_bands_means_no_spectral_verdicts():
    # an incomplete band analysis must not read as "nothing above 11 kHz" (a transcode) or "upsampled"
    a = {"errors": [], "samples": 96000 * 8, "full_db": -12.0, "bands_db": {}, "bits_used": 24, "peak_db": -3.0,
         "flat_factor": 0.0, "silences": [], "complete": False, "flac_t": None}
    findings, m = [], {}
    V._decoded_checks(V.AudioInfo(8.0, 96000, 24, 2, "flac", "flac-streaminfo"), a, findings, m)
    assert [c for c, _ in findings] == ["skipped"] and m["cutoff_khz"] is None


def test_cutoff_message_when_nothing_is_above_11_khz():
    a = {"errors": [], "samples": 44100 * 8, "full_db": -12.0, "bands_db": {e: -130.0 for e in V.BAND_EDGES_KHZ},
         "bits_used": 16, "peak_db": -3.0, "flat_factor": 0.0, "silences": [], "complete": True, "flac_t": None}
    findings = []
    V._decoded_checks(V.AudioInfo(8.0, 44100, 16, 2, "flac", "flac-streaminfo"), a, findings, {})
    msg = next(msg for c, msg in findings if c == "transcode")
    assert "nothing above 11 kHz" in msg and "≈0" not in msg


def test_an_incomplete_band_analysis_does_not_shift_bands():
    text = "[Parsed_astats_1 @ 0x1] [info] RMS level dB: -20.0\n[Parsed_astats_3 @ 0x2] [info] RMS level dB: -30.0\n"
    m = V.parse_ffmpeg(text, [11, 13, 15])                          # 1 of 3 band branches reported
    assert m["bands_db"] == {} and m["complete"] is False


def test_a_timeout_is_reported_not_raised(tmp_path, monkeypatch):
    p = make_flac(tmp_path / "long.flac", total=44100 * 300, pad_bytes=300 * 900_000 // 8)
    seen = {}

    def slow(cmd, **kw):
        seen.setdefault(cmd[0], kw.get("timeout"))
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    monkeypatch.setattr(V.subprocess, "run", slow)
    monkeypatch.setattr(V.shutil, "which", lambda name: "/usr/bin/" + name)
    v = V.verify(p, 300, tier="crate")
    assert v.ok and any("timed out" in w for w in v.warnings), (v.problems, v.warnings)
    assert seen["ffmpeg"] >= 600                                    # scales with length × rate, never under 10 min


@needs_tools
def test_an_estimated_mp3_length_defers_to_the_decoded_length(d):
    # library sweep: 6 mp3s "truncated" because ffprobe estimates the length of a VBR mp3 without a Xing header
    # (or with big cover art) from the bitrate; the decoded length is the real one, for both length checks
    vbr = convert(make_audio(d / "vsrc.flac", lead_silence=3), d / "vbr.mp3", "-q:a", "2", "-write_xing", "0")
    v = V.verify(vbr, 11, tier="low")
    assert v.ok, v.problems
    assert v.measurements["duration_s"] > 20 and abs(v.measurements["decoded_s"] - 11) < 0.2
    assert not V.verify(vbr, 30, tier="low").ok                     # the real length is still checked
    assert not V.verify(vbr, 11).ok                                 # header-only can't know better: unchanged
