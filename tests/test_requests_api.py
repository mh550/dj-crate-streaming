"""S3-01: `POST /api/requests {"url": …}` turns a Spotify track, album or playlist link into a request and answers
with the request and its rows. The app is built like tests/test_service.py's `svc`, with the Spotify fetch injected
(`CrateApp(..., fetch_entity=…)`), so nothing reaches the network."""
import http.client
import json
import urllib.error
import urllib.parse

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


# --- S3-01b: a catalog pick (`mbReleaseId`, `mbRecordingId`), and rows the library has already

RELEASE_ID = "3c9a52ee-ee0a-3362-a563-d9d28b02a53e"
RECORDING_ID = "cdac1a50-8ba6-4edd-8137-618928580d38"
STUB_ID = "5705b0b0-0000-4000-8000-000000000000"            # a release MusicBrainz lists no tracks for


def release():
    return json.loads((FIXTURES / "musicbrainz_release_al-green-still-in-love.json").read_text())


def recording():
    """The docs example's shape (no relations), as `recording()` asks it (`inc=artist-credits …`): with its credit."""
    doc = json.loads((FIXTURES / "musicbrainz_recording.docs-example.json").read_text())
    return {**doc, "id": RECORDING_ID, "title": "I’m Still in Love With You", "length": 193973,
            "artist-credit": [{"name": "Al Green", "joinphrase": ""}]}


class MusicBrainzStub:
    """`MusicBrainz(opener=…)`'s opener: release/<RELEASE_ID> and recording/<RECORDING_ID> answer their JSON,
    anything else is a 404 (or `error`, raised). Records each path asked."""

    def __init__(self, error=None):
        self.error, self.paths = error, []

    def __call__(self, req, timeout=None):
        import io
        path = urllib.parse.urlsplit(req.full_url).path.removeprefix("/ws/2/")
        self.paths.append(path)
        if self.error is not None:
            raise self.error
        body = {f"release/{RELEASE_ID}": release(), f"recording/{RECORDING_ID}": recording(),
                f"release/{STUB_ID}": {**release(), "id": STUB_ID, "media": [{"format": "CD", "tracks": []}]}}.get(path)
        if body is None:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b"{}"))
        return io.BytesIO(json.dumps(body).encode())


@pytest.fixture
def mb_api():
    """A fake Navidrome, the app with a stub Spotify (album) and a `MusicBrainz` on MusicBrainzStub."""
    from sourcing.musicbrainz import MusicBrainz
    made = []

    def make(error=None, subsonic_url=None):
        stub = MusicBrainzStub(error)
        fake = FakeSubsonicServer().__enter__()
        cfg = Config(subsonic_url=subsonic_url or fake.url, username="demo", password="demo", db_path=":memory:",
                     port=0)
        app = CrateApp(cfg, store=CrateStore(), fetch_entity=Spotify(album()),
                       musicbrainz=MusicBrainz(opener=stub, sleep=lambda s: None, min_interval_s=0))
        srv = CrateServer(app).__enter__()
        made.append((fake, srv))
        return fake, app, srv, stub
    yield make
    for fake, srv in made:
        srv.__exit__(None, None, None)
        fake.__exit__(None, None, None)


