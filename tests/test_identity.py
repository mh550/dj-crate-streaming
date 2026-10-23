"""sourcing.identity: song / version / copy, from real library titles (M7 plan, measured fact 3)."""
import pytest

from sourcing.identity import Copy, can_be_song, is_placeholder, lead_artist, parse_filename, loose, parse_title, same_version, song_key, strip_trackno, version_groups, words


def test_words_and_loose():
    assert words("Risqué (1979) [FLAC]") == "risque 1979 flac"
    assert words("Chic & Nile") == "chic and nile"
    assert loose("Catendé - Live!") == "catendelive"
    assert loose("Earth, Wind & Fire") == loose("Earth Wind and Fire")
    assert words("Good Times (Original Mix) feat. X", noise=True) == "good times original mix x"
    assert words(None) == "" and loose(None) == ""


def test_folding_drops_latin_style_accents_only():
    assert loose("Catendé") == loose("Catende") == "catende"
    assert words("Beyoncé") == "beyonce" and words("Motörhead") == "motorhead" and words("Ñ") == "n"
    assert words("Ά") == "α"                      # Greek tonos is a combining mark in U+0300-036F: folds
    assert words("й") == "и"                      # й is и + U+0306: folds to и, accepted (same range)


def test_folding_keeps_japanese_voiced_marks():
    assert loose("ガ") != loose("カ") and words("ガ") != words("カ")
    assert loose("パ") != loose("ハ") != loose("バ")
    assert words("ガ") == "ガ"                    # recomposed (NFC), not left as カ + U+3099
    assert loose("ｶﾞ") == loose("ガ")             # half-width kana folds to the same key as full-width


def test_words_noise_drops_copy_and_credit_words():
    assert words("Le Freak - 2006 Remaster", noise=True) == "le freak"
    assert words("Virgin (Album Version) [Explicit] HQ", noise=True) == "virgin"


def test_lead_artist():
    assert lead_artist("Vinícius de Moraes • Maria Creuza") == "Vinícius de Moraes"
    assert lead_artist("A; B") == "A"
    assert lead_artist("Chic feat. Nile Rodgers") == "Chic"
    assert lead_artist("Chic Featuring Nile Rodgers") == "Chic"
    assert lead_artist("Chic ft. Nile Rodgers") == "Chic"
    assert lead_artist("Earth, Wind & Fire") == "Earth, Wind & Fire"
    assert lead_artist(None) == ""


@pytest.mark.parametrize("title, artist, base, kinds, by", [
    ("Good Times", "Chic", "Good Times", set(), ""),
    ("You're Lying (12' Mix)", "Linx", "You're Lying", {"extended"}, ""),
    ('You\'re Lying (12" Mix)', "Linx", "You're Lying", {"extended"}, ""),
    ("My Love Is Free (tom Moulton 12” Mix)", "Double Exposure", "My Love Is Free", {"extended"}, "tommoulton"),
    ("Where You Are (Live)", "X", "Where You Are", {"live"}, ""),
    ("Where You Are - Live", "X", "Where You Are", {"live"}, ""),
    ("Tyrone - Extended Version", "X", "Tyrone", {"extended"}, ""),
    ("Move on Up - Single Edit", "X", "Move on Up", {"edit"}, ""),
    ("I Found My Smile Again (radio edit)", "X", "I Found My Smile Again", {"edit"}, ""),
    ("Voyager (Dominique Torti's Wild Style Edit)", "X", "Voyager", {"reedit"}, "dominiquetortiswildstyle"),
    ("Batanayi - Special Dub Mix", "X", "Batanayi", {"dub"}, "special"),
    ("Dreamin' (Original 12 Inch Club Mix)", "X", "Dreamin'", {"original", "extended", "club"}, ""),
    ("Glide - Original Mix", "X", "Glide", {"original"}, ""),
    ("Star Love - Disco Version", "X", "Star Love", {"alt"}, "disco"),
    ("Downstairs - Alternate Take 21", "X", "Downstairs", {"alt"}, "21"),        # review ruling 1: the take number is the credit
    ("Je Suis Music - Armand Van Helden Remix Edit", "X", "Je Suis Music", {"remix", "edit"}, "armandvanhelden"),
    ("Sugar - Delfonic Rework", "X", "Sugar", {"remix"}, "delfonic"),
    ("Mothership Reconnection (feat. Parliament/Funkadelic) - (Daft Punk Remix)", "Scott Grooves",
     "Mothership Reconnection", {"remix"}, "daftpunk"),
    ('Tonight\'s the Night (Good Time) [12" Version] - Remix', "X", "Tonight's the Night (Good Time)",
     {"extended", "remix"}, ""),
    ('Boogie Nights (12" Single Version)', "Heatwave", "Boogie Nights", {"extended"}, ""),
    ("Good Times (7in Edit)", "Chic", "Good Times", {"edit"}, ""),
    ("Baby's Gone (Remastered 1999)", "Prince", "Baby's Gone", set(), ""),
    ("Softly As In A Morning Sunrise - Remastered 2001/Rudy Van Gelder Edition", "X",
     "Softly As In A Morning Sunrise", set(), ""),
    ("Virgin (Album Version)", "X", "Virgin", set(), ""),
    ("Dudley Boyz (feat. Action Bronson)", "Your Old Droog", "Dudley Boyz", set(), ""),
    ("100 - Smokey Robinson - Why You Wanna See My Bad Side.mp3", "Smokey Robinson",
     "Why You Wanna See My Bad Side", set(), ""),
    ("A Change Is Gonna Come - Jennifer Lara", "Jennifer Lara", "A Change Is Gonna Come", set(), ""),
    ("Pepe Link - Vem Menina", "Pepe Link", "Vem Menina", set(), ""),
])
def test_parse_title_real_library_titles(title, artist, base, kinds, by):
    t = parse_title(title, artist)
    assert (t.base, t.kinds, t.by) == (base, frozenset(kinds), by)


