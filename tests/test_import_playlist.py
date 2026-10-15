from sourcing import import_playlist as ip
from sourcing.playlist_sources import Row
from subsonic.client import Song, SubsonicClient
from subsonic.fake_server import FakeSubsonicServer


def song(id, title, artist, duration, path="x/y.flac", album="A"):
    return Song.from_json({"id": id, "title": title, "artist": artist, "album": album, "duration": duration, "path": path})


def test_norm_and_query_words():
    assert ip.norm("Catendé - Live!") == "catendelive"
    assert ip.query_words("Earth, Wind & Fire", "After the Love Has Gone") == ["earth", "wind", "fire", "after", "the", "love", "has", "gone"]
    assert ip.build_query(Row(1, "Piano Joint (This Kind Of Love)", "Michael Kiwanuka", 232)) == "michael kiwanuka piano joint this kind of love"


def test_choose_by_duration_within_tolerance():
    row = Row(1, "After the Love Has Gone", "Earth, Wind & Fire", 278)
    hits = [song("a", "After The Love Has Gone", "Earth, Wind & Fire", 267), song("b", "After the Love Has Gone", "Earth, Wind & Fire", 278)]
    m = ip.choose(row, hits)
    assert m.status == "matched" and m.song_id == "b"


def test_choose_treats_redundant_copies_as_one_track():
    row = Row(1, "The Weasil", "Donald Byrd", 541)
    hits = [song("c1", "The Weasil", "Donald Byrd", 540, path="Compilations/Tea tent/01 - The Weasil.flac"),
            song("c2", "The Weasil", "Donald Byrd", 538, path="Donald Byrd/Fancy Free (1970)/01 - The Weasil.flac")]
    m = ip.choose(row, hits)
    assert m.status == "matched" and m.song_id == "c1"           # nearest duration wins
    hits[1].duration = 540
    assert ip.choose(row, hits).song_id == "c2"                  # tie → the copy not under Compilations/


def test_choose_is_ambiguous_when_two_different_tracks_fit():
    row = Row(1, "The Magician", "Twain", None)                  # report row: no duration
    hits = [song("t1", "The Magician", "Twain", 353, album="Rare Feeling"), song("t2", "The Magician (Live)", "Twain", 300)]
    assert ip.choose(row, hits).status == "matched" and ip.choose(row, hits).song_id == "t1"   # exact normalised title wins
    hits[1].title = "The Magician"; hits[1].album = "Live at X"      # same name, 353 s vs 300 s: two recordings
    m = ip.choose(row, hits)
    assert m.status == "ambiguous" and set(m.candidates) == {"t1", "t2"}
    hits[1].duration = 351                                             # within ±4 s of each other → one track, two copies
    assert ip.choose(row, hits).status == "matched"


def test_choose_without_duration_needs_title_and_lead_artist():
    row = Row(1, "A Change Is Gonna Come", "Jennifer Lara", None)
    assert ip.choose(row, [song("j", "A Change Is Gonna Come - Jennifer Lara", "Studio One", 145)]).status == "matched"
    assert ip.choose(row, [song("k", "A Change Is Gonna Come", "Sam Cooke", 190)]).status == "missing"
    assert ip.choose(row, []).status == "missing"


def test_match_retries_with_title_only_words():
    with FakeSubsonicServer() as srv:
        srv.state.songs["m1"] = dict(srv.state.songs["s1"], id="m1", title="Smokey Robinson - Why You Wanna See My Bad Side.mp3", artist="100 - Smokey Robinson", duration=224)
        c = SubsonicClient(srv.url, "demo", "demo")
        assert ip.match(c, Row(1, "Why You Wanna See My Bad Side", "Smokey Robinson", 224)).song_id == "m1"
        assert ip.match(c, Row(2, "Why You Wanna See My Bad Side", "William Robinson Jr.", 224)).status == "missing"   # title-only retry still needs the lead artist
        srv.state.songs["m2"] = dict(srv.state.songs["s1"], id="m2", title="Catendé - Live", artist="Vinícius de Moraes • Maria Creuza", duration=302)
        assert ip.match(c, Row(4, "Catendé - Live", "Vinicius de Moraes; Toquinho", 302, sep="; ")).song_id == "m2"    # retry finds it; lead artist present
        assert ip.match(c, Row(3, "Piano Joint", "Michael Kiwanuka", 232)).status == "missing"


from crates.store import CrateStore


