"""S3-01: `POST /api/requests {"url": …}` turns a Spotify track, album or playlist link into a request and answers
with the request and its rows. The app is built like tests/test_service.py's `svc`, with the Spotify fetch injected
(`CrateApp(..., fetch_entity=…)`), so nothing reaches the network."""
import http.client
import json
import urllib.error

import pytest

from crates.service import Config, CrateApp, CrateServer
from crates.store import CrateStore
from sourcing.requests import UnknownLink, parse_link
from subsonic.fake_server import FakeSubsonicServer
from tests.helpers import FIXTURES
from tests.test_service import post

ALBUM_ID = "2nTlIPIQ7fHOnNN7BRch0Z"
ALBUM_URL = f"https://open.spotify.com/album/{ALBUM_ID}"
PLAYLIST_URL = "https://open.spotify.com/playlist/37i9dQZF1DXtea"


def album():
    return json.loads((FIXTURES / "spotify_embed_album_al-green-still-in-love.json").read_text())


def track():
    """One track of the album as a track embed shows it: its own `name` and `artists`, `type: track`."""
    t = album()["trackList"][2]
    return {**t, "type": "track", "name": t["title"], "artists": [{"name": t["subtitle"]}]}


def playlist():
    """Tea tent, cut to its first three tracks (none of them is in the fake library)."""
    tea = json.loads((FIXTURES / "spotify_embed_tea-tent-1.json").read_text())
    return {**tea, "trackList": tea["trackList"][:3]}


class Spotify:
    """The injected fetch: answers `entity` (or raises it) and remembers every URL asked."""

    def __init__(self, entity):
        self.entity, self.calls = entity, []

    def __call__(self, url):
        self.calls.append(url)
        if isinstance(self.entity, BaseException):
            raise self.entity
        return self.entity


@pytest.fixture
def api():
    def make(entity):
        spotify = Spotify(entity)
        fake = FakeSubsonicServer().__enter__()
        cfg = Config(subsonic_url=fake.url, username="demo", password="demo", db_path=":memory:", port=0)
        app = CrateApp(cfg, store=CrateStore(), fetch_entity=spotify)
        srv = CrateServer(app).__enter__()
        made.append((fake, srv))
        return fake, app, srv, spotify
    made = []
    yield make
    for fake, srv in made:
        srv.__exit__(None, None, None)
        fake.__exit__(None, None, None)


def test_an_album_url_answers_201_with_the_request_and_its_nine_rows(api):
    fake, app, srv, spotify = api(album())
    s, body = post(srv.url + "/api/requests", {"url": ALBUM_URL})
    assert s == 201
    req = body["request"]
    assert {k: req[k] for k in ("kind", "artist", "album", "year", "mbReleaseId", "status")} == {
        "kind": "album", "artist": "Al Green", "album": "I'm Still in Love With You", "year": None,
        "mbReleaseId": None, "status": "open"}
    assert isinstance(req["id"], int) and isinstance(req["createdAt"], float)
    rows = body["rows"]
    assert [r["trackNo"] for r in rows] == list(range(1, 10))
    assert [r["id"] for r in rows] == [f"ext-{i}" for i in range(1, 10)]
    assert rows[0] == {"id": "ext-1", "trackNo": 1, "artist": "Al Green", "title": "I'm Still In Love With You",
                       "album": "I'm Still in Love With You", "year": None, "durationS": 196, "status": "needs_source",
                       "reason": None, "librarySongId": None, "mbRecordingId": None}
    assert rows[5]["title"] == "Oh ,Pretty Woman"
    assert spotify.calls == [ALBUM_URL]                       # one Spotify fetch per call
    assert app.store.request(req["id"])["source"] == ALBUM_URL


def test_the_same_album_again_answers_200_with_the_existing_request_and_no_new_rows(api):
    fake, app, srv, spotify = api(album())
    s1, first = post(srv.url + "/api/requests", {"url": ALBUM_URL})
    s2, again = post(srv.url + "/api/requests", {"url": f"https://open.spotify.com/intl-de/album/{ALBUM_ID}?si=x1"})
    s3, uri = post(srv.url + "/api/requests", {"url": f"spotify:album:{ALBUM_ID}"})
    assert (s1, s2, s3) == (201, 200, 200)
    assert again == first == uri
    assert len(app.store.requests()) == 1 and app.store.external_count() == 9
    assert spotify.calls == [ALBUM_URL] * 3                   # every form asks the same embed


@pytest.mark.parametrize("url", ["https://open.spotify.com/track/" + "3cyGx6m1IIFxRnxEOGaAb2",
                                 "spotify:track:3cyGx6m1IIFxRnxEOGaAb2"])