def test_an_mb_release_id_is_an_album_request_with_the_releases_tracks(mb_api):
    fake, app, srv, stub = mb_api()
    s, body = post(srv.url + "/api/requests", {"mbReleaseId": RELEASE_ID})
    assert s == 201, body
    req = body["request"]
    assert {k: req[k] for k in ("kind", "artist", "album", "year", "mbReleaseId", "status", "source")} == {
        "kind": "album", "artist": "Al Green", "album": "I’m Still in Love With You", "year": 1993,
        "mbReleaseId": RELEASE_ID, "status": "open", "source": f"https://musicbrainz.org/release/{RELEASE_ID}"}
    tracks = release()["media"][0]["tracks"]
    rows = body["rows"]
    assert [r["trackNo"] for r in rows] == list(range(1, 10))
    assert [r["mbRecordingId"] for r in rows] == [t["recording"]["id"] for t in tracks]
    assert [r["title"] for r in rows] == [t["title"] for t in tracks]
    assert [r["durationS"] for r in rows] == [round(t["length"] / 1000) for t in tracks]
    assert {(r["artist"], r["album"], r["year"], r["status"]) for r in rows} == {
        ("Al Green", "I’m Still in Love With You", 1993, "needs_source")}
    assert app.store.request(req["id"])["tracktotal"] == 9
    s, again = post(srv.url + "/api/requests", {"mbReleaseId": RELEASE_ID})
    assert (s, again) == (200, body) and len(app.store.requests()) == 1 and app.store.external_count() == 9
    assert stub.paths == [f"release/{RELEASE_ID}"]              # the second ask is the client's cache


def test_an_mb_recording_id_is_a_track_request_with_one_row(mb_api):
    fake, app, srv, stub = mb_api()
    s, body = post(srv.url + "/api/requests", {"mbRecordingId": RECORDING_ID})
    assert s == 201, body
    req = body["request"]
    assert (req["kind"], req["artist"], req["album"], req["mbReleaseId"]) == ("track", "Al Green", None, None)
    assert req["source"] == f"https://musicbrainz.org/recording/{RECORDING_ID}"
    [row] = body["rows"]
    assert (row["title"], row["artist"], row["durationS"], row["mbRecordingId"], row["trackNo"], row["status"]) == (
        "I’m Still in Love With You", "Al Green", 194, RECORDING_ID, None, "needs_source")


@pytest.mark.parametrize("body, reason", [
    ({"mbReleaseId": STUB_ID}, f"MusicBrainz release {STUB_ID} lists no tracks"),
    ({"mbReleaseId": "0b0b0b0b-0000-4000-8000-000000000000"},
     "MusicBrainz has no release 0b0b0b0b-0000-4000-8000-000000000000"),
    ({"mbRecordingId": "0b0b0b0b-0000-4000-8000-000000000000"},
     "MusicBrainz has no recording 0b0b0b0b-0000-4000-8000-000000000000"),
])
def test_an_id_musicbrainz_does_not_know_is_404(mb_api, body, reason):
    fake, app, srv, stub = mb_api()
    s, out = post(srv.url + "/api/requests", body)
    assert (s, out) == (404, {"error": reason})
    assert app.store.requests() == [] and app.store.external_count() == 0


@pytest.mark.parametrize("body, reason", [
    ({"url": ALBUM_URL, "mbReleaseId": RELEASE_ID}, "one of url, mbReleaseId, mbRecordingId"),
    ({"mbReleaseId": RELEASE_ID, "mbRecordingId": RECORDING_ID}, "one of url, mbReleaseId, mbRecordingId"),
    ({"mbReleaseId": "../recording/x"}, "mbReleaseId is not a MusicBrainz id"),
    ({"mbRecordingId": 7}, "mbRecordingId is not a MusicBrainz id"),
])
def test_two_keys_or_a_malformed_id_is_400_and_asks_nothing(mb_api, body, reason):
    fake, app, srv, stub = mb_api()
    s, out = post(srv.url + "/api/requests", body)
    assert (s, out) == (400, {"error": reason})
    assert stub.paths == [] and app.fetch_entity.calls == [] and app.store.requests() == []


def test_musicbrainz_unreachable_is_502_and_records_nothing(mb_api):
    fake, app, srv, stub = mb_api(error=urllib.error.URLError("no route to host"))
    s, out = post(srv.url + "/api/requests", {"mbReleaseId": RELEASE_ID})
    assert s == 502 and out["error"].startswith("cannot reach MusicBrainz"), out
    assert app.store.requests() == []


