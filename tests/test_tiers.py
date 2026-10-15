"""Quality tiers (spec §1, D9): low / medium / high / crate."""
import pytest

from sourcing.policy import DEFAULT_POLICY, TIERS
from sourcing.scorer import Wanted, estimated_arrival_s, explain, parse_responses, rank

WANTED = Wanted("Chic", "Good Times", "Risqué", 501, 1979)


def response(user, filename, size, ext, kbps=None, free=True, queue=0, speed=2_000_000, length=501):
    f = {"filename": filename, "size": size, "extension": ext, "length": length}
    if kbps:
        f["bitRate"] = kbps
    return {"username": user, "hasFreeUploadSlot": free, "queueLength": queue, "uploadSpeed": speed, "files": [f]}


# The spec's acceptance pair: a small 64 kbps mp3 on a fast peer, a big FLAC on a slow queued peer.
FAST_MP3 = response("fastpeer", r"music\Chic\Risque\03 - Good Times.mp3", 2_000_000, "mp3", kbps=64, speed=2_500_000)
# (35 MB, not the spec's 30: at 501 s a 30 MB "FLAC" implies 479 kbps and the fake-FLAC check rightly rejects it.)
SLOW_FLAC = response("slowpeer", r"music\Chic\Risque (1979)\03 - Good Times.flac", 35_000_000, "flac",
                     free=False, queue=5, speed=100_000)


@pytest.mark.parametrize("tier, winner", [("low", "fastpeer"), ("medium", "fastpeer"), ("high", "slowpeer"), ("crate", "slowpeer")])
def test_acceptance_pair_ranks_per_tier(tier, winner):
    ranked = [c for c in rank([FAST_MP3, SLOW_FLAC], WANTED, TIERS[tier]) if not c.rejected]
    assert ranked[0].username == winner


@pytest.mark.parametrize("tier, floor", [("low", 32), ("medium", 64), ("high", 128), ("crate", 320)])
def test_each_tier_pins_its_lossy_floor(tier, floor):
    def verdict(kbps):
        return rank([response("p", r"m\Chic\Risque\03 - Good Times.mp3", 5_000_000, "mp3", kbps=kbps)], WANTED, TIERS[tier])[0].rejected
    assert verdict(floor) is None and verdict(floor - 1) is not None


def test_crate_is_todays_policy():
    assert DEFAULT_POLICY is TIERS["crate"] and TIERS["crate"].speed_weight == 0 and TIERS["crate"].min_lossy_bitrate == 320
    assert [t.name for t in TIERS.values()] == ["low", "medium", "high", "crate"]


def test_estimated_arrival():
    [free_fast] = parse_responses([response("a", "x.mp3", 2_000_000, "mp3", speed=2_000_000)])
    [queued_slow] = parse_responses([response("b", "x.flac", 30_000_000, "flac", free=False, queue=5, speed=100_000)])
    [unknown] = parse_responses([response("c", "x.mp3", 1_000_000, "mp3", speed=0)])
    assert estimated_arrival_s(free_fast, cap_Bps=0) == pytest.approx(1.0)
    assert estimated_arrival_s(free_fast, cap_Bps=500_000) == pytest.approx(4.0)          # our own cap binds
    assert estimated_arrival_s(queued_slow, cap_Bps=0) == pytest.approx(300 + 30 + 20 * 5)
    assert estimated_arrival_s(unknown, cap_Bps=0) == pytest.approx(20.0)                  # unknown speed → 50 kB/s


def test_listening_tiers_explain_the_arrival_and_crate_does_not():
    low = explain(rank([FAST_MP3], WANTED, TIERS["low"]))
    assert "arrival ~2 s" in low                                   # 2 MB at our 1 MB/s cap
    assert "arrival" not in explain(rank([SLOW_FLAC], WANTED, TIERS["crate"]))


def test_listening_tiers_accept_opus_crate_does_not():
    opus = response("o", r"m\Chic\Risque\03 - Good Times.opus", 3_000_000, "opus", kbps=96)
    assert rank([opus], WANTED, TIERS["low"])[0].rejected is None
    assert rank([opus], WANTED, TIERS["crate"])[0].rejected is not None


# Live, 2026-10-15 (Stevie Wonder — Lookin' For Another Pure Love, 253 peers): peers *report* upload speeds
# up to 61 MB/s, so without our own cap a 28.5 MB FLAC "arrives" in under a second and wins low.
BRAG_FLAC = response("bragger", r"m\Stevie Wonder\Talking Book\09 - Lookin' for Another Pure Love.flac", 28_500_000, "flac",
                     speed=61_123_797, length=283)
SMALL_M4A = response("small", r"m\Stevie Wonder\Talking Book\09 - Lookin' for Another Pure Love.m4a", 5_041_379, "m4a",
                     kbps=138, speed=5_000_000, length=283)
STEVIE = Wanted("Stevie Wonder", "Lookin' For Another Pure Love", None, 283, None)


@pytest.mark.parametrize("tier, winner", [("low", "small"), ("medium", "small"), ("high", "bragger"), ("crate", "bragger")])
def test_our_download_cap_keeps_a_bragging_peer_from_winning_low(tier, winner):
    ranked = [c for c in rank([BRAG_FLAC, SMALL_M4A], STEVIE, TIERS[tier]) if not c.rejected]
    assert ranked[0].username == winner


def test_listening_tiers_share_our_download_cap():
    assert {TIERS[t].download_cap_Bps for t in ("low", "medium", "high")} == {1_000_000}


def test_a_listing_without_a_size_gets_no_speed_bonus():
    # Opus M4 review: size 0 (missing) used to mean "arrives instantly" and a 100 speed score.
    sizeless = response("nosize", r"m\Chic\Risque\03 - Good Times.mp3", 0, "mp3", kbps=128, speed=2_500_000)
    [c] = parse_responses([sizeless])
    assert estimated_arrival_s(c) == float("inf")
    [ranked] = rank([sizeless], WANTED, TIERS["low"])
    assert "arrival unknown" in ranked.reasons and ranked.score < 30
