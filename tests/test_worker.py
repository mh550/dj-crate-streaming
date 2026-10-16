"""M6 Task 6: the worker consumes approvals (D23), re-checks `verify` rows, prefers the approved candidate."""
import shutil

import pytest

from crates.store import CrateStore
from sourcing import cli
from sourcing.fake_slskd import FakeSlskdServer
from sourcing.fetch import FetchResult
from sourcing.filer import BeetsFiler
from sourcing.scorer import Wanted, rank
from sourcing.policy import TIERS
from sourcing.slskd_client import SlskdClient
from sourcing.worker import Worker
from subsonic.fake_server import FakeSubsonicServer
from tests.helpers import beets_items_db, fake_beet
from tests.test_fetch import GOOD, RESPONSES, good_flac_bytes, header_only, new_song, run, world  # noqa: F401  (world: fixture)
from tests.test_tier_rows import _cli_env

def worker(world, srv, lines=None, **kw):
    lines = [] if lines is None else lines
    return Worker(store=world["store"], slskd=SlskdClient(srv.url, "k"), navidrome=world["client"], reconciler=world["rec"],
                  fetch_kwargs=dict(music_root=world["music"], downloads_root=world["dl"], filer=world["filer"],
                                    verifier=header_only, poll_s=0.01, download_timeout_s=1, scan_timeout_s=1),
                  log=lines.append, **kw)


def pick_events(world):
    return [e["detail"] for e in world["store"].events(limit=1000) if e["kind"] == "pick"]


def test_tick_with_no_approvals_downloads_nothing(world):
    lines = []
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        report = worker(world, srv, lines).tick()
    assert report.approvals == 0 and srv.enqueued == []
    assert lines[-1] == "tick: 0 approvals, 0 rechecked"


def test_tick_fetches_an_approved_row_and_spends_the_approval(world, tmp_path):
    store = world["store"]
    store.approve("s4", "michael", None, "crate"); store.commit()
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        report = worker(world, srv).tick()
    assert report.approvals == 1 and report.results[0].startswith("s4: ok:")
    assert [e.id for e in world["client"].playlist("pl-2").entries] == ["s3", "s9", "s5"]
    assert store.pending_approvals() == []
    assert store.approval("s4")["result"].startswith("ok:")


def test_approved_candidate_is_preferred_while_offered(world, tmp_path):
    cands = rank(RESPONSES, Wanted("Chic", "Good Times", "Risqué", 501, 1979), TIERS["crate"])
    second = [c for c in cands if not c.rejected][1]
    flac = good_flac_bytes(tmp_path)
    world["store"].approve("s4", "michael", second.as_dict(), "crate"); world["store"].commit()
    with FakeSlskdServer(RESPONSES, world["dl"], files={second.filename: flac}) as srv:
        new_song(world["nd"], len(flac))
        worker(world, srv).tick()
    assert srv.enqueued == [(second.username, second.filename)]
    assert pick_events(world) == [f"approved candidate still offered: {second.basename}"]


def test_gone_candidate_falls_back_to_the_top_ranked(world, tmp_path):
    flac = good_flac_bytes(tmp_path)
    world["store"].approve("s4", "michael", {"username": "x", "filename": "gone.flac"}, "crate"); world["store"].commit()
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        worker(world, srv).tick()
    assert srv.enqueued[0][1] == GOOD
    assert pick_events(world) == ["approved candidate no longer offered; using the top-ranked 03 - Good Times.flac"]


def test_one_failing_row_does_not_stop_the_tick(world):
    store, lines = world["store"], []
    ext = store.add_external_wanted("Chic", "Everybody Dance")
    assert ext == "ext-1"
    store.approve("ext-1", "michael", None, "crate"); store.approve("s4", "michael", None, "crate"); store.commit()

    def fetcher(wanted_id, **kw):
        assert kw["approve"] is True and "tier" not in kw
        if wanted_id == "ext-1":
            raise RuntimeError("boom")
        return FetchResult("ok", "fine")

    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        report = worker(world, srv, lines, fetcher=fetcher).tick()
    assert report.results == ["ext-1: error: RuntimeError: boom", "s4: ok: fine"]
    assert store.approval("ext-1")["result"] == "error: RuntimeError: boom"
    assert store.approval("s4")["result"] == "ok: fine"
    assert any("ext-1" in l and "boom" in l for l in lines) and lines[-1] == "tick: 2 approvals, 0 rechecked"


