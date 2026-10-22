"""AcoustID: parse the documented response, POST the key in the body, and the verify step that uses it."""
import json
import urllib.error
from pathlib import Path

import pytest

from sourcing import acoustid
from sourcing.verify import verify
from tests.helpers import FIXTURES, make_audio


def test_parse_docs_example():
    resp = json.loads((FIXTURES / "acoustid_lookup.docs-example.json").read_text())
    first = resp["results"][0]["recordings"][0]
    recs = acoustid.parse(resp)
    assert recs[0]["id"] == first["id"] and recs[0]["title"] == first["title"] and recs[0]["score"] == 1.0


def test_parse_orders_by_score_and_dedupes():
    resp = {"status": "ok", "results": [
        {"score": 0.4, "recordings": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}]},
        {"score": 0.9, "recordings": [{"id": "b", "title": "B"}]},
        {"score": 0.7}]}
    assert [(r["id"], r["score"]) for r in acoustid.parse(resp)] == [("b", 0.9), ("a", 0.4)]


def test_parse_rejects_error_status():
    with pytest.raises(ValueError):
        acoustid.parse({"status": "error", "error": {"message": "invalid API key"}})


def test_lookup_posts_the_key_in_the_body_not_the_url(tmp_path, monkeypatch):
    monkeypatch.setattr(acoustid, "compressed_fingerprint", lambda path: (212, "AQAA-fp"))
    seen = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"status": "ok", "results": []}).encode()

    def opener(req, timeout):
        seen.update(req=req, timeout=timeout)
        return Resp()

    assert acoustid.lookup(tmp_path / "x.flac", "KEY", opener=opener) == []
    req = seen["req"]
    body = req.data.decode()
    assert req.get_method() == "POST" and req.full_url == acoustid.URL
    assert "client=KEY" in body and "meta=recordings" in body and "duration=212" in body and "fingerprint=AQAA-fp" in body
    assert "KEY" not in req.full_url and seen["timeout"] == 10


def test_compressed_fingerprint_runs_fpcalc_without_raw(tmp_path, monkeypatch):
    calls = []

    class Done:
        stdout = json.dumps({"duration": 211.6, "fingerprint": "AQAD"})

    monkeypatch.setattr(acoustid.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)) or Done())
    assert acoustid.compressed_fingerprint(tmp_path / "a.flac") == (212, "AQAD")
    cmd, kw = calls[0]
    assert cmd[:4] == ["fpcalc", "-json", "-length", "120"] and "-raw" not in cmd
    assert kw["stdin"] is not None and kw["encoding"] == "utf-8" and kw["errors"] == "replace"


@pytest.fixture(scope="module")
def audio(tmp_path_factory):
    return make_audio(tmp_path_factory.mktemp("aid") / "a.flac")


def test_verify_records_acoustid_and_fails_only_on_disagreement(audio):
    look = lambda p: [{"id": "r1", "title": "T", "score": 0.9}]
    v = verify(audio, tier="medium", recording_id="r1", lookup=look)
    assert v.ok, v.problems
    assert v.measurements["acoustid"]["recording_id"] == "r1"
    v = verify(audio, tier="medium", recording_id="r2", lookup=look)
    assert not v.ok and any("not recording r2" in p for p in v.problems)
    assert verify(audio, tier="medium", recording_id=None, lookup=look).ok


def test_verify_lookup_error_is_a_warning(audio):
    def down(p):
        raise urllib.error.URLError("down")

    v = verify(audio, tier="medium", recording_id="r1", lookup=down)
    assert v.ok and any("AcoustID lookup failed" in w for w in v.warnings)
    assert "error" in v.measurements["acoustid"]


def test_verify_empty_lookup_warns_and_never_fails(audio):
    v = verify(audio, tier="medium", recording_id="r1", lookup=lambda p: [])
    assert v.ok and "fingerprint not in AcoustID" in v.warnings
    assert v.measurements["acoustid"]["recording_id"] is None


def test_verify_without_a_tier_skips_the_lookup(audio):
    def boom(p):
        raise AssertionError("lookup must not run without a tier")

    assert verify(audio, lookup=boom).ok


