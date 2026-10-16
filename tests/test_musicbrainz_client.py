"""The rate-limited MusicBrainz client (offline: fake opener, fake clock, recording sleep).

The fixtures are live captures (2026-10-16): an ISRC lookup, a recording with works + ISRCs, and the first 10 of
61 search results for "Double Exposure" / "My Love Is Free".
"""
import io
import json
import urllib.error
import urllib.parse

import pytest

from sourcing.musicbrainz import USER_AGENT, MusicBrainz, MusicBrainzError, Recording, parse_recording
from tests.helpers import FIXTURES


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class FakeResponse:
    def __init__(self, body: dict):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


def http_error(code: int, **headers) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://musicbrainz.org/ws/2/x", code, "msg", headers, io.BytesIO(b"{}"))


class Script:
    """An opener answering from a list: dict -> 200 with that body, an Exception -> raised. Records the requests."""
    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(a, Exception):
            raise a
        return FakeResponse(a)


class Time:
    """A clock that only moves when `sleep` is called, so spacing is observable and tests take no real time."""
    def __init__(self, advance=True):
        self.now, self.sleeps, self.advance = 1000.0, [], advance

    def clock(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        if self.advance:
            self.now += s


def client(opener, t=None, **kw):
    t = t or Time()
    return MusicBrainz(opener=opener, sleep=t.sleep, clock=t.clock, **kw), t


def test_parse_isrc_fixture():
    mb, _ = client(Script(fixture("musicbrainz_isrc.sample.json")))
    recs = mb.isrc("GBARL0601475")
    assert len(recs) == 1
    assert recs[0].id.startswith("470a364c") and recs[0].length_s == 228.213
    assert recs[0].work_ids == ("769c5c09-7179-310f-b092-77af2ed3462b",)
    assert recs[0].title == "Virtual Insanity"


def test_parse_recording_fixture():
    opener = Script(fixture("musicbrainz_recording_work.sample.json"))
    mb, _ = client(opener)
    rec = mb.recording("2f9f850a-f0d7-4cf2-93fe-e4929abf16a9")
    assert rec.length_s == 402.0 and rec.work_ids == ("6815e26f-f6b2-30f0-962b-419d35fc2091",)
    assert "QM4221500415" in rec.isrcs
    q = urllib.parse.urlparse(opener.requests[0].full_url)
    assert q.path == "/ws/2/recording/2f9f850a-f0d7-4cf2-93fe-e4929abf16a9"
    assert urllib.parse.parse_qs(q.query) == {"fmt": ["json"], "inc": ["work-rels isrcs"]}


def test_parse_search_fixture():
    mb, _ = client(Script(fixture("musicbrainz_search.sample.json")))
    recs = mb.search("Double Exposure", "My Love Is Free")
    assert len(recs) == 10
    near = {r.id.split("-")[0] for r in recs if r.length_s is not None and abs(r.length_s - 579.8) <= 4}
    assert near == {"af09e6b5", "5fe60cf6"}
    assert {r.artist for r in recs} == {"Double Exposure"}
    assert all(r.releases for r in recs)


def test_parse_recording_without_length_or_credit():
    rec = parse_recording({"id": "x", "title": "T"})
    assert rec == Recording("x", "T", None, "")


def test_parse_recording_joins_credit_names_with_joinphrases_and_keeps_only_performance_works():
    rec = parse_recording({"id": "x", "title": "T", "length": 1500,
                           "artist-credit": [{"name": "A", "joinphrase": " feat. "}, {"name": "B"}],
                           "relations": [{"type": "performance", "work": {"id": "w1"}},
                                         {"type": "performance", "work": {"id": "w1"}},
                                         {"type": "arranger", "work": {"id": "w2"}},
                                         {"type": "performance", "url": {"id": "u"}}]})
    assert rec.artist == "A feat. B" and rec.length_s == 1.5 and rec.work_ids == ("w1",)


def test_requests_are_spaced_and_carry_the_user_agent():
    opener = Script({"recordings": []})
    mb, t = client(opener, Time(advance=False))
    for i in range(3):
        mb.isrc(f"ISRC{i}")
    assert sum(t.sleeps) >= 2 * 1.05
    assert len(opener.requests) == 3
    assert all(r.get_header("User-agent") == USER_AGENT for r in opener.requests)


def test_spacing_counts_time_already_elapsed():
    t = Time()
    mb, _ = client(Script({"recordings": []}), t)
    mb.isrc("A")
    t.now += 0.5
    mb.isrc("B")
    assert t.sleeps == [pytest.approx(0.55)]


def test_503_is_retried_with_backoff_then_raises():
    body = fixture("musicbrainz_isrc.sample.json")
    mb, t = client(Script(http_error(503), http_error(503), body))
    assert len(mb.isrc("GBARL0601475")) == 1
    assert 2 in t.sleeps and 4 in t.sleeps

    opener = Script(http_error(503))
    mb, t = client(opener)
    with pytest.raises(MusicBrainzError, match="503 after 4 tries"):
        mb.isrc("X")
    assert len(opener.requests) == 4

    mb, t = client(Script(http_error(503, **{"Retry-After": "7"}), body))
    mb.isrc("GBARL0601475")
    assert 7 in t.sleeps


def test_every_retry_is_spaced_too():
    t = Time(advance=False)
    mb, _ = client(Script(http_error(503), http_error(503), {"recordings": []}), t)
    mb.isrc("X")
    assert sum(s for s in t.sleeps if s == 1.05) >= 2 * 1.05


def test_other_http_errors_and_network_failures_raise_without_retry():
    opener = Script(http_error(400))
    mb, _ = client(opener)
    with pytest.raises(MusicBrainzError, match="400"):
        mb.recording("x")
    assert len(opener.requests) == 1
    mb, _ = client(Script(urllib.error.URLError("down")))
    with pytest.raises(MusicBrainzError):
        mb.recording("x")


def test_404_is_none_and_empty():
    mb, _ = client(Script(http_error(404)))
    assert mb.recording("2f9f850a-f0d7-4cf2-93fe-e4929abf16a9") is None
    assert mb.isrc("NOPE") == []
    assert mb.get("recording/x") is None


def test_cache_answers_without_the_network(tmp_path):
    cache = tmp_path / "mb.jsonl"
    first, _ = client(Script(fixture("musicbrainz_recording_work.sample.json"), http_error(404)), cache=cache)
    rec = first.recording("2f9f850a-f0d7-4cf2-93fe-e4929abf16a9")
    assert first.isrc("NOPE") == []

    def forbidden(req, timeout=None):
        raise AssertionError("network used")
    second, t = client(forbidden, cache=cache)
    assert second.recording("2f9f850a-f0d7-4cf2-93fe-e4929abf16a9") == rec
    assert second.isrc("NOPE") == []                       # a cached 404 is a hit too
    assert t.sleeps == []


def test_cache_survives_a_torn_last_line_and_503s_are_not_cached(tmp_path):
    cache = tmp_path / "sub" / "mb.jsonl"
    mb, _ = client(Script(http_error(503)), cache=cache, retries=2)
    with pytest.raises(MusicBrainzError):
        mb.recording("a")
    assert not cache.exists() or cache.read_text() == ""
    mb, _ = client(Script({"id": "a", "title": "A"}), cache=cache)
    mb.recording("a")
    with cache.open("a") as f:
        f.write('{"url": "torn')                            # a killed run
    again, _ = client(Script(http_error(400)), cache=cache)
    assert again.recording("a").id == "a"


def test_search_escapes_quotes():
    opener = Script({"recordings": []})
    mb, _ = client(opener)
    mb.search('A "B"', "T\\")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(opener.requests[0].full_url).query)
    assert q["query"] == ['artist:"A \\"B\\"" AND recording:"T\\\\"']
    assert q["limit"] == ["100"]