def test_a_track_link_is_a_track_request_with_one_row(api, url):
    fake, app, srv, spotify = api(track())
    s, body = post(srv.url + "/api/requests", {"url": url})
    assert s == 201 and body["request"]["kind"] == "track" and body["request"]["album"] is None
    [row] = body["rows"]
    assert row["title"] == track()["name"] and row["artist"] == "Al Green" and row["trackNo"] is None
    assert spotify.calls == ["https://open.spotify.com/track/3cyGx6m1IIFxRnxEOGaAb2"]


def test_a_playlist_url_is_the_merge_import_plus_a_playlist_request(api):
    fake, app, srv, spotify = api(playlist())
    s, body = post(srv.url + "/api/requests", {"url": PLAYLIST_URL})
    assert s == 201 and spotify.calls == [PLAYLIST_URL]
    req = body["request"]
    assert req["kind"] == "playlist" and req["album"] == "Tea tent" and req["status"] == "open"
    pid = body["playlist"]["id"]
    assert body["playlist"] == {"id": pid, "name": "Tea tent", "matched": 0, "wanted": 3, "ambiguous": 0}
    assert app.store.is_playlist_imported(pid)
    wanted = [o["wanted_id"] for o in app.store.import_order(pid)]
    assert [r["id"] for r in body["rows"]] == wanted and len(wanted) == 3
    assert [r["title"] for r in body["rows"]] == [t["title"] for t in playlist()["trackList"]]
    s, again = post(srv.url + "/api/requests", {"url": PLAYLIST_URL})
    assert s == 200 and again["request"] == req and app.store.external_count() == 3


def test_a_playlist_url_adopts_a_same_named_playlist_as_merge_does(api):
    fake, app, srv, spotify = api(playlist())
    existing = app.api.create_playlist("Tea tent", [])            # made by hand: not import-playlist's
    s, body = post(srv.url + "/api/requests", {"url": PLAYLIST_URL})
    assert s == 201 and body["playlist"]["id"] == existing.id
    assert app.store.is_playlist_imported(existing.id)


def test_another_users_playlist_of_that_name_is_409_and_nothing_is_recorded(api):
    fake, app, srv, spotify = api(playlist())
    fake.state.playlists["pl-9"] = {"id": "pl-9", "name": "Tea tent", "comment": "", "owner": "someone",
                                    "public": True, "songs": []}
    before = json.dumps(fake.state.playlists, sort_keys=True)
    s, out = post(srv.url + "/api/requests", {"url": PLAYLIST_URL})
    assert s == 409 and "Tea tent" in out["error"] and "someone" in out["error"], out
    assert app.store.requests() == [] and app.store.external_count() == 0
    assert json.dumps(fake.state.playlists, sort_keys=True) == before        # Navidrome untouched too


def test_a_playlist_the_library_has_whole_answers_200_with_no_request(api):
    fake, app, srv, spotify = api(playlist())
    for i, t in enumerate(playlist()["trackList"]):          # every track is in the library already
        fake.state.songs[f"t{i}"] = dict(fake.state.songs["s1"], id=f"t{i}", title=t["title"], artist=t["subtitle"],
                                         duration=round(t["duration"] / 1000), path=f"x/{i}.flac")
    s, body = post(srv.url + "/api/requests", {"url": PLAYLIST_URL})
    assert s == 200 and body["request"] is None and body["rows"] == []
    assert body["playlist"]["matched"] == 3 and body["playlist"]["wanted"] == 0
    assert app.store.requests() == []


def test_a_comment_navidrome_did_not_keep_is_502_and_the_request_is_recorded(api, monkeypatch):
    from subsonic.client import SubsonicError
    from tests.test_import_playlist import _comment_update_raises
    monkeypatch.setenv("CRATES_OWNER", "comment")               # only the comment owner writes a comment
    fake, app, srv, spotify = api(playlist())
    _comment_update_raises(monkeypatch, SubsonicError(0, "boom"))
    s, out = post(srv.url + "/api/requests", {"url": PLAYLIST_URL})
    assert s == 502 and "could not write comment" in out["error"]
    [req] = app.store.requests()                                # the rows are recorded: so is their request
    assert req["kind"] == "playlist" and len(req["rows"]) == 3


def test_a_second_playlist_url_with_the_same_name_joins_that_playlist_and_its_request(api):
    # D52 *default*: a playlist's identity is its name (import-playlist's, S2-07), not its URL
    fake, app, srv, spotify = api(playlist())
    s1, first = post(srv.url + "/api/requests", {"url": PLAYLIST_URL})
    s2, again = post(srv.url + "/api/requests", {"url": "https://open.spotify.com/playlist/0therTeaTent"})
    assert (s1, s2) == (201, 200) and again["request"]["id"] == first["request"]["id"]
    assert again["request"]["source"] == PLAYLIST_URL and again["playlist"]["id"] == first["playlist"]["id"]


