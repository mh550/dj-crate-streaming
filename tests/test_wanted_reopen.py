"""S1-08: `crates.cli wanted reopen <ext-id> [--apply]` puts a row filed as the wrong song (ext-74) back to
`needs_source`: the asked names return, the library song and the placements go, and one `reopened` event keeps
every old value (the reverse). It talks only to crates.db: no file, no playlist, no Navidrome call. Dry run by
default."""
import copy
import json
import sqlite3

import pytest

from crates.store import CrateStore
from subsonic.fake_server import FakeSubsonicServer

WRONG = "One of These Good Old Days"
ASKED = "I'm Still In Love With You"


def seed_ext74(st: CrateStore) -> str:
    """ext-74 as it was live: asked for one song, renamed onto another and placed into pl-2."""
    ext = st.add_external_wanted("Al Green", ASKED, duration_s=196, playlist_id="pl-2", position=3)
    st.set_wanted_names(ext, "Al Green", WRONG)
    st.set_library_song(ext, "s9")
    st.set_external_status(ext, "ok", f"filed as Al Green/Singles/{WRONG}.flac")
    st.record_import_order("pl-2", [(3, None, ext)])
    st.mark_imported("pl-2", ["s9"])
    st.note_placement(ext, "pl-2", "done", "inserted at 2 into 5 entries", song_id="s9")
    st.set_preview(ext, {"status": "ok", "candidates": [{"filename": "wrong.flac"}]})
    st.commit()
    return ext


def placements(st, ext):
    return [dict(r) for r in st.db.execute("SELECT * FROM placements WHERE wanted_id=?", (ext,))]


def kinds(st):
    return [e["kind"] for e in st.events(500)]


@pytest.fixture
def st():
    return CrateStore()


def test_dry_run_returns_the_plan_and_changes_nothing(st):
    ext = seed_ext74(st)
    before = st.external(ext)
    n_events = len(st.events(500))
    plan = st.reopen_external(ext, apply=False)
    assert plan["id"] == ext and plan["applied"] is False
    assert plan["old"]["title"] == WRONG and plan["old"]["library_song_id"] == "s9" and plan["old"]["status"] == "ok"
    assert plan["new"]["title"] == ASKED and plan["new"]["library_song_id"] is None
    assert plan["new"]["status"] == "needs_source"
    assert [p["playlist_id"] for p in plan["old"]["placements"]] == ["pl-2"]
    assert st.external(ext) == before
    assert len(placements(st, ext)) == 1 and len(st.events(500)) == n_events
    assert st.preview(ext) is not None


def test_apply_puts_the_asked_row_back(st):
    ext = seed_ext74(st)
    st.set_external_song(ext, "s9", provisional=False)
    plan = st.reopen_external(ext, apply=True)
    assert plan["applied"] is True
    row = st.external(ext)
    assert (row["artist"], row["title"]) == ("Al Green", ASKED)
    assert (row["asked_artist"], row["asked_title"]) == ("Al Green", ASKED)
    assert row["library_song_id"] is None and row["provisional"] == 0
    assert row["status"] == "needs_source"
    assert row["reason"] == f"reopened: was ok (filed as Al Green – {WRONG})"
    assert placements(st, ext) == []
    assert st.preview(ext) is None                  # approve must not reuse the wrong pick
    events = [e for e in st.events(500) if e["kind"] == "reopened"]
    assert len(events) == 1 and events[0]["song_id"] == ext
    old = json.loads(events[0]["detail"])
    assert {"artist", "title", "library_song_id", "status", "reason", "placements"} <= set(old)
    assert old["artist"] == "Al Green" and old["title"] == WRONG and old["library_song_id"] == "s9"
    assert old["status"] == "ok" and old["reason"] == f"filed as Al Green/Singles/{WRONG}.flac"
    assert old["provisional"] == 0
    [p] = old["placements"]
    assert (p["playlist_id"], p["song_id"], p["state"]) == ("pl-2", "s9", "done")
    assert "trash" not in kinds(st) and kinds(st).count("renamed") == 1    # the original rename only


def test_the_right_file_is_placed_after_reopen(st):
    ext = seed_ext74(st)
    assert st.due_placements() == []
    st.reopen_external(ext, apply=True)
    assert st.due_placements() == []                # needs_source: nothing to place yet
    st.set_library_song(ext, "s10")
    st.set_external_status(ext, "ok", "filed as Al Green/Singles/I'm Still In Love With You.flac")
    st.commit()
    [due] = st.due_placements()
    assert (due["wanted_id"], due["playlist_id"], due["song_id"]) == (ext, "pl-2", "s10")


def test_apply_survives_a_reopen_of_the_store(tmp_path):
    st = CrateStore(tmp_path / "c.db")
    ext = seed_ext74(st)
    st.reopen_external(ext, apply=True)
    again = CrateStore(tmp_path / "c.db")
    assert again.external(ext)["status"] == "needs_source" and placements(again, ext) == []


