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


# ---- the MusicBrainz release match (S2-03) ------------------------------------------------------------------------

import io  # noqa: E402
import urllib.error  # noqa: E402
import urllib.parse  # noqa: E402

from sourcing.musicbrainz import MusicBrainz  # noqa: E402

CD = "3c9a52ee-ee0a-3362-a563-d9d28b02a53e"


class MusicBrainzStub:
    """An opener for `MusicBrainz(opener=…)`: the captured search for any release search, the captured release for
    the ids in `releases`, 404 for everything else. Records the paths asked."""
    def __init__(self, releases=(CD,), search="musicbrainz_release_search_al-green.json"):
        self.releases, self.search, self.paths = set(releases), search, []

    def __call__(self, req, timeout=None):
        path = urllib.parse.urlparse(req.full_url).path.removeprefix("/ws/2/")
        self.paths.append(path)
        if path == "release" and self.search:
            body = (FIXTURES / self.search).read_text()
        elif path.removeprefix("release/") in self.releases:
            body = (FIXTURES / "musicbrainz_release_al-green-still-in-love.json").read_text()
        else:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b"{}"))
        return io.BytesIO(body.encode())


def stub_mb(opener):
    return MusicBrainz(opener=opener, sleep=lambda s: None, min_interval_s=0)


def test_album_request_gets_its_release_and_every_row_its_recording():
    store = CrateStore()
    req = rq.add_spotify(store, ALBUM_URL, fetch=lambda url: _album())
    opener = MusicBrainzStub()
    assert rq.match_request_release(store, req["id"], stub_mb(opener)) is True
    req = store.request(req["id"])
    assert req["mb_release_id"] == CD
    rows = req["rows"]
    assert rows[0]["mb_recording_id"] == "cdac1a50-8ba6-4edd-8137-618928580d38"
    assert rows[8]["mb_recording_id"].startswith("83f06455") and all(r["mb_recording_id"] for r in rows)
    [ev] = [e for e in store.events(limit=100) if e["kind"] == "release"]
    assert f"musicbrainz release {CD} (CD 1993)" in ev["detail"] and ev["detail"].startswith(f"#{req['id']} ")
    assert opener.paths[0] == "release" and opener.paths[-1] == f"release/{CD}"


def test_no_one_to_one_release_stores_nothing_and_the_request_goes_on():
    store = CrateStore()
    req = rq.add_spotify(store, ALBUM_URL, fetch=lambda url: _album())
    assert rq.match_request_release(store, req["id"], stub_mb(MusicBrainzStub(releases=()))) is False
    req = store.request(req["id"])
    assert req["mb_release_id"] is None and not any(r["mb_recording_id"] for r in req["rows"])
    assert [e for e in store.events(limit=100) if e["kind"] == "release"] == [] and req["status"] == "open"


def test_a_track_request_is_not_matched_to_a_release():
    store = CrateStore()
    entity = {"type": "track", "name": "Love And Happiness", "uri": "spotify:track:6NW0y8AxOfqqC7FxRjWTGF",
              "artists": [{"name": "Al Green"}], "duration": 303306}
    req = rq.add_spotify(store, "https://open.spotify.com/track/6NW0y8AxOfqqC7FxRjWTGF", fetch=lambda url: entity)
    opener = MusicBrainzStub()
    assert rq.match_request_release(store, req["id"], stub_mb(opener)) is False and opener.paths == []


def test_a_matched_request_is_not_asked_again():
    store = CrateStore()
    req = rq.add_spotify(store, ALBUM_URL, fetch=lambda url: _album())
    assert rq.match_request_release(store, req["id"], stub_mb(MusicBrainzStub()))
    opener = MusicBrainzStub()
    assert rq.match_request_release(store, req["id"], stub_mb(opener)) is True and opener.paths == []
    assert len([e for e in store.events(limit=100) if e["kind"] == "release"]) == 1


def _fail(store, ext):
    store.db.execute("UPDATE external_wanted SET status='failed', reason='no source' WHERE id=?", (int(ext[4:]),))
    store.commit()


def test_a_re_seeded_row_gets_the_matched_recording_too():
    store = CrateStore()
    req = rq.add_spotify(store, ALBUM_URL, fetch=lambda url: _album())
    assert rq.match_request_release(store, req["id"], stub_mb(MusicBrainzStub()))
    _fail(store, req["rows"][2]["song_id"])
    req = rq.add_spotify(store, ALBUM_URL, fetch=lambda url: _album())          # seed-spotify again: a new track-3 row
    assert len(req["rows"]) == 10
    assert rq.match_request_release(store, req["id"], stub_mb(MusicBrainzStub())) is True
    rows = store.request(req["id"])["rows"]
    assert {r["mb_recording_id"] for r in rows if r["track_no"] == 3} == {"eed211fe-122d-4c48-ace0-f85aab5d5ade"}
    assert len([e for e in store.events(limit=100) if e["kind"] == "release"]) == 1


def test_a_re_seeded_row_before_any_match_still_matches():
    store = CrateStore()
    req = rq.add_spotify(store, ALBUM_URL, fetch=lambda url: _album())
    _fail(store, req["rows"][2]["song_id"])
    req = rq.add_spotify(store, ALBUM_URL, fetch=lambda url: _album())
    assert rq.match_request_release(store, req["id"], stub_mb(MusicBrainzStub())) is True
    assert all(r["mb_recording_id"] for r in store.request(req["id"])["rows"])


def test_a_matched_request_is_written_in_one_transaction_and_leaves_updated_at():
    store = CrateStore()
    req = rq.add_spotify(store, ALBUM_URL, fetch=lambda url: _album())
    before = {r["song_id"]: r["updated_at"] for r in req["rows"]}
    commits = []
    real = store.db

    class Spy:
        def __getattr__(self, name):
            return getattr(real, name)

        def commit(self):
            commits.append(1)
            real.commit()
    store.db = Spy()
    try:
        assert rq.match_request_release(store, req["id"], stub_mb(MusicBrainzStub()))
    finally:
        store.db = real
    assert len(commits) == 1
    assert {r["song_id"]: r["updated_at"] for r in store.request(req["id"])["rows"]} == before


def test_the_match_uses_the_title_the_row_asked_for():
    store = CrateStore()
    req = rq.add_spotify(store, ALBUM_URL, fetch=lambda url: _album())
    assert store.set_wanted_names(req["rows"][2]["song_id"], "Al Green", "Love & Happiness (Live)")
    assert rq.match_request_release(store, req["id"], stub_mb(MusicBrainzStub())) is True