def test_the_app_builds_its_musicbrainz_from_the_cache_variable(monkeypatch, tmp_path):
    monkeypatch.setenv("MUSICBRAINZ_CACHE", str(tmp_path / "mb.jsonl"))
    app = CrateApp(Config(subsonic_url="http://127.0.0.1:9", username="u", password="p", db_path=":memory:"),
                   store=CrateStore())
    assert app.musicbrainz._cache_path == tmp_path / "mb.jsonl"


def library_song(fake, sid, title, duration):
    """A song Navidrome has, as tests/test_fetch.py's new_song adds one."""
    fake.state.songs[sid] = dict(fake.state.songs["s1"], id=sid, title=title, artist="Al Green",
                                 album="I'm Still in Love With You", duration=duration, path=f"Al Green/{sid}.flac")


def test_an_album_row_the_library_has_answers_ok_with_its_library_song(mb_api):
    fake, app, srv, stub = mb_api()
    library_song(fake, "ag5", "Simply Beautiful", 256)           # row 5: Spotify's 255.666 s
    s, body = post(srv.url + "/api/requests", {"url": ALBUM_URL})
    assert s == 201
    rows = body["rows"]
    assert (rows[4]["status"], rows[4]["librarySongId"]) == ("ok", "ag5")
    assert [r["status"] for r in rows[:4] + rows[5:]] == ["needs_source"] * 8
    assert body["request"]["status"] == "partly"
    ev = [e for e in app.store.events(200) if e["kind"] == "matched"]
    assert [(e["song_id"], e["detail"]) for e in ev] == [(rows[4]["id"], "same version: Simply Beautiful")]


def test_a_release_row_the_library_has_is_marked_too(mb_api):
    fake, app, srv, stub = mb_api()
    library_song(fake, "ag5", "Simply Beautiful", 250)           # MusicBrainz's 249.893 s
    s, body = post(srv.url + "/api/requests", {"mbReleaseId": RELEASE_ID})
    assert s == 201 and [r["librarySongId"] for r in body["rows"]] == [None] * 4 + ["ag5"] + [None] * 4


def test_a_track_the_library_has_is_a_done_request(mb_api):
    fake, app, srv, stub = mb_api()
    library_song(fake, "ag1", "I’m Still in Love With You", 194)
    s, body = post(srv.url + "/api/requests", {"mbRecordingId": RECORDING_ID})
    assert s == 201 and body["request"]["status"] == "done"
    assert (body["rows"][0]["status"], body["rows"][0]["librarySongId"]) == ("ok", "ag1")


def test_navidrome_unreachable_leaves_the_rows_open_with_one_event_on_the_request(mb_api):
    fake, app, srv, stub = mb_api(subsonic_url="http://127.0.0.1:9")
    s, body = post(srv.url + "/api/requests", {"mbReleaseId": RELEASE_ID})
    assert s == 201 and {r["status"] for r in body["rows"]} == {"needs_source"}
    ev = [e for e in app.store.events(200) if e["kind"] == "matched"]
    assert len(ev) == 1 and ev[0]["song_id"] is None
    assert ev[0]["detail"].startswith(f"#{body['request']['id']} library not asked: "), ev
    assert ev[0]["detail"].endswith("library not asked: URLError")


def test_a_release_whose_album_was_asked_for_from_spotify_answers_that_request(mb_api):
    # every row is the Spotify request's already (find_external folds ’ and case): no second album, no new rows
    fake, app, srv, stub = mb_api()
    s1, first = post(srv.url + "/api/requests", {"url": ALBUM_URL})
    s2, pick = post(srv.url + "/api/requests", {"mbReleaseId": RELEASE_ID})
    assert (s1, s2) == (201, 200) and pick["request"]["id"] == first["request"]["id"]
    assert app.store.external_count() == 9 and len(app.store.requests()) == 1
    assert pick["request"]["mbReleaseId"] is None              # the release is S2-03's to match, not the pick's


def test_a_second_ask_for_the_same_recording_answers_200(mb_api):
    fake, app, srv, stub = mb_api()
    s1, first = post(srv.url + "/api/requests", {"mbRecordingId": RECORDING_ID})
    s2, again = post(srv.url + "/api/requests", {"mbRecordingId": RECORDING_ID.upper()})
    assert (s1, s2) == (201, 200) and again == first and app.store.external_count() == 1