def test_parse_keeps_the_acoustid_track_id():
    resp = json.loads((FIXTURES / "acoustid_lookup.docs-example.json").read_text())
    assert acoustid.parse(resp)[0]["acoustid"] == resp["results"][0]["id"]


# ── the cache beside the proposal and the 3 req/s spacing (M9 §8a) ──────────────────────────────────────────────

DOCS = (FIXTURES / "acoustid_lookup.docs-example.json").read_bytes()


def docs_opener(calls):
    """The documented example as every answer; each request is recorded."""
    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return DOCS

    def opener(req, timeout):
        calls.append(req)
        return Resp()
    return opener


@pytest.fixture
def stub_fp(monkeypatch):
    prints = []
    monkeypatch.setattr(acoustid, "compressed_fingerprint", lambda path: prints.append(path) or (212, "AQAA-fp"))
    return prints


def lines(path):
    return [json.loads(x) for x in path.read_text().splitlines()]


def test_a_cached_file_is_neither_fingerprinted_nor_looked_up_again(tmp_path, stub_fp):
    song = tmp_path / "a.flac"
    song.write_bytes(b"audio")
    calls, cache = [], tmp_path / "out" / "acoustid-cache.jsonl"
    look = acoustid.make_lookup("KEY", cache=acoustid.Cache(cache), opener=docs_opener(calls), sleep=lambda s: None)
    first = look(song)
    assert first == acoustid.parse(json.loads(DOCS)) and first[0]["id"] == "cd2e7c47-16f5-46c6-a37c-a1eb7bf599ff"
    assert look(song) == first
    assert len(calls) == 1 and stub_fp == [song]
    st = song.stat()
    assert lines(cache) == [{"path": str(song), "size": st.st_size, "mtime_ns": st.st_mtime_ns, "recordings": first}]
    # a new Cache over the same file (the next run) answers from disk
    again = acoustid.make_lookup("KEY", cache=acoustid.Cache(cache), opener=docs_opener(calls), sleep=lambda s: None)
    assert again(song) == first and len(calls) == 1


def test_a_changed_mtime_or_size_looks_up_again_and_appends(tmp_path, stub_fp):
    import os
    song = tmp_path / "a.flac"
    song.write_bytes(b"audio")
    calls, cache = [], tmp_path / "acoustid-cache.jsonl"
    look = acoustid.make_lookup("KEY", cache=acoustid.Cache(cache), opener=docs_opener(calls), sleep=lambda s: None)
    look(song)
    st = song.stat()
    os.utime(song, ns=(st.st_atime_ns, st.st_mtime_ns + 1))          # one nanosecond: still a different file
    look(song)
    assert len(calls) == 2 and len(lines(cache)) == 2
    song.write_bytes(b"audio, longer")
    os.utime(song, ns=(st.st_atime_ns, st.st_mtime_ns + 1))          # same mtime as the second, new size
    look(song)
    assert len(calls) == 3 and [x["size"] for x in lines(cache)] == [5, 5, 13]
    # the last line for a key wins when a run reloads it
    reloaded = acoustid.Cache(cache)
    assert reloaded.get(acoustid.Cache.stamp(song)) == lines(cache)[-1]["recordings"]


def test_a_corrupt_or_torn_cache_line_is_skipped_not_fatal(tmp_path, stub_fp):
    song = tmp_path / "a.flac"
    song.write_bytes(b"audio")
    st = song.stat()
    cache = tmp_path / "acoustid-cache.jsonl"
    good = {"path": str(song), "size": st.st_size, "mtime_ns": st.st_mtime_ns, "recordings": [{"id": "r1"}]}
    shapes = [{**good, "recordings": "oops"}, {**good, "recordings": [1]}, {**good, "recordings": [{"title": "t"}]},
              [good]]                                       # valid JSON, wrong shape: skipped like garbage
    cache.write_text("not json\n" + json.dumps({"path": "x"}) + "\n" + json.dumps(good) + "\n"
                     + "".join(json.dumps(x) + "\n" for x in shapes) + "{\"path\": \"TORN-TAIL")
    calls = []
    look = acoustid.make_lookup("KEY", cache=acoustid.Cache(cache), opener=docs_opener(calls), sleep=lambda s: None)
    assert look(song) == [{"id": "r1"}] and calls == []
    other = tmp_path / "b.flac"
    other.write_bytes(b"other")
    look(other)
    assert len(calls) == 1
    text = cache.read_text()
    assert text.endswith("\n") and "TORN-TAIL" not in text             # the torn tail was cut, not merged into
    assert json.loads(text.splitlines()[-1])["path"] == str(other)


