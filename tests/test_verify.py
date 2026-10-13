from pathlib import Path

from sourcing.verify import flac_streaminfo, verify
from tests.helpers import make_flac


def test_streaminfo_parse(tmp_path):
    p = tmp_path / "a.flac"
    make_flac(p, sr=96000, bps=24, ch=2, total=96000 * 120)
    info = flac_streaminfo(p)
    assert info.sample_rate == 96000 and info.bit_depth == 24 and info.channels == 2
    assert abs(info.duration_s - 120) < 0.01


def test_verify_flags_duration_and_fake_lossless(tmp_path):
    p = tmp_path / "b.flac"
    make_flac(p, total=44100 * 300, pad_bytes=10_000)  # 300 s but only 10 KB → fake
    v = verify(p, expected_duration_s=501)
    assert not v.ok
    assert any("duration" in x for x in v.problems)
    assert any("transcode" in x for x in v.problems)


def test_verify_ok(tmp_path):
    p = tmp_path / "c.flac"
    make_flac(p, total=44100 * 300, pad_bytes=300 * 900_000 // 8)  # ~900 kbps
    v = verify(p, expected_duration_s=302)
    assert v.ok, v.problems