def test_review_row_from_s1_03_reopens_with_its_names(st):
    """S1-03 already kept the asked names: reopen only moves the row back and drops the song (none here)."""
    ext = st.add_external_wanted("Al Green", ASKED)
    reason = f"filed {WRONG} as Al Green/Singles/{WRONG}.flac, asked for {ASKED}"
    st.set_external_status(ext, "review", reason)
    st.commit()
    st.reopen_external(ext, apply=True)
    row = st.external(ext)
    assert (row["artist"], row["title"], row["status"]) == ("Al Green", ASKED, "needs_source")
    assert row["reason"] == "reopened: was review"
    assert json.loads([e for e in st.events(500) if e["kind"] == "reopened"][0]["detail"])["reason"] == reason


def test_row_without_asked_names_keeps_its_names(st):
    ext = st.add_external_wanted("Chic", "Good Times")
    st.set_library_song(ext, "s1")
    st.set_external_status(ext, "ok", "already in the library: Good Times (s1)")
    st.commit()
    st.reopen_external(ext, apply=True)
    row = st.external(ext)
    assert (row["artist"], row["title"]) == ("Chic", "Good Times")
    assert row["library_song_id"] is None and row["status"] == "needs_source"
    assert row["reason"] == "reopened: was ok (filed as Chic – Good Times)"


@pytest.mark.parametrize("status", ["sourcing", "verify"])
def test_refuses_a_download_in_flight(st, status):
    ext = seed_ext74(st)
    st.set_external_status(ext, status, "downloading")
    st.commit()
    before = st.external(ext)
    with pytest.raises(ValueError, match=status):
        st.reopen_external(ext, apply=True)
    assert st.external(ext) == before and len(placements(st, ext)) == 1


@pytest.mark.parametrize("status,reason,why", [
    ("failed", "Navidrome never indexed Al Green/Singles/x.flac; file is in the library", "re-checks"),
    ("failed", "filed as Al Green/Singles/x.flac but Navidrome never listed it", "re-checks"),
    ("review", "ambiguous (2 versions): s9, s10", "question"),
])
def test_refuses_a_filed_file_or_an_open_question(st, status, reason, why):
    """A filed file not yet indexed is re-checked, never downloaded again (its path lives only in the reason), and an
    import's pick between library versions is Michael's question: reopen would lose both (review I1, I3)."""
    ext = seed_ext74(st)
    st.set_external_status(ext, status, reason)
    st.commit()
    with pytest.raises(ValueError, match=why):
        st.reopen_external(ext, apply=True)
    assert st.external(ext)["reason"] == reason


def test_a_failed_row_without_a_filed_file_reopens(st):
    ext = seed_ext74(st)
    st.set_external_status(ext, "failed", "no candidate")
    st.commit()
    st.reopen_external(ext, apply=True)
    assert st.external(ext)["reason"] == f"reopened: was failed (filed as Al Green – {WRONG})"


def test_refuses_an_open_copy_replacement(st):
    """replace._settle would set the row `ok` with the new song again, undoing the reopen (review I2)."""
    ext = seed_ext74(st)
    job = st.add_replacement(wanted_id=ext, old_song_id="s9", new_song_id="s11", old_path="a.flac",
                             new_path="b.flac", reference=None)
    with pytest.raises(ValueError, match=f"replacement #{job}"):
        st.reopen_external(ext, apply=True)
    st.set_replacement(job, "done"); st.commit()
    st.reopen_external(ext, apply=True)
    assert st.external(ext)["status"] == "needs_source"


def test_apply_checks_and_writes_under_the_write_lock(tmp_path):
    """The worker writes crates.db too: apply takes the lock before its checks, and a lock it cannot get changes
    nothing and leaves no transaction open (review I4)."""
    st = CrateStore(tmp_path / "c.db")
    ext = seed_ext74(st)
    other = sqlite3.connect(tmp_path / "c.db", isolation_level=None)
    other.execute("BEGIN IMMEDIATE")
    st.db.execute("PRAGMA busy_timeout=50")
    with pytest.raises(sqlite3.OperationalError):
        st.reopen_external(ext, apply=True)
    assert not st.db.in_transaction
    plan = st.reopen_external(ext, apply=False)     # a dry run reads without the lock
    assert plan["applied"] is False
    other.execute("ROLLBACK")
    st.reopen_external(ext, apply=True)
    assert st.external(ext)["status"] == "needs_source"


def test_plan_lists_every_import_slot_it_will_be_placed_into(st):
    """While the row had the wrong names another import could have queued it too (review I5): the plan says so."""
    ext = seed_ext74(st)
    st.record_import_order("pl-5", [(7, None, ext)])
    st.commit()
    assert st.reopen_external(ext, apply=False)["playlists"] == [("pl-2", 3), ("pl-5", 7)]