def _lib(srv):
    s = srv.state.songs
    s["w1"] = dict(s["s1"], id="w1", title="The Weasil", artist="Donald Byrd", duration=540, path="Donald Byrd/Fancy Free (1970)/01 - The Weasil.flac")
    s["w2"] = dict(s["s1"], id="w2", title="The Weasil", artist="Donald Byrd", duration=538, path="Compilations/Tea tent/01 - The Weasil.flac")
    s["k1"] = dict(s["s1"], id="k1", title="Bag Lady", artist="Erykah Badu", duration=347)
    s["t1"] = dict(s["s1"], id="t1", title="The Magician", artist="Twain", duration=353, album="Rare Feeling")
    s["t2"] = dict(s["s1"], id="t2", title="The Magician", artist="Twain", duration=300, album="Live")


ROWS = [Row(1, "The Weasil", "Donald Byrd", 541, "sp1"), Row(2, "Piano Joint (This Kind Of Love)", "Michael Kiwanuka", 232, "sp2"),
        Row(3, "Bag Lady", "Erykah Badu", 347, "sp3"), Row(4, "The Magician", "Twain", None, "sp4")]


def test_import_creates_public_playlist_in_order_and_queues_the_rest():
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        rep = ip.import_playlist("Tea tent", ROWS, c, store, source="https://open.spotify.com/playlist/x")
        assert rep.created and rep.matched == 2 and rep.wanted == 1 and rep.ambiguous == 1 and rep.added == 2
        pl = c.playlist(rep.playlist_id)
        assert pl.name == "Tea tent" and pl.public is True and [e.id for e in pl.entries] == ["w1", "k1"]
        ext = store.external_for_playlist(rep.playlist_id)
        assert [(r["artist"], r["title"], r["position"], r["status"]) for r in ext] == [
            ("Michael Kiwanuka", "Piano Joint (This Kind Of Love)", 2, "needs_source"),
            ("Twain", "The Magician", 4, "review")]
        why, _, ids = ext[1]["reason"].partition("): ")
        assert why == "ambiguous (several versions" and set(ids.split(", ")) == {"t1", "t2"}
        assert ext[0]["source"] == "https://open.spotify.com/playlist/x" and ext[0]["duration"] == 232
        assert "matched" in rep.table() and "The Weasil" in rep.table()


def test_import_is_idempotent_and_never_removes_or_duplicates():
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        first = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        # Michael removes one entry and adds his own by hand: both edits must survive every re-run
        c.update_playlist(first.playlist_id, remove_indexes=[1], add_song_ids=["s5"])
        second = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        assert not second.created and second.playlist_id == first.playlist_id and second.added == 0
        assert [e.id for e in c.playlist(first.playlist_id).entries] == ["w1", "s5"]        # k1 stays removed
        assert store.external_count() == 2
        third = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        assert third.added == 0 and [e.id for e in c.playlist(first.playlist_id).entries] == ["w1", "s5"]


def test_import_refuses_a_foreign_playlist_unless_merge_and_never_publishes_it():
    # Live 2026-10-14: "Tea tent" silently merged into last night's folder playlist and flipped it public.
    import pytest
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        existing = c.create_playlist("Tea tent", ["k1"])                 # made by hand: no marker in its comment
        with pytest.raises(ip.NameCollision) as e:
            ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        assert e.value.playlist_id == existing.id
        assert [x.id for x in c.playlist(existing.id).entries] == ["k1"] and store.external_count() == 0
        dry = ip.import_playlist("Tea tent", ROWS, c, store, source="s", dry_run=True, merge=True)
        assert dry.playlist_id == existing.id and dry.matched == 2 and dry.added == 1   # what it *would* add
        assert [x.id for x in c.playlist(existing.id).entries] == ["k1"] and store.external_count() == 0
        rep = ip.import_playlist("Tea tent", ROWS, c, store, source="s", merge=True)
        assert rep.playlist_id == existing.id and [x.id for x in c.playlist(existing.id).entries] == ["k1", "w1"]
        assert c.playlist(existing.id).public is False                   # not ours: visibility is left alone


def test_import_marks_its_playlists_so_reruns_need_no_merge_flag():
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        first = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        assert "#imported" in (c.playlist(first.playlist_id).comment or "") and c.playlist(first.playlist_id).public is True
        again = ip.import_playlist("Tea tent", ROWS, c, store, source="s")       # no merge flag needed
        assert again.playlist_id == first.playlist_id and again.added == 0


