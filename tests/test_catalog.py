"""S3-02: `GET /api/catalog/search?q=&kind=album|track` searches MusicBrainz releases or recordings through a
small provider interface (`sourcing/catalog.py`). Each hit names its provider and that provider's ids, and says
whether the library already has it (`inLibrary`). Nothing reaches the network: MusicBrainz answers from the
captured fixtures through a stub opener, Navidrome is the fake."""
import io
import json
import urllib.error
import urllib.parse

import pytest

from crates.service import Config, CrateApp, CrateServer
from crates.store import CrateStore
from sourcing import catalog
from sourcing.catalog import PROVIDERS, CatalogBusy, Hit, MusicBrainzCatalog
from sourcing.musicbrainz import MusicBrainz
from subsonic.fake_server import FakeSubsonicServer
from tests.helpers import FIXTURES
from tests.test_service import get

AL_GREEN_CD = "3c9a52ee-ee0a-3362-a563-d9d28b02a53e"
CALL_ME = "197991db"                                         # "I'm Still in Love With You & Call Me", 18 tracks


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class Opener:
    """`MusicBrainz(opener=…)`: a release search answers the Al Green fixture, a recording search the Double
    Exposure one; `error` (an exception) is raised for every request instead. Records each (path, query)."""

    def __init__(self, error=None):
        self.error, self.asked = error, []

    def __call__(self, req, timeout=None):
        u = urllib.parse.urlsplit(req.full_url)
        path = u.path.removeprefix("/ws/2/")
        self.asked.append((path, urllib.parse.parse_qs(u.query).get("query", [None])[0]))
        if self.error is not None:
            raise self.error
        body = {"release": "musicbrainz_release_search_al-green.json",
                "recording": "musicbrainz_search.sample.json"}[path]
        return io.BytesIO((FIXTURES / body).read_bytes())


def busy():
    return urllib.error.HTTPError("https://musicbrainz.org/ws/2/release", 503, "busy", {}, io.BytesIO(b"{}"))


def mb(opener):
    return MusicBrainz(opener=opener, sleep=lambda s: None, min_interval_s=0)


# --- the MusicBrainz provider

def test_an_album_search_is_one_release_search_and_its_ten_releases_are_hits():
    opener = Opener()
    hits = MusicBrainzCatalog(mb(opener)).search("Al Green I'm Still in Love", "album")
    # no dash: the words on the title and the artist, unquoted (a phrase on the title alone finds nothing on
    # MusicBrainz when the artist's words are in it)
    assert opener.asked == [("release", "release:(Al Green I'm Still in Love) OR artist:(Al Green I'm Still in Love)")]
    assert len(hits) == 10 and all(isinstance(h, Hit) for h in hits)
    first = hits[0]
    assert first == Hit(provider="musicbrainz", kind="album", title="I’m Still in Love With You", artist="Al Green",
                        year=1993, track_count=9, length_s=None, format="CD", ids={"mbReleaseId": AL_GREEN_CD},
                        in_library=None)
    assert [h.year for h in hits] == [1993, 2009, 2019, 2009, 2022, 2003, 1972, 1972, None, None]
    assert [h.track_count for h in hits] == [9] * 5 + [11] + [9] * 3 + [18]


def test_an_artist_dash_album_query_is_split_into_artist_and_release():
    opener = Opener()
    MusicBrainzCatalog(mb(opener)).search('Al Green - I\'m Still "in" Love', "album")
    assert opener.asked == [("release", 'artist:"Al Green" AND release:"I\'m Still \\"in\\" Love"')]


def test_a_track_search_asks_recordings_and_parses_them():
    opener = Opener()
    hits = MusicBrainzCatalog(mb(opener)).search("Double Exposure - My Love Is Free", "track")
    assert opener.asked == [("recording", 'artist:"Double Exposure" AND recording:"My Love Is Free"')]
    recordings = fixture("musicbrainz_search.sample.json")["recordings"]
    assert len(hits) == len(recordings)
    assert hits[0] == Hit(provider="musicbrainz", kind="track", title="My Love Is Free", artist="Double Exposure",
                          year=1976, track_count=None, length_s=570.0, format=None,
                          ids={"mbRecordingId": recordings[0]["id"]}, in_library=None)
    no_date = next(h for h in hits if h.ids["mbRecordingId"].startswith("af09e6b5"))
    assert no_date.year is None and no_date.length_s == 582.8


