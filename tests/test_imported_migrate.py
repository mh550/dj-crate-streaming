"""N2-03: the one-time move of the `#imported` comment marker into crates.db `imported_playlists` (D33/D37).
A dry run writes nothing; --apply records the row first, then strips the token through write_comment (read back);
another user's playlist and lookalike markers are never written."""
import pytest

from crates import imported as imp
from crates.store import CrateStore
from subsonic.client import SubsonicClient
from subsonic.fake_server import FakeSubsonicServer


@pytest.fixture
def env():
    with FakeSubsonicServer() as srv:
        client = SubsonicClient(srv.url, "demo", "demo")
        yield srv, client, CrateStore()


def set_comment(srv, pid, text):
    srv.state.playlists[pid]["comment"] = text


def comment(srv, pid):
    return srv.state.playlists[pid]["comment"]


def updates(srv):
    return [q for m, q in srv.state.requests if m == "updatePlaylist"]


@pytest.mark.parametrize("old,new", [
    ("#imported", ""),
    ("Tea #imported notes", "Tea notes"),
    ("mine #imported", "mine"),
    ("#imported #tier:medium", "#tier:medium"),
    ("sunset only\n#imported #tier:medium", "sunset only\n#tier:medium"),
    ("x#imported #IMPORTED", "x#imported"),
    ("a\t#imported\tb", "a b"),
    ("#imported-old keep", "#imported-old keep"),
])
def test_strip_marker_removes_whole_tokens_only(old, new):
    assert imp.strip_marker(old) == new


def test_strip_marker_of_a_bare_marker_is_the_empty_string_not_none():
    assert imp.strip_marker("#imported") == "" and imp.strip_marker("#imported") is not None


def test_plan_lists_our_marked_playlists_and_skips_others(env):
    srv, client, store = env
    set_comment(srv, "pl-1", "Tea #imported notes")
    set_comment(srv, "pl-2", "x#imported #crate")                  # lookalike: never touched
    set_comment(srv, "pl-3", "#imported")
    srv.state.playlists["pl-3"]["owner"] = "amperfy"
    steps = imp.plan(client, store)
    assert [(s.playlist_id, s.action, s.new) for s in steps] == [
        ("pl-1", "record + strip", "Tea notes"), ("pl-3", "skip", None)]
    assert steps[1].owner == "amperfy"


def test_dry_run_report_writes_nothing(env):
    srv, client, store = env
    set_comment(srv, "pl-1", "Tea #imported notes")
    srv.state.requests.clear()
    text = imp.report(imp.plan(client, store))
    assert "would record + strip: Disco Edits (pl-1)" in text and "Tea notes" in text
    assert updates(srv) == [] and not store.is_playlist_imported("pl-1")
    assert comment(srv, "pl-1") == "Tea #imported notes"


def test_apply_records_the_row_then_strips_the_comment(env):
    srv, client, store = env
    set_comment(srv, "pl-1", "Tea #imported notes")
    set_comment(srv, "pl-3", "#imported")
    _, failed = imp.apply(client, store, imp.plan(client, store))
    assert failed == []
    assert comment(srv, "pl-1") == "Tea notes" and comment(srv, "pl-3") == ""
    rows = {r["playlist_id"]: r for r in store.imported_playlists()}
    assert rows["pl-1"]["name"] == "Disco Edits" and rows["pl-1"]["source"] == "migrated"
    assert set(rows) == {"pl-1", "pl-3"}
    ev = [e for e in store.events() if e["kind"] == "imported"]
    assert {e["playlist_id"] for e in ev} == {"pl-1", "pl-3"}
    assert all(e["detail"].startswith("migrated from comment") for e in ev)
    assert any("Tea #imported notes" in e["detail"] for e in ev)          # the old comment: the reverse log


def test_an_empty_result_is_sent_as_an_empty_comment(env):
    srv, client, store = env
    set_comment(srv, "pl-3", "#imported")
    srv.state.requests.clear()
    imp.apply(client, store, imp.plan(client, store))
    assert [q.get("comment") for q in updates(srv)] == [""]


def test_a_second_apply_is_a_no_op(env):
    srv, client, store = env
    set_comment(srv, "pl-1", "Tea #imported notes")
    imp.apply(client, store, imp.plan(client, store))
    srv.state.requests.clear()
    assert imp.plan(client, store) == []
    assert imp.report([]) == "nothing to migrate"
    assert updates(srv) == []
    assert len([e for e in store.events() if e["kind"] == "imported"]) == 1


def test_another_users_playlist_is_never_written(env):
    srv, client, store = env
    set_comment(srv, "pl-2", "#imported")
    srv.state.playlists["pl-2"]["owner"] = "amperfy"
    steps = imp.plan(client, store)
    assert "skipped: owned by amperfy" in imp.report(steps)
    srv.state.requests.clear()
    assert imp.apply(client, store, steps) == ([], [])
    assert updates(srv) == [] and comment(srv, "pl-2") == "#imported"
    assert not store.is_playlist_imported("pl-2")


class Forgetful(SubsonicClient):
    """Navidrome keeps the old comment: every write is read back unchanged."""

    def update_playlist(self, *a, **k):
        pass


