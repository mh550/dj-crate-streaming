from pathlib import Path

import pytest

from crates.store import CrateStore
from sourcing import cli
from sourcing.policy import IMPORT_TIER
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


def test_seed_spotify_album_records_one_request(tmp_path, monkeypatch, capsys):
    import json
    from tests.helpers import FIXTURES
    db = tmp_path / "crates.db"; monkeypatch.setenv("CRATES_DB", str(db))
    entity = json.loads((FIXTURES / "spotify_embed_album_al-green-still-in-love.json").read_text())
    monkeypatch.setattr(cli, "fetch_entity", lambda url: entity)
    url = "https://open.spotify.com/album/2nTlIPIQ7fHOnNN7BRch0Z"
    assert cli.main(["seed-spotify", url]) == 0
    store = CrateStore(db)
    [req] = store.requests()
    assert f"request {req['id']}: Al Green \u2013 I'm Still in Love With You (9 rows)" in capsys.readouterr().out
    w = store.wanted()
    assert len(w) == 9 and {r["request_id"] for r in w} == {req["id"]}
    assert sorted(r["track_no"] for r in w) == list(range(1, 10))
    assert {r["tier"] for r in w} == {IMPORT_TIER}
    assert cli.main(["seed-spotify", url]) == 0                     # again: no second request, no second row
    store = CrateStore(db)
    assert len(store.requests()) == 1 and len(store.wanted()) == 9


def test_seed_spotify_track_records_one_track_request(tmp_path, monkeypatch, capsys):
    db = tmp_path / "crates.db"; monkeypatch.setenv("CRATES_DB", str(db))
    entity = {"type": "track", "name": "Love And Happiness", "uri": "spotify:track:6NW0y8AxOfqqC7FxRjWTGF",
              "artists": [{"name": "Al Green"}], "duration": 303306}
    monkeypatch.setattr(cli, "fetch_entity", lambda url: entity)
    assert cli.main(["seed-spotify", "https://open.spotify.com/track/6NW0y8AxOfqqC7FxRjWTGF", "--tier", "crate"]) == 0
    [req] = CrateStore(db).requests()
    assert f"request {req['id']}: Al Green \u2013 Love And Happiness (1 row)" in capsys.readouterr().out
    assert req["kind"] == "track" and [r["tier"] for r in req["rows"]] == ["crate"]


ALBUM_URL = "https://open.spotify.com/album/2nTlIPIQ7fHOnNN7BRch0Z"


def _seed_album(tmp_path, monkeypatch):
    import json
    from tests.helpers import FIXTURES
    db = tmp_path / "crates.db"; monkeypatch.setenv("CRATES_DB", str(db))
    monkeypatch.delenv("MUSICBRAINZ_CACHE", raising=False)
    entity = json.loads((FIXTURES / "spotify_embed_album_al-green-still-in-love.json").read_text())
    monkeypatch.setattr(cli, "fetch_entity", lambda url: entity)
    made = []

    def client(**kw):                                   # cli.MusicBrainz, offline: the captured search and release
        from tests.test_requests import MusicBrainzStub, stub_mb
        made.append(kw)
        return stub_mb(MusicBrainzStub())
    monkeypatch.setattr(cli, "MusicBrainz", client)
    return db, made


def test_seed_spotify_album_with_musicbrainz_stores_the_release(tmp_path, monkeypatch, capsys):
    db, made = _seed_album(tmp_path, monkeypatch)
    assert cli.main(["seed-spotify", ALBUM_URL, "--musicbrainz"]) == 0
    [req] = CrateStore(db).requests()
    assert req["mb_release_id"] == "3c9a52ee-ee0a-3362-a563-d9d28b02a53e"
    assert all(r["mb_recording_id"] for r in req["rows"])
    out = capsys.readouterr().out
    assert "(9 rows)" in out and "musicbrainz release 3c9a52ee-ee0a-3362-a563-d9d28b02a53e" in out
    assert made == [{"cache": None}]