def test_parse_title_keeps_label_and_copy_note_as_written():
    assert parse_title("Baby's Gone (Remastered 1999)").copy_note == "Remastered 1999"
    assert parse_title("You're Lying (12' Mix)").label == "12' Mix"
    t = parse_title('Tonight\'s the Night (Good Time) [12" Version] - Remix')
    assert t.label == '12" Version, Remix' and t.copy_note == ""
    t = parse_title("Mothership Reconnection (feat. Parliament/Funkadelic) - (Daft Punk Remix)")
    assert t.label == "Daft Punk Remix" and t.copy_note == "feat. Parliament/Funkadelic"
    assert parse_title(None) == parse_title("")


@pytest.mark.parametrize("title", [
    "In da Club", "Tropical Club", "Peace and Love Dub", "How Can One Man Live", "C12H16N2",
    "Mary Jane (All Night Long)", "(They Long to Be) Close to You", "Feeling U, Feeling Me (Interlude)",
])
def test_words_inside_the_song_name_are_not_labels(title):
    t = parse_title(title)
    assert t.kinds == frozenset() and t.base == title and t.label == ""


def test_peeling_stops_at_the_first_decoration_without_a_label():
    t = parse_title("Next Lifetime (Interlude) - Live")
    assert t.base == "Next Lifetime (Interlude)" and t.kinds == {"live"}


def test_a_whole_title_in_brackets_is_never_a_decoration():
    assert parse_title("(Live)").base == "(Live)"


def test_version_tag_only_counts_when_it_is_a_label():
    assert parse_title("Good Times", version_tag="2003").kinds == frozenset()
    assert parse_title("Good Times", version_tag="PMEDIA").kinds == frozenset()
    assert parse_title("Good Times", version_tag="").kinds == frozenset()
    assert parse_title("Good Times", version_tag='12" Version').kinds == {"extended"}


def test_feat_with_a_version_word_is_still_a_credit_not_a_label():
    t = parse_title("Rise (feat. The Live Band)")
    assert t.base == "Rise" and t.kinds == frozenset() and t.copy_note == "feat. The Live Band"


def test_remaster_never_hides_a_version_label():
    t = parse_title("Rock With You (Live - 2011 Remaster)")
    assert t.kinds == {"live"} and t.key == parse_title("Rock With You (Live)").key


def test_key_ignores_original_and_spelling():
    assert parse_title("Glide - Original Mix").key == parse_title("Glide").key
    assert parse_title("You're Lying (12' Mix)").key == parse_title('You\'re Lying (12" Mix)').key
    assert parse_title("The Art Of Easing - Live").key != parse_title("The Art Of Easing").key


def test_key_keeps_the_credit():
    assert parse_title("Voyager (Tom Moulton Mix)").key != parse_title("Voyager (Larry Levan Mix)").key
    assert parse_title("Good Times (12\" Version)").key != parse_title("Good Times (Radio Edit)").key


def _c(title, length, artist="Chic", **kw):
    return Copy(artist=artist, title=title, length_s=length, **kw)