def test_rerun_does_not_reset_an_ambiguous_row_michael_resolved():
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        rep = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        twain = next(r for r in store.external_for_playlist(rep.playlist_id) if r["artist"] == "Twain")
        assert twain["status"] == "review"
        store.set_external_status(twain["song_id"], "ok", "picked t1 by hand"); store.commit()
        ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        assert store.external(twain["song_id"])["status"] == "ok"


def test_degenerate_queries_never_match_by_duration_alone():
    with FakeSubsonicServer() as srv:
        c = SubsonicClient(srv.url, "demo", "demo")
        assert ip.build_query(Row(1, "!!", "?", 501)) == ""
        assert ip.match(c, Row(1, "!!", "?", 501)).status == "missing"            # empty query must not list everything
        assert ip.match(c, Row(2, "!!", "Chic", 501)).status == "missing"         # artist-only query: s1 has the length but not the title


def test_match_reads_past_the_first_twenty_hits():
    with FakeSubsonicServer() as srv:
        for i in range(25):
            srv.state.songs[f"L{i}"] = dict(srv.state.songs["s1"], id=f"L{i}", title="Love", artist="Someone", duration=100 + i)
        c = SubsonicClient(srv.url, "demo", "demo")
        assert ip.match(c, Row(1, "Love", "Someone", 124)).song_id == "L24"


def test_unresolved_comma_artist_is_noted_and_resolution_happens_before_any_write():
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        rows = [Row(1, "Nope", "Earth, Wind & Fire", 100, "sp9")]
        rep = ip.import_playlist("EWF", rows, c, store, source="s", resolve=lambda sid: None)
        assert store.external_for_playlist(rep.playlist_id)[0]["artist"] == "Earth"
        assert any("Earth, Wind & Fire" in n and "Earth" in n for n in rep.notes) and rep.notes[0] in rep.table()
        rep2 = ip.import_playlist("EWF2", rows, c, store, source="s", resolve=lambda sid: "Earth, Wind & Fire")
        assert rep2.notes == []


def test_table_says_whether_the_playlist_was_created_or_already_existed():
    # Live 2026-10-14: "Tea tent" silently merged into last night's folder playlist of the same name.
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        assert "created playlist" in ip.import_playlist("Tea tent", ROWS, c, store, source="s").table()
        again = ip.import_playlist("Tea tent", ROWS, c, store, source="s").table()
        assert "updated existing playlist" in again and "2 entries were already there" in again


def test_title_only_retry_accepts_an_untagged_artist_when_the_length_fits():
    # Live 2026-10-14: "[Unknown Artist]/[Unknown Album]/The Good Wine.mp3" (125 s) is Alabaster DePlume's
    # 126 s track; a placeholder artist is no evidence against the match, but the length must agree.
    with FakeSubsonicServer() as srv:
        srv.state.songs["u1"] = dict(srv.state.songs["s1"], id="u1", title="The Good Wine", artist="[Unknown Artist]", album="[Unknown Album]", duration=125)
        c = SubsonicClient(srv.url, "demo", "demo")
        assert ip.match(c, Row(1, "The Good Wine", "Alabaster DePlume", 126)).song_id == "u1"
        assert ip.match(c, Row(2, "The Good Wine", "Alabaster DePlume", None)).status == "missing"
        assert ip.match(c, Row(3, "The Good Wine", "Alabaster DePlume", 200)).status == "missing"



def test_title_must_be_the_same_song_not_a_substring():
    # Opus review 2026-10-14 (proved): "Love" matched "Love and Happiness".
    assert ip.choose(Row(1, "Love", "Al Green", None, sep="; "), [song("h", "Love and Happiness", "Al Green", 300)]).status == "ambiguous"
    m = ip.choose(Row(1, "Love", "Al Green", None, sep="; "), [song("h", "Love and Happiness", "Al Green", 300)])
    assert m.why == "title differs" and m.candidates == ["h"]


def test_noise_that_does_not_change_the_recording_still_matches():
    cases = [
        (Row(1, "Fascination", "Everything But The Girl", None), song("f", "Fascination - 2012 Remaster", "Everything But The Girl", 200)),
        (Row(1, "Arrow Through Me", "Wings", None), song("a", "Arrow Through Me - Remastered 1993", "Wings", 200)),
        (Row(1, "Why You Wanna See My Bad Side", "Smokey Robinson", None),
         song("m", "100 - Smokey Robinson - Why You Wanna See My Bad Side.mp3", "100 - Smokey Robinson - Why You Wanna See My Bad Side.mp3", 224)),
        (Row(1, "A Change Is Gonna Come", "Jennifer Lara", None), song("j", "A Change Is Gonna Come - Jennifer Lara", "Studio One", 145)),
        (Row(1, "Vem Menina", "Pepe Link", None), song("p", "Pepe Link - Vem Menina", "Pepe Link", 300)),
        (Row(1, "Dudley Boyz", "Your Old Droog", None), song("d", "Dudley Boyz (feat. Action Bronson)", "Your Old Droog", 150)),
    ]
    for row, hit in cases:
        assert ip.choose(row, [hit]).status == "matched", hit.title


