import json
from pathlib import Path

from crates.store import CrateStore
from sourcing import cli
from sourcing.fake_slskd import FakeSlskdServer
from subsonic.fake_server import FakeSubsonicServer

RESPONSES = json.loads(Path("fixtures/search_responses.sample.json").read_text())


def test_fetch_without_approve_prints_pick(tmp_path, monkeypatch, capsys):
    db = tmp_path / "crates.db"
    with FakeSubsonicServer() as nd, FakeSlskdServer(RESPONSES, tmp_path / "dl", files={}) as sl:
        nd.state.songs["s4"].update(title="Good Times", artist="Chic")
        monkeypatch.setenv("SUBSONIC_URL", nd.url); monkeypatch.setenv("SUBSONIC_USER", "demo"); monkeypatch.setenv("SUBSONIC_PASS", "demo")
        monkeypatch.setenv("CRATES_DB", str(db)); monkeypatch.setenv("SLSKD_URL", sl.url); monkeypatch.setenv("SLSKD_API_KEY", "k")
        monkeypatch.setenv("MUSIC_ROOT", str(tmp_path / "music")); monkeypatch.setenv("DOWNLOADS_ROOT", str(tmp_path / "dl"))
        from crates.cli import main as crates_main
        assert crates_main(["toggle", "pl-2", "on"]) == 0
        rc = cli.main(["fetch", "--wanted", "s4"])
    out = capsys.readouterr().out
    assert rc == 0 and "vinylhead77" in out and "--approve" in out and sl.enqueued == []


def test_seed_spotify_adds_external_rows(tmp_path, monkeypatch, capsys):
    db = tmp_path / "crates.db"; monkeypatch.setenv("CRATES_DB", str(db))
    entity = {"name": "Test", "trackList": [{"title": "Good Times", "subtitle": "Chic", "duration": 501_000}]}
    monkeypatch.setattr(cli, "fetch_entity", lambda url: entity)
    rc = cli.main(["seed-spotify", "https://open.spotify.com/playlist/abc"])
    assert rc == 0
    w = CrateStore(db).wanted()
    assert len(w) == 1 and w[0]["artist"] == "Chic" and w[0]["title"] == "Good Times" and w[0]["duration"] == 501
    assert "1 added" in capsys.readouterr().out
    assert cli.main(["seed-spotify", "https://open.spotify.com/playlist/abc"]) == 0      # idempotent
    assert len(CrateStore(db).wanted()) == 1 and "0 added, 1 already queued" in capsys.readouterr().out