def test_same_version():
    assert same_version(_c("You're Lying (12' Mix)", 397.0), _c('You\'re Lying (12" Mix)', 398.0))
    assert not same_version(_c("Where You Are (Live)", 306), _c("Where You Are (Live)", 464))
    assert same_version(_c("A", 300, recording_id="r1"), _c("B", 302, recording_id="R1"))   # M7 final I2: was 100 s
    assert not same_version(_c("A", 300, recording_id="r1"), _c("A", 300, recording_id="r2"))
    assert not same_version(_c("A", None), _c("A", 300))
    assert not same_version(_c("A", 300, work_id="w1"), _c("A", 300, work_id="w2"))
    # review ruling 3: a shared work id makes one *song*; the version still needs the same base and label
    assert not same_version(_c("Feeling U, Feeling Me (Interlude)", 200, work_id="w1"),
                            _c("Feeling U, Feeling Me", 200, work_id="w1"))
    assert same_version(_c("Feeling U, Feeling Me", 200, work_id="w1"), _c("Feeling U, Feeling Me", 201, work_id="w1"))
    assert same_version(_c("Where You Are (Live)", 479.0), _c("Where You Are - Live", 479.4))


def test_same_version_errs_toward_different():
    # a 12" is never the radio edit, even at a matching length; another artist is another song
    assert not same_version(_c('Good Times (12" Version)', 300), _c("Good Times", 300))
    assert not same_version(_c("Good Times", 300), _c("Good Times", 300, artist="Nile Rodgers"))
    assert not same_version(_c("Good Times", 300), _c("Good Times", 304.5))
    # remasters and features are copies, not versions
    assert same_version(_c("Good Times - 2006 Remaster", 300), _c("Good Times (feat. Nile)", 301, artist="Chic feat. Nile"))
    # the version tag counts when it is a label
    assert not same_version(_c("Good Times", 300, version_tag='12" Version'), _c("Good Times", 300))
    assert same_version(_c("Good Times", 300, version_tag="2003"), _c("Good Times", 300))


def test_version_groups():
    copies = [_c("A", 352.3), _c("A", 352.2), _c("B", 240.0), _c("B", 288.8),
              _c("C (Live)", 300), _c("C", 300)]
    assert version_groups(copies) == [[0, 1]]


def test_version_groups_are_pairwise_same_version():
    # 300 / 303 / 306: neighbours are within 4 s, but 300 and 306 are not the same version
    copies = [_c("A", 300), _c("A", 303), _c("A", 306)]
    groups = version_groups(copies)
    assert groups == [[0, 1]]
    for g in groups:
        assert all(same_version(copies[i], copies[j]) for i in g for j in g)


def test_version_groups_split_on_disagreeing_recording_ids():
    copies = [_c("A", 300, recording_id="r1"), _c("A", 300.5, recording_id="r2"), _c("A", 301)]
    groups = version_groups(copies)
    assert len(groups) == 1 and not {0, 1} <= set(groups[0])        # the id-less copy joins one of them, never both
    assert version_groups([_c("A", 300, recording_id="r1"), _c("A", 300.5, recording_id="r2")]) == []


def test_song_key():
    assert song_key("Smokey Robinson", "100 - Smokey Robinson - Why You Wanna See My Bad Side.mp3") == \
        "smokeyrobinson|whyyouwannaseemybadside"
    assert song_key("Chic", "Good Times (12\" Version)") == song_key("chic", "Good Times")
    assert song_key("Chic feat. Nile Rodgers", "Good Times (Live)") == song_key("Chic", "Good Times")


def test_the_beets_trap_is_two_versions():
    # measured fact 5: beets applied the 403 s "90's-mix" recording to the 412 s "Original 12'' Version"
    a = _c("Get Down Saturday Night (Original 12'' Version)", 412, artist="Oliver Cheatham")
    b = _c("Get Down Saturday Night (Get Down in the 90's-mix)", 412, artist="Oliver Cheatham")
    assert parse_title(a.title).kinds == {"original", "extended"}
    assert not same_version(a, b)


def test_a_track_number_prefix_needs_a_title_after_it():
    assert parse_title("1-2-3").base == "1-2-3"
    assert parse_title("04 - 122 - Wendell Harrison - Peace Of Mind.mp3.mp3", "Wendell Harrison").base == "Peace Of Mind"


# ── review fix round: pairs that must never be one version (M8 deletes a copy on "same") ──

