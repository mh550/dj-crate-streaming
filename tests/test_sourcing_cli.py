from pathlib import Path

import pytest

from crates.store import CrateStore
from sourcing import cli
from sourcing.fake_slskd import FakeSlskdServer
from subsonic.fake_server import FakeSubsonicServer
from tests.helpers import load_responses

RESPONSES = load_responses()


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
    assert rc == 0 and "pick: 03 - Good Times.flac" in out and "vinylhead77" not in out and "--approve" in out and sl.enqueued == []


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


def _env(monkeypatch, nd, db):
    monkeypatch.setenv("SUBSONIC_URL", nd.url); monkeypatch.setenv("SUBSONIC_USER", "demo"); monkeypatch.setenv("SUBSONIC_PASS", "demo")
    monkeypatch.setenv("CRATES_DB", str(db))


def test_import_playlist_from_report_and_two_urls(tmp_path, monkeypatch, capsys):
    db = tmp_path / "crates.db"
    report = tmp_path / "nothin to it.txt"
    report.write_text("Download Report - x\n---\n\n[SUCCESS] Good Times - Chic\n[SUCCESS] Nope - Nobody\n")
    with FakeSubsonicServer() as nd:
        _env(monkeypatch, nd, db)
        rc = cli.main(["import-playlist", str(report)])
        out = capsys.readouterr().out
        assert rc == 0 and "nothin to it: 1 matched, 1 wanted, 0 ambiguous" in out
        from subsonic.client import SubsonicClient
        c = SubsonicClient(nd.url, "demo", "demo")
        pl = next(p for p in c.playlists() if p.name == "nothin to it")
        assert pl.public and [e.id for e in c.playlist(pl.id).entries] == ["s1"]
        w = CrateStore(db).external_for_playlist(pl.id)
        assert [(x["title"], x["position"]) for x in w] == [("Nope", 2)]

        e1 = {"name": "Tea tent", "trackList": [{"title": "I Feel Love", "subtitle": "Donna Summer", "duration": 356_000, "uri": "spotify:track:a"}]}
        e2 = {"name": "Tea tent2222", "trackList": [{"title": "Strings of Life", "subtitle": "Rhythim Is Rhythim", "duration": 480_000, "uri": "spotify:track:b"}]}
        monkeypatch.setattr(cli, "fetch_entity", lambda url: e1 if url.endswith("/one") else e2)
        rc = cli.main(["import-playlist", "--name", "Tea tent", "https://open.spotify.com/playlist/one", "https://open.spotify.com/playlist/two"])
        assert rc == 0 and "Tea tent: 2 matched, 0 wanted, 0 ambiguous" in capsys.readouterr().out
        pl = next(p for p in c.playlists() if p.name == "Tea tent")
        assert [e.id for e in c.playlist(pl.id).entries] == ["s2", "s5"]


def test_import_playlist_rejects_two_sources_without_name_and_bad_url(tmp_path, monkeypatch, capsys):
    db = tmp_path / "crates.db"
    with FakeSubsonicServer() as nd:
        _env(monkeypatch, nd, db)
        assert cli.main(["import-playlist", "a.txt", "b.txt"]) == 1
        assert "--name" in capsys.readouterr().err
        def boom(url): raise SystemExit("embed page had no __NEXT_DATA__ (private playlist, or Spotify changed the page)")
        monkeypatch.setattr(cli, "fetch_entity", boom)
        assert cli.main(["import-playlist", "https://open.spotify.com/playlist/private"]) == 1
        assert "private playlist" in capsys.readouterr().err
        assert len(nd.state.playlists) == 3 and not db.exists()


def test_import_playlist_bad_csv_header_exits_cleanly(tmp_path, monkeypatch, capsys):
    db = tmp_path / "crates.db"
    bad = tmp_path / "weird.csv"; bad.write_text("Song,Who\nGood Times,Chic\n")
    with FakeSubsonicServer() as nd:
        _env(monkeypatch, nd, db)
        assert cli.main(["import-playlist", str(bad)]) == 1
        assert "weird.csv" in capsys.readouterr().err and not db.exists()


def test_import_playlist_name_collision_needs_merge(tmp_path, monkeypatch, capsys):
    db = tmp_path / "crates.db"
    report = tmp_path / "Disco Edits.txt"; report.write_text("[SUCCESS] Good Times - Chic\n")
    with FakeSubsonicServer() as nd:
        _env(monkeypatch, nd, db)
        assert cli.main(["import-playlist", str(report)]) == 1                     # "Disco Edits" exists in the fake, not ours
        assert "--merge" in capsys.readouterr().err
        assert cli.main(["import-playlist", "--merge", str(report)]) == 0
        assert "updated existing playlist" in capsys.readouterr().out


def test_approve_of_a_non_retryable_review_row_is_refused_and_changes_nothing(tmp_path, monkeypatch, capsys):
    db = tmp_path / "crates.db"; monkeypatch.setenv("CRATES_DB", str(db))
    store = CrateStore(db)
    ext = store.add_external_wanted("Twain", "The Magician")
    store.set_external_status(ext, "review", "ambiguous (2 library versions): a, b"); store.commit()
    tier = store.external(ext)["tier"]
    store.db.close()
    rc = cli.main(["fetch", "--wanted", ext, "--approve", "--tier", "high" if tier != "high" else "low"])
    err = capsys.readouterr().err
    store = CrateStore(db)
    assert rc == 1 and "needs a pick first" in err
    assert store.approval(ext) is None and store.external(ext)["tier"] == tier


def test_rank_download_is_gone_and_names_preview_and_approve(capsys):
    fx = str(Path(__file__).resolve().parent.parent / "fixtures" / "search_responses.sample.json")
    args = ["rank", "--fixture", fx, "--artist", "Chic", "--title", "Good Times", "--duration", "501"]
    with pytest.raises(SystemExit) as e:
        cli.main(args + ["--download"])
    err = capsys.readouterr().err
    assert e.value.code == 2
    assert "rank no longer downloads: use Preview + Approve in the web client (the worker downloads, D23)" in err
    assert cli.main(args) == 0                                     # without it, rank still ranks the fixture
    assert "03 - Good Times.flac" in capsys.readouterr().out
