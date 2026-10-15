"""M4 step 2 (spec §1, D9): the tier travels — wanted rows, CLI, fetch, stream setting."""
import json
import sqlite3

import pytest

from crates.reconcile import Reconciler
from crates.store import CrateStore
from sourcing import cli
from sourcing.fake_slskd import FakeSlskdServer
from sourcing.fetch import fetch
from sourcing.policy import STREAM, TIERS
from sourcing.slskd_client import SlskdClient
from subsonic.client import SubsonicClient
from subsonic.fake_server import FakeSubsonicServer
from tests.test_service import get, post, svc  # noqa: F401  (fixture)
from tests.test_tiers import FAST_MP3, SLOW_FLAC


# --- store
def test_external_rows_default_to_crate_and_take_a_tier():
    st = CrateStore()
    a = st.add_external_wanted("Chic", "Good Times")
    b = st.add_external_wanted("Cerrone", "Supernature", tier="low")
    assert st.external(a)["tier"] == "crate" and st.external(b)["tier"] == "low"
    assert st.add_external_wanted("Chic", "Good Times") == a and st.external(a)["tier"] == "crate"   # none given: unchanged
    st.add_external_wanted("Chic", "Good Times", tier="high")                                       # given: raised
    assert st.external(a)["tier"] == "high"
    assert {w["song_id"]: w["tier"] for w in st.wanted()} == {a: "high", b: "low"}
    with pytest.raises(ValueError):
        st.add_external_wanted("X", "Y", tier="ultra")


