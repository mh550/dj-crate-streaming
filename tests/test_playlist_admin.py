"""crates.cli rename / merge / delete: Michael's playlist decisions run as tested commands (2026-10-15 review)."""
import pytest

from subsonic.fake_server import FakeSubsonicServer


@pytest.fixture
def srv(monkeypatch, tmp_path):
    with FakeSubsonicServer() as s:
        monkeypatch.setenv("SUBSONIC_URL", s.url); monkeypatch.setenv("SUBSONIC_USER", "demo"); monkeypatch.setenv("SUBSONIC_PASS", "demo")
        monkeypatch.setenv("CRATES_DB", str(tmp_path / "c.db"))
        yield s


def test_rename(srv, capsys):
    from crates.cli import main
    assert main(["rename", "pl-1", "Disco Edits (old)"]) == 0
    assert srv.state.playlists["pl-1"]["name"] == "Disco Edits (old)"
    assert "Disco Edits → Disco Edits (old)" in capsys.readouterr().out


def test_merge_appends_missing_songs_in_order_and_keeps_the_source(srv, capsys):
    from crates.cli import main
    assert main(["merge", "pl-1", "pl-2"]) == 0          # pl-1 s1 s2 s3 + pl-2 s3 s4 s5
    st = srv.state.playlists
    assert st["pl-1"]["songs"] == ["s1", "s2", "s3", "s4", "s5"]   # s3 already there: not doubled
    assert "pl-2" in st
    out = capsys.readouterr().out
    assert "added 2" in out and "1 already" in out


def test_merge_with_delete_removes_the_source(srv):
    from crates.cli import main
    assert main(["merge", "pl-1", "pl-2", "--delete-source"]) == 0
    assert "pl-2" not in srv.state.playlists and srv.state.playlists["pl-1"]["songs"][-1] == "s5"


def test_merge_into_itself_is_refused(srv):
    from crates.cli import main
    assert main(["merge", "pl-1", "pl-1"]) == 1
    assert srv.state.playlists["pl-1"]["songs"] == ["s1", "s2", "s3"]


def test_delete_names_the_playlist(srv, capsys):
    from crates.cli import main
    assert main(["delete", "pl-3"]) == 0
    assert "pl-3" not in srv.state.playlists
    assert "deleted Sunday Listening (1 songs)" in capsys.readouterr().out
