"""M5 step 3: fetch verifies at the row's tier and keeps the result on the row; the CLI prints it; the web shows it."""
import json
import shutil

import pytest

from sourcing import cli
from sourcing import fetch as fetch_mod
from sourcing.fake_slskd import FakeSlskdServer
from sourcing.slskd_client import SlskdClient
from sourcing.verify import Verdict
from tests.helpers import make_audio
from tests.test_fetch import GOOD, RESPONSES, good_flac_bytes, new_song, run, world  # noqa: F401  (fixture)
from tests.test_service import get, svc  # noqa: F401  (fixture)

BAD = Verdict(False, ["cutoff ≈16 kHz …"], None, ["4.0s of silence at the start"], {"cutoff_khz": 16, "bits_used": 16})


class Spy:
    def __init__(self, verdict):
        self.verdict, self.calls = verdict, []

    def __call__(self, path, duration, tier=None, reference=None):
        self.calls.append((path.name, duration, tier))
        return self.verdict


def test_fetch_verifies_at_the_rows_tier_and_keeps_the_result(world, tmp_path, monkeypatch):
    spy = Spy(BAD)
    monkeypatch.setattr(fetch_mod, "verify", spy)                      # the default verifier is sourcing.verify.verify
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: good_flac_bytes(tmp_path)}) as srv:
        r = fetch_mod.fetch("s4", store=world["store"], slskd=SlskdClient(srv.url, "k"),
                            navidrome=world["client"], reconciler=world["rec"], music_root=world["music"],
                            downloads_root=world["dl"], approve=True, poll_s=0.01, download_timeout_s=1, scan_timeout_s=1)
    assert spy.calls == [("03 - Good Times.flac", 501, "crate")]          # crate rows are crate
    assert r.status == "failed" and r.reason == "cutoff ≈16 kHz …"
    v = world["store"].verification("s4")
    assert v["ok"] is False and v["tier"] == "crate" and v["file"] == "03 - Good Times.flac"
    assert v["measurements"] == {"cutoff_khz": 16, "bits_used": 16} and v["warnings"] == ["4.0s of silence at the start"]
    row = next(w for w in world["store"].wanted() if w["song_id"] == "s4")     # failed rows stay in the queue
    assert row["verify"]["measurements"]["cutoff_khz"] == 16


def test_fetch_keeps_a_passing_result_too_and_uses_an_external_rows_tier(world, tmp_path):
    ext = world["store"].add_external_wanted("Chic", "Good Times", duration_s=501, tier="high")
    spy = Spy(Verdict(True, [], None, [], {"cutoff_khz": 20}))
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True, wanted_id=ext, verifier=spy)
    assert r.status == "ok" and spy.calls[0][2] == "high"
    assert world["store"].verification(ext)["measurements"] == {"cutoff_khz": 20}


def test_wanted_api_carries_the_verification(svc):  # noqa: F811
    fake, app, srv = svc
    app.store.set_verification("ext-1", {"ok": False, "tier": "crate", "problems": ["x"], "warnings": [],
                                         "measurements": {"cutoff_khz": 16}, "file": "a.flac"})
    ext = app.store.add_external_wanted("Chic", "Good Times", duration_s=501)
    assert ext == "ext-1"
    s, _, w = get(srv.url + "/api/wanted")
    assert next(t for t in w if t["song_id"] == ext)["verify"]["measurements"] == {"cutoff_khz": 16}
    assert all("verify" in t for t in w)                               # None when never verified


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")
def test_cli_verify_with_tier_prints_measurements_and_json(tmp_path, capsys):
    fake = make_audio(tmp_path / "fake.flac", via_mp3_kbps=128)
    assert cli.main(["verify", str(fake), "--duration", "8", "--tier", "crate"]) == 2
    out = capsys.readouterr().out
    assert out.startswith("BAD ") and "cutoff" in out and "16 kHz" in out and "tier crate" in out
    assert cli.main(["verify", str(fake), "--duration", "8", "--tier", "low", "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["ok"] and d["measurements"]["cutoff_khz"] == 16 and d["warnings"]


@pytest.mark.skipif(not shutil.which("fpcalc"), reason="fpcalc not on PATH")
def test_cli_verify_reference(tmp_path, capsys):
    a = make_audio(tmp_path / "a.flac", seconds=20)
    b = make_audio(tmp_path / "b.flac", seconds=20, seed=9, color="brown")
    assert cli.main(["verify", str(b), "--tier", "low", "--reference", str(a)]) == 2
    assert "different recording" in capsys.readouterr().out
