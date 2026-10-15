from scripts import tag_rules as tr


def f(**kw):
    base = dict(title="", artist="", albumartist="", album="", comp=False, comments="", in_compilations=False)
    base.update(kw)
    return base


def test_remaster_suffix_moves_into_comments():
    new, rules = tr.clean(f(title="Baby's Gone - Remastered 1999", artist="Prince", comments="https://github.com/spotbye/SpotiFLAC"))
    assert new == {"title": "Baby's Gone", "comments": "https://github.com/spotbye/SpotiFLAC\nversion: Remastered 1999"}
    assert rules == ["remaster"]
    for t, want in [("I Can't Tell You Why - 2013 Remaster", "I Can't Tell You Why"), ("Rescue Me - Remastered", "Rescue Me"),
                    ("Fascination - 2012 Remaster", "Fascination"), ("Song - Digitally Remastered 2004", "Song")]:
        assert tr.clean(f(title=t, artist="X"))[0]["title"] == want, t


def test_live_and_mixes_are_left_alone():
    for t in ("Catendé - Live", "Boogie Nights - Live", "Glide - Original Mix", "Each and Every One - Home Demo"):
        assert tr.clean(f(title=t, artist="X")) == ({}, []), t


def test_sockseek_title_splits_into_fields():
    new, rules = tr.clean(f(title="Gino Soccio - 'The Visitors (Original)' (Outline)", artist="Gino Soccio", album="[Unknown Album]"))
    assert new == {"title": "The Visitors (Original)", "album": "Outline"} and rules == ["sockseek"]
    new, rules = tr.clean(f(title="Queen - 'Cool Cat - Remastered 2011' (Hot Space (Deluxe Remastered Version))", artist="Queen", album="Hot Space"))
    assert new == {"title": "Cool Cat", "comments": "version: Remastered 2011"} and rules == ["sockseek", "remaster"]   # a real album tag stays


def test_junk_filename_titles_become_artist_and_title():
    junk = "100 - Smokey Robinson - Why You Wanna See My Bad Side.mp3"
    new, rules = tr.clean(f(title=junk, artist=junk, albumartist="Various Artists"))
    assert new["artist"] == "Smokey Robinson" and new["title"] == "Why You Wanna See My Bad Side" and rules == ["junk"]


def test_missing_artist_with_one_dash_splits():
    assert tr.clean(f(title="September - Ostavi Trag", artist=""))[0] == {"artist": "September", "title": "Ostavi Trag"}
    assert tr.clean(f(title="September - Ostavi Trag", artist="[Unknown Artist]"))[0] == {"artist": "September", "title": "Ostavi Trag"}
    assert tr.clean(f(title="Organic Dream - 02 - Winter", artist=""))[0] == {}          # two dashes: unclear, left alone


def test_artist_prefix_is_dropped():
    assert tr.clean(f(title="Pepe Link - Vem Menina", artist="Pepe Link"))[0] == {"title": "Vem Menina"}
    assert tr.clean(f(title="A Change Is Gonna Come - Jennifer Lara", artist="Studio One"))[0] == {}   # suffix: not ours to guess


def test_compilation_files_get_their_own_album_artist():
    new, rules = tr.clean(f(title="Vem Menina", artist="Pepe Link", albumartist="Music For Dreams", comp=True, in_compilations=True))
    assert new == {"albumartist": "Pepe Link", "comp": False} and rules == ["compilation"]
    junk = "122 - Wendell Harrison - Peace Of Mind.mp3"
    new, _ = tr.clean(f(title=junk, artist=junk, albumartist="Various Artists", comp=True, in_compilations=True))
    assert new["albumartist"] == "Wendell Harrison"                                       # uses the cleaned artist
    for junk_artist in ("", "08", "[Unknown Artist]"):                      # nothing usable to file it under: left as is
        assert tr.clean(f(title="The Jacksons", artist=junk_artist, comp=True, in_compilations=True)) == ({}, []), junk_artist
    assert tr.clean(f(title="In da Club", artist="50 Cent", comp=True, in_compilations=True))[0]["albumartist"] == "50 Cent"
    assert tr.usable_artist("50 Cent") and not tr.usable_artist("12") and not tr.usable_artist(" ")


def test_clean_is_idempotent():
    start = f(title="Queen - 'Cool Cat - Remastered 2011' (x)", artist="Queen", albumartist="VA", comp=True, in_compilations=True)
    new, _ = tr.clean(start)
    again = dict(start, **new)
    assert tr.clean(again) == ({}, [])
