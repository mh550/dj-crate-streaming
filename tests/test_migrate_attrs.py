"""M8 Task 4: the one-time move of crates.db's crate flags and import tiers into playlist comments (D21).
Only ever adds tokens; a dry run writes nothing to Navidrome; a playlist edited since the plan is refused."""
import pytest

from crates import migrate_attrs as mig
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


def imported(store, pid, *tiers):
    for i, t in enumerate(tiers):
        store.add_external_wanted("Artist", f"Title {pid} {i}", playlist_id=pid, position=i, tier=t)


def by_id(changes):
    return {c.playlist_id: c for c in changes}


def updates(srv):
    return [m for m, _ in srv.state.requests if m == "updatePlaylist"]


def test_plan_flags_crates_and_tiers_imported_playlists(env):
    srv, client, store = env
    store.set_enabled("pl-1", "Disco Edits", True)
    set_comment(srv, "pl-3", "#imported")
    imported(store, "pl-3", "medium", "medium")
    ch = by_id(mig.plan(client, store))
    assert set(ch) == {"pl-1", "pl-3"}
    assert (ch["pl-1"].old, ch["pl-1"].new, ch["pl-1"].name) == ("", "#crate", "Disco Edits")
    assert "crates.db" in ch["pl-1"].why
    assert (ch["pl-3"].old, ch["pl-3"].new) == ("#imported", "#imported #tier:medium")
    assert "medium" in ch["pl-3"].why


def test_plan_keeps_every_other_byte_of_the_comment(env):
    srv, client, store = env
    store.set_enabled("pl-1", "Disco Edits", True)
    set_comment(srv, "pl-1", "late set\nno vocals")
    assert by_id(mig.plan(client, store))["pl-1"].new == "late set\nno vocals #crate"


def test_plan_leaves_tagged_playlists_and_others_alone(env):
    srv, client, store = env
    store.set_enabled("pl-2", "Chicago 86", True)                       # comment already says #crate (as "sockseek / clouds")
    set_comment(srv, "pl-3", "#imported #tier:high")
    imported(store, "pl-3", "medium")                                    # the comment's tier stays, whatever the rows say
    set_comment(srv, "pl-1", "just a note")                              # untagged, not imported, not a crate
    assert mig.plan(client, store) == []


def test_plan_ignores_disabled_crates_name_marked_crates_and_imported_crates(env):
    srv, client, store = env
    store.set_enabled("pl-1", "Disco Edits", False)                      # disabled row: nothing
    store.set_enabled("pl-3", "Sunday Listening [crate]", True)          # crate by its name already
    srv.state.playlists["pl-3"]["name"] = "Sunday Listening [crate]"
    set_comment(srv, "pl-2", "#imported #crate")                         # already a crate: no tier is added
    imported(store, "pl-2", "medium")
    assert mig.plan(client, store) == []


def test_plan_skips_a_tier_tag_it_cannot_read(env):
    srv, client, store = env
    set_comment(srv, "pl-3", "#imported #tier:hgh")                      # never written over: it is a problem to show
    imported(store, "pl-3", "medium")
    assert mig.plan(client, store) == []


def test_rows_at_several_tiers_take_the_highest(env):
    srv, client, store = env
    set_comment(srv, "pl-3", "#imported")
    imported(store, "pl-3", "low", "high", "medium")
    assert by_id(mig.plan(client, store))["pl-3"].new == "#imported #tier:high"


def test_imported_playlist_without_rows_gets_the_import_tier(env):
    srv, client, store = env
    set_comment(srv, "pl-3", "#imported")
    ch = by_id(mig.plan(client, store))["pl-3"]
    assert ch.new == "#imported #tier:medium" and "medium" in ch.why


def test_report_counts_tracks_that_would_queue(env):
    srv, client, store = env
    srv.state.songs["s9"] = dict(srv.state.songs["s4"], id="s9", title="Tiny", bitRate=48)
    srv.state.playlists["pl-3"].update(comment="#imported", songs=["s1", "s9"])      # a flac and a 48 kbps mp3
    imported(store, "pl-3", "medium")
    text = mig.report(mig.plan(client, store), client, store)
    assert "Sunday Listening" in text and "#imported #tier:medium" in text
    line = next(x for x in text.splitlines() if "queue" in x and "Sunday Listening" in x)
    assert "1 of 2" in line


def test_report_with_nothing_to_do_says_so(env):
    _, client, store = env
    assert "nothing to change" in mig.report([], client, store).lower()