def test_seed_spotify_album_uses_the_musicbrainz_cache_from_the_environment(tmp_path, monkeypatch, capsys):
    db, made = _seed_album(tmp_path, monkeypatch)
    monkeypatch.setenv("MUSICBRAINZ_CACHE", str(tmp_path / "mb.jsonl"))
    assert cli.main(["seed-spotify", ALBUM_URL]) == 0
    assert made == [{"cache": tmp_path / "mb.jsonl"}] and CrateStore(db).requests()[0]["mb_release_id"]


def test_seed_spotify_album_without_musicbrainz_asks_nothing(tmp_path, monkeypatch, capsys):
    db, made = _seed_album(tmp_path, monkeypatch)
    assert cli.main(["seed-spotify", ALBUM_URL]) == 0
    assert made == [] and CrateStore(db).requests()[0]["mb_release_id"] is None
    assert "musicbrainz" not in capsys.readouterr().out


def test_seed_spotify_album_without_a_match_or_with_musicbrainz_down_keeps_the_request(tmp_path, monkeypatch, capsys):
    from sourcing.musicbrainz import MusicBrainzError
    db, made = _seed_album(tmp_path, monkeypatch)

    class Down:
        def release_search(self, artist, album, limit=25):
            raise MusicBrainzError("MusicBrainz request failed (URLError): release")
    monkeypatch.setattr(cli, "MusicBrainz", lambda **kw: Down())
    assert cli.main(["seed-spotify", ALBUM_URL, "--musicbrainz"]) == 0
    captured = capsys.readouterr()
    assert "(9 rows)" in captured.out and "MusicBrainz request failed" in captured.err
    [req] = CrateStore(db).requests()
    assert req["mb_release_id"] is None and len(req["rows"]) == 9

    class Nothing:
        def release_search(self, artist, album, limit=25):
            return []

        def release(self, mbid):
            return None
    monkeypatch.setattr(cli, "MusicBrainz", lambda **kw: Nothing())
    assert cli.main(["seed-spotify", ALBUM_URL, "--musicbrainz"]) == 0
    assert "no MusicBrainz release matches its 9 rows one to one" in capsys.readouterr().out


def test_seed_spotify_album_with_an_unusable_musicbrainz_cache_keeps_the_request(tmp_path, monkeypatch, capsys):
    db, _ = _seed_album(tmp_path, monkeypatch)
    from sourcing.musicbrainz import MusicBrainz
    monkeypatch.setattr(cli, "MusicBrainz", MusicBrainz)
    (tmp_path / "cache-dir").mkdir()
    monkeypatch.setenv("MUSICBRAINZ_CACHE", str(tmp_path / "cache-dir"))           # a directory: reading it fails
    assert cli.main(["seed-spotify", ALBUM_URL]) == 0
    assert "goes on without MusicBrainz ids" in capsys.readouterr().err
    assert len(CrateStore(db).requests()[0]["rows"]) == 9


def test_seed_spotify_playlist_with_musicbrainz_asks_nothing(tmp_path, monkeypatch, capsys):
    db = tmp_path / "crates.db"; monkeypatch.setenv("CRATES_DB", str(db))
    entity = {"name": "Test", "trackList": [{"title": "Good Times", "subtitle": "Chic", "duration": 501_000}]}
    monkeypatch.setattr(cli, "fetch_entity", lambda url: entity)
    monkeypatch.setattr(cli, "MusicBrainz", lambda **kw: pytest.fail("MusicBrainz asked for a playlist"))
    assert cli.main(["seed-spotify", "https://open.spotify.com/playlist/abc", "--musicbrainz"]) == 0


def test_spotify_csv_refuses_a_track_url(monkeypatch, tmp_path):
    from sourcing import spotify_csv
    monkeypatch.setattr(spotify_csv, "fetch_entity", lambda url: {"type": "track", "name": "x"})
    with pytest.raises(SystemExit, match="seed-spotify"):
        spotify_csv.main(["https://open.spotify.com/track/abc", "-d", str(tmp_path)])


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