def test_old_database_gains_the_tier_column_as_crate(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE external_wanted (id INTEGER PRIMARY KEY, artist TEXT NOT NULL, title TEXT NOT NULL, album TEXT,"
                " year INTEGER, duration INTEGER, source TEXT, status TEXT NOT NULL DEFAULT 'needs_source', reason TEXT,"
                " created_at REAL NOT NULL, updated_at REAL NOT NULL)")
    con.execute("INSERT INTO external_wanted(artist,title,created_at,updated_at) VALUES('Chic','Good Times',0,0)")
    con.commit(); con.close()
    assert CrateStore(db).external("ext-1")["tier"] == "crate"


def test_crate_rows_carry_tier_crate():
    with FakeSubsonicServer() as nd:
        st = CrateStore()
        Reconciler(SubsonicClient(nd.url, "demo", "demo"), st).set_crate("pl-2", True)
        rows = st.wanted()
        assert rows and {r["tier"] for r in rows} == {"crate"}
        assert st.find_wanted(rows[0]["song_id"])["tier"] == "crate"


def test_stream_tier_setting_defaults_to_crate():
    st = CrateStore()
    assert st.stream_tier() == "crate"
    st.set_stream_tier("medium")
    assert st.stream_tier() == "medium"
    with pytest.raises(ValueError):
        st.set_stream_tier("ultra")


def test_stream_mapping_matches_the_spec():
    assert STREAM == {"low": ("opus", 64), "medium": ("opus", 96), "high": ("opus", 160), "crate": ("raw", None)}
    assert list(STREAM) == list(TIERS)


# --- rank --tier
def test_rank_cli_takes_a_tier(tmp_path, capsys):
    fx = tmp_path / "pair.json"; fx.write_text(json.dumps([FAST_MP3, SLOW_FLAC]))
    args = ["rank", "--fixture", str(fx), "--artist", "Chic", "--title", "Good Times", "--duration", "501", "--json"]
    assert cli.main(args + ["--tier", "low"]) == 0
    low = json.loads(capsys.readouterr().out)
    assert cli.main(args) == 0                                     # default: crate
    crate = json.loads(capsys.readouterr().out)
    assert low[0]["username"] == "fastpeer" and crate[0]["username"] == "slowpeer"
    with pytest.raises(SystemExit):
        cli.main(args + ["--tier", "ultra"])


# --- fetch uses the row's tier
@pytest.fixture
def world(tmp_path):
    with FakeSubsonicServer() as nd:
        store = CrateStore()
        client = SubsonicClient(nd.url, "demo", "demo")
        yield dict(nd=nd, store=store, client=client, rec=Reconciler(client, store), music=tmp_path / "m", dl=tmp_path / "dl")


def _fetch(world, wid, **kw):
    with FakeSlskdServer([FAST_MP3, SLOW_FLAC], world["dl"], files={}) as srv:
        return fetch(wid, store=world["store"], slskd=SlskdClient(srv.url, "k"), navidrome=world["client"],
                     reconciler=world["rec"], music_root=world["music"], downloads_root=world["dl"], approve=False,
                     poll_s=0.01, download_timeout_s=1, scan_timeout_s=1, **kw)


def test_fetch_scores_with_the_rows_tier(world):
    low = world["store"].add_external_wanted("Chic", "Good Times", duration_s=501, tier="low")
    assert _fetch(world, low).pick.username == "fastpeer"
    world["store"].add_external_wanted("Chic", "Good Times", tier="crate")
    assert _fetch(world, low).pick.username == "slowpeer"
    assert _fetch(world, low, policy=TIERS["medium"]).pick.username == "fastpeer"     # an explicit policy wins


def _cli_env(monkeypatch, tmp_path, nd, sl):
    for k, v in dict(SUBSONIC_URL=nd.url, SUBSONIC_USER="demo", SUBSONIC_PASS="demo", CRATES_DB=str(tmp_path / "c.db"),
                     SLSKD_URL=sl.url, SLSKD_API_KEY="k", MUSIC_ROOT=str(tmp_path / "m"), DOWNLOADS_ROOT=str(tmp_path / "dl")).items():
        monkeypatch.setenv(k, v)


def test_fetch_cli_tier_overrides_external_and_is_refused_on_crate_rows(tmp_path, monkeypatch, capsys):
    with FakeSubsonicServer() as nd, FakeSlskdServer([FAST_MP3, SLOW_FLAC], tmp_path / "dl", files={}) as sl:
        nd.state.songs["s4"].update(title="Good Times", artist="Chic")
        _cli_env(monkeypatch, tmp_path, nd, sl)
        st = CrateStore(tmp_path / "c.db")
        ext = st.add_external_wanted("Chic", "Good Times", duration_s=501); st.commit()
        assert cli.main(["fetch", "--wanted", ext, "--tier", "low"]) == 0
        assert "pick: fastpeer" in capsys.readouterr().out
        from crates.cli import main as crates_main
        assert crates_main(["toggle", "pl-2", "on"]) == 0
        capsys.readouterr()
        assert cli.main(["fetch", "--wanted", "s4", "--tier", "low"]) == 1
        assert "crate" in capsys.readouterr().err and sl.enqueued == []


def test_seed_spotify_and_import_playlist_take_a_tier(tmp_path, monkeypatch, capsys):
    db = tmp_path / "c.db"; monkeypatch.setenv("CRATES_DB", str(db))
    entity = {"name": "Test", "trackList": [{"title": "Good Times", "subtitle": "Chic", "duration": 501_000}]}
    monkeypatch.setattr(cli, "fetch_entity", lambda url: entity)
    assert cli.main(["seed-spotify", "https://open.spotify.com/playlist/abc", "--tier", "medium"]) == 0
    assert [w["tier"] for w in CrateStore(db).wanted()] == ["medium"]
    report = tmp_path / "r.txt"; report.write_text("[SUCCESS] Nobody Has This - Nobody\n")
    with FakeSubsonicServer() as nd:
        for k, v in dict(SUBSONIC_URL=nd.url, SUBSONIC_USER="demo", SUBSONIC_PASS="demo").items():
            monkeypatch.setenv(k, v)
        assert cli.main(["import-playlist", str(report), "--name", "T", "--tier", "low"]) == 0
    tiers = {w["title"]: w["tier"] for w in CrateStore(db).wanted()}
    assert tiers == {"Good Times": "medium", "Nobody Has This": "low"}


# --- web: the stream tier
def test_stream_tier_endpoint_and_stream_by_tier(svc):  # noqa: F811
    fake, app, srv = svc
    s, _, v = get(srv.url + "/api/stream-tier")
    assert s == 200 and v["tier"] == "crate" and v["tiers"]["high"] == {"format": "opus", "maxBitRate": 160}
    assert v["tiers"]["crate"] == {"format": "raw", "maxBitRate": None}
    assert post(srv.url + "/api/stream-tier", {"tier": "low"}) == (200, {"tier": "low"})
    assert get(srv.url + "/api/stream-tier")[2]["tier"] == "low"
    assert post(srv.url + "/api/stream-tier", {"tier": "ultra"})[0] == 400
    s, h, _ = get(srv.url + "/api/stream/s1?tier=medium", raw=True)
    assert s == 302 and "format=opus" in h["Location"] and "maxBitRate=96" in h["Location"]
    loc = get(srv.url + "/api/stream/s1?tier=crate", raw=True)[1]["Location"]
    assert "format=raw" in loc and "maxBitRate" not in loc
    assert get(srv.url + "/api/stream/s1?tier=ultra", raw=True)[0] == 400
