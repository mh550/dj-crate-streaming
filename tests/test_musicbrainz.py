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
