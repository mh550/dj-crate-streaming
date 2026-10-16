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