def test_a_comment_not_kept_leaves_the_row_recorded_and_names_the_playlist(env):
    srv, _, store = env
    client = Forgetful(srv.url, "demo", "demo")
    set_comment(srv, "pl-1", "Tea #imported notes")
    set_comment(srv, "pl-3", "mine #imported")
    _, failed = imp.apply(client, store, imp.plan(client, store))
    assert len(failed) == 2 and "Disco Edits" in failed[0] and "Sunday Listening" in failed[1]
    assert store.is_playlist_imported("pl-1") and store.is_playlist_imported("pl-3")   # committed before the write
    # a re-run (Navidrome fixed) strips only: no second event
    real = SubsonicClient(srv.url, "demo", "demo")
    steps = imp.plan(real, store)
    assert [s.action for s in steps] == ["strip", "strip"]
    assert "would strip: Disco Edits (pl-1)" in imp.report(steps)
    assert imp.apply(real, store, steps)[1] == []
    assert comment(srv, "pl-1") == "Tea notes" and comment(srv, "pl-3") == "mine"
    assert len([e for e in store.events() if e["kind"] == "imported"]) == 2


def test_the_row_is_committed_before_the_comment_write(env, tmp_path):
    srv, _, _ = env
    store = CrateStore(tmp_path / "c.db")
    seen = []

    class Watching(SubsonicClient):
        def update_playlist(self, pid, **k):
            other = CrateStore(tmp_path / "c.db")                  # another connection sees only committed rows
            seen.append(other.is_playlist_imported(pid))
            other.db.close()
            super().update_playlist(pid, **k)

    client = Watching(srv.url, "demo", "demo")
    set_comment(srv, "pl-1", "#imported")
    assert imp.apply(client, store, imp.plan(client, store))[1] == []
    assert seen == [True]


# ---- the CLI

@pytest.fixture
def cli(env, monkeypatch, tmp_path):
    srv, _, _ = env
    monkeypatch.setenv("SUBSONIC_URL", srv.url); monkeypatch.setenv("SUBSONIC_USER", "demo"); monkeypatch.setenv("SUBSONIC_PASS", "demo")
    monkeypatch.setenv("CRATES_DB", str(tmp_path / "c.db"))
    from crates.cli import main
    return main


def db(tmp_path):
    return CrateStore(tmp_path / "c.db")


def test_cli_dry_run_writes_nothing(env, cli, capsys, tmp_path):
    srv, _, _ = env
    set_comment(srv, "pl-1", "Tea #imported notes")
    srv.state.requests.clear()
    assert cli(["imported", "migrate"]) == 0
    out = capsys.readouterr().out
    assert "would record + strip: Disco Edits (pl-1)" in out and "dry run" in out.lower()
    assert updates(srv) == [] and comment(srv, "pl-1") == "Tea #imported notes"
    assert db(tmp_path).imported_playlists() == []


def test_cli_apply_then_list_then_rerun(env, cli, capsys, tmp_path):
    srv, _, _ = env
    set_comment(srv, "pl-1", "Tea #imported notes")
    assert cli(["imported", "migrate", "--apply"]) == 0
    assert "Disco Edits" in capsys.readouterr().out
    assert comment(srv, "pl-1") == "Tea notes"
    assert cli(["imported", "list"]) == 0
    line = capsys.readouterr().out.strip()
    assert line.startswith("pl-1") and "Disco Edits" in line and "migrated" in line
    assert cli(["imported", "migrate", "--apply"]) == 0
    assert "nothing to migrate" in capsys.readouterr().out


def test_cli_list_with_no_rows(env, cli, capsys):
    assert cli(["imported", "list"]) == 0
    assert "no imported playlists" in capsys.readouterr().out


def test_cli_apply_exits_1_and_names_a_playlist_whose_comment_is_not_kept(env, cli, capsys, monkeypatch, tmp_path):
    srv, _, _ = env
    set_comment(srv, "pl-1", "Tea #imported notes")
    monkeypatch.setattr(SubsonicClient, "update_playlist", lambda self, *a, **k: None)
    assert cli(["imported", "migrate", "--apply"]) == 1
    assert "Disco Edits" in capsys.readouterr().err
    assert db(tmp_path).is_playlist_imported("pl-1")
    assert comment(srv, "pl-1") == "Tea #imported notes"


def test_a_failure_message_carries_what_navidrome_kept(env):
    srv, _, store = env                                             # apply reports it; it does not raise
    client = Forgetful(srv.url, "demo", "demo")
    set_comment(srv, "pl-1", "#imported")
    _, failed = imp.apply(client, store, imp.plan(client, store))
    assert failed and "Navidrome now has" in failed[0]


def test_apply_returns_the_names_it_migrated(env):
    srv, client, store = env
    set_comment(srv, "pl-1", "#imported")
    set_comment(srv, "pl-3", "mine #imported")
    assert imp.apply(client, store, imp.plan(client, store)) == (["Disco Edits", "Sunday Listening"], [])


def test_a_comment_changed_since_the_plan_is_refused_before_anything_is_recorded(env):
    srv, client, store = env
    set_comment(srv, "pl-1", "Tea #imported notes")
    steps = imp.plan(client, store)
    set_comment(srv, "pl-1", "Tea #imported notes, edited meanwhile")
    srv.state.requests.clear()
    done, failed = imp.apply(client, store, steps)
    assert done == [] and len(failed) == 1 and "Disco Edits" in failed[0] and "changed" in failed[0]
    assert updates(srv) == [] and not store.is_playlist_imported("pl-1")
    assert comment(srv, "pl-1") == "Tea #imported notes, edited meanwhile"
