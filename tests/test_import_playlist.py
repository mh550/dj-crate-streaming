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
        assert not store.is_playlist_imported(existing.id)
        assert "not recorded as imported in crates.db (re-run with --merge to adopt it)" in str(e.value)
        dry = ip.import_playlist("Tea tent", ROWS, c, store, source="s", dry_run=True, merge=True)
        assert dry.playlist_id == existing.id and dry.matched == 2 and dry.added == 1   # what it *would* add
        assert [x.id for x in c.playlist(existing.id).entries] == ["k1"] and store.external_count() == 0
        assert not store.is_playlist_imported(existing.id)                   # a dry run records nothing
        rep = ip.import_playlist("Tea tent", ROWS, c, store, source="s", merge=True)
        assert rep.playlist_id == existing.id and [x.id for x in c.playlist(existing.id).entries] == ["k1", "w1"]
        assert c.playlist(existing.id).public is False                   # not ours: visibility is left alone
        assert store.is_playlist_imported(existing.id)                       # adopted: recorded in crates.db


def test_import_marks_its_playlists_so_reruns_need_no_merge_flag():
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        first = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        # D33: the flag is a crates.db row; no comment ever carries #imported
        assert store.is_playlist_imported(first.playlist_id) and c.playlist(first.playlist_id).public is True
        assert "#imported" not in (c.playlist(first.playlist_id).comment or "")
        again = ip.import_playlist("Tea tent", ROWS, c, store, source="s")       # no merge flag needed
        assert again.playlist_id == first.playlist_id and again.added == 0
        assert "#imported" not in (c.playlist(first.playlist_id).comment or "")


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
        # was: assert twain["song_id"] not in [w["song_id"] for w in store.wanted()]
        # (follow-up ruling: review rows are listed in Wanted with their reason; only retryable ones offer buttons)
        listed = next(w for w in store.wanted() if w["song_id"] == twain["song_id"])
        assert listed["status"] == "review" and listed["reason"].startswith("ambiguous")


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


def test_marker_is_a_token_not_a_substring():
    # M8 Task 4 review: "x#imported" and "#imported-old" are not ours.
    for yes in ("#imported", "mine #IMPORTED #tier:high", "a\n#imported\tb"):
        assert ip.is_imported(yes), yes
    for no in ("", None, "x#imported", "#imported-old", "#imported,", "#importedx"):
        assert not ip.is_imported(no), no


def test_a_comment_marker_without_a_row_is_a_foreign_playlist():
    # D33: only crates.db says "ours"; a real #imported token in the comment (not yet migrated, N2-03) is not enough.
    import pytest
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        existing = c.create_playlist("Tea tent", ["k1"])
        c.update_playlist(existing.id, comment="old #imported")
        with pytest.raises(ip.NameCollision):
            ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        ip.import_playlist("Tea tent", ROWS, c, store, source="s", merge=True)
        assert store.is_playlist_imported(existing.id)
        assert c.playlist(existing.id).comment == "old #imported"            # adopted: the comment is left byte for byte


def test_a_playlist_recreated_under_the_same_name_is_foreign_until_merged():
    # D33/D37: the flag is per playlist id. Deleted in Navidrome and made again by hand (new id): not ours.
    import pytest
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        first = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        c.delete_playlist(first.playlist_id)
        again = c.create_playlist("Tea tent", ["k1"])
        assert again.id != first.playlist_id and store.is_playlist_imported(first.playlist_id)
        with pytest.raises(ip.NameCollision):
            ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        assert [x.id for x in c.playlist(again.id).entries] == ["k1"] and not store.is_playlist_imported(again.id)
        ip.import_playlist("Tea tent", ROWS, c, store, source="s", merge=True)
        assert store.is_playlist_imported(again.id)


def test_merge_never_adopts_another_users_playlist():
    # N2-04 review: getPlaylists lists other users' public playlists too; --merge must not record or write one.
    import pytest
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        theirs = c.create_playlist("Tea tent", ["k1"])
        srv.state.playlists[theirs.id]["owner"] = "amperfy"
        for merge in (False, True):
            with pytest.raises(ip.NameCollision) as e:
                ip.import_playlist("Tea tent", ROWS, c, store, source="s", merge=merge)
            assert "belongs to amperfy" in str(e.value) and "--merge" not in str(e.value)
        assert not store.is_playlist_imported(theirs.id) and store.external_count() == 0
        assert [x.id for x in c.playlist(theirs.id).entries] == ["k1"]


def test_a_rerun_refreshes_the_rows_name_and_an_adoption_says_so():
    # N2-04 review: `imported list` shows the name as last imported; the event tells an adoption from a creation.
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        first = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        c.update_playlist(first.playlist_id, name="Tea tent 26")
        ip.import_playlist("Tea tent 26", ROWS, c, store, source="s2")
        assert [(r["name"], r["source"]) for r in store.imported_playlists()] == [("Tea tent 26", "s")]
        hand = c.create_playlist("Mine", ["k1"])
        ip.import_playlist("Mine", ROWS, c, store, source="s3", merge=True)
        ev = {e["playlist_id"]: e["detail"] for e in store.events() if e["kind"] == "imported"}
        assert ev == {first.playlist_id: "made by import-playlist: s", hand.id: "adopted with --merge: s3"}