@pytest.mark.parametrize("body, reason", [
    ({}, "url is required"),
    ({"url": ""}, "url is required"),
    ({"url": "   "}, "url is required"),
    ({"url": 7}, "url is required"),
    ({"url": "https://music.apple.com/us/album/x/123"}, "unknown link kind: music.apple.com"),
    ({"url": "https://open.spotify.com/artist/3dkbV4qihUeMsqN4vBGg93"}, "unknown link kind: artist"),
])
def test_a_bad_or_unknown_link_is_400_with_its_reason_and_asks_nothing(api, body, reason):
    fake, app, srv, spotify = api(album())
    s, out = post(srv.url + "/api/requests", body)
    assert (s, out) == (400, {"error": reason})
    assert spotify.calls == [] and app.store.requests() == []


def test_a_list_body_is_400(api):
    fake, app, srv, spotify = api(album())
    s, out = post(srv.url + "/api/requests", [ALBUM_URL])
    assert (s, out) == (400, {"error": "url is required"})


@pytest.mark.parametrize("error", [
    urllib.error.HTTPError(ALBUM_URL, 503, "Service Unavailable", {}, None),
    urllib.error.URLError("no route to host"),
    SystemExit("couldn't reach Spotify (timed out)"),           # spotify_csv.fetch_entity's own way to fail
    http.client.IncompleteRead(b"<html>"),                       # a page cut short: an HTTPException, no OSError
    TypeError("'NoneType' object is not subscriptable"),         # the page's JSON changed shape
])
def test_a_spotify_fetch_error_is_502_and_records_nothing(api, error):
    fake, app, srv, spotify = api(error)
    s, out = post(srv.url + "/api/requests", {"url": ALBUM_URL})
    assert s == 502 and out["error"].startswith("cannot reach Spotify")
    assert app.store.requests() == [] and app.store.external_count() == 0


@pytest.mark.parametrize("url, entity", [
    (PLAYLIST_URL, album()),                                     # an embed of another kind
    (ALBUM_URL, {k: v for k, v in album().items() if k != "subtitle"}),
    (ALBUM_URL, {**album(), "trackList": [{"uri": "spotify:track:x"}]}),
    ("spotify:track:3cyGx6m1IIFxRnxEOGaAb2", {k: v for k, v in track().items() if k != "artists"}),
    (PLAYLIST_URL, {k: v for k, v in playlist().items() if k != "name"}),
])
def test_an_embed_this_code_cannot_read_is_502_not_400(api, url, entity):
    fake, app, srv, spotify = api(entity)
    s, out = post(srv.url + "/api/requests", {"url": url})
    assert s == 502 and out["error"].startswith("cannot reach Spotify"), out
    assert app.store.requests() == [] and app.store.external_count() == 0


def test_the_app_fetches_with_spotify_csv_by_default():
    from sourcing import spotify_csv
    app = CrateApp(Config(subsonic_url="http://127.0.0.1:9", username="u", password="p", db_path=":memory:"),
                   store=CrateStore())
    assert app.fetch_entity is spotify_csv.fetch_entity


# --- parse_link: the four forms, and what is refused

@pytest.mark.parametrize("url, want", [
    (f"https://open.spotify.com/album/{ALBUM_ID}", ("album", ALBUM_ID)),
    (f"https://open.spotify.com/intl-de/album/{ALBUM_ID}", ("album", ALBUM_ID)),
    (f"https://open.spotify.com/playlist/37i9dQZF1DXtea?si=abc&pt=1", ("playlist", "37i9dQZF1DXtea")),
    ("spotify:track:3cyGx6m1IIFxRnxEOGaAb2", ("track", "3cyGx6m1IIFxRnxEOGaAb2")),
    (f"  open.spotify.com/intl-fr/track/3cyGx6m1IIFxRnxEOGaAb2?si=1 ", ("track", "3cyGx6m1IIFxRnxEOGaAb2")),
])
def test_parse_link_reads_the_open_spotify_url_and_the_uri(url, want):
    assert parse_link(url) == want


@pytest.mark.parametrize("url, reason", [
    ("https://music.apple.com/us/album/x/123", "unknown link kind: music.apple.com"),
    ("https://www.youtube.com/watch?v=abc", "unknown link kind: www.youtube.com"),
    ("https://open.spotify.com/artist/3dkbV4qihUeMsqN4vBGg93", "unknown link kind: artist"),
    ("spotify:artist:3dkbV4qihUeMsqN4vBGg93", "unknown link kind: artist"),
    ("https://open.spotify.com/album/", "unknown link kind: album without an id"),
    ("not a link", "unknown link kind: not a link"),
])
def test_parse_link_refuses_other_platforms_and_kinds(url, reason):
    with pytest.raises(UnknownLink) as e:
        parse_link(url)
    assert str(e.value) == reason