def test_report_lists_crate_lookalikes_that_do_not_parse_as_crate(env):
    srv, client, store = env
    srv.state.playlists["pl-3"].update(name="Warm #Crate.", comment="")
    srv.state.playlists["pl-2"]["comment"] = "x#crate"
    for i, text in enumerate(("#crate.", "#Crate,")):
        srv.state.playlists[f"pl-{4 + i}"] = {"id": f"pl-{4 + i}", "name": f"Odd {i}", "comment": text,
                                              "owner": "demo", "public": False, "songs": []}
    set_comment(srv, "pl-1", "peak hour #crates")
    srv.state.playlists["pl-6"] = {"id": "pl-6", "name": "Real", "comment": "ok #crate", "owner": "demo",
                                   "public": False, "songs": []}
    changes = mig.plan(client, store)
    assert changes == []                                                 # the migration changes none of them
    text = mig.report(changes, client, store)
    head = next(i for i, x in enumerate(text.splitlines()) if "#crate" in x.lower() and x.startswith("#"))
    tail = "\n".join(text.splitlines()[head:])
    for needle in ("Disco Edits", "peak hour #crates", "Warm #Crate.", "Chicago 86", "x#crate", "Odd 0", "#crate.", "Odd 1", "#Crate,"):
        assert needle in tail, needle
    assert "Real" not in tail                                            # a real crate is not a lookalike
    assert "Sunday Listening" not in tail                                # (renamed above, listed under its new name)
    assert [m for m, _ in srv.state.requests if m == "updatePlaylist"] == []


def test_lookalike_list_is_empty_when_there_are_none(env):
    _, client, store = env
    assert mig.lookalikes(client.playlists()) == []
    assert "not read as a crate" not in mig.report([], client, store)


def test_apply_writes_and_reads_back(env):
    srv, client, store = env
    store.set_enabled("pl-1", "Disco Edits", True)
    written, refused = mig.apply(client, mig.plan(client, store))
    assert written == ["Disco Edits"] and refused == []
    assert comment(srv, "pl-1") == "#crate"
    assert mig.plan(client, store) == []                                 # a re-run plans nothing


def test_apply_refuses_a_comment_changed_since_the_plan(env):
    srv, client, store = env
    store.set_enabled("pl-1", "Disco Edits", True)
    set_comment(srv, "pl-3", "#imported")
    changes = mig.plan(client, store)
    client.update_playlist("pl-1", comment="edited meanwhile")
    written, refused = mig.apply(client, changes)
    assert comment(srv, "pl-1") == "edited meanwhile"                    # untouched
    assert len(refused) == 1 and "Disco Edits" in refused[0] and "changed" in refused[0]
    assert written == ["Sunday Listening"] and comment(srv, "pl-3") == "#imported #tier:medium"


def test_apply_refuses_what_navidrome_does_not_keep(env):
    srv, _, store = env

    class Forgetful(SubsonicClient):
        wrote = False

        def update_playlist(self, *a, **k):
            super().update_playlist(*a, **k)
            self.wrote = True

        def playlist(self, pid):
            pl = super().playlist(pid)
            if self.wrote:
                pl.comment = ""
            return pl

    client = Forgetful(srv.url, "demo", "demo")
    store.set_enabled("pl-1", "Disco Edits", True)
    written, refused = mig.apply(client, mig.plan(client, store))
    assert written == [] and len(refused) == 1 and "Disco Edits" in refused[0]


def test_apply_refuses_a_playlist_that_is_gone(env):
    srv, client, store = env
    store.set_enabled("pl-1", "Disco Edits", True)
    changes = mig.plan(client, store)
    del srv.state.playlists["pl-1"]
    written, refused = mig.apply(client, changes)
    assert written == [] and len(refused) == 1 and "Disco Edits" in refused[0]


@pytest.fixture
def cli(env, monkeypatch, tmp_path):
    srv, client, _ = env
    monkeypatch.setenv("SUBSONIC_URL", srv.url); monkeypatch.setenv("SUBSONIC_USER", "demo"); monkeypatch.setenv("SUBSONIC_PASS", "demo")
    monkeypatch.setenv("CRATES_DB", str(tmp_path / "c.db"))
    from crates.cli import main
    store = CrateStore(tmp_path / "c.db")
    store.set_enabled("pl-1", "Disco Edits", True)
    set_comment(srv, "pl-3", "#imported")
    store.add_external_wanted("Bag Lady", "Erykah Badu", playlist_id="pl-3", position=1, tier="medium")
    store.db.close()
    return main


