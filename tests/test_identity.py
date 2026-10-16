"""sourcing.identity: song / version / copy, from real library titles (M7 plan, measured fact 3)."""
import pytest

from sourcing.identity import Copy, lead_artist, loose, parse_title, same_version, song_key, version_groups, words


def test_words_and_loose():
    assert words("Risqué (1979) [FLAC]") == "risque 1979 flac"
    assert words("Chic & Nile") == "chic and nile"
    assert loose("Catendé - Live!") == "catendelive"
    assert loose("Earth, Wind & Fire") == loose("Earth Wind and Fire")
    assert words("Good Times (Original Mix) feat. X", noise=True) == "good times original mix x"
    assert words(None) == "" and loose(None) == ""


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
    ("Downstairs - Alternate Take 21", "X", "Downstairs", {"alt"}, ""),
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
    assert same_version(_c("A", 300, recording_id="r1"), _c("B", 100, recording_id="R1"))
    assert not same_version(_c("A", 300, recording_id="r1"), _c("A", 300, recording_id="r2"))
    assert not same_version(_c("A", None), _c("A", 300))
    assert not same_version(_c("A", 300, work_id="w1"), _c("A", 300, work_id="w2"))
    assert same_version(_c("Feeling U, Feeling Me (Interlude)", 200, work_id="w1"),
                        _c("Feeling U, Feeling Me", 200, work_id="w1"))
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
