"""The import matcher asks: same recording (ISRC) → same version → an other version the tier accepts (M7 Task 4).

A playlist row names a song; which version stands at that spot is the playlist's choice. So a hit with another
version label is never a silent copy match: it is matched only when the tier's policy accepts that label, and then
it is named in the report's notes. Every other doubt stays a `review` row.
"""
from crates.store import CrateStore
from sourcing import import_playlist as ip
from sourcing.playlist_sources import Row, rows_from_csv
from subsonic.client import Song, SubsonicClient
from subsonic.fake_server import FakeSubsonicServer
from tests.test_import_playlist import song

TWELVE = 'My Love Is Free (Tom Moulton 12" Mix)'


def test_same_isrc_matches_whatever_the_title_says():
    row = Row(1, "Good Times", "Chic", 210, isrc="USAT21234567")
    hit = song("g", 'Good Times (12" Version)', "Chic", 501)
    hit.raw["isrc"] = ["usat21234567"]
    m = ip.choose(row, [hit])
    assert m.status == "matched" and m.song_id == "g" and m.how == "same recording"
    assert m.title == 'Good Times (12" Version)'


def test_isrc_as_a_plain_string_and_a_different_isrc_is_no_recording_match():
    row = Row(1, "Good Times", "Chic", 210, isrc="USAT21234567")
    hit = Song.from_json({"id": "g", "title": "Good Times", "artist": "Chic", "duration": 210, "isrc": "USAT21234567"})
    assert ip.choose(row, [hit]).how == "same recording"
    other = Song.from_json({"id": "o", "title": "Good Times", "artist": "Chic", "duration": 210, "isrc": ["GBXXX0000001"]})
    m = ip.choose(row, [other])
    assert m.status == "matched" and m.how == "same version"           # falls through to the version question


def test_same_length_different_label_is_another_version():
    m = ip.choose(Row(1, "Good Times - Single Version", "Chic", 210), [song("g", "Good Times", "Chic", 210)])
    assert m.status == "ambiguous" and m.why == "other version" and m.candidates == ["g"]
    m = ip.choose(Row(1, "Good Times", "Chic", 210), [song("g", "Good Times (Live)", "Chic", 210)])
    assert m.status == "ambiguous" and m.why == "other version"


def test_same_version_is_named():
    m = ip.choose(Row(1, "Glide", "Pharoah Sanders", 300), [song("g", "Glide - Original Mix", "Pharoah Sanders", 301)])
    assert m.status == "matched" and m.how == "same version"           # "original" is neutral in the version key
    m = ip.choose(Row(1, "The Magician", "Twain", None), [song("t", "The Magician", "Twain", 353)])
    assert m.status == "matched" and m.how == "same version"


def test_an_accepted_12_inch_stands_in_and_is_named():
    row = Row(1, "My Love Is Free", "Double Exposure", 459)
    hits = [song("x", TWELVE, "Double Exposure", 581)]
    m = ip.choose(row, hits, accept=frozenset({"extended"}))
    assert m.status == "matched" and m.song_id == "x" and m.how == 'other version: Tom Moulton 12" Mix'
    assert m.title == TWELVE
    m = ip.choose(row, hits, accept=frozenset())
    assert m.status == "ambiguous" and m.why == "length differs" and m.how is None


def test_an_accepted_other_version_without_a_row_length():
    row = Row(1, "My Love Is Free", "Double Exposure", None)
    hits = [song("x", TWELVE, "Double Exposure", 581)]
    m = ip.choose(row, hits, accept=frozenset({"extended"}))
    assert m.status == "matched" and m.how == 'other version: Tom Moulton 12" Mix'
    m = ip.choose(row, hits)
    assert m.status == "ambiguous" and m.why == "other version"        # same song, label the tier does not accept