def test_lookups_are_spaced_a_third_of_a_second_apart(tmp_path, stub_fp):
    now, slept = [100.0], []
    clock = lambda: now[0]
    sleep = lambda s: (slept.append(s), now.__setitem__(0, now[0] + s))
    calls = []
    songs = []
    for n in "abc":
        songs.append(tmp_path / f"{n}.flac")
        songs[-1].write_bytes(n.encode())
    one = acoustid.make_lookup("KEY", opener=docs_opener(calls), clock=clock, sleep=sleep)
    two = acoustid.make_lookup("KEY", opener=docs_opener(calls), clock=clock, sleep=sleep)
    one(songs[0])
    now[0] += 0.1
    two(songs[1])                     # another lookup, the same process-wide limiter
    one(songs[2])
    assert len(calls) == 3
    assert slept == pytest.approx([1 / 3 - 0.1, 1 / 3])
    assert acoustid.MIN_INTERVAL_S == pytest.approx(1 / 3)
    from sourcing import musicbrainz
    assert acoustid._SHARED is not musicbrainz._SHARED       # two services, two allowances


def test_a_cache_hit_waits_for_no_slot(tmp_path, stub_fp):
    song = tmp_path / "a.flac"
    song.write_bytes(b"audio")
    slept = []
    look = acoustid.make_lookup("KEY", cache=acoustid.Cache(tmp_path / "c.jsonl"), opener=docs_opener([]),
                                clock=lambda: 0.0, sleep=slept.append)
    look(song)
    look(song)
    assert slept == []


def test_the_key_never_reaches_the_cache_file(tmp_path, stub_fp):
    song = tmp_path / "a.flac"
    song.write_bytes(b"audio")
    cache = tmp_path / "acoustid-cache.jsonl"
    acoustid.make_lookup("s3cret-key", cache=acoustid.Cache(cache), opener=docs_opener([]), sleep=lambda s: None)(song)
    assert cache.exists() and "s3cret-key" not in cache.read_text()


def test_a_failed_lookup_is_not_cached(tmp_path, stub_fp):
    song = tmp_path / "a.flac"
    song.write_bytes(b"audio")
    cache = tmp_path / "acoustid-cache.jsonl"

    def down(req, timeout):
        raise urllib.error.URLError("down")
    look = acoustid.make_lookup("KEY", cache=acoustid.Cache(cache), opener=down, sleep=lambda s: None)
    with pytest.raises(urllib.error.URLError):
        look(song)
    assert not cache.exists() or cache.read_text() == ""


def test_the_stamp_is_taken_before_fingerprinting(tmp_path):
    """A file rewritten while it is fingerprinted is asked about again next time, not served a stale answer."""
    song = tmp_path / "a.flac"
    song.write_bytes(b"audio")
    asked = []

    def lookup(path):
        asked.append(path)
        if len(asked) == 1:
            path.write_bytes(b"audio, rewritten meanwhile")
        return [{"id": "r1"}]
    look = acoustid.cached(lookup, acoustid.Cache(tmp_path / "c.jsonl"))
    look(song)
    look(song)
    assert len(asked) == 2


def test_a_cache_that_cannot_be_written_still_returns_the_answer(tmp_path):
    song = tmp_path / "a.flac"
    song.write_bytes(b"audio")
    blocker = tmp_path / "out"
    blocker.write_text("a file where the cache directory should be")
    look = acoustid.cached(lambda path: [{"id": "r1"}], acoustid.Cache(blocker / "acoustid-cache.jsonl"))
    assert look(song) == [{"id": "r1"}]
