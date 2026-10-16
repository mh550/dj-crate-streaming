"""The scorer's version preference (D16, from the policy file) and the crate-upgrade copy intent (M7 plan, Task 5)."""
import dataclasses

from sourcing.policy import DEFAULT_POLICY, TIERS
from sourcing.scorer import Wanted, rank
from tests.test_scorer import FIX, WANT
from tests.test_tiers import response

PLAIN = response("plain", r"music\Chic\Risque\03 - Good Times.flac", 35_000_000, "flac", length=501)
TWELVE = response("twelve", r'music\Chic\Risque\03 - Good Times (12" Version).flac', 35_000_000, "flac", length=501)


def by_user(cands, u):
    return next(c for c in cands if c.username == u)


def test_crate_prefers_the_12_inch_over_the_plain_flac():
    cands = rank([PLAIN, TWELVE], Wanted("Chic", "Good Times", duration_s=210), TIERS["crate"])
    assert [c.username for c in cands] == ["twelve", "plain"]
    twelve, plain = cands
    assert "prefers extended +6" in twelve.reasons
    assert "another version (12\" Version): length not compared" in twelve.reasons
    assert not any(r.startswith("duration") for r in twelve.reasons)
    assert any(r.startswith("duration off") for r in plain.reasons)


def test_medium_has_no_preference_but_accepts_the_12_inch_length():
    cands = rank([PLAIN, TWELVE], Wanted("Chic", "Good Times", duration_s=210), TIERS["medium"])
    assert not any(r.startswith("prefers") for c in cands for r in c.reasons)
    assert any("length not compared" in r for r in by_user(cands, "twelve").reasons)
    assert not any("length not compared" in r for r in by_user(cands, "plain").reasons)


def test_crate_row_rejects_another_version():
    live = response("live", r"music\Chic\Risque\03 - Good Times (Live).flac", 35_000_000, "flac")
    original = response("orig", r"music\Chic\Risque\03 - Good Times (Original Mix).flac", 35_000_000, "flac")
    cands = rank([PLAIN, live, original, TWELVE], Wanted("Chic", "Good Times", duration_s=501, copy=True), TIERS["crate"])
    assert "a crate upgrade must be the same version" in by_user(cands, "live").rejected
    assert "another version (Live)" in by_user(cands, "live").rejected
    assert "another version (12\" Version)" in by_user(cands, "twelve").rejected
    assert by_user(cands, "orig").rejected is None          # "original" is neutral in the version key
    assert by_user(cands, "plain").rejected is None


def test_copy_of_a_labelled_version_names_its_label():
    cands = rank([PLAIN], Wanted("Chic", "Good Times (Live)", duration_s=501, copy=True), TIERS["crate"])
    assert "another version (no label)" in cands[0].rejected and "the same version (Live)" in cands[0].rejected


def test_copy_defaults_to_false():
    assert Wanted("a", "b").copy is False


def test_existing_fixture_ranking_is_unchanged():
    bare = dataclasses.replace(DEFAULT_POLICY, prefer_versions=(), accept_versions=())
    got = [(c.username, c.score, c.rejected) for c in rank(FIX, WANT)]
    assert got == [(c.username, c.score, c.rejected) for c in rank(FIX, WANT, bare)]