def test_a_recording_an_album_request_holds_answers_that_request_and_writes_no_id_onto_it(mb_api):
    fake, app, srv, stub = mb_api()
    s1, album_req = post(srv.url + "/api/requests", {"url": ALBUM_URL})
    s2, pick = post(srv.url + "/api/requests", {"mbRecordingId": RECORDING_ID})     # the album's track 1
    assert (s1, s2) == (201, 200) and pick["request"]["id"] == album_req["request"]["id"]
    assert pick == album_req and pick["rows"][0]["mbRecordingId"] is None
    assert len(app.store.requests()) == 1 and app.store.external_count() == 9


def test_mark_in_library_links_only_open_rows(mb_api):
    from sourcing.requests import add_release, mark_in_library
    fake, app, srv, stub = mb_api()
    req = add_release(app.store, app.musicbrainz, RELEASE_ID)                  # no navidrome: nothing marked
    tracks = release()["media"][0]["tracks"]
    for i in range(4):                                                         # the library has rows 1-4
        library_song(fake, f"ag{i + 1}", tracks[i]["title"], round(tracks[i]["length"] / 1000))
    r1, r2, r3, r4 = [r["song_id"] for r in req["rows"][:4]]
    app.store.set_external_status(r1, "failed", "no source")                    # not needs_source
    app.store.approve(r2, "michael", None, "medium")                            # an approval waiting
    app.store.set_external_song(r3, "s1", True)                                 # a play-now copy: an upgrade
    app.store.commit()
    mark_in_library(app.store, app.api, req["id"])
    rows = {r["song_id"]: r for r in app.store.request(req["id"])["rows"]}
    assert [(rows[w]["status"], rows[w]["library_song_id"]) for w in (r1, r2, r3, r4)] == [
        ("failed", None), ("needs_source", None), ("needs_source", "s1"), ("ok", "ag4")]


def test_navidrome_failing_midway_keeps_the_links_made_and_names_no_url(mb_api, monkeypatch):
    fake, app, srv, stub = mb_api()
    tracks = release()["media"][0]["tracks"]
    for i in (0, 4):                                                           # rows 1 and 5 are in the library
        library_song(fake, f"ag{i + 1}", tracks[i]["title"], round(tracks[i]["length"] / 1000))
    search = app.api.search_songs

    def flaky(query, *a, **kw):
        if "happiness" in query.lower():               # row 3: Navidrome goes away
            raise OSError("http://nd/rest/search3?u=demo&t=TOKEN&s=SALT refused")
        return search(query, *a, **kw)
    monkeypatch.setattr(app.api, "search_songs", flaky)
    s, body = post(srv.url + "/api/requests", {"mbReleaseId": RELEASE_ID})
    assert s == 201
    assert [r["librarySongId"] for r in body["rows"]] == ["ag1"] + [None] * 8   # row 5 was never asked
    [ev] = [e for e in app.store.events(200) if e["kind"] == "matched" and e["song_id"] is None]
    assert ev["detail"] == f"#{body['request']['id']} library not asked: OSError"


@pytest.mark.parametrize("error", [KeyError("subsonic-response"), TypeError("odd answer")])
def test_an_odd_navidrome_answer_is_an_event_not_an_error(mb_api, monkeypatch, error):
    fake, app, srv, stub = mb_api()
    monkeypatch.setattr(app.api, "search_songs", lambda *a, **kw: (_ for _ in ()).throw(error))
    s, body = post(srv.url + "/api/requests", {"mbRecordingId": RECORDING_ID})
    assert s == 201 and body["rows"][0]["status"] == "needs_source"
    assert [e["detail"] for e in app.store.events(200) if e["kind"] == "matched"] == [
        f"#{body['request']['id']} library not asked: {type(error).__name__}"]
