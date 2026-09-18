import urllib.request

import pytest

from subsonic.client import SubsonicClient, SubsonicError
from subsonic.fake_server import FakeSubsonicServer


@pytest.fixture
def srv():
    with FakeSubsonicServer() as s:
        yield s


def test_token_auth_and_envelope(srv):
    c = SubsonicClient(srv.url, "demo", "demo", client_name="t")
    info = c.ping()
    assert info["openSubsonic"] is True and info["type"] == "fake-navidrome"
    method, q = srv.state.requests[-1]
    assert method == "ping" and set(q) >= {"u", "t", "s", "v", "c", "f"} and "p" not in q
    assert q["c"] == "t" and q["f"] == "json"


def test_wrong_password_is_error_40(srv):
    with pytest.raises(SubsonicError) as ei:
        SubsonicClient(srv.url, "demo", "wrong").ping()
    assert ei.value.code == 40


def test_playlists_and_entries(srv):
    c = SubsonicClient(srv.url, "demo", "demo")
    pls = c.playlists()
    assert [p.name for p in pls] == ["Disco Edits", "Chicago 86", "Sunday Listening"]
    p = c.playlist("pl-1")
    assert [e.suffix for e in p.entries] == ["flac", "flac", "mp3"]
    assert p.entries[1].bit_depth == 24 and p.entries[1].sample_rate == 96000


def test_update_playlist_adds_by_id_removes_by_index(srv):
    c = SubsonicClient(srv.url, "demo", "demo")
    c.update_playlist("pl-1", add_song_ids=["s5"], remove_indexes=[0], comment="hello")
    p = c.playlist("pl-1")
    assert [e.id for e in p.entries] == ["s2", "s3", "s5"] and p.comment == "hello"
    c.update_playlist("pl-1", comment="")
    assert c.playlist("pl-1").comment == ""


def test_create_and_delete_playlist(srv):
    c = SubsonicClient(srv.url, "demo", "demo")
    p = c.create_playlist("New", ["s1", "s4"])
    assert p.song_count == 2
    c.delete_playlist(p.id)
    with pytest.raises(SubsonicError) as ei:
        c.playlist(p.id)
    assert ei.value.code == 70


def test_search_and_song(srv):
    c = SubsonicClient(srv.url, "demo", "demo")
    assert {s.id for s in c.search_songs("feel")} == {"s2", "s4"}
    assert c.song("s3").bit_rate == 320


def test_stream_url_honours_format_and_bitrate(srv):
    c = SubsonicClient(srv.url, "demo", "demo", client_name="phone")
    raw = urllib.request.urlopen(c.stream_url("s1")).read()
    assert raw.endswith(b"raw")
    t = urllib.request.urlopen(c.stream_url("s1", max_bit_rate=128, fmt="opus"))
    assert t.headers["X-Fake-Transcode"] == "transcoded:opus@128" and t.headers["Content-Type"] == "audio/ogg"
    assert urllib.request.urlopen(c.stream_url("s1", fmt="raw")).read().endswith(b"raw")
    # cap above the source bitrate → direct play; cap below → opus (DefaultDownsamplingFormat)
    assert urllib.request.urlopen(c.stream_url("s3", max_bit_rate=320)).headers["X-Fake-Transcode"] == "raw"
    assert urllib.request.urlopen(c.stream_url("s1", max_bit_rate=320)).headers["X-Fake-Transcode"] == "transcoded:opus@320"
    assert urllib.request.urlopen(c.stream_url("s3", fmt="mp3")).headers["X-Fake-Transcode"] == "raw"   # same format
    # a forced per-player profile applies when the request says nothing
    srv.state.players[("demo", "phone")] = {"format": "opus", "maxBitRate": 128}
    assert urllib.request.urlopen(c.stream_url("s1")).headers["X-Fake-Transcode"] == "transcoded:opus@128"
    assert urllib.request.urlopen(c.download_url("s1")).read().endswith(b"original")
    # a Player exists per (user, client name)
    assert ("demo", "phone") in srv.state.players


def test_extensions(srv):
    c = SubsonicClient(srv.url, "demo", "demo")
    assert c.supports("transcodeOffset") and not c.supports("apiKeyAuthentication")
    assert SubsonicClient(srv.url, "nobody", "nothing").extensions()   # reachable without valid credentials
    assert "/rest/ping.view?" in c.url("ping")