# --- S3-04: `sourcing.cli request add|list|show|preview|approve`, the shell's /api/requests (CrateApp's methods)

import json                                                   # noqa: E402

from crates.service import Config, CrateApp                   # noqa: E402
from tests.helpers import FIXTURES                            # noqa: E402
from tests.test_album_job import DIR, PEER, album_folder      # noqa: E402

TRACK_URL = "https://open.spotify.com/track/6NW0y8AxOfqqC7FxRjWTGF"
ROW_1 = "  01 ext-1  I'm Still In Love With You  needs_source"


def _album_entity():
    return json.loads((FIXTURES / "spotify_embed_album_al-green-still-in-love.json").read_text())


@pytest.fixture
def rq_cli(tmp_path, monkeypatch, capsys):
    """A fake Navidrome in the environment, crates.db under tmp_path, Spotify stubbed (`spotify["entity"]`), no
    slskd and no MusicBrainz cache; `run(*args)` → (exit code, stdout, stderr)."""
    db = tmp_path / "crates.db"
    for k in ("SLSKD_URL", "SLSKD_API_KEY", "MUSICBRAINZ_CACHE"):
        monkeypatch.delenv(k, raising=False)
    spotify = {"entity": _album_entity(), "calls": 0}

    def fetch(url):
        spotify["calls"] += 1
        return spotify["entity"]
    monkeypatch.setattr(cli, "fetch_entity", fetch)
    from tests.test_requests import MusicBrainzStub, stub_mb
    monkeypatch.setattr(cli, "MusicBrainz", lambda **kw: stub_mb(MusicBrainzStub()))   # offline: the captured CD
    with FakeSubsonicServer() as nd:
        _env(monkeypatch, nd, db)

        def run(*args):
            rc = cli.main(["request", *args])
            out = capsys.readouterr()
            return rc, out.out, out.err
        run.db, run.nd, run.spotify = db, nd, spotify
        yield run


def _app(db):
    """The crate service's view of the same database (what /api/requests answers)."""
    return CrateApp(Config.from_env(), store=CrateStore(db))


def test_request_add_prints_the_request_and_its_rows_and_again_finds_it(rq_cli):
    rc, out, _ = rq_cli("add", ALBUM_URL)
    lines = out.splitlines()
    assert rc == 0 and lines[0] == "request 1: Al Green – I'm Still in Love With You (album, 9 rows, 0 in library)"
    assert lines[1] == ROW_1 and len(lines) == 10 and lines[9].startswith("  09 ext-9  ")
    rc, again, _ = rq_cli("add", ALBUM_URL + "?si=abc")
    assert rc == 0 and again.splitlines()[0] == lines[0] + "; already requested"
    assert again.splitlines()[1:] == lines[1:]
    assert len(CrateStore(rq_cli.db).requests()) == 1 and rq_cli.spotify["calls"] == 2