def test_known_length_far_off_is_not_a_match():
    # Opus review (proved): a 210 s row matched a 612 s copy through the title fallback.
    m = ip.choose(Row(1, "Good Times", "Chic", 210), [song("g", "Good Times", "Chic", 612)])
    assert m.status == "ambiguous" and m.why == "length differs" and m.candidates == ["g"]
    assert ip.choose(Row(1, "Good Times", "Chic", 210), [song("x", "Le Freak", "Chic", 210)]).status == "missing"


def test_rerun_respects_a_playlist_michael_made_private():
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        first = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        c.update_playlist(first.playlist_id, public=False)
        ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        assert c.playlist(first.playlist_id).public is False


def test_a_later_match_retires_the_wanted_row():
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        first = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        kiwa = next(r for r in store.external_for_playlist(first.playlist_id) if r["artist"] == "Michael Kiwanuka")
        srv.state.songs["kw"] = dict(srv.state.songs["s1"], id="kw", title="Piano Joint (This Kind Of Love)", artist="Michael Kiwanuka", duration=232)
        again = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        assert again.added == 1 and "kw" in [e.id for e in c.playlist(first.playlist_id).entries]
        row = store.external(kiwa["song_id"])
        assert row["status"] == "ok" and row["reason"] == "in library: kw"


def test_fetch_leaves_review_rows_alone():
    # Opus review (proved): fetch on an ambiguous row failed it, and it re-entered the wanted queue.
    from pathlib import Path
    from sourcing.fetch import fetch
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        rep = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        twain = next(r for r in store.external_for_playlist(rep.playlist_id) if r["artist"] == "Twain")
        r = fetch(twain["song_id"], store=store, slskd=None, navidrome=c, reconciler=None,
                  music_root=Path("/nonexistent"), downloads_root=Path("/nonexistent"), approve=False)
        assert r.status == "review" and "pick" in r.reason
        assert store.external(twain["song_id"])["status"] == "review"
        assert twain["song_id"] not in [w["song_id"] for w in store.wanted()]


def test_copies_with_junk_tags_collapse_and_the_cleanly_tagged_copy_wins():
    # Live 2026-10-14: four files of Wendell Harrison "Peace of Mind" (438-439 s), two tagged
    # "122 - Wendell Harrison - Peace Of Mind.mp3" as both artist and title.
    row = Row(1, "Peace of Mind", "Wendell Harrison", None, sep="; ")
    junk = "122 - Wendell Harrison - Peace Of Mind.mp3"
    hits = [song("j1", junk, junk, 438, path="Compilations/pure soul 128/04.mp3"),
            song("c3", "Peace Of Mind", "Wendell Harrison", 439, path="Compilations/Le Top/04.mp3"),
            song("f1", "Peace of Mind", "Wendell Harrison", 439, path="Wendell Harrison/Organic Dream (1981)/04.flac")]
    m = ip.choose(row, hits)
    assert m.status == "matched" and m.song_id == "f1" and set(m.candidates) == {"j1", "c3", "f1"}


def test_rerun_never_appends_a_second_copy_of_a_track_already_in_the_playlist():
    with FakeSubsonicServer() as srv:
        s = srv.state.songs
        s["c3"] = dict(s["s1"], id="c3", title="Peace Of Mind", artist="Wendell Harrison", duration=439, path="Compilations/Le Top/04.mp3")
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        rows = [Row(1, "Peace of Mind", "Wendell Harrison", None, sep="; ")]
        first = ip.import_playlist("PoM", rows, c, store, source="s")
        s["f1"] = dict(s["s1"], id="f1", title="Peace of Mind", artist="Wendell Harrison", duration=439,
                       path="Wendell Harrison/Organic Dream (1981)/04.flac")      # a better-filed copy appears
        again = ip.import_playlist("PoM", rows, c, store, source="s")
        assert again.added == 0 and [e.id for e in c.playlist(first.playlist_id).entries] == ["c3"]