def test_a_plain_track_query_is_its_words_on_the_title_and_the_artist():
    opener = Opener()
    MusicBrainzCatalog(mb(opener)).search("  Double Exposure My Love Is Free ", "track")
    assert opener.asked == [("recording", "recording:(Double Exposure My Love Is Free) OR "
                                          "artist:(Double Exposure My Love Is Free)")]


def test_a_plain_querys_upper_case_operators_are_words():
    opener = Opener()
    MusicBrainzCatalog(mb(opener)).search("10cc I'M NOT IN LOVE AND OR", "album")
    words = "10cc I'M not IN LOVE and or"
    assert opener.asked == [("release", f"release:({words}) OR artist:({words})")]


def test_a_plain_querys_lucene_characters_are_escaped():
    opener = Opener()
    MusicBrainzCatalog(mb(opener)).search('AC/DC (live) "Back" in: Black!', "album")
    words = 'AC\\/DC \\(live\\) \\"Back\\" in\\: Black\\!'
    assert opener.asked == [("release", f"release:({words}) OR artist:({words})")]


def test_another_kind_is_refused_before_musicbrainz_is_asked():
    opener = Opener()
    with pytest.raises(ValueError):
        MusicBrainzCatalog(mb(opener)).search("x", "playlist")
    assert opener.asked == []


@pytest.mark.parametrize("error", [busy(), urllib.error.URLError("no route")])
def test_musicbrainz_failing_is_catalog_busy(error):
    with pytest.raises(CatalogBusy, match="^MusicBrainz is busy, try again$"):
        MusicBrainzCatalog(mb(Opener(error))).search("x", "album")


def test_the_registry_has_musicbrainz_only_and_spotify_is_named_as_not_yet():
    assert PROVIDERS == {"musicbrainz": MusicBrainzCatalog}
    doc = catalog.__doc__
    assert "Spotify" in doc and "scripts/capture_spotify.py" in doc


# --- inLibrary

def library_song(fake, sid, title, artist, album, duration, album_artist=None):
    """A song as Navidrome 0.64 sends it (fixtures/navidrome_playlist_song_search3.sample.json): the album artist
    is `displayAlbumArtist` and `albumArtists`, never `albumArtist`."""
    album_artist = album_artist or artist
    fake.state.songs[sid] = dict(fake.state.songs["s1"], id=sid, title=title, artist=artist, album=album,
                                 duration=duration, path=f"{artist}/{sid}.flac", displayAlbumArtist=album_artist,
                                 albumArtists=[{"id": "ar-" + sid, "name": album_artist}])


@pytest.fixture
def navidrome():
    with FakeSubsonicServer() as fake:
        from subsonic.client import SubsonicClient
        yield fake, SubsonicClient(fake.url, "demo", "demo")


def test_an_album_the_library_has_by_name_and_artist_is_in_library(navidrome):
    fake, client = navidrome
    library_song(fake, "ag5", "Simply Beautiful", "Al Green", "I'm Still in Love With You", 256)
    hits = catalog.search([MusicBrainzCatalog(mb(Opener()))], "Al Green - Still in Love", "album", client)
    assert [h.in_library for h in hits] == [True] * 9 + [False]        # "… & Call Me" is another album
    assert hits[-1].ids["mbReleaseId"].startswith(CALL_ME)


def test_an_album_by_another_artist_or_of_another_name_is_not_in_library(navidrome):
    fake, client = navidrome
    library_song(fake, "x1", "Simply Beautiful", "Al Greene", "I'm Still in Love With You", 256)
    library_song(fake, "x2", "Simply Beautiful", "Al Green", "I'm Still in Love With You (Live)", 256)
    hits = catalog.search([MusicBrainzCatalog(mb(Opener()))], "Al Green - Still in Love", "album", client)
    assert {h.in_library for h in hits} == {False}


def test_a_track_is_in_library_when_import_playlist_would_match_it(navidrome):
    fake, client = navidrome
    library_song(fake, "dx1", "My Love Is Free", "Double Exposure", "Ten Percent", 571)      # the 9:30 mix
    hits = catalog.search([MusicBrainzCatalog(mb(Opener()))], "Double Exposure - My Love Is Free", "track", client)
    inside = [h.length_s for h in hits if h.in_library]
    assert inside and all(abs(s - 571) <= 4 for s in inside)                 # same version: the same length
    assert any(h.in_library is False for h in hits)                         # the 3-minute edits are not