def test_approval_is_marked_started_before_the_fetch(world):
    store, seen = world["store"], []
    store.approve("s4", "michael", None, "crate"); store.commit()

    def fetcher(wanted_id, **kw):
        seen.append((store.pending_approvals(), store.approval(wanted_id)["result"]))
        return FetchResult("ok", "fine")

    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        worker(world, srv, fetcher=fetcher).tick()
    assert seen == [([], "started")]


def test_tick_rechecks_verify_rows_without_downloading(world, tmp_path):
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        assert run(world, srv, approve=True).status == "verify"        # Navidrome has not indexed it yet
        assert world["store"].find_wanted("s4")["status"] == "verify"
        new_song(world["nd"], len(flac))
        report = worker(world, srv).tick()
    assert world["store"].find_wanted("s9")["status"] == "ok" and report.rechecked == 1 and report.approvals == 0
    assert len(srv.enqueued) == 1                                      # no second download


def test_verify_ids_covers_crate_and_external_rows(world):
    store = world["store"]
    ext = store.add_external_wanted("Chic", "Everybody Dance")
    other = store.add_external_wanted("Chic", "Le Freak")
    store.set_wanted_status("s4", "verify", "filed as x but Navidrome has not picked it up yet")
    store.set_wanted_status(ext, "verify", "filed as y but Navidrome has not picked it up yet")
    assert store.verify_ids() == ["s4", ext] and other not in store.verify_ids()


def test_run_survives_a_tick_exception(world, monkeypatch):
    lines, calls = [], []

    def tick(self):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("slskd is down")

    monkeypatch.setattr(Worker, "tick", tick)
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        worker(world, srv, lines).run(0, ticks=2)
    assert len(calls) == 2 and len([l for l in lines if "slskd is down" in l]) == 1


def test_cli_worker_once(tmp_path, monkeypatch, capsys):
    shutil.copy(cli.DEFAULT_BEETS_CONFIG, tmp_path / "beets.yaml")
    with FakeSubsonicServer() as nd, FakeSlskdServer(RESPONSES, tmp_path / "dl", files={}) as sl:
        _cli_env(monkeypatch, tmp_path, nd, sl)
        monkeypatch.setenv("BEETS_CONFIG", str(tmp_path / "beets.yaml"))
        assert cli.main(["worker", "--once"]) == 0
    assert "0 approvals" in capsys.readouterr().out


def test_cli_fetch_approve_records_an_approval(tmp_path, monkeypatch, capsys):
    music, dl = tmp_path / "m", tmp_path / "dl"
    music.mkdir(); dl.mkdir()
    lib = beets_items_db(tmp_path / "library.db")
    monkeypatch.setattr(cli, "BeetsFiler", lambda cfg, **kw: BeetsFiler(
        cfg, library=lib, tagger=lambda p, n: [], **kw,
        runner=fake_beet(music, lib, "Chic/Risqué (1979)/03 - Good Times.flac", artist="Chic", title="Good Times")))
    flac = good_flac_bytes(tmp_path)
    with FakeSubsonicServer() as nd, FakeSlskdServer(RESPONSES, dl, files={GOOD: flac}) as sl:
        nd.state.songs["s4"].update(title="Good Times", artist="Chic", album="Risqué", year=1979, track=3, duration=501)
        _cli_env(monkeypatch, tmp_path, nd, sl)
        from crates.cli import main as crates_main
        assert crates_main(["toggle", "pl-2", "on"]) == 0
        capsys.readouterr()
        code = cli.main(["fetch", "--wanted", "s4", "--approve"])
    out = capsys.readouterr().out
    approval = CrateStore(tmp_path / "c.db").approval("s4")
    assert approval["approved_by"] == "michael" and approval["tier"] == "crate" and approval["candidate"] is None
    assert approval["used_at"] and approval["result"] and out.splitlines()[-1].startswith(approval["result"].split(":")[0])
    assert "pick: 03 - Good Times.flac" in out
    peers = [r["username"] for r in RESPONSES if r["username"] != "locked"]     # "locked" is also the word in "rejected: locked"
    assert len(peers) == 7 and not [p for p in peers if p in out]                # no Soulseek peer name on stdout
    assert code in (0, 2)


