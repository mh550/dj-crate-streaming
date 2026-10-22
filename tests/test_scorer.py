import json
from pathlib import Path

import pytest

from sourcing.scorer import Wanted, rank, name_match, parse_responses, score_candidate, norm, strip_trackno
from sourcing.policy import QualityPolicy

FIX = json.loads((Path(__file__).parent.parent / "fixtures" / "search_responses.sample.json").read_text())
WANT = Wanted("Chic", "Good Times", album="Risqué", duration_s=501, year=1979)


def by_user(cands, u):
    return next(c for c in cands if c.username == u)


def test_normalization():
    assert norm("Risqué (1979) [FLAC]") == "risque 1979 flac"
    assert strip_trackno("03 - Good Times") == "Good Times"
    assert strip_trackno("A1 Good Times") == "Good Times"
    assert norm("Chic & Nile") == "chic and nile"


def test_ranking_prefers_real_album_flac_with_matching_duration():
    cands = rank(FIX, WANT)
    accepted = [c for c in cands if not c.rejected]
    assert accepted[0].username in ("vinylhead77", "hires")
    top2 = {c.username for c in accepted[:2]}
    assert top2 == {"vinylhead77", "hires"}


def test_rejections():
    cands = rank(FIX, WANT)
    assert "lossy below" in by_user(cands, "lowbit").rejected
    assert "suspicious lossless" in by_user(cands, "fakeflac").rejected
    assert by_user(cands, "locked").rejected == "locked file"
    # the INXS song has the same title; artist isn't in the path → weak match → rejected or far down
    inxs = by_user(cands, "wrongsong")
    assert inxs.rejected is not None or inxs.score < by_user(cands, "mp3guy").score


def test_other_album_track_is_not_a_match():
    cands = rank(FIX, WANT)
    other = next(c for c in cands if "Forbidden" in c.basename)
    assert other.rejected is not None


def test_edit_version_is_penalized_by_duration():
    cands = rank(FIX, WANT)
    edit = by_user(cands, "editversion")
    good = by_user(cands, "vinylhead77")
    assert edit.rejected is None
    assert edit.score < good.score - 15
    assert any("duration off" in r for r in edit.reasons)


def test_mp3_320_is_acceptable_but_below_flac():
    cands = rank(FIX, WANT)
    mp3 = by_user(cands, "mp3guy")
    assert mp3.rejected is None
    assert mp3.score < by_user(cands, "vinylhead77").score


def test_policy_can_forbid_lossy():
    pol = QualityPolicy(allow=["flac", "wav", "aiff"])
    cands = rank(FIX, WANT, pol)
    assert by_user(cands, "mp3guy").rejected is not None


def test_name_match_requires_artist_context_for_title_only():
    c = parse_responses([{"username": "x", "files": [{"filename": "misc\\Good Times.flac", "size": 1, "extension": "flac"}]}])[0]
    s, how = name_match(c, WANT)
    assert s < 0.75


def test_unknown_duration_is_neutral():
    w = Wanted("Chic", "Good Times")
    cands = rank(FIX, w)
    assert by_user(cands, "editversion").rejected is None
    assert not any("duration" in r for r in by_user(cands, "editversion").reasons)


def _nena(filename):
    """The fixture's first response with one file renamed: a shape slskd really sends."""
    r = json.loads(json.dumps(FIX[0]))
    r["files"] = [dict(FIX[0]["files"][0], filename=filename, length=232)]
    return [r]


@pytest.mark.parametrize("filename", ["@@music\\Nena\\Nena (1983)\\Nena - 99 Luftballons.flac",
                                      "@@music\\Nena\\Nena (1983)\\99 Luftballons.flac",
                                      "@@music\\Nena\\Nena (1983)\\01 99 Luftballons.flac"])
def test_99_luftballons_is_a_title_match(filename):
    """M9 §8b: the "99 " of "99 Luftballons" is the title, not a track number."""
    [c] = rank(_nena(filename), Wanted("Nena", "99 Luftballons"))
    assert c.rejected is None
    assert c.reasons[0].startswith("name 1.00"), c.reasons


@pytest.mark.parametrize("filename, wanted", [("@@music\\Taylor Swift\\Red\\22 Shake It Off.flac", Wanted("Taylor Swift", "22")),
                                              ("@@music\\Prince\\1999\\7 Little Red Corvette.flac", Wanted("Prince", "7"))])
def test_a_track_number_equal_to_a_numeric_title_is_still_a_track_number(filename, wanted):
    [c] = rank(_nena(filename), wanted)
    assert c.rejected and "name match too weak" in c.rejected
