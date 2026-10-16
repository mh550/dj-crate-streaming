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
    assert "another version (12\" Version): length fits another version +15" in twelve.reasons
    assert not any(r.startswith("duration") for r in twelve.reasons)
    assert any(r.startswith("duration off") for r in plain.reasons)


def test_medium_has_no_preference_but_accepts_the_12_inch_length():
    cands = rank([PLAIN, TWELVE], Wanted("Chic", "Good Times", duration_s=210), TIERS["medium"])
    assert not any(r.startswith("prefers") for c in cands for r in c.reasons)
    assert any("length fits another version" in r for r in by_user(cands, "twelve").reasons)
    assert not any("length fits" in r for r in by_user(cands, "plain").reasons)


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


def test_a_short_file_called_12_inch_is_still_penalised():
    short = response("short", r'music\Chic\Risque\03 - Good Times (12" Version).mp3', 1_000_000, "mp3", kbps=320, length=30)
    [c] = rank([short], Wanted("Chic", "Good Times", duration_s=210), TIERS["crate"])
    assert any(r.startswith("duration off") for r in c.reasons) and not any("fits another" in r for r in c.reasons)


def test_an_accepted_12_inch_earns_the_length_points_so_it_outranks_the_edit_in_flac_only():
    edit = response("edit", r"music\Chic\Risque\03 - Good Times (Radio Edit).flac", 17_000_000, "flac", length=210)
    lossy = response("lossy", r'music\Chic\Risque\03 - Good Times (12" Version).mp3', 20_000_000, "mp3", kbps=320, length=501)
    w = Wanted("Chic", "Good Times", duration_s=210)
    flac_12 = rank([TWELVE, edit], w, TIERS["crate"])
    assert [c.username for c in flac_12] == ["twelve", "edit"]
    assert [c.username for c in rank([lossy, edit], w, TIERS["crate"])] == ["edit", "lossy"]


def test_a_12_inch_dub_is_not_an_accepted_extended_version():
    # Task 4 review: every kind of a file's version must be accepted (preferred) before it stands in or earns a bonus.
    dub = response("dub", r'music\Chic\Risque\03 - Good Times (12" Dub).flac', 35_000_000, "flac", length=501)
    club = response("club", r'music\Chic\Risque\03 - Good Times (12" Club Mix).flac', 35_000_000, "flac", length=501)
    cands = rank([dub, club], Wanted("Chic", "Good Times", duration_s=210), TIERS["crate"])
    d, c = by_user(cands, "dub"), by_user(cands, "club")
    assert not any(r.startswith("prefers") or "fits another version" in r for r in d.reasons)
    assert any(r.startswith("duration off") for r in d.reasons)
    assert "prefers extended +6" in c.reasons and any("fits another version" in r for r in c.reasons)


def test_an_original_mix_is_no_accepted_stand_in_for_another_version():
    # "original" is neutral: it names no accepted kind, so it never earns the other-version length points
    orig = response("orig", r"music\Chic\Risque\03 - Good Times (Original Mix).flac", 35_000_000, "flac", length=501)
    [c] = rank([orig], Wanted("Chic", "Good Times (Live)", duration_s=210), TIERS["crate"])
    assert not any("fits another version" in r for r in c.reasons) and any(r.startswith("duration off") for r in c.reasons)


# ---- M7 final fixes I4: a stand-in keeps every kind the row asked for (other than edit) ----

def test_a_vocal_12_inch_earns_nothing_for_an_instrumental_a_cappella_live_or_dub_row():
    for title in ("Lovely Day - Instrumental", "Lovely Day - A Cappella", "Lovely Day - Live", "Lovely Day (Dub)"):
        for label in ('12" Version', "Extended Version"):
            twelve = response("t", rf"music\Bill Withers\Menagerie\03 - Bill Withers - Lovely Day ({label}).flac", 40_000_000, "flac", length=380)
            [c] = rank([twelve], Wanted("Bill Withers", title, duration_s=250), TIERS["crate"])
            assert not any("fits another version" in r or r.startswith("prefers") for r in c.reasons), (title, c.reasons)
            assert any(r.startswith("duration off") for r in c.reasons), (title, c.reasons)


def test_a_12_inch_instrumental_stands_in_for_an_instrumental_row_at_crate():
    inst = response("i", r'music\Bill Withers\Menagerie\03 - Bill Withers - Lovely Day (12" Instrumental).flac', 40_000_000, "flac", length=380)
    vocal = response("v", r'music\Bill Withers\Menagerie\03 - Bill Withers - Lovely Day (12" Version).flac', 40_000_000, "flac", length=380)
    cands = rank([vocal, inst], Wanted("Bill Withers", "Lovely Day - Instrumental", duration_s=250), TIERS["crate"])
    assert [c.username for c in cands] == ["i", "v"]
    i = by_user(cands, "i")
    assert any("fits another version" in r for r in i.reasons) and "prefers extended +6" in i.reasons