def test_claim_approval_is_conditional_on_unused():
    store = CrateStore()
    first = store.approve("s4", "michael", None, "crate")
    assert store.claim_approval(first) is True and store.approval("s4")["result"] == "started"
    assert store.claim_approval(first) is False                         # already used
    second = store.approve("s4", "michael", None, "crate")
    third = store.approve("s4", "michael", None, "crate")               # supersedes #second
    assert store.claim_approval(second) is False and store.approval("s4")["id"] == third
    assert store.db.execute("SELECT result FROM approvals WHERE id=?", (second,)).fetchone()[0] == f"superseded by #{third}"
    assert store.claim_approval(999) is False


def test_stale_snapshot_does_not_revive_a_superseded_approval(world):
    store, lines, fetched = world["store"], [], []
    ext = store.add_external_wanted("Chic", "Everybody Dance")
    store.approve("s4", "michael", None, "crate")
    a1 = store.approve(ext, "michael", {"username": "x", "filename": "old.flac"}, "crate")     # in this tick's snapshot

    def fetcher(wanted_id, **kw):
        fetched.append((wanted_id, kw["prefer"]))
        if wanted_id == "s4":                                           # slow fetch: Michael re-approves ext-1 meanwhile
            fetcher.a2 = store.approve(ext, "michael", {"username": "y", "filename": "new.flac"}, "crate")
        return FetchResult("ok", "fine")

    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        w = worker(world, srv, lines, fetcher=fetcher)
        first = w.tick()
        assert [f[0] for f in fetched] == ["s4"] and first.approvals == 1       # the old approval was not fetched
        assert f"skipped {ext}: approval #{a1} already used" in lines
        assert store.db.execute("SELECT result FROM approvals WHERE id=?", (a1,)).fetchone()[0] == f"superseded by #{fetcher.a2}"
        second = w.tick()
    assert second.approvals == 1 and fetched[1] == (ext, {"username": "y", "filename": "new.flac"})
    assert len(fetched) == 2 and store.pending_approvals() == []


def test_same_filename_from_another_peer_is_not_the_preferred_candidate(world, tmp_path):
    flac = good_flac_bytes(tmp_path)
    world["store"].approve("s4", "michael", {"username": "someone-else", "filename": GOOD}, "crate")
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        worker(world, srv).tick()
    assert srv.enqueued[0][0] == "vinylhead77"
    assert pick_events(world) == ["approved candidate no longer offered; using the top-ranked 03 - Good Times.flac"]


# --- re-checks are throttled per row (WORKER_RECHECK_S) ------------------------------------------------

def test_verify_rows_are_rechecked_at_most_once_per_interval(world):
    store, seen = world["store"], []
    store.set_wanted_status("s4", "verify", "filed as x but Navidrome has not picked it up yet")

    def fetcher(wanted_id, **kw):
        seen.append(wanted_id)
        store.set_wanted_status(wanted_id, "verify", "filed as x but Navidrome has not picked it up yet (check 1)")
        return FetchResult("verify", "still not indexed")

    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        w = worker(world, srv, fetcher=fetcher, recheck_s=300)
        assert w.tick().rechecked == 0                                  # just filed: Navidrome gets time
        store.db.execute("UPDATE crate_tracks SET updated_at = updated_at - 301 WHERE song_id='s4'"); store.commit()
        assert w.tick().rechecked == 1
        assert w.tick().rechecked == 0                                  # the re-check itself restarted the clock
    assert seen == ["s4"]


