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


def _named(*names):
    return parse_responses([{"username": f"p{i}", "files": [{"filename": f"Music\\Al Green\\{n}", "size": 1, "extension": "flac"}]}
                            for i, n in enumerate(names)])


def test_a_title_track_wanted_never_matches_another_track_through_the_album_name():
    """2026-10-21, ext-74: "I'm Still In Love With You" (the album's title track) scored 1.00 against
    "Al Green - I'm Still in Love With You - 09 - One of These Good Old Days.flac" and that song was filed."""
    w = Wanted("Al Green", "I'm Still In Love With You", duration_s=196)
    other, real, real2 = _named("Al Green - I’m Still in Love With You - 09 - One of These Good Old Days.flac",
                                "Al Green - I’m Still in Love With You - 01 - I’m Still in Love With You.flac",
                                "Al Green_I’m Still in Love With You_01_I’m Still in Love With You.flac")
    assert name_match(other, w)[0] < name_match(real, w)[0] == 1.0
    assert name_match(real2, w)[0] == 1.0
    assert rank([{"username": "a", "files": [{"filename": "M\\" + other.basename, "size": 1, "extension": "flac"}]},
                 {"username": "b", "files": [{"filename": "M\\" + real.basename, "size": 1, "extension": "flac"}]}],
                w)[0].username == "b"


def test_the_title_slot_after_a_track_number_still_matches_and_numbers_in_titles_survive():
    for name, title in [("Al Green - I’m Still in Love With You - 03 - Love and Happiness.flac", "Love And Happiness"),
                        ("Nena - 99 Luftballons.flac", "99 Luftballons"),
                        ("Al Green - Greatest Hits - 05 - Love and Happiness.flac", "Love And Happiness")]:
        assert name_match(_named(name)[0], Wanted("Al Green" if "Green" in name else "Nena", title))[0] == 1.0, name


def test_unknown_duration_is_neutral():
    w = Wanted("Chic", "Good Times")
    cands = rank(FIX, w)
    assert by_user(cands, "editversion").rejected is None
    assert not any("duration" in r for r in by_user(cands, "editversion").reasons)
