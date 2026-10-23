import json
from pathlib import Path

import pytest

from sourcing.scorer import Wanted, explain, rank, name_match, parse_responses, score_candidate, norm, strip_trackno
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


def _peer_a(filename, length=195):
    """One response from peer `a` in the fixture's shape, its only file `filename` (a flac at about 900 kbps)."""
    r = json.loads(json.dumps(FIX[0]))
    r["username"] = "a"
    r["files"] = [dict(FIX[0]["files"][0], filename=filename, extension="flac", bitRate=900, length=length,
                       size=900 * 1000 // 8 * length)]
    return [r]


EXT74 = "@@music\\Al Green\\I’m Still in Love With You (1972)\\Al Green - I’m Still in Love With You - 09 - One of These Good Old Days.flac"


def test_a_title_slot_naming_another_song_is_rejected():
    """S1-01, ext-74: a peer offering only track 09 of the same-named album has nothing acceptable for the title
    track; before, that file was ok at about 84.5 and was downloaded and filed."""
    cands = rank(_peer_a(EXT74), Wanted("Al Green", "I'm Still In Love With You", duration_s=196))
    assert cands and all(c.rejected and c.rejected.startswith("title slot is") for c in cands), \
        [c.rejected for c in cands]
    assert cands[0].rejected == "title slot is One of These Good Old Days"
    assert cands[0].score == 0
    assert next((c for c in cands if not c.rejected), None) is None
    assert "✗ title slot is One of These Good Old Days" in explain(cands, peers=False)


@pytest.mark.parametrize("filename, title", [
    ("@@music\\Al Green\\I’m Still in Love With You (1972)\\Al Green - I’m Still in Love With You - 03 - Love and Happiness.flac",
     "Love And Happiness"),                                       # the same song, spelled otherwise
    ("@@music\\Al Green\\I’m Still in Love With You (1972)\\Al Green - I’m Still in Love With You - 01 - I’m Still in Love With You.flac",
     "I'm Still In Love With You"),
    ("@@music\\Al Green\\Still in Love\\Al Green_I’m Still in Love With You_01_I’m Still in Love With You.flac",
     "I'm Still In Love With You"),
    ("@@music\\VA\\Soul Hits\\VA - Soul Hits - 07 - Al Green - Love and Happiness.flac", "Love And Happiness"),
])
def test_a_title_slot_naming_the_wanted_song_stays_acceptable(filename, title):
    [c] = rank(_peer_a(filename), Wanted("Al Green", title, duration_s=196))
    assert c.rejected is None, c.rejected


@pytest.mark.parametrize("basename", [
    "Al Green - I’m Still in Love With You - 09. One of These Good Old Days.flac",
    "Al Green – I’m Still in Love With You – 09 – One of These Good Old Days.flac",
    "Al_Green_-_I’m_Still_in_Love_With_You_-_09_-_One_of_These_Good_Old_Days.flac",
])
def test_the_ext74_shape_is_rejected_with_other_separators(basename):
    [c] = rank(_peer_a("@@music\\Al Green\\I’m Still in Love With You (1972)\\" + basename),
               Wanted("Al Green", "I'm Still In Love With You", duration_s=196))
    assert (c.rejected or "").startswith("title slot is"), c.rejected


@pytest.mark.parametrize("basename, title", [
    ("Chic - Risqué - 03 - Good Times feat. Nile Rodgers.flac", "Good Times"),
    ("Chic - Risqué - 03 - Good Times ft. Nile Rodgers.flac", "Good Times"),
    ("Chic - Risqué - 03 - Good Times.flac", "Good Times feat. Nile Rodgers"),
    ("VA_-_Disco_Hits_-_07_-_Chic_-_Good_Times.flac", "Good Times"),
    ("VA_Disco_Hits_07_Chic_Good_Times.flac", "Good Times"),
    ("VA - Disco Hits - 07 - Good Times - Chic & Nile Rodgers.flac", "Good Times"),
])
def test_a_title_slot_with_credits_or_underscores_is_still_the_song(basename, title):
    """Review of S1-01: credits around the title and underscore compilations are the wanted song, not another."""
    [c] = rank(_peer_a("@@music\\Chic\\" + basename, length=501), Wanted("Chic", title, duration_s=501))
    assert c.rejected is None, c.rejected


def test_a_compilation_slot_credits_the_artist_before_the_title():
    """parse_title drops only the lead artist; "Chic feat. Nile Rodgers - Good Times" is still Good Times."""
    [c] = rank(_peer_a("@@music\\VA\\Disco\\VA - Disco - 03 - Chic feat. Nile Rodgers - Good Times.flac", length=501),
               Wanted("Chic", "Good Times", duration_s=501))
    assert c.rejected is None, c.rejected


def test_a_labelled_title_slot_is_left_to_the_version_rules():
    """The slot rule compares songs (base titles); which version a file is stays with D26's rules."""
    [c] = rank(_peer_a("@@music\\Al Green\\Greatest Hits\\Al Green - Greatest Hits - 01 - Love and Happiness (Live).flac"),
               Wanted("Al Green", "Love And Happiness", duration_s=196))
    assert not (c.rejected or "").startswith("title slot is"), c.rejected
    [c] = rank(_peer_a("@@music\\Chic\\Risqué (1979)\\Chic - Risqué - 03 - Good Times (12'' Version).flac", length=501),
               Wanted("Chic", "Good Times", duration_s=501))
    assert not (c.rejected or "").startswith("title slot is"), c.rejected


def test_a_file_without_a_title_slot_is_unchanged():
    cands = rank(FIX, WANT)
    assert not any((c.rejected or "").startswith("title slot is") for c in cands)