@pytest.mark.parametrize("a, b", [
    ("Downstairs - Alternate Take 21", "Downstairs - Alternate Take 22"),
    ("Downstairs (Take 1)", "Downstairs (Take 2)"),
    ("We Got By - Live 1977 Version", "We Got By (Live 1979)"),
    ("Tutu (Live at Montreux 1979)", "Tutu (Live at Montreux 1982)"),
    ("Tutu - 2009 Mix", "Tutu - 2017 Mix"),
    ("Tutu (Remix 1987)", "Tutu (Remix 1995)"),
    ("Tutu (Single Mix)", "Tutu (Album Mix)"),
    ("Tutu (Remastered Mono)", "Tutu (Remastered Stereo)"),
    ("Tutu (With Strings)", "Tutu"),
    ("Tutu (feat. X - Dub Mix)", "Tutu (feat. X)"),
    ("Tutu [The Reflex Revision]", "Tutu"),
    ("Tutu (Sonias 2 Euro Bootleg)", "Tutu"),
    ("Tutu (Joey Negro Refix)", "Tutu"),
    ("Tutu (12’ Mix)", "Tutu"),
    ("Tutu (12-Inch Mix)", "Tutu"),
])
def test_review_pairs_are_different_versions(a, b):
    assert not same_version(_c(a, 300), _c(b, 300))


def test_a_remaster_beside_a_label_is_still_the_same_version():
    assert same_version(_c("Rock With You (Live - 2011 Remaster)", 300), _c("Rock With You (Live)", 300))
    assert same_version(_c("Rock With You - 2011 Remaster", 300), _c("Rock With You", 300))
    assert same_version(_c("Rock With You (Remastered Version)", 300), _c("Rock With You", 300))


def test_only_the_remaster_phrase_is_a_copy_marker():
    assert parse_title("Tutu (Remastered Mono)").kinds == {"alt"}
    assert parse_title("Tutu (Remastered Mono)").by == "mono"
    assert parse_title("Tutu - Remastered 2001/Rudy Van Gelder Edition").copy_note == "Remastered 2001/Rudy Van Gelder Edition"


def test_a_label_named_like_the_artist_is_not_stripped_as_glue():
    t = parse_title("Song - Live", "Live")
    assert t.base == "Song" and t.kinds == {"live"}


def test_feat_decoration_with_a_label_tail():
    t = parse_title("Tutu (feat. X - Dub Mix)")
    assert t.base == "Tutu" and t.kinds == {"dub"} and t.copy_note == "feat. X" and t.label == "Dub Mix"
    assert parse_title("Tutu (With Strings)").base == "Tutu (With Strings)"


def test_version_tag_repeating_the_title_label_adds_no_credit():
    t = parse_title("Voyager (Tom Moulton Mix)", version_tag="Tom Moulton Mix")
    assert t.by == "tommoulton" and t.label == "Tom Moulton Mix"
    t = parse_title("Voyager (Tom Moulton Mix)", version_tag="Dub")
    assert t.by == "tommoulton" and t.kinds == {"remix", "dub"}
    t = parse_title("Voyager (Tom Moulton Mix) [Larry Levan Edit]")
    assert t.by == "tommoulton|larrylevan"


@pytest.mark.parametrize("title", ["Tutu (12’ Mix)", "Tutu (12‘ Mix)", "Tutu (12“ Mix)", "Tutu (12-Inch Mix)",
                                   "Tutu (12 Inch Mix)", "Tutu (12inch Mix)"])
def test_twelve_inch_spellings(title):
    assert parse_title(title).kinds == {"extended"} and parse_title(title).by == ""


@pytest.mark.parametrize("title, kinds, by", [
    ("Tutu [The Reflex Revision]", {"reedit"}, "thereflex"),
    ("Tutu (Sonias 2 Euro Bootleg)", {"remix"}, "sonias2euro"),
    ("Tutu (Joey Negro Refix)", {"remix"}, "joeynegro"),
    ("Tutu - Delfonic Rework", {"remix"}, "delfonic"),
])
def test_remix_family_words(title, kinds, by):
    t = parse_title(title)
    assert (t.base, t.kinds, t.by) == ("Tutu", frozenset(kinds), by)


def test_version_groups_never_disagree_with_same_version():
    copies = [_c("A", 300, recording_id="r1"), _c("B", 299, recording_id="r1"),      # M7 final: was "A (Live)" 280 s
              _c("A", 300, work_id="w1"), _c("A", 301, work_id="w2"), _c("A", 302), _c("A", 302.5)]
    groups = version_groups(copies)
    for g in groups:
        assert all(same_version(copies[i], copies[j]) for i in g for j in g if i != j)
    assert [0, 1] in groups                              # one recording id is one version, whatever the titles