def test_cli_worker_takes_the_recheck_interval_from_the_environment(tmp_path, monkeypatch):
    import sourcing.worker
    seen = []

    class Spy(Worker):
        def __init__(self, **kw):
            seen.append(kw.get("recheck_s"))
            super().__init__(**kw)

    monkeypatch.setattr(sourcing.worker, "Worker", Spy)
    shutil.copy(cli.DEFAULT_BEETS_CONFIG, tmp_path / "beets.yaml")
    with FakeSubsonicServer() as nd, FakeSlskdServer(RESPONSES, tmp_path / "dl", files={}) as sl:
        _cli_env(monkeypatch, tmp_path, nd, sl)
        monkeypatch.delenv("WORKER_RECHECK_S", raising=False)
        assert cli.main(["worker", "--once"]) == 0
        monkeypatch.setenv("WORKER_RECHECK_S", "60")
        assert cli.main(["worker", "--once"]) == 0
    assert seen == [300.0, 60.0]


# --- a worker stopped mid-fetch leaves honest records ------------------------------------------------------

def test_recover_marks_started_approvals_interrupted_and_fails_their_sourcing_rows(world):
    store = world["store"]
    ext = store.add_external_wanted("Chic", "Everybody Dance")
    a1 = store.approve("s4", "michael", None, "crate"); store.claim_approval(a1)
    store.set_wanted_status("s4", "sourcing", "downloading 03 - Good Times.flac")      # then SIGTERM
    a2 = store.approve(ext, "michael", None, "crate")                                   # not taken yet: untouched
    used_at = store.approval("s4")["used_at"]
    assert store.recover_interrupted() == ["s4"]
    a = store.approval("s4")
    assert a["result"] == "interrupted: worker restarted" and a["used_at"] == used_at
    row = store.find_wanted("s4")
    assert (row["status"], row["reason"]) == ("failed", "interrupted: worker restarted")
    assert [p["id"] for p in store.pending_approvals()] == [a2]
    assert store.recover_interrupted() == []                            # once is enough


def test_recover_keeps_a_filed_row_in_verify(world):
    store = world["store"]
    a = store.approve("s4", "michael", None, "crate"); store.claim_approval(a)
    store.set_wanted_status("s4", "verify", "filed as x but Navidrome has not picked it up yet")   # killed while scanning
    assert store.recover_interrupted() == ["s4"]
    assert store.approval("s4")["result"] == "interrupted: worker restarted"
    assert store.find_wanted("s4")["status"] == "verify"                # the re-check finds the file, no second copy


def test_a_tick_after_recovery_does_not_fetch_the_interrupted_row(world):
    store, fetched, lines = world["store"], [], []
    a = store.approve("s4", "michael", None, "crate"); store.claim_approval(a)
    store.set_wanted_status("s4", "sourcing", "downloading 03 - Good Times.flac")

    def fetcher(wanted_id, **kw):
        fetched.append(wanted_id)
        return FetchResult("ok", "fine")

    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        w = worker(world, srv, lines, fetcher=fetcher)
        w.run(0, ticks=1)                                               # run() recovers once, before the first tick
    assert fetched == [] and store.find_wanted("s4")["status"] == "failed"
    assert any("interrupted" in l and "s4" in l for l in lines)


def test_cli_worker_once_recovers_before_its_tick(tmp_path, monkeypatch, capsys):
    shutil.copy(cli.DEFAULT_BEETS_CONFIG, tmp_path / "beets.yaml")
    with FakeSubsonicServer() as nd, FakeSlskdServer(RESPONSES, tmp_path / "dl", files={}) as sl:
        _cli_env(monkeypatch, tmp_path, nd, sl)
        st = CrateStore(tmp_path / "c.db")
        ext = st.add_external_wanted("Chic", "Everybody Dance")
        st.claim_approval(st.approve(ext, "michael", None, "crate"))
        st.set_wanted_status(ext, "sourcing", "downloading x.flac")
        assert cli.main(["worker", "--once"]) == 0
    assert "0 approvals" in capsys.readouterr().out
    assert CrateStore(tmp_path / "c.db").external(ext)["status"] == "failed"


def test_wanted_lists_rows_in_progress(world):
    store = world["store"]
    ext = store.add_external_wanted("Chic", "Everybody Dance")
    store.set_wanted_status("s4", "verify", "filed as x but Navidrome has not picked it up yet")
    store.set_wanted_status(ext, "sourcing", "downloading x.flac")
    by_id = {w["song_id"]: w["status"] for w in store.wanted()}
    assert by_id["s4"] == "verify" and by_id[ext] == "sourcing"