def test_two_accepted_other_versions_are_ambiguous():
    row = Row(1, "My Love Is Free", "Double Exposure", 459)
    hits = [song("x", TWELVE, "Double Exposure", 581), song("y", "My Love Is Free (Extended)", "Double Exposure", 420)]
    m = ip.choose(row, hits, accept=frozenset({"extended"}))
    assert m.status == "ambiguous" and m.why == "several versions" and set(m.candidates) == {"x", "y"}


def test_copies_of_one_accepted_other_version_collapse():
    row = Row(1, "My Love Is Free", "Double Exposure", 459)
    hits = [song("x1", TWELVE, "Double Exposure", 581, path="Compilations/a.flac"),
            song("x2", TWELVE, "Double Exposure", 580, path="Double Exposure/b.flac")]
    m = ip.choose(row, hits, accept=frozenset({"extended"}))
    assert m.status == "matched" and m.song_id == "x2" and set(m.candidates) == {"x1", "x2"}


def test_an_other_version_must_be_the_same_song_by_the_same_artist():
    # "title fits" lets "Love" sit inside "Love and Happiness"; a stand-in must have the very same base title
    row = Row(1, "Love and Happiness", "Al Green", 300)
    assert ip.choose(row, [song("l", "Love (Extended)", "Al Green", 420)], accept=frozenset({"extended"})).status != "matched"
    row = Row(1, "My Love Is Free", "Double Exposure", 459)
    m = ip.choose(row, [song("x", TWELVE, "[Unknown Artist]", 581)], accept=frozenset({"extended"}))
    assert m.status != "matched"


def test_a_same_version_beats_an_accepted_other_version():
    row = Row(1, "My Love Is Free", "Double Exposure", 459)
    hits = [song("x", TWELVE, "Double Exposure", 581), song("r", "My Love Is Free", "Double Exposure", 460)]
    m = ip.choose(row, hits, accept=frozenset({"extended"}))
    assert m.status == "matched" and m.song_id == "r" and m.how == "same version"


def test_import_notes_name_the_stand_in():
    with FakeSubsonicServer() as srv:
        srv.state.songs["x"] = dict(srv.state.songs["s1"], id="x", title=TWELVE, artist="Double Exposure", duration=581)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        rows = [Row(1, "My Love Is Free", "Double Exposure", 459, "sp1")]
        rep = ip.import_playlist("Disco", rows, c, store, source="s", tier="medium")
        note = 'matched with another version: 1 Double Exposure — My Love Is Free → My Love Is Free (Tom Moulton 12" Mix)'
        assert rep.matched == 1 and note in rep.notes and note in rep.table()
        assert [e.id for e in c.playlist(rep.playlist_id).entries] == ["x"]


def test_import_at_a_tier_that_accepts_nothing_parks_the_other_version_for_review():
    import sourcing.policy as policy
    with FakeSubsonicServer() as srv:
        srv.state.songs["x"] = dict(srv.state.songs["s1"], id="x", title=TWELVE, artist="Double Exposure", duration=581)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        policy.TIERS["medium"].accept_versions, saved = (), policy.TIERS["medium"].accept_versions
        try:
            rep = ip.import_playlist("Disco", [Row(1, "My Love Is Free", "Double Exposure", 459, "sp1")], c, store,
                                     source="s")
        finally:
            policy.TIERS["medium"].accept_versions = saved
        assert rep.matched == 0 and rep.ambiguous == 1 and not any("another version" in n for n in rep.notes)


def test_exportify_isrc_is_read():
    csv = ("Track URI,Track Name,Album Name,Artist Name(s),Duration (ms),ISRC\n"
           "spotify:track:a,Good Times,Risqué,Chic,210000,USAT21234567\n"
           "spotify:track:b,Le Freak,C'est Chic,Chic,330000,\n")
    rows = rows_from_csv(csv)
    assert rows[0].isrc == "USAT21234567" and rows[1].isrc is None