def _comment_update_raises(monkeypatch, exc):
    real = SubsonicClient.update_playlist

    def flaky(self, pid, **k):
        if k.get("comment") is not None:
            raise exc
        return real(self, pid, **k)
    monkeypatch.setattr(SubsonicClient, "update_playlist", flaky)


def test_a_comment_write_error_after_the_add_still_records_our_facts_and_reports(monkeypatch):
    # Any error from the comment write (not only CommentNotKept) is handled like Task 3's CommentNotKept.
    import pytest
    from urllib.error import URLError
    from crates.reconcile import CommentNotKept
    from subsonic.client import SubsonicError
    for exc in (SubsonicError(0, "boom"), URLError("reset")):
        with FakeSubsonicServer() as srv:
            _lib(srv)
            c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
            _comment_update_raises(monkeypatch, exc)
            with pytest.raises(CommentNotKept) as e:
                ip.import_playlist("Tea tent", ROWS, c, store, source="s")
            pid = e.value.report.playlist_id
            assert [x.id for x in c.playlist(pid).entries] == ["w1", "k1"]             # the songs are in
            assert store.imported(pid) == {"w1", "k1"}                                  # removed-stays-removed still works
            assert store.is_playlist_imported(pid)                                      # recorded before the comment write
            assert len(store.import_order(pid)) == 4                                    # and the order (N4)
            assert {x["title"] for x in store.external_for_playlist(pid)} == {"Piano Joint (This Kind Of Love)", "The Magician"}
            assert type(exc).__name__ in str(e.value) and e.value.report.table()


def _order(store, pid):
    return [(r["position"], r["song_id"], r["wanted_id"]) for r in store.import_order(pid)]


def test_a_real_import_records_the_spotify_order_and_a_rerun_replaces_it():
    # N4-02: song id for a matched row, the wanted id for a queued one; the newest real import is the order.
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        rep = ip.import_playlist("Tea tent", ROWS[:3], c, store, source="s")     # matched, missing, matched
        [kiwanuka] = store.external_for_playlist(rep.playlist_id)
        assert _order(store, rep.playlist_id) == [(1, "w1", None), (2, None, kiwanuka["song_id"]), (3, "k1", None)]
        again = ip.import_playlist("Tea tent", ROWS, c, store, source="s")      # one more row (ambiguous → review)
        twain = next(r for r in store.external_for_playlist(rep.playlist_id) if r["artist"] == "Twain")
        assert again.playlist_id == rep.playlist_id
        assert _order(store, rep.playlist_id) == [(1, "w1", None), (2, None, kiwanuka["song_id"]), (3, "k1", None),
                                                  (4, None, twain["song_id"])]


def test_a_dry_run_records_no_order():
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        ip.import_playlist("Tea tent", ROWS, c, store, source="s", dry_run=True)
        assert store.db.execute("SELECT COUNT(*) FROM import_order").fetchone()[0] == 0
        rep = ip.import_playlist("Tea tent", ROWS[:3], c, store, source="s")
        ip.import_playlist("Tea tent", ROWS, c, store, source="s", dry_run=True)    # nor replaces one
        assert len(_order(store, rep.playlist_id)) == 3


def test_the_order_records_the_copy_already_in_the_playlist():
    # A matched row switched to a copy that is already there (the `present` switch) names that copy.
    with FakeSubsonicServer() as srv:
        s = srv.state.songs
        s["c3"] = dict(s["s1"], id="c3", title="Peace Of Mind", artist="Wendell Harrison", duration=439, path="Compilations/Le Top/04.mp3")
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        rows = [Row(1, "Peace of Mind", "Wendell Harrison", None, sep="; ")]
        first = ip.import_playlist("PoM", rows, c, store, source="s")
        s["f1"] = dict(s["s1"], id="f1", title="Peace of Mind", artist="Wendell Harrison", duration=439,
                       path="Wendell Harrison/Organic Dream (1981)/04.flac")      # a better-filed copy appears
        assert ip.match(c, rows[0]).song_id == "f1"
        ip.import_playlist("PoM", rows, c, store, source="s")
        assert _order(store, first.playlist_id) == [(1, "c3", None)]


def test_a_track_wanted_by_two_playlists_has_an_order_row_in_each():
    # M9 §1: wanted row × playlist is many-to-many; the wanted row itself keeps only the last slot.
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        a = ip.import_playlist("Tea tent", ROWS[:3], c, store, source="a")
        b = ip.import_playlist("Late set", [Row(1, "Bag Lady", "Erykah Badu", 347, "sp3"),
                                            Row(2, "Piano Joint (This Kind Of Love)", "Michael Kiwanuka", 232, "sp2")],
                               c, store, source="b")
        [ext] = {r["wanted_id"] for r in store.import_order(a.playlist_id) if r["wanted_id"]}
        assert store.external_count() == 1
        assert _order(store, b.playlist_id) == [(1, "k1", None), (2, None, ext)]
        assert [(r["playlist_id"], r["position"]) for r in store.import_order_for(ext)] == sorted(
            [(a.playlist_id, 2), (b.playlist_id, 2)])