def test_request_add_marks_the_rows_the_library_has(rq_cli):
    from tests.test_requests_api import library_song
    row5 = _album_entity()["trackList"][4]
    library_song(rq_cli.nd, "ag5", row5["title"], row5["duration"] // 1000)
    rc, out, _ = rq_cli("add", ALBUM_URL)
    assert rc == 0 and "(album, 9 rows, 1 in library)" in out
    assert f"  05 ext-5  {row5['title']}  ok" in out.splitlines()
    assert CrateStore(rq_cli.db).find_wanted("ext-5")["library_song_id"] == "ag5"


def test_request_add_a_track_and_a_bad_link(rq_cli):
    t = _album_entity()["trackList"][2]
    rq_cli.spotify["entity"] = {**t, "type": "track", "name": t["title"], "artists": [{"name": t["subtitle"]}]}
    rc, out, _ = rq_cli("add", TRACK_URL)
    assert rc == 0 and out.splitlines()[0] == f"request 1: Al Green – {t['title']} (track, 1 row, 0 in library)"
    assert out.splitlines()[1] == f"  -- ext-1  Al Green – {t['title']}  needs_source"
    rc, out, err = rq_cli("add", "https://music.apple.com/us/album/x/1")
    assert (rc, out) == (1, "") and err.strip() == "unknown link kind: music.apple.com"


def test_request_add_json_is_the_apis_shape(rq_cli):
    rc, out, _ = rq_cli("add", ALBUM_URL, "--json")
    body = json.loads(out)
    assert rc == 0 and set(body) == {"request", "rows"} and body["request"]["id"] == 1
    assert body["request"]["mbReleaseId"] == "3c9a52ee-ee0a-3362-a563-d9d28b02a53e"     # matched at add (S2-03)
    detail = _app(rq_cli.db).request_detail("1")
    assert body["request"] == detail["request"]
    assert body["rows"] == [{k: v for k, v in r.items() if k != "approval"} for r in detail["rows"]]


def test_request_add_a_musicbrainz_release_link(rq_cli, monkeypatch):
    from sourcing.musicbrainz import MusicBrainz
    from tests.test_requests_api import RELEASE_ID, MusicBrainzStub
    monkeypatch.setattr(cli, "MusicBrainz", lambda **kw: MusicBrainz(opener=MusicBrainzStub(), sleep=lambda s: None,
                                                                    min_interval_s=0))
    rc, out, _ = rq_cli("add", f"https://musicbrainz.org/release/{RELEASE_ID}")
    assert rc == 0 and out.startswith("request 1: Al Green – ") and "(album, 9 rows, 0 in library)" in out
    assert CrateStore(rq_cli.db).request(1)["mb_release_id"] == RELEASE_ID and rq_cli.spotify["calls"] == 0


def test_request_list_and_show(rq_cli):
    assert rq_cli("list") == (0, "no requests\n", "")
    rq_cli("add", ALBUM_URL)
    t = {"title": "Tired of Being Alone"}                       # not on the album: a request of its own
    rq_cli.spotify["entity"] = {"type": "track", "name": t["title"], "uri": "spotify:track:6NW0y8AxOfqqC7FxRjWTGF",
                                "artists": [{"name": "Al Green"}], "duration": 170_000}
    rq_cli("add", TRACK_URL)
    store = CrateStore(rq_cli.db)
    store.set_wanted_status("ext-2", "failed", "no source: /srv/music/Al_Green/x.flac was a transcode")
    store.db.execute("UPDATE requests SET mb_release_id='3c9a52ee-ee0a-3362-a563-d9d28b02a53e' WHERE id=1")
    store.commit()
    rc, out, _ = rq_cli("list")
    assert rc == 0 and out.splitlines() == [
        f"request 2: Al Green – {t['title']} (track, 1 row, 0 in library) open",
        "request 1: Al Green – I'm Still in Love With You (album, 9 rows, 0 in library) open"]
    rc, out, _ = rq_cli("list", "--json")
    assert rc == 0 and json.loads(out) == _app(rq_cli.db).requests()

    rc, out, _ = rq_cli("show", "1")
    lines = out.splitlines()
    assert rc == 0 and lines[0] == "request 1: Al Green – I'm Still in Love With You (album, 9 rows, 0 in library) open"
    assert "  source https://open.spotify.com/album/2nTlIPIQ7fHOnNN7BRch0Z" in lines
    assert "  musicbrainz release 3c9a52ee-ee0a-3362-a563-d9d28b02a53e" in lines
    assert ROW_1 + "  recording cdac1a50-8ba6-4edd-8137-618928580d38" in lines and "/srv/music" not in out
    assert any(x.startswith("  02 ext-2  ") and "  failed: no source: x.flac was a transcode  recording " in x
               for x in lines)
    assert lines[-1] == "no plan yet: request preview 1"
    rc, out, _ = rq_cli("show", "1", "--json")
    assert rc == 0 and json.loads(out) == _app(rq_cli.db).request_detail("1")
    assert rq_cli("show", "99") == (1, "", "no request #99\n")
    assert rq_cli("show", "x")[::2] == (1, "request id must be a number, not 'x'\n")


def test_request_commands_need_crates_db(rq_cli, monkeypatch):
    monkeypatch.delenv("CRATES_DB")
    rc, out, err = rq_cli("list")
    assert rc == 1 and "set CRATES_DB" in err and "docker compose exec -T worker python -m sourcing.cli request" in err


def test_request_preview_without_slskd_exits_2(rq_cli):
    rq_cli("add", ALBUM_URL)
    assert rq_cli("preview", "1") == (2, "", "preview needs --slskd or $SLSKD_URL\n")


@pytest.fixture
def album_slskd(rq_cli, tmp_path, monkeypatch):
    """rq_cli with the album requested and a fake slskd in the environment answering with PEER's folder minus 9."""
    rq_cli("add", ALBUM_URL)
    rows = CrateStore(rq_cli.db).request(1)["rows"]
    resp, _ = album_folder(tmp_path, rows, skip={9})
    with FakeSlskdServer([resp], tmp_path / "dl", files={}) as sk:
        monkeypatch.setenv("SLSKD_URL", sk.url); monkeypatch.setenv("SLSKD_API_KEY", sk.api_key)
        yield sk


def test_request_preview_prints_the_plan_without_peers_and_show_has_it(rq_cli, album_slskd):
    rc, out, _ = rq_cli("preview", "1")
    first = "Al Green - I'm Still in Love With You - 01 - I'm Still In Love With You.flac"
    assert rc == 0 and out.splitlines()[0].startswith("folder 1: 8 of 9")
    assert f"  1. I'm Still In Love With You → {first}" in out.splitlines()
    assert "per track: 1 of 9" in out
    assert PEER not in out and DIR not in out and "@@" not in out
    assert album_slskd.searched == ["Al Green I'm Still in Love With You"] and album_slskd.enqueued == []
    rc, shown, _ = rq_cli("show", "1")
    assert rc == 0 and "plan:" in shown.splitlines() and f"  1. I'm Still In Love With You → {first}" in shown
    rc, js, _ = rq_cli("show", "1", "--json")
    assert json.loads(js)["preview"]["folders"][0]["coverage"] == "8 of 9"
    rc, js, _ = rq_cli("preview", "1", "--json")
    assert rc == 0 and json.loads(js) == {"plan": _app(rq_cli.db).request_detail("1")["preview"]}


def test_request_approve_records_approvals_and_downloads_nothing(rq_cli, album_slskd):
    rq_cli("preview", "1")
    rc, out, _ = rq_cli("approve", "1")
    assert (rc, out) == (0, "approved 9 rows of request 1; the worker downloads them on its next tick\n")
    pending = CrateStore(rq_cli.db).pending_approvals()
    assert len(pending) == 9 and {a["purpose"] for a in pending} == {"album"}
    assert album_slskd.enqueued == []                               # no POST /transfers: the worker downloads
    rc, out, err = rq_cli("approve", "1", "--json")
    assert rc == 0 and [a["wantedId"] for a in json.loads(out)["approved"]] == [f"ext-{n}" for n in range(1, 10)]
    assert PEER not in out


@pytest.mark.parametrize("status", ["sourcing", "verify"])
def test_request_approve_of_a_row_in_progress_prints_the_409_and_exits_1(rq_cli, status):
    rq_cli("add", ALBUM_URL)
    store = CrateStore(rq_cli.db)
    store.set_wanted_status("ext-3", status, "why"); store.commit()
    rc, out, err = rq_cli("approve", "1")
    assert (rc, out) == (1, "") and err == f"ext-3 is {status} (in progress): the worker finishes it\n"
    assert CrateStore(rq_cli.db).pending_approvals() == []


def test_request_approve_of_a_done_request(rq_cli):
    rq_cli("add", ALBUM_URL)
    store = CrateStore(rq_cli.db)
    for n in range(1, 10):
        store.set_wanted_status(f"ext-{n}", "ok", "already in the library")
    store.commit()
    assert rq_cli("approve", "1") == (1, "", "nothing to approve\n")


def test_request_add_a_playlist_imports_it_and_records_its_request(rq_cli):
    tea = json.loads((FIXTURES / "spotify_embed_tea-tent-1.json").read_text())
    rq_cli.spotify["entity"] = {**tea, "trackList": tea["trackList"][:3]}
    rc, out, _ = rq_cli("add", "https://open.spotify.com/playlist/37i9dQZF1DXtea")
    lines = out.splitlines()
    assert rc == 0 and lines[0] == f"playlist {tea['name']}: 0 matched, 3 wanted, 0 ambiguous"
    assert lines[1] == f"request 1: {tea['name']} (playlist, 3 rows, 0 in library)"
    assert len(lines) == 5 and all(x.startswith("  -- ext-") for x in lines[2:])
    assert rq_cli.spotify["calls"] == 1


def test_request_add_with_navidrome_away_is_one_line_and_exit_1(rq_cli, monkeypatch):
    monkeypatch.setenv("SUBSONIC_URL", "http://127.0.0.1:9")                 # nothing listens: a URLError
    tea = json.loads((FIXTURES / "spotify_embed_tea-tent-1.json").read_text())
    rq_cli.spotify["entity"] = {**tea, "trackList": tea["trackList"][:3]}
    rc, out, err = rq_cli("add", "https://open.spotify.com/playlist/37i9dQZF1DXtea")
    assert (rc, out) == (1, "") and err.startswith("cannot reach Navidrome: ") and len(err.splitlines()) == 1


def test_request_add_a_playlist_when_comment_is_not_kept_is_exit_1(rq_cli, monkeypatch):
    from crates.reconcile import CommentNotKept
    from sourcing import requests as requests_

    def not_kept(*a, **kw):
        raise CommentNotKept("Navidrome did not keep the comment")
    monkeypatch.setattr(requests_, "add_link", not_kept)
    assert rq_cli("add", ALBUM_URL) == (1, "", "Navidrome did not keep the comment\n")


def test_request_preview_with_slskd_away_or_without_a_key(rq_cli, album_slskd, monkeypatch):
    monkeypatch.delenv("SLSKD_API_KEY")
    assert rq_cli("preview", "1") == (2, "", "preview needs --api-key or $SLSKD_API_KEY\n")
    monkeypatch.setenv("SLSKD_API_KEY", album_slskd.api_key)
    monkeypatch.setenv("SLSKD_URL", "http://127.0.0.1:9")
    rc, out, err = rq_cli("preview", "1")
    assert (rc, out) == (1, "") and err.startswith("cannot reach slskd (") and len(err.splitlines()) == 1


def test_request_show_says_when_the_plan_went_stale(rq_cli, album_slskd):
    rq_cli("preview", "1")
    store = CrateStore(rq_cli.db)
    cache = store.preview("req-1")
    store.set_preview("req-1", cache | {"at": 0}); store.commit()
    rc, out, _ = rq_cli("show", "1")
    assert rc == 0 and "plan (stale: a folder failed; the job plans again):" in out.splitlines()


def test_a_playlist_request_shows_no_artist_and_its_per_track_plan(rq_cli, album_slskd):
    tea = json.loads((FIXTURES / "spotify_embed_tea-tent-1.json").read_text())
    rq_cli.spotify["entity"] = {**tea, "trackList": tea["trackList"][:3]}
    rc, out, _ = rq_cli("add", "https://open.spotify.com/playlist/37i9dQZF1DXtea")
    assert rc == 0 and out.splitlines()[1] == f"request 2: {tea['name']} (playlist, 3 rows, 0 in library)"
    rc, out, _ = rq_cli("preview", "2")
    assert (rc, out) == (0, "per track: 3 rows\n")
    assert rq_cli("list")[1].splitlines()[0] == f"request 2: {tea['name']} (playlist, 3 rows, 0 in library) open"