def test_a_compilation_is_in_library_by_its_album_artist(navidrome):
    """Various Artists: each song's `artist` is the track's, the album artist is the release's credit."""
    fake, client = navidrome
    library_song(fake, "va1", "Love Is the Message", "MFSB", "Philly Sound", 420, album_artist="Various Artists")

    class Compilation:
        @staticmethod
        def search(q, kind):
            return [Hit("stub", "album", "Philly Sound", "Various Artists", 1999, 12, None, None, {"x": "1"})]
    [hit] = catalog.search([Compilation], "Philly Sound", "album", client)
    assert hit.in_library is True


class Counting:
    """A Navidrome that has nothing and counts its searches."""

    def __init__(self):
        self.asked = []

    def search_songs(self, query, count=20, offset=0):
        self.asked.append((query, count, offset))
        return []


def test_a_track_search_asks_navidrome_each_question_once():
    nd = Counting()
    hits = catalog.search([MusicBrainzCatalog(mb(Opener()))], "Double Exposure - My Love Is Free", "track", nd)
    assert len(hits) == 10 and {h.in_library for h in hits} == {False}
    assert len(nd.asked) == len(set(nd.asked)) == 2          # artist + title, then the title alone (match's retry)


def stub_hits(*hits):
    class Stub:
        @staticmethod
        def search(q, kind):
            return list(hits)
    return Stub


def test_hits_the_library_cannot_be_asked_about_are_unknown_not_false():
    """No artist (any same-title song would pass), or names that fold to nothing ("÷", "!!!"): unknown."""
    nd = Counting()
    hits = catalog.search([stub_hits(Hit("stub", "track", "My Love Is Free", "", None, None, 570.0, None, {}),
                                     Hit("stub", "album", "÷", "Ed Sheeran", 2017, 16, None, None, {}),
                                     Hit("stub", "album", "Louden Up Now", "!!!", 2004, 10, None, None, {}),
                                     Hit("stub", "album", "X", "Y", None, 1, None, None, {}))],
                          "q", "album", nd)
    assert [h.in_library for h in hits] == [None] * 4 and nd.asked == []


@pytest.mark.parametrize("error", [KeyError("subsonic-response"), TypeError("odd"),
                                   __import__("subsonic.client").client.SubsonicError(40, "Wrong username")])
def test_any_navidrome_failure_is_unknown(error):
    class Odd:
        def search_songs(self, *a, **k):
            raise error
    hits = catalog.search([MusicBrainzCatalog(mb(Opener()))], "Al Green - Still in Love", "album", Odd())
    assert {h.in_library for h in hits} == {None}


@pytest.mark.parametrize("date, year", [("1972-10-23", 1972), ("19", None), ("0000", None), ("", None), (None, None)])
def test_a_year_is_four_digits_or_none(date, year):
    assert catalog._year(date) == year


def test_an_en_dash_splits_artist_and_title_too():
    opener = Opener()
    MusicBrainzCatalog(mb(opener)).search("Al Green – Still in Love", "album")
    assert opener.asked == [("release", 'artist:"Al Green" AND release:"Still in Love"')]


def test_navidrome_unreachable_leaves_in_library_unknown_for_every_hit():
    class Down:
        calls = 0

        def search_songs(self, *a, **k):
            Down.calls += 1
            raise OSError("http://nd/rest/search3?u=demo&t=TOKEN&s=SALT refused")
    for kind, q in (("album", "Al Green - Still in Love"), ("track", "Double Exposure - My Love Is Free")):
        Down.calls = 0
        hits = catalog.search([MusicBrainzCatalog(mb(Opener()))], q, kind, Down())
        assert hits and {h.in_library for h in hits} == {None}
        assert Down.calls == 1                                               # asked once, not once per hit


def test_one_navidrome_question_per_distinct_album(navidrome):
    fake, client = navidrome
    asked = []
    search = client.search_songs
    client.search_songs = lambda *a, **k: asked.append(a) or search(*a, **k)
    catalog.search([MusicBrainzCatalog(mb(Opener()))], "Al Green - Still in Love", "album", client)
    # Ten releases, two albums ("I'm Still in Love With You" in every spelling, and "… & Call Me"), none in the
    # library: each album asked with its artist's words, then by its title alone; no question twice.
    assert len(asked) == len(set(asked)) == 4


# --- the endpoint