def test_dry_run_writes_nothing(env, cli, capsys, tmp_path):
    srv, _, _ = env
    srv.state.requests.clear()
    out = tmp_path / "report.md"
    assert cli(["attrs", "migrate", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "Disco Edits" in text and "#crate" in text and "dry run" in text.lower()
    assert out.read_text(encoding="utf-8").strip() == text.strip()
    assert updates(srv) == []
    assert comment(srv, "pl-1") == "" and comment(srv, "pl-3") == "#imported"


def test_cli_apply_writes_and_a_rerun_plans_nothing(env, cli, capsys):
    srv, _, _ = env
    assert cli(["attrs", "migrate", "--apply"]) == 0
    out = capsys.readouterr().out
    assert "Disco Edits" in out and "written" in out.lower()
    assert comment(srv, "pl-1") == "#crate" and comment(srv, "pl-3") == "#imported #tier:medium"
    srv.state.requests.clear()
    assert cli(["attrs", "migrate", "--apply"]) == 0
    assert "nothing to change" in capsys.readouterr().out.lower()
    assert updates(srv) == []


def test_cli_apply_exits_1_when_a_playlist_is_refused(env, cli, capsys, monkeypatch):
    srv, _, _ = env
    real = mig.plan

    def stale(client, store):                    # the plan is made, then Michael edits the playlist before the write
        ch = real(client, store)
        client.update_playlist("pl-1", comment="edited meanwhile")
        return ch

    monkeypatch.setattr(mig, "plan", stale)
    assert cli(["attrs", "migrate", "--apply"]) == 1
    assert "Disco Edits" in capsys.readouterr().err
    assert comment(srv, "pl-1") == "edited meanwhile"


# ---- Task 4 review lows

def test_plan_does_not_read_a_lookalike_marker_as_imported(env):
    srv, client, store = env
    set_comment(srv, "pl-3", "x#imported")
    set_comment(srv, "pl-1", "#imported-old")
    assert mig.plan(client, store) == []


def test_plan_reports_an_enabled_crate_whose_playlist_is_gone(env):
    srv, client, store = env
    store.set_enabled("pl-1", "Disco Edits", True)
    store.set_enabled("pl-gone", "Vanished Mix", True)
    store.set_enabled("pl-gone2", "Disabled Ghost", False)               # disabled: not worth a line
    assert [c.playlist_id for c in mig.plan(client, store)] == ["pl-1"]  # nothing is changed for the missing one
    text = mig.report(mig.plan(client, store), client, store)
    assert "crates.db says crate, but the playlist no longer exists: Vanished Mix" in text
    assert "Disabled Ghost" not in text
    assert [m for m, _ in srv.state.requests if m == "updatePlaylist"] == []
    store.set_enabled("pl-gone", "", True)
    assert "no longer exists: pl-gone" in mig.report([], client, store)  # no name: the id


def test_apply_catches_any_error_per_playlist_and_continues(env):
    srv, _, store = env
    from urllib.error import URLError

    class Flaky(SubsonicClient):
        def playlist(self, pid):
            if pid == "pl-1":
                raise URLError("connection reset")
            return super().playlist(pid)

    client = Flaky(srv.url, "demo", "demo")
    store.set_enabled("pl-1", "Disco Edits", True)
    set_comment(srv, "pl-3", "#imported")
    written, refused = mig.apply(client, mig.plan(client, store))
    assert written == ["Sunday Listening"]
    assert len(refused) == 1 and "Disco Edits" in refused[0] and "connection reset" in refused[0]


def test_to_decide_excludes_lookalikes_already_planned(env):
    srv, client, store = env
    set_comment(srv, "pl-1", "peak #crates")
    store.set_enabled("pl-1", "Disco Edits", True)                       # lookalike AND crates.db says crate: planned
    set_comment(srv, "pl-2", "x#crate")                                  # a lookalike nobody planned
    changes = mig.plan(client, store)
    assert [c.playlist_id for c in changes] == ["pl-1"]
    text = mig.report(changes, client, store)
    assert "Total: 1 to change, 1 to decide." in text
    assert "#crate will be added" in text and "x#crate" in text


def test_cli_apply_lists_refused_playlists_by_name_on_stdout(env, cli, capsys, monkeypatch):
    real = mig.plan

    def stale(client, store):
        ch = real(client, store)
        client.update_playlist("pl-1", comment="edited meanwhile")
        return ch

    monkeypatch.setattr(mig, "plan", stale)
    assert cli(["attrs", "migrate", "--apply"]) == 1
    cap = capsys.readouterr()
    assert "Refused (1)" in cap.out and "Disco Edits" in cap.out.split("Refused (1)")[1]
    assert "Written (1)" in cap.out


def test_cli_apply_survives_an_unexpected_error_and_still_prints_the_summary(env, cli, capsys, monkeypatch):
    real = SubsonicClient.update_playlist

    def boom(self, pid, **k):
        if pid == "pl-1":
            raise ValueError("odd response")
        return real(self, pid, **k)

    monkeypatch.setattr(SubsonicClient, "update_playlist", boom)
    assert cli(["attrs", "migrate", "--apply"]) == 1
    out = capsys.readouterr().out
    assert "Written (1): Sunday Listening" in out and "Disco Edits" in out and "odd response" in out