@pytest.mark.parametrize("a, b", [
    ("Song (Clean Mix)", "Song (Explicit Mix)"),
    ("Song (Clean Edit)", "Song (Edit)"),
    ("Song (Clean)", "Song"),
    ("Song (Explicit)", "Song"),
    ("Song - Dirty", "Song"),
    ("Song (Clean Version)", "Song (Explicit Version)"),
])
def test_clean_and_explicit_are_versions_not_copies(a, b):
    # a clean edit mutes lyrics at the same length: M8 must never replace an explicit file with it
    assert not same_version(_c(a, 300), _c(b, 300))


def test_clean_is_an_alt_kept_in_the_credit():
    t = parse_title("Song (Clean Edit)")
    assert t.base == "Song" and t.kinds == {"alt", "edit"} and t.by == "clean" and t.copy_note == ""


@pytest.mark.parametrize("a, b", [
    ("Song (Remastered 2009 Mono Edition)", "Song (Remastered 2009 Stereo Edition)"),
    ("Song (feat. X - Acoustic)", "Song (feat. X)"),
])
def test_rereview_pairs_are_different_versions(a, b):
    assert not same_version(_c(a, 300), _c(b, 300))


def test_a_feat_decoration_with_an_unknown_tail_stays_in_the_base():
    assert parse_title("Song (feat. X - Acoustic)").base == "Song (feat. X - Acoustic)"


@pytest.mark.parametrize("s", ["Catendé - Live!", "Chic & Nile", "Earth, Wind & Fire", "Jettin’", "It's #1, Baby"])
def test_normalisers_agree(s):
    # one owner for "is this the same text": every caller folds through identity (M7 Task 2)
    from crates import store
    from scripts import dedupe_copies, tag_rules
    from sourcing import import_playlist, scorer
    want = loose(s)
    assert import_playlist.norm(s) == store._loose(s) == dedupe_copies._norm(s) == want
    assert tag_rules._same(s, s.upper())
    assert scorer.norm(s) == words(s, noise=True)


def test_rulings_ampersand_accents_and_original_mix():
    from crates import store
    from scripts import dedupe_copies, tag_rules
    from sourcing import import_playlist, scorer
    # "&" is "and" on both sides, in every caller except Navidrome's search tokeniser
    assert import_playlist.norm("X & Y") == import_playlist.norm("X and Y")
    assert store._loose("X & Y") == store._loose("X and Y") and dedupe_copies._norm("X & Y") == dedupe_copies._norm("X and Y")
    assert import_playlist.query_words("Chic & Nile") == ["chic", "nile"]      # Navidrome's search drops "&": untouched
    # accents are ignored by find_external's key, dedupe and the sockseek rule
    assert store._loose("Catendé") == store._loose("Catende")
    assert dedupe_copies._norm("Catendé") == dedupe_copies._norm("Catende")
    assert tag_rules._same("Catendé", "Catende")
    # "original mix" is a version label (D16): the scorer keeps it in names
    assert scorer.norm("Glide (Original Mix)") == "glide original mix"


# ---- M7 final fixes I2: a shared recording id is not proof when the lengths disagree ----

def test_equal_recording_ids_with_disagreeing_lengths_are_different_versions():
    r = "bb31a869-0000-0000-0000-000000000000"
    a = Copy("Kool & the Gang", "Get Down Saturday Night (Original 12'' Version)", 412, recording_id=r)
    b = Copy("Kool & the Gang", "Get Down Saturday Night (Get Down in the 90's-mix)", 403, recording_id=r)
    c = Copy("Chic", "Good Times", 220, recording_id=r)
    assert not same_version(a, b) and not same_version(a, c) and not same_version(b, c)
    assert version_groups([a, b, c]) == []


def test_equal_recording_ids_decide_within_the_tolerance_or_with_a_length_unknown():
    r = "bb31a869-0000-0000-0000-000000000000"
    assert same_version(Copy("Chic", "Good Times", 300, recording_id=r), Copy("Chic", "Good Times", 303.5, recording_id=r))
    # fix round 2 ruling 1: was True for "Good Times" vs "Good Times (Live)"; a shared id needs the same label too
    assert not same_version(Copy("Chic", "Good Times", 300, recording_id=r), Copy("Chic", "Good Times (Live)", 303.5, recording_id=r))
    assert same_version(Copy("Chic", "Good Times", None, recording_id=r), Copy("Chic", "Good Times", 300, recording_id=r))
    assert not same_version(Copy("Chic", "Good Times", 300, recording_id=r), Copy("Chic", "Good Times", 304.5, recording_id=r))


