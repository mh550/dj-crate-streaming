"""MusicBrainz recording length: the D22 'confident' check that beets' own match cannot make (offline: fake opener)."""
import json
import urllib.error

from sourcing.filer import FiledItem
from sourcing.musicbrainz import USER_AGENT, confirm_recording_length, recording_length
from tests.helpers import FIXTURES

RECORDING = json.loads((FIXTURES / "musicbrainz_recording.docs-example.json").read_text())


class FakeResponse:
    def __init__(self, body: dict):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


def opener_for(body: dict):
    def opener(req, timeout=None):
        opener.requests.append(req)
        return FakeResponse(body)
    opener.requests = []
    return opener


def item(length=501.0, mbid="rec-1") -> FiledItem:
    from pathlib import Path
    return FiledItem(Path("/x.flac"), "Chic", "Good Times", mbid, False, length=length)


def test_recording_length_sends_the_user_agent_and_parses_ms():
    opener = opener_for(RECORDING)
    assert recording_length(RECORDING["id"], opener=opener) == 501.0
    (req,) = opener.requests
    assert req.get_header("User-agent") == USER_AGENT
    assert RECORDING["id"] in req.full_url and "fmt=json" in req.full_url


def test_recording_without_length_is_none():
    assert recording_length("rec-1", opener=opener_for({k: v for k, v in RECORDING.items() if k != "length"})) is None


def test_confirm_agrees_within_tolerance():
    ok, why = confirm_recording_length(item(503.0), lookup=lambda mbid: 501.0)
    assert ok is True and why == "MusicBrainz length 501 s vs file 503 s"


def test_confirm_rejects_no_length_and_disagreement_and_errors():
    ok, why = confirm_recording_length(item(), lookup=lambda mbid: None)
    assert ok is False and "no length" in why and "rec-1" in why
    ok, why = confirm_recording_length(item(501.0), lookup=lambda mbid: 580.0)
    assert ok is False and "Δ79" in why

    def down(mbid):
        raise urllib.error.URLError("down")
    ok, why = confirm_recording_length(item(), lookup=down)
    assert ok is False and "lookup failed" in why and "URLError" in why


# ---- release match (S2-03): the Spotify album's rows against the captured MusicBrainz releases ------------------

import copy  # noqa: E402

from crates.store import CrateStore  # noqa: E402
from sourcing import requests as rq  # noqa: E402
from sourcing.musicbrainz import match_release  # noqa: E402

SEARCH = json.loads((FIXTURES / "musicbrainz_release_search_al-green.json").read_text())["releases"]
RELEASE = json.loads((FIXTURES / "musicbrainz_release_al-green-still-in-love.json").read_text())
CD, DIGITAL = "3c9a52ee-ee0a-3362-a563-d9d28b02a53e", "095b1ca3-34ba-4d14-8eba-602fe6c1a5a1"


def album_rows():
    entity = json.loads((FIXTURES / "spotify_embed_album_al-green-still-in-love.json").read_text())
    return rq.add_spotify(CrateStore(), "https://open.spotify.com/album/x", fetch=lambda url: entity)["rows"]


def serving(ids, body=RELEASE):
    """A fetch_release that answers `body` for the given ids and None (404) for the rest; records what it asked."""
    asked = []

    def fetch(mbid):
        asked.append(mbid)
        return body if mbid in ids else None
    fetch.asked = asked
    return fetch


def test_the_spotify_rows_match_the_cd_one_to_one():
    rows = album_rows()
    m = match_release(rows, SEARCH, serving({CD}))
    assert m is not None and m.id == CD and (m.format, m.date) == ("CD", "1993")
    assert [t.recording_id for t in m.tracks][0] == "cdac1a50-8ba6-4edd-8137-618928580d38"
    assert m.tracks[8].recording_id.startswith("83f06455")
    assert all(m.tracks[i].position == rows[i]["track_no"] for i in range(9))
    assert rows[5]["title"] == "Oh ,Pretty Woman" and m.tracks[5].title == "Oh, Pretty Woman"


def test_digital_media_wins_over_cd_and_the_search_stops_at_the_first_match():
    fetch = serving({CD, DIGITAL})
    m = match_release(album_rows(), SEARCH, fetch)
    assert m.id == DIGITAL and m.format == "Digital Media" and fetch.asked == [DIGITAL]


def test_tie_order_is_digital_then_cd_then_earliest_date_with_no_date_last():
    fetch = serving(set())
    assert match_release(album_rows(), SEARCH, fetch) is None
    assert fetch.asked == [
        DIGITAL, "5ee0b926-4c9d-4be3-b504-a634cf0338f5",              # digital: 2019-12-20, then no date
        CD, "15e4ea1a-3fb2-4e41-bf8e-ca38bea4075f",                   # CD 1993, 2009 (the 11- and 18-track CDs never)
        "c875ae04-801b-444e-8a1f-afd38162412d", "4c95ac93-1334-47d7-9f21-1fcdf67d17d3",   # vinyl 1972, 1972-10-23
        "18068679-fd83-422e-b929-bd4428d951a9", "b084438f-e7ef-4af5-ab20-bb3d599e52d7"]   # 2009-06-23, 2022


def test_eight_rows_match_no_nine_track_release():
    fetch = serving({CD})
    assert match_release(album_rows()[:8], SEARCH, fetch) is None and fetch.asked == []


def test_one_different_title_is_no_match():
    body = copy.deepcopy(RELEASE)
    body["media"][0]["tracks"][2]["title"] = "Love and Hate"
    assert match_release(album_rows(), SEARCH, serving({CD}, body)) is None


def test_titles_must_match_in_track_order_not_only_as_a_set():
    rows = album_rows()
    rows[0]["track_no"], rows[8]["track_no"] = 9, 1                  # ext-74's trap: track 1 is not track 9
    assert match_release(rows, SEARCH, serving({CD})) is None


def test_positions_run_across_media():
    body = copy.deepcopy(RELEASE)
    tracks = body["media"][0]["tracks"]
    disc2 = [{**t, "position": i + 1} for i, t in enumerate(tracks[5:])]
    body["media"] = [{"format": "CD", "position": 1, "tracks": tracks[:5]},
                     {"format": "CD", "position": 2, "tracks": disc2}]
    m = match_release(album_rows(), SEARCH, serving({CD}, body))
    assert [t.position for t in m.tracks] == list(range(1, 10))
    assert m.tracks[5].recording_id == "1473b0bc-05b4-4951-b80d-4b4f01de89f3"


def test_a_release_body_with_another_track_count_than_its_search_entry_is_skipped():
    body = copy.deepcopy(RELEASE)
    body["media"][0]["tracks"] = body["media"][0]["tracks"][:8]
    assert match_release(album_rows(), SEARCH, serving({CD}, body)) is None


def test_rows_without_track_numbers_match_nothing():
    rows = album_rows()
    rows[3]["track_no"] = None
    fetch = serving({CD})
    assert match_release(rows, SEARCH, fetch) is None and fetch.asked == []


def test_another_version_of_a_title_is_no_match():
    body = copy.deepcopy(RELEASE)
    body["media"][0]["tracks"][2]["title"] = "Love and Happiness (live)"
    assert match_release(album_rows(), SEARCH, serving({CD}, body)) is None
