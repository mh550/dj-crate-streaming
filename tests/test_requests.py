"""sourcing.requests: a Spotify URL becomes one request whose rows are external_wanted rows (S2-02)."""
import json

from crates.store import CrateStore, public
from sourcing import requests as rq
from tests.helpers import FIXTURES

ALBUM_URL = "https://open.spotify.com/album/2nTlIPIQ7fHOnNN7BRch0Z"


def _album():
    return json.loads((FIXTURES / "spotify_embed_album_al-green-still-in-love.json").read_text())


def test_album_url_is_one_album_request_with_nine_rows():
    store = CrateStore()
    req = rq.add_spotify(store, ALBUM_URL, fetch=lambda url: _album())
    assert req["kind"] == "album" and req["artist"] == "Al Green" and req["album"] == "I'm Still in Love With You"
    assert req["year"] is None and req["source"] == ALBUM_URL
    rows = req["rows"]
    assert [r["track_no"] for r in rows] == list(range(1, 10))
    assert all(r["request_id"] == req["id"] and r["album"] == "I'm Still in Love With You" for r in rows)
    assert all(r["artist"] == "Al Green" and r["source"] == ALBUM_URL for r in rows)
    assert rows[5]["title"] == "Oh ,Pretty Woman" and rows[0]["duration"] == 196
    assert req["status"] == "open" and len(store.wanted()) == 9


def test_album_year_reaches_the_request_and_its_rows():
    store = CrateStore()
    req = rq.add_spotify(store, ALBUM_URL, fetch=lambda url: {**_album(), "releaseDate": "1972-10-23"})
    assert req["year"] == 1972 and {r["year"] for r in req["rows"]} == {1972}


def test_same_album_again_adds_no_request_and_no_row():
    store = CrateStore()
    first = rq.add_spotify(store, ALBUM_URL, fetch=lambda url: _album())
    again = rq.add_spotify(store, ALBUM_URL + "?si=abc123", fetch=lambda url: _album())   # a share link
    assert again["id"] == first["id"] and len(store.requests()) == 1
    assert len(again["rows"]) == 9 and store.external_count() == 9


def test_lead_artist_of_a_shared_album():
    store = CrateStore()
    entity = {**_album(), "subtitle": "Al Green,\xa0Willie Mitchell"}
    for t in entity["trackList"]:
        t["subtitle"] = "Al Green,\xa0Willie Mitchell"
    req = rq.add_spotify(store, ALBUM_URL, fetch=lambda url: entity)
    assert req["artist"] == "Al Green" and {r["artist"] for r in req["rows"]} == {"Al Green"}


def test_track_url_is_one_track_request():
    store = CrateStore()
    entity = {"type": "track", "name": "Love And Happiness", "uri": "spotify:track:6NW0y8AxOfqqC7FxRjWTGF",
              "artists": [{"name": "Al Green"}], "duration": 303306}
    req = rq.add_spotify(store, "https://open.spotify.com/track/6NW0y8AxOfqqC7FxRjWTGF", fetch=lambda url: entity)
    assert req["kind"] == "track" and req["artist"] == "Al Green" and req["album"] is None
    [row] = req["rows"]
    assert row["title"] == "Love And Happiness" and row["request_id"] == req["id"] and row["duration"] == 303


def test_playlist_url_is_not_a_request_yet():
    store = CrateStore()
    entity = json.loads((FIXTURES / "spotify_embed_tea-tent-1.json").read_text())
    assert rq.add_spotify(store, "https://open.spotify.com/playlist/x", fetch=lambda url: entity) is None
    assert store.requests() == [] and store.external_count() == 0


def test_a_row_already_queued_joins_the_album_request():
    store = CrateStore()
    old = store.add_external_wanted("Al Green", "Love And Happiness", duration_s=303)
    req = rq.add_spotify(store, ALBUM_URL, fetch=lambda url: _album())
    row = store.find_wanted(old)
    assert row["request_id"] == req["id"] and row["track_no"] == 3 and len(req["rows"]) == 9


def test_request_payload_is_public():
    store = CrateStore()
    req = rq.add_spotify(store, ALBUM_URL, fetch=lambda url: _album())
    assert json.dumps(public(req))             # serialisable for the API (S3)


def test_track_already_in_an_album_request_answers_that_request():
    store = CrateStore()
    album = rq.add_spotify(store, ALBUM_URL, fetch=lambda url: _album())
    entity = {"type": "track", "name": "Love And Happiness", "uri": "spotify:track:6NW0y8AxOfqqC7FxRjWTGF",
              "artists": [{"name": "Al Green"}], "duration": 303306}
    req = rq.add_spotify(store, "https://open.spotify.com/track/6NW0y8AxOfqqC7FxRjWTGF", fetch=lambda url: entity)
    assert req["id"] == album["id"] and len(store.requests()) == 1     # no empty request that stays open forever


def test_a_queued_row_joining_an_album_gets_its_album_and_year():
    store = CrateStore()
    old = store.add_external_wanted("Al Green", "Love And Happiness", duration_s=303)
    rq.add_spotify(store, ALBUM_URL, fetch=lambda url: {**_album(), "releaseDate": "1972-10-23"})
    row = store.find_wanted(old)
    assert row["album"] == "I'm Still in Love With You" and row["year"] == 1972


def test_canonical_drops_share_parameters_and_locale():
    assert rq.canonical("https://open.spotify.com/intl-de/album/2nTlIPIQ7fHOnNN7BRch0Z?si=x") == ALBUM_URL
