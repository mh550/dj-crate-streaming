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
        assert ip.match(c, Row(2, "Why You Wanna See My Bad Side", "William Robinson Jr.", 224)).song_id == "m1"   # artist words miss → title-only retry
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
            ("Twain", "The Magician", 4, "verify")]
        assert ext[1]["reason"].startswith("ambiguous: ") and set(ext[1]["reason"][11:].split(", ")) == {"t1", "t2"}
        assert ext[0]["source"] == "https://open.spotify.com/playlist/x" and ext[0]["duration"] == 232
        assert "matched" in rep.table() and "The Weasil" in rep.table()


def test_import_is_idempotent_and_never_removes_or_duplicates():
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        first = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        # Michael removes one entry and adds his own by hand
        c.update_playlist(first.playlist_id, remove_indexes=[1], add_song_ids=["s5"])
        second = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        assert not second.created and second.playlist_id == first.playlist_id and second.added == 1
        assert [e.id for e in c.playlist(first.playlist_id).entries] == ["w1", "s5", "k1"]   # s5 kept, k1 re-added once
        assert store.external_count() == 2
        third = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        assert third.added == 0 and [e.id for e in c.playlist(first.playlist_id).entries] == ["w1", "s5", "k1"]


def test_import_makes_an_existing_private_playlist_public_and_dry_run_touches_nothing():
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        existing = c.create_playlist("Tea tent", ["k1"])
        dry = ip.import_playlist("Tea tent", ROWS, c, store, source="s", dry_run=True)
        assert dry.playlist_id == existing.id and dry.matched == 2 and dry.added == 1   # what it *would* add
        assert [e.id for e in c.playlist(existing.id).entries] == ["k1"] and c.playlist(existing.id).public is False
        assert store.external_count() == 0
        rep = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        assert rep.playlist_id == existing.id and c.playlist(existing.id).public is True
        assert [e.id for e in c.playlist(existing.id).entries] == ["k1", "w1"]