def test_a_stand_in_needs_every_kind_of_its_version_accepted():
    # Task 4 review: at medium (accept extended) a 12" Dub is a dub, not the vocal row's stand-in.
    acc = frozenset({"extended"})
    for label in ('12" Dub', '12" Instrumental', "Extended Remix", 'Live 12" Version'):
        hit = song("x", f"My Love Is Free ({label})", "Double Exposure", 581)
        m = ip.choose(Row(1, "My Love Is Free", "Double Exposure", None), [hit], accept=acc)
        assert m.status == "ambiguous" and m.why == "other version", label
        m = ip.choose(Row(1, "My Love Is Free", "Double Exposure", 581), [hit], accept=acc)
        assert m.status == "ambiguous" and m.why == "other version", label
    for label in ('12" Version', "Extended Mix"):
        hit = song("x", f"My Love Is Free ({label})", "Double Exposure", 581)
        m = ip.choose(Row(1, "My Love Is Free", "Double Exposure", 459), [hit], accept=acc)
        assert m.status == "matched" and m.how == f"other version: {label}", label


def test_other_version_reason_needs_the_same_song():
    # "Love" fits inside "Love and Happiness (Live)", but that is another song: its length says nothing of versions
    m = ip.choose(Row(1, "Love", "Al Green", 300), [song("h", "Love and Happiness (Live)", "Al Green", 300)])
    assert m.status == "ambiguous" and m.why == "length differs"


# ---- M7 final fixes I4: a stand-in keeps every kind the row asked for (other than edit) ----

def _crate_accept():
    from sourcing.policy import TIERS
    return frozenset(TIERS["crate"].accept_versions)


def test_a_vocal_12_inch_never_stands_in_for_an_instrumental_a_cappella_live_or_dub_row():
    for title in ("Lovely Day - Instrumental", "Lovely Day - A Cappella", "Lovely Day - Live", "Lovely Day (Dub)"):
        for label in ('12" Version', "Extended Version"):
            hit = song("x", f"Lovely Day ({label})", "Bill Withers", 380)
            for length in (250, None):
                m = ip.choose(Row(1, title, "Bill Withers", length), [hit], accept=_crate_accept())
                assert m.status == "ambiguous" and m.song_id is None, (title, label, length)
            m = ip.choose(Row(1, title, "Bill Withers", None), [hit], accept=_crate_accept())
            assert m.why == "other version", (title, label)


def test_a_12_inch_instrumental_stands_in_for_an_instrumental_row_at_crate():
    hit = song("x", 'Lovely Day (12" Instrumental)', "Bill Withers", 380)
    for length in (250, None):
        m = ip.choose(Row(1, "Lovely Day - Instrumental", "Bill Withers", length), [hit], accept=_crate_accept())
        assert m.status == "matched" and m.song_id == "x" and m.how == 'other version: 12" Instrumental', length


def test_a_12_inch_still_stands_in_for_a_radio_edit_row():
    hit = song("x", 'Lovely Day (12" Version)', "Bill Withers", 380)
    m = ip.choose(Row(1, "Lovely Day - Radio Edit", "Bill Withers", 250), [hit], accept=_crate_accept())
    assert m.status == "matched" and m.how == 'other version: 12" Version'


def test_a_stand_in_keeps_the_asked_remixer():
    hit = song("x", "Lovely Day (Extended Remix)", "Bill Withers", 380)
    m = ip.choose(Row(1, "Lovely Day (Tom Moulton Remix)", "Bill Withers", None), [hit],
                  accept=frozenset({"extended", "club", "remix"}))
    assert m.status == "ambiguous"


def test_a_plain_copy_never_stands_in_for_a_labelled_row():
    hit = song("x", "Lovely Day - Instrumental", "Bill Withers", 250)
    m = ip.choose(Row(1, "Lovely Day - Instrumental Radio Edit", "Bill Withers", None), [hit], accept=_crate_accept())
    assert m.status == "ambiguous"