# ---- M7 final fixes I3: untagged copies are never one version ----

@pytest.mark.parametrize("a, b", [
    (Copy("", "", 200), Copy("", "", 202)),
    (Copy("", "Track 01", 200), Copy("", "Track 01", 203)),
    (Copy("[Unknown Artist]", "Intro", 60), Copy("[Unknown Artist]", "Intro", 61)),
    (Copy("Unknown Artist", "Intro", 60), Copy("Unknown Artist", "Intro", 61)),
    (Copy("Various Artists", "Intro", 60), Copy("Various Artists", "Intro", 61)),
    (Copy("Chic", "Track 01", 200), Copy("Chic", "Track 01", 201)),
    (Copy("Chic", "07", 200), Copy("Chic", "07", 201)),
    (Copy("Chic", "Track01.mp3", 200), Copy("Chic", "Track01.mp3", 201)),
    (Copy("Chic", "", 200), Copy("Chic", "", 201)),
])
def test_placeholder_artist_or_title_is_never_the_same_version(a, b):
    assert not same_version(a, b)
    assert version_groups([a, b]) == []


def test_is_placeholder():
    for artist, title in [("", "Good Times"), ("[Unknown Artist]", "Good Times"), ("various artists", "X"),
                          ("Chic", ""), ("Chic", "Track 12"), ("Chic", "track_03"), ("Chic", "12"),
                          ("Chic", "AUDIO_0003.wav"), ("Chic", "01 - Track 01.mp3"), (None, None)]:
        assert is_placeholder(artist, title), (artist, title)
    for artist, title in [("Chic", "Good Times"), ("Chic feat. X", "Good Times (Live)"), ("Prince", "1999"),
                          ("Chic", "Intro"), ("Smokey Robinson", "100 - Smokey Robinson - Why You Wanna See My Bad Side.mp3")]:
        assert not is_placeholder(artist, title), (artist, title)


# ---- M7 final fixes m8: feat/ft with or without the dot, and a bracketed "(feat. X)" in the artist ----

@pytest.mark.parametrize("artist", ["Chic feat Nile Rodgers", "Chic ft Nile Rodgers", "Chic (feat. Nile Rodgers)",
                                    "Chic (ft. Nile Rodgers)", "Chic [feat. Nile Rodgers]", "Chic (featuring Nile Rodgers)"])
def test_lead_artist_splits_every_feat_spelling(artist):
    assert lead_artist(artist) == "Chic"


def test_lead_artist_does_not_split_inside_a_word():
    assert lead_artist("Lil Feather") == "Lil Feather" and lead_artist("Daft Punk") == "Daft Punk"
    assert lead_artist("Swift ft") == "Swift ft"                      # nothing credited after it


# ---- M7 final fixes m9: a numbered version and a numbered take are different versions ----

def test_version_number_and_take_number_have_different_keys():
    assert parse_title("Song (Version 2)").key != parse_title("Song (Take 2)").key
    assert not same_version(_c("Song (Version 2)", 300), _c("Song (Take 2)", 300))
    assert parse_title("Song (Version 2)").key == parse_title("Song - Version 2").key


# ---- M7 final fixes m2: a Soulseek file name's trailing format/bitrate/year junk does not hide its label ----

@pytest.mark.parametrize("name, base, kinds", [
    ("03 - Good Times (Extended Mix) [320].mp3", "Good Times", {"extended"}),
    ("Good Times (Extended) [FLAC].flac", "Good Times", {"extended"}),
    ("Good Times (Extended Mix) (320 kbps).mp3", "Good Times", {"extended"}),
    ("Good Times (Live) [WEB].flac", "Good Times", {"live"}),
    ("Good Times (12\" Version) [24-96] [FLAC].flac", "Good Times", {"extended"}),
    ("A1 Good Times (Dub) (1979).flac", "Good Times", {"dub"}),
    ("Chic - Good Times (1979).flac", "Good Times", set()),
    ("03. Good Times [320kbps].mp3", "Good Times", set()),
    ("Good Times (Live 1977).flac", "Good Times", {"live"}),
])
def test_parse_filename_peels_file_junk_before_the_label(name, base, kinds):
    t = parse_filename(name, "Chic")
    assert (t.base, set(t.kinds)) == (base, kinds)