@pytest.fixture
def api():
    """A fake Navidrome and the app with a `MusicBrainz` on `Opener` (the `svc` shape of tests/test_service.py)."""
    made = []

    def make(error=None, subsonic_url=None):
        opener = Opener(error)
        fake = FakeSubsonicServer().__enter__()
        cfg = Config(subsonic_url=subsonic_url or fake.url, username="demo", password="demo", db_path=":memory:",
                     port=0)
        app = CrateApp(cfg, store=CrateStore(), musicbrainz=mb(opener))
        srv = CrateServer(app).__enter__()
        made.append((fake, srv))
        return fake, srv, opener
    yield make
    for fake, srv in made:
        srv.__exit__(None, None, None)
        fake.__exit__(None, None, None)


def search(srv, **q):
    s, _, body = get(srv.url + "/api/catalog/search?" + urllib.parse.urlencode(q))
    return s, body


def test_an_album_search_answers_200_with_camel_case_hits(api):
    fake, srv, opener = api()
    library_song(fake, "ag5", "Simply Beautiful", "Al Green", "I'm Still in Love With You", 256)
    s, body = search(srv, q="Al Green I'm Still in Love", kind="album")
    assert s == 200 and list(body) == ["hits"]
    assert len(body["hits"]) == 10
    assert body["hits"][0] == {"provider": "musicbrainz", "kind": "album", "title": "I’m Still in Love With You",
                               "artist": "Al Green", "year": 1993, "trackCount": 9, "lengthS": None, "format": "CD",
                               "ids": {"mbReleaseId": AL_GREEN_CD}, "inLibrary": True}
    assert opener.asked == [("release", "release:(Al Green I'm Still in Love) OR artist:(Al Green I'm Still in Love)")]


def test_a_track_search_answers_200_with_recordings(api):
    fake, srv, opener = api()
    s, body = search(srv, q="Double Exposure - My Love Is Free", kind="track")
    assert s == 200
    hit = body["hits"][0]
    assert {k: hit[k] for k in ("provider", "kind", "title", "artist", "year", "trackCount", "lengthS",
                                "inLibrary")} == {
        "provider": "musicbrainz", "kind": "track", "title": "My Love Is Free", "artist": "Double Exposure",
        "year": 1976, "trackCount": None, "lengthS": 570.0, "inLibrary": False}
    assert set(hit["ids"]) == {"mbRecordingId"}


@pytest.mark.parametrize("q", [{"q": "Al Green"}, {"q": "Al Green", "kind": "playlist"},
                               {"q": "Al Green", "kind": ""}])
def test_kind_missing_or_other_is_400(api, q):
    fake, srv, opener = api()
    assert search(srv, **q) == (400, {"error": "kind must be album or track"})
    assert opener.asked == []


@pytest.mark.parametrize("q", [{"kind": "album"}, {"q": "", "kind": "album"}, {"q": "   ", "kind": "track"}])
def test_an_empty_query_is_400(api, q):
    fake, srv, opener = api()
    assert search(srv, **q) == (400, {"error": "q is required"})
    assert opener.asked == []


def test_musicbrainz_busy_after_the_clients_retries_is_503(api):
    fake, srv, opener = api(error=busy())
    assert search(srv, q="Al Green", kind="album") == (503, {"error": "MusicBrainz is busy, try again"})
    assert len(opener.asked) == 4                            # the client's retries (MusicBrainz(retries=4)), not ours


def test_navidrome_down_is_200_with_in_library_null(api):
    fake, srv, opener = api(subsonic_url="http://127.0.0.1:9")
    s, body = search(srv, q="Al Green - Still in Love", kind="album")
    assert s == 200 and len(body["hits"]) == 10
    assert {h["inLibrary"] for h in body["hits"]} == {None}


def test_a_registered_provider_is_searched_too_without_a_new_endpoint(api, monkeypatch):
    class Stub:
        """A second provider: a class with `from_app` and `search`, registered by name."""
        @classmethod
        def from_app(cls, app):
            return cls()

        def search(self, q, kind):
            return [Hit(provider="stub", kind=kind, title=f"{q} (stub)", artist="Al Green", year=None,
                        track_count=None, length_s=None, format=None, ids={"stubId": "s-1"})]
    monkeypatch.setitem(PROVIDERS, "stub", Stub)
    fake, srv, opener = api()
    s, body = search(srv, q="Al Green - Still in Love", kind="album")
    assert s == 200
    assert [h["provider"] for h in body["hits"]] == ["musicbrainz"] * 10 + ["stub"]
    assert body["hits"][-1]["ids"] == {"stubId": "s-1"} and body["hits"][-1]["inLibrary"] is False