def test_refuses_an_approval_waiting(st):
    ext = seed_ext74(st)
    st.approve(ext, "michael", None, "medium")
    st.commit()
    with pytest.raises(ValueError, match="approval"):
        st.reopen_external(ext, apply=True)
    assert st.external(ext)["status"] == "ok"


def test_refuses_a_placement_being_written(st):
    ext = seed_ext74(st)
    st.note_placement(ext, "pl-2", "writing", "inserting at 2")
    st.commit()
    with pytest.raises(ValueError, match="writing"):
        st.reopen_external(ext, apply=True)
    assert st.external(ext)["status"] == "ok"


def test_refuses_a_removed_row(st):
    ext = seed_ext74(st)
    st.set_external_status(ext, "removed", "superseded by ext-9")
    st.commit()
    with pytest.raises(ValueError, match="removed"):
        st.reopen_external(ext, apply=True)


def test_refuses_a_row_already_open_and_a_second_reopen(st):
    fresh = st.add_external_wanted("Chic", "Good Times"); st.commit()
    with pytest.raises(ValueError, match="already needs_source"):
        st.reopen_external(fresh, apply=True)
    ext = seed_ext74(st)
    st.reopen_external(ext, apply=True)
    with pytest.raises(ValueError, match="already needs_source"):
        st.reopen_external(ext, apply=True)
    assert kinds(st).count("reopened") == 1


@pytest.mark.parametrize("bad", ["s1", "ext-", "ext-x", "ext-999", ""])
def test_refuses_a_bad_or_missing_id(st, bad):
    seed_ext74(st)
    with pytest.raises(ValueError):
        st.reopen_external(bad, apply=True)


# ---- the CLI

@pytest.fixture
def cli(monkeypatch, tmp_path):
    with FakeSubsonicServer() as srv:
        monkeypatch.setenv("SUBSONIC_URL", srv.url); monkeypatch.setenv("SUBSONIC_USER", "demo")
        monkeypatch.setenv("SUBSONIC_PASS", "demo")
        monkeypatch.setenv("CRATES_DB", str(tmp_path / "c.db"))
        from crates.cli import main
        yield srv, main


def tree(path):
    return sorted((str(p.relative_to(path)), p.stat().st_size) for p in path.rglob("*") if p.is_file())


def test_cli_dry_run_then_apply(cli, capsys, tmp_path):
    srv, main = cli
    music = tmp_path / "music" / "Al Green" / "Singles"
    music.mkdir(parents=True)
    (music / f"{WRONG}.flac").write_bytes(b"fLaC" + b"\0" * 64)
    ext = seed_ext74(CrateStore(tmp_path / "c.db"))
    playlists = copy.deepcopy(srv.state.playlists)
    files = tree(tmp_path / "music")
    srv.state.requests.clear()

    assert main(["wanted", "reopen", ext]) == 0
    out = capsys.readouterr().out
    assert WRONG in out and ASKED in out and "s9" in out and "pl-2" in out
    assert "dry run: add --apply" in out and "placed when the right file arrives: pl-2 (#3)" in out
    assert CrateStore(tmp_path / "c.db").external(ext)["status"] == "ok"

    assert main(["wanted", "reopen", ext, "--apply"]) == 0
    assert f"reopened {ext}" in capsys.readouterr().out
    st = CrateStore(tmp_path / "c.db")
    assert st.external(ext)["status"] == "needs_source" and st.external(ext)["title"] == ASKED
    assert "trash" not in kinds(st) and kinds(st).count("renamed") == 1
    assert srv.state.requests == []                # not one Navidrome call
    assert srv.state.playlists == playlists
    assert tree(tmp_path / "music") == files


def test_cli_refusal_exits_1(cli, capsys, tmp_path):
    _, main = cli
    ext = seed_ext74(CrateStore(tmp_path / "c.db"))
    st = CrateStore(tmp_path / "c.db")
    st.set_external_status(ext, "sourcing", "downloading"); st.commit()
    assert main(["wanted", "reopen", ext, "--apply"]) == 1
    assert "sourcing" in capsys.readouterr().err
    assert main(["wanted", "reopen", "ext-999"]) == 1
    assert "ext-999" in capsys.readouterr().err


def test_cli_a_locked_database_exits_1(cli, capsys, tmp_path, monkeypatch):
    _, main = cli
    ext = seed_ext74(CrateStore(tmp_path / "c.db"))

    def locked(self, ext_id, apply):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(CrateStore, "reopen_external", locked)
    assert main(["wanted", "reopen", ext, "--apply"]) == 1
    assert "database is locked" in capsys.readouterr().err


def test_cli_wanted_json_still_works(cli, capsys, tmp_path):
    _, main = cli
    st = CrateStore(tmp_path / "c.db")
    st.add_external_wanted("Chic", "Good Times"); st.commit()
    assert main(["wanted", "--json"]) == 0
    assert isinstance(json.loads(capsys.readouterr().out), list)
    assert main(["wanted"]) == 0