def test_parse_filename_keeps_a_years_credit_inside_a_label():
    assert parse_filename("Good Times (Live 1977).flac", "Chic").key != parse_filename("Good Times (Live 1979).flac", "Chic").key


# ---- M7 fix round 2, ruling 1: a shared recording id is one version only with the same version key ----

@pytest.mark.parametrize("a, b", [("Song (Explicit)", "Song (Clean)"), ("Song", "Song (Instrumental)"),
                                  ("Song (Mono)", "Song (Stereo)"), ("Song", "Song (Live)"),
                                  ("Song (Radio Edit)", "Song (Instrumental Radio Edit)")])
def test_a_shared_recording_id_with_different_labels_is_two_versions(a, b):
    r = "bb31a869-0000-0000-0000-000000000000"
    assert not same_version(Copy("X", a, 210, recording_id=r), Copy("X", b, 211, recording_id=r))
    assert not same_version(Copy("X", a, None, recording_id=r), Copy("X", b, 211, recording_id=r))


# ---- M7 fix round 2, ruling 2: more placeholder spellings ----

@pytest.mark.parametrize("artist, title", [("VA", "Intro"), ("Various", "Intro"), ("Unknown", "Intro"),
                                           ("<unknown>", "Intro"), ("va", "Intro"), ("<Unknown>", "Intro"),
                                           ("X", "Audio Track"), ("X", "Untitled Track"), ("X", "No Title"),
                                           ("X", "Audio Track 03"), ("X", "Untitled Track 12"), ("X", "No Title 2")])
def test_more_placeholders(artist, title):
    assert is_placeholder(artist, title)
    assert not same_version(Copy(artist, title, 60), Copy(artist, title, 61))


def test_real_names_are_not_placeholders():
    for artist, title in [("Prince", "1999"), ("X", "Intro"), ("Vanessa", "Intro"), ("Various Cruelties", "Intro"),
                          ("X", "No Title Needed"), ("X", "Audio Tracks of My Life")]:
        assert not is_placeholder(artist, title), (artist, title)


# ---- M7 fix round 2, ruling 3: a trailing group is file junk when every token in it is ----

@pytest.mark.parametrize("name, base, kinds", [
    ("Song (Extended Mix) [FLAC 24-96].flac", "Song", {"extended"}),
    ("Song (Extended Mix) [MP3 320].mp3", "Song", {"extended"}),
    ("Song (Extended Mix) [WEB FLAC].flac", "Song", {"extended"}),
    ("Song (Extended Mix) {320}.mp3", "Song", {"extended"}),
    ("Song (Extended Mix) - 320.mp3", "Song", {"extended"}),
    ("Song (Extended Mix) [24bit-96kHz].flac", "Song", {"extended"}),
    ("Song (Extended Mix) [320 kbps].mp3", "Song", {"extended"}),
    ("Song (Dub) [16-44.1, CD Rip].flac", "Song", {"dub"}),
    ("Song (Extended Mix) [FLAC Deluxe].flac", "Song (Extended Mix) [FLAC Deluxe]", set()),   # one real word: kept
])
def test_parse_filename_peels_groups_made_only_of_file_junk(name, base, kinds):
    t = parse_filename(name)
    assert (t.base, set(t.kinds)) == (base, kinds)


def test_parse_filename_keeps_a_remaster_as_a_copy_marker_behind_junk():
    t = parse_filename("Title (1979 Remaster) [FLAC 24-96].flac")
    assert t.base == "Title" and not t.kinds and t.copy_note == "1979 Remaster"


def test_parse_filename_never_peels_the_song_itself():
    assert parse_filename("Prince - 1999.flac", "Prince").base == "1999"
    assert parse_filename("1999.flac", "Prince").base == "1999"
    assert parse_filename("Taylor Swift - 22.flac", "Taylor Swift").base == "22"


# ---- M9 §8b: a bare leading number stays when it is part of the wanted title ("99 Luftballons") ----

