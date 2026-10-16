"""The playlist-comment grammar (D21): #crate and #tier:<t>, and Michael's other bytes left alone."""
import pytest

from crates.attrs import Attrs, parse, write
from sourcing.policy import max_tier, tier_rank

CASES = ["trailing space ", "trailing tab\t", "Late sets 🎛 — 120–124 BPM", "line one\nline two\n", "  leading spaces", "tab\tseparated",
         "naïve café ガ", "x" * 1000 + " end", ""]


def test_parse_reads_crate_and_tier():
    assert parse("warmup #crate").crate
    assert parse("#tier:medium").tier == "medium"
    a = parse("#imported #tier:HIGH")
    assert a.tier == "high" and not a.crate
    assert parse("#CRATE").crate
    for c in ("#crates", "x#crate", "#crate,", "crate digging"):
        assert not parse(c).crate, c
    assert parse("") == Attrs(False, None)
    assert parse(None) == Attrs(False, None)
    assert parse("#tier:crate").crate and parse("#tier:crate").tier is None


def test_effective_tier():
    assert parse("#crate #tier:medium").effective == "crate"
    assert parse("#tier:low").effective == "low"
    assert parse("").effective is None


def test_unknown_and_repeated_tier_tags_are_problems_not_errors():
    a = parse("#tier:hgh")
    assert a.tier is None and len(a.problems) == 1 and "hgh" in a.problems[0]
    b = parse("#tier:low #tier:high")
    assert b.tier == "high" and len(b.problems) == 1


@pytest.mark.parametrize("c", CASES)
def test_write_keeps_michaels_text_byte_for_byte(c):
    assert write(write(c, crate=True), crate=False) == c
    assert write(write(c, tier="medium"), tier=None) == c


@pytest.mark.parametrize("c", CASES)
def test_write_with_no_change_returns_the_comment(c):
    assert write(c) == c


def test_write_is_idempotent_and_minimal():
    assert write(None) == ""
    assert write("warmup", crate=True) == "warmup #crate"
    assert write("", tier="medium") == "#tier:medium"
    assert write("#imported", tier="medium") == "#imported #tier:medium"
    assert write("#imported #tier:medium", tier="high") == "#imported #tier:high"
    assert write("#tier:low mix\nnotes", tier=None) == "mix\nnotes"
    assert write("a #tier:hgh", tier=None) == "a"
    assert write("x", tier="crate") == "x #crate"
    once = write("x", tier="medium")
    assert write(once, tier="medium") == once
    assert write(write("x", crate=True), crate=True) == "x #crate"


def test_write_removes_every_crate_token_and_never_a_newline():
    assert write("a #crate #CRATE b", crate=False) == "a b"
    assert write("#crate #tier:crate", crate=False) == ""
    assert write("a\n#crate", crate=False) == "a\n"


def test_write_refuses_an_unknown_tier():
    with pytest.raises(ValueError):
        write("", tier="hgh")


def test_max_tier():
    assert max_tier("medium", None, "crate", "low") == "crate"
    assert max_tier() is None and max_tier(None) is None
    assert tier_rank("low") < tier_rank("crate")
    with pytest.raises(ValueError):
        tier_rank("nope")


def test_rewriting_the_tier_a_comment_already_has_changes_nothing():
    # Task 1 review: re-setting the same tier used to move the token to the end.
    assert write("a #tier:medium b", tier="medium") == "a #tier:medium b"
    assert write("a #TIER:Medium\tb", tier="medium") == "a #TIER:Medium\tb"
    # a problem in the #tier: tokens is still rewritten
    assert write("a #tier:low #tier:medium b", tier="medium") == "a b #tier:medium"
    assert write("a #tier:hgh", tier="medium") == "a #tier:medium"


def test_changing_the_tier_keeps_a_crate_spelled_tier_crate():
    # Task 1 review: write(tier=…) removes every #tier: token, #tier:crate included; the crate flag stays.
    for c in ("#tier:crate", "mix #tier:crate", "#tier:crate #tier:low"):
        for t in (None, "low", "high"):
            a = parse(write(c, tier=t))
            assert a.crate and a.tier == t, (c, t)
    assert not parse(write("#tier:crate", crate=False, tier="low")).crate