@pytest.mark.parametrize("name, wanted, out", [
    ("03 - Good Times", "Good Times", "Good Times"),
    ("03. Good Times", "Good Times", "Good Times"),
    ("A1 Good Times", "Good Times", "Good Times"),
    ("03 Good Times", "Good Times", "Good Times"),
    ("99 Luftballons", "99 Luftballons", "99 Luftballons"),
    ("01 99 Luftballons", "99 Luftballons", "99 Luftballons"),
    ("01 - 99 Luftballons", "99 Luftballons", "99 Luftballons"),
    ("99 Luftballons (Extended)", "99 Luftballons (12'' Version)", "99 Luftballons (Extended)"),
    ("99 luftballons", "99 Luftballons", "99 luftballons"),       # the scorer's folded text
])
def test_strip_trackno_keeps_a_number_the_wanted_title_starts_with(name, wanted, out):
    assert strip_trackno(name, wanted) == out


@pytest.mark.parametrize("name, out", [("03 - Good Times", "Good Times"), ("03. Good Times", "Good Times"),
                                       ("A1 Good Times", "Good Times"), ("99 Luftballons", "Luftballons"),
                                       ("1999", "1999")])
def test_strip_trackno_without_a_wanted_title_is_unchanged(name, out):
    assert strip_trackno(name) == out


def test_parse_filename_passes_the_wanted_title_through():
    assert parse_filename("99 Luftballons.flac", "Nena", "99 Luftballons").base == "99 Luftballons"
    assert parse_filename("01 99 Luftballons.flac", "Nena", "99 Luftballons").base == "99 Luftballons"
    assert parse_filename("99 Luftballons.flac", "Nena").base == "Luftballons"


@pytest.mark.parametrize("name, wanted, out", [
    ("22 Shake It Off", "22", "Shake It Off"),                     # the wanted title is only the number
    ("7 Little Red Corvette", "7", "Little Red Corvette"),
    ("17 Againx", "17 Again", "Againx"),                           # whole words only
])
def test_strip_trackno_keeps_a_number_only_when_the_wanted_words_follow_it(name, wanted, out):
    assert strip_trackno(name, wanted) == out


@pytest.mark.parametrize("title, asked", [
    ("Love and Happiness", "Love And Happiness"), ("Love and Happiness (Live)", "Love And Happiness"),
    ("Love And Happiness feat. Bob", "Love and Happiness"), ('Love and Happiness - From "Movie"', "Love and Happiness"),
    ("02 Can You Feel It", "Can You Feel It"), ("Al Green - Love and Happiness", "Love and Happiness"),
    ("", "Love and Happiness"), ("Love and Happiness", None),
    ("Love and Happiness (Acoustic)", "Love and Happiness"), ("Love and Happiness", "Love and Happiness (Acoustic)"),
    ("Good Times - Chic & Nile Rodgers", "Good Times"), ("Chic - Good Times", "Good Times"),
    ("Love and Happiness ft. Bob", "Love and Happiness"), ("01 - Love and Happiness", "Love and Happiness"),
    # extra words on both sides, other track number forms, `,` `:` `/` and unspaced dashes (S1-R1 re-review)
    ('Song (From "Movie")', 'Song - From "Movie" Soundtrack'), ("Al Green - Song", "Song (Acoustic)"),
    ("02 Song", "Song (Acoustic)"), ("1-01 Song", "Song"), ("A1 Song", "Song"), ("A1. Song", "Song"),
    ("01_Song", "Song"), ("01.Song", "Song"),
    ("Can't Get Enough of Your Love, Babe", "Can't Get Enough of Your Love"),
    ("Get Up (I Feel Like Being A) Sex Machine, Pts. 1 & 2", "Sex Machine"), ("Song, Pt. 1", "Song"),
    ("Medley: Song / Other", "Song"), ("Intro: Song", "Song"), ("Song: Reprise", "Song"), ("Song—Remastered", "Song")])
def test_can_be_song_is_lenient_about_spelling_labels_credits_and_prefixes(title, asked):
    assert can_be_song(title, asked)


def test_can_be_song_tells_another_song_apart():
    """ext-74: the same-named album's track 9 is not the title track (S1-02, S1-03)."""
    assert not can_be_song("One of These Good Old Days", "I'm Still In Love With You")
    assert not can_be_song("Le Freak", "Good Times")


@pytest.mark.parametrize("title, asked", [
    ("Take Me Home", "Home"), ("Home", "Take Me Home"), ("Lovely Day", "Love"), ("Love Me Do", "Love"),
    ("Love and Happiness", "Happiness"), ("Happiness Is a Warm Gun", "Happiness")])
def test_can_be_song_does_not_take_a_song_whose_title_holds_the_asked_words(title, asked):
    """Containment is not enough (S1-R1 review I-1): the extra words must stand apart, after ` - `, a bracket or a
    credit, or be a track number in front."""
    assert not can_be_song(title, asked)
