"""M8 Task 5 (spec fact #7, D10/D15/D21): a track's tier is derived, the highest effective tier of the playlists that
hold it (crate > high > medium > low). One file per song is kept, so the tier only says how good that file must be:
crate keeps the strict rules, a listening tier asks for an upgrade only below its floor."""
import pytest

from crates import migrate_attrs as mig
from crates.reconcile import Reconciler, judge
from crates.store import CrateStore, never_indexed
from sourcing import cli
from sourcing import import_playlist as ip
from sourcing.fetch import fetch
from sourcing.playlist_sources import Row
from sourcing.policy import TIERS
from sourcing.worker import Worker
from subsonic.client import SubsonicClient
from subsonic.fake_server import FakeSubsonicServer
from tests.test_crates import song
from tests.test_fetch import world  # noqa: F401  (fixture)
from tests.test_service import svc  # noqa: F401  (fixture)


@pytest.fixture
def env():
    with FakeSubsonicServer() as srv:
        client = SubsonicClient(srv.url, "demo", "demo")
        store = CrateStore()
        yield srv, client, store, Reconciler(client, store)


def wanted_by_id(store):
    return {w["song_id"]: w for w in store.wanted()}


def row(store, pid, sid):
    return next(t for t in store.tracks(pid, include_removed=True) if t["song_id"] == sid)


# --- the derived tier
def test_track_tier_is_the_highest_of_its_playlists(env):
    srv, client, store, rec = env
    client.update_playlist("pl-1", comment="#tier:medium")          # s1 s2 s3; pl-2 "warmup #crate": s3 s4 s5
    rec.run()
    w = wanted_by_id(store)
    assert w["s3"]["tier"] == "crate"                                # a 320 mp3 needs lossless at crate
    assert w["s3"]["crates"] == ["Chicago 86"] and sorted(w["s3"]["playlists"]) == ["Chicago 86", "Disco Edits"]
    assert row(store, "pl-1", "s3")["status"] == "needs_source"       # judged once, at the derived tier
    assert store.song_tier("s3") == "crate" and store.song_tier("s1") == "medium"
    client.update_playlist("pl-2", comment="warmup")
    rec.run()
    assert row(store, "pl-1", "s3")["status"] == "ok"                 # judged at medium now
    assert "s3" not in wanted_by_id(store) and store.song_tier("s3") == "medium"


def test_flagging_a_playlist_crate_queues_upgrades_without_approving(env):
    srv, client, store, rec = env
    rec.set_crate("pl-1", True)
    assert "s3" in wanted_by_id(store)
    assert store.pending_approvals() == []
    assert not [e for e in store.events(1000) if e["kind"] == "approved"]


def test_a_setter_rejudges_the_songs_rows_in_other_playlists(env):
    """Michael un-flags a crate in the web client: s3's row in the medium playlist must not keep asking for
    lossless until the next periodic reconcile (a download could be approved in between)."""
    srv, client, store, rec = env
    client.update_playlist("pl-1", comment="#tier:medium")
    rec.run()
    assert row(store, "pl-1", "s3")["status"] == "needs_source"
    rec.set_crate("pl-2", False)
    assert row(store, "pl-1", "s3")["status"] == "ok"
    rec.set_tier("pl-2", "crate")
    assert row(store, "pl-1", "s3")["status"] == "needs_source"


def test_listening_tiers_do_not_ask_for_lossless():
    for t in ("low", "medium", "high"):
        p = TIERS[t]
        assert judge(song(suffix="mp3", bit_rate=320), p)[0] == "ok", t
        assert judge(song(suffix="mp3", bit_rate=24), p)[0] == "needs_source", t
        assert judge(song(suffix="flac", bit_rate=900, sample_rate=44100, bit_depth=16), p)[0] == "ok", t
        assert judge(song(suffix="wma", bit_rate=320), p)[0] == "needs_source", t
        assert judge(song(suffix="flac", bit_rate=200), p)[0] == "ok", t      # no lossless sanity checks
    p = TIERS["medium"]
    assert judge(song(suffix="mp3", bit_rate=48), p)[0] == "needs_source"
    assert "64" in judge(song(suffix="mp3", bit_rate=48), p)[1]
    assert judge(song(suffix="mp3", bit_rate=100), TIERS["high"])[0] == "needs_source"
    assert judge(song(suffix="", bit_rate=320), p)[0] == "needs_source"
    crate = TIERS["crate"]                                                 # unchanged (test_crates::test_judge_policy)
    assert judge(song(suffix="mp3", bit_rate=320), crate) == ("needs_source", ".mp3 320 kbps acceptable; lossless preferred")
    assert judge(song(suffix="flac", bit_rate=200), crate)[0] == "needs_source"
    assert judge(song(suffix="flac", bit_rate=900, sample_rate=44100, bit_depth=16), crate)[0] == "ok"


def test_track_in_no_tiered_playlist_has_no_row_and_external_rows_keep_their_tier(env):
    srv, client, store, rec = env
    alone = store.add_external_wanted("Chic", "Le Freak", tier="high")
    untiered = store.add_external_wanted("Chic", "My Forbidden Lover", playlist_id="pl-3", position=1, tier="medium")
    rec.run()                                                          # only pl-2 is tiered (crate)
    assert store.find_wanted("s1") is None and store.song_tier("s1") is None
    assert not store.tracks("pl-1") and not store.tracks("pl-3")
    assert store.external(alone)["tier"] == "high" and store.external(untiered)["tier"] == "medium"


def test_external_rows_follow_their_playlists_tier(env):
    srv, client, store, rec = env
    a = store.add_external_wanted("Chic", "Le Freak", playlist_id="pl-3", position=1, tier="medium")
    b = store.add_external_wanted("Chic", "My Forbidden Lover", playlist_id="pl-3", position=2, tier="medium")
    store.set_external_status(b, "sourcing", "downloading x"); store.commit()
    rec.set_tier("pl-3", "high")
    assert store.external(a)["tier"] == "high" and store.external(b)["tier"] == "medium"
    tier_events = [e for e in store.events(1000) if e["kind"] == "tier" and e["song_id"] == a]
    assert len(tier_events) == 1 and "medium → high" in tier_events[0]["detail"]
    assert not [e for e in store.events(1000) if e["kind"] == "tier" and e["song_id"] == b]
    rec.set_tier("pl-3", "low")
    assert store.external(a)["tier"] == "low"                          # lowering is Michael's explicit act
    rec.set_crate("pl-3", True)
    assert store.external(a)["tier"] == "crate"


def test_reconcile_run_derives_external_tiers_from_a_comment_edited_elsewhere(env):
    srv, client, store, rec = env
    a = store.add_external_wanted("Chic", "Le Freak", playlist_id="pl-3", position=1, tier="medium")
    client.update_playlist("pl-3", comment="#tier:high")               # Amperfy edit
    rec.run()
    assert store.external(a)["tier"] == "high"
    assert wanted_by_id(store)[a]["tier"] == "high"


def test_untiering_removes_its_rows(env):
    srv, client, store, rec = env
    client.update_playlist("pl-1", comment="#tier:high")
    rec.run()
    assert {t["song_id"] for t in store.tracks("pl-1")} == {"s1", "s2", "s3"}
    client.update_playlist("pl-1", comment="")                         # edited elsewhere
    rec.run()
    assert store.tracks("pl-1") == []
    assert {t["reason"] for t in store.tracks("pl-1", include_removed=True)} == {"playlist no longer tiered"}
    rec.set_tier("pl-1", "low")
    assert len(store.tracks("pl-1")) == 3
    rec.set_tier("pl-1", None)                                         # the setter path
    assert store.tracks("pl-1") == []


def test_review_rows_are_not_clobbered_by_reconcile(env):
    srv, client, store, rec = env
    rec.run()
    store.set_track_status("pl-2", "s4", "review", "keep both? a new copy is in the library")
    store.set_track_status("pl-2", "s3", "review", "keep both?")
    client.update_playlist("pl-2", comment="#tier:low")                # s3 (320 mp3) is ok at low: still review
    rec.run()
    assert row(store, "pl-2", "s4")["status"] == "review" and row(store, "pl-2", "s3")["status"] == "review"
    assert row(store, "pl-2", "s4")["reason"] == "keep both? a new copy is in the library"


@pytest.mark.parametrize("status,reason", [
    ("sourcing", "downloading x.flac"),
    ("verify", "filed as A/B/x.flac but Navidrome has not picked it up yet"),
    ("failed", never_indexed("A/B/x.flac")),
])
def test_in_flight_and_filed_rows_keep_their_status(env, status, reason):
    srv, client, store, rec = env
    rec.run()
    store.set_track_status("pl-2", "s4", status, reason)
    rec.run()
    assert (row(store, "pl-2", "s4")["status"], row(store, "pl-2", "s4")["reason"]) == (status, reason)


def test_fetch_refuses_a_tier_override_on_a_playlist_row(env, tmp_path):
    srv, client, store, rec = env
    client.update_playlist("pl-1", comment="#tier:high")
    rec.run()
    r = fetch("s3", store=store, slskd=None, navidrome=client, reconciler=rec, music_root=tmp_path / "m",
              downloads_root=tmp_path / "dl", approve=False, tier="low")
    assert r.status == "refused" and "its tier comes from its playlists (crate)" in r.reason


def test_retier_skips_rows_whose_playlist_owns_the_tier(tmp_path, monkeypatch, capsys):
    db = tmp_path / "c.db"; monkeypatch.setenv("CRATES_DB", str(db))
    st = CrateStore(db)
    st.set_attrs("pl-3", "Sunday Listening", False, "high")
    owned = st.add_external_wanted("Chic", "Le Freak", playlist_id="pl-3", position=1, tier="crate")
    free = st.add_external_wanted("Chic", "Good Times", tier="crate")
    untiered = st.add_external_wanted("Chic", "My Forbidden Lover", playlist_id="pl-9", position=1, tier="crate")
    st.commit()
    assert cli.main(["retier", "--from", "crate", "--to", "medium"]) == 0
    out = capsys.readouterr().out
    assert "moved 2 rows crate → medium" in out
    assert "skipped 1 row whose playlist owns the tier (crates.cli tier)" in out
    st = CrateStore(db)
    assert [st.external(i)["tier"] for i in (owned, free, untiered)] == ["crate", "medium", "medium"]


class CountingReconciler:
    def __init__(self, fail=False):
        self.runs, self.fail = 0, fail

    def run(self):
        self.runs += 1
        if self.fail:
            raise OSError("navidrome down")


def _worker(rec, now, lines, **kw):
    return Worker(store=CrateStore(), slskd=None, navidrome=None, reconciler=rec, fetch_kwargs={},
                  log=lines.append, clock=lambda: now[0], **kw)


def test_worker_reconciles_every_interval():
    rec, now, lines = CountingReconciler(), [1000.0], []
    wk = _worker(rec, now, lines, reconcile_s=600)
    wk.tick()
    assert rec.runs == 1
    now[0] += 30
    wk.tick()
    assert rec.runs == 1
    now[0] += 571                                                      # +601 s since the first
    wk.tick()
    assert rec.runs == 2


def test_worker_without_an_interval_never_reconciles_and_a_failed_reconcile_does_not_stop_the_tick():
    rec, now, lines = CountingReconciler(), [0.0], []
    _worker(rec, now, lines).tick()
    assert rec.runs == 0
    bad = CountingReconciler(fail=True)
    report = _worker(bad, now, lines, reconcile_s=600).tick()
    assert bad.runs == 1 and report.approvals == 0
    assert any("reconcile failed" in x and "navidrome down" in x for x in lines)


# --- carried from the Task 3/4 reviews
ROWS2 = [Row(1, "Good Times", "Chic", None, "sp1"), Row(2, "Nope", "Nobody", None, "sp2")]


def test_import_rerun_without_tier_queues_new_rows_at_the_comments_tier(env):
    srv, client, store, rec = env
    a = ip.import_playlist("Tea tent", ROWS2, client, store, source="s")
    client.update_playlist(a.playlist_id, comment="#imported #tier:high")
    ip.import_playlist("Tea tent", ROWS2 + [Row(3, "Also Nope", "Nobody", None, "sp3")], client, store, source="s")
    by_title = {r["title"]: r for r in store.external_for_playlist(a.playlist_id)}
    assert by_title["Also Nope"]["tier"] == "high"
    assert srv.state.playlists[a.playlist_id]["comment"] == "#imported #tier:high"     # a plain re-run writes no tier


def test_import_rerun_without_tier_matches_at_the_comments_tier(env):
    """crate accepts a club mix in place of the radio version (deploy/policy.toml), medium does not."""
    srv, client, store, rec = env
    srv.state.songs["s1"]["title"] = "Good Times (Club Mix)"
    a = ip.import_playlist("Tea tent", ROWS2, client, store, source="s")
    assert [m.status for m in a.matches] == ["ambiguous", "missing"]
    client.update_playlist(a.playlist_id, comment="#imported #crate")
    b = ip.import_playlist("Tea tent", ROWS2, client, store, source="s")
    assert b.matches[0].status == "matched" and b.matches[0].song_id == "s1"


def test_migration_report_judges_a_new_crate_at_crate(env):
    srv, client, store, rec = env
    store.set_enabled("pl-1", "Disco Edits", True)                      # crates.db says crate; comment says nothing
    text = mig.report(mig.plan(client, store), client, store)
    line = next(x for x in text.splitlines() if "queue" in x and "Disco Edits" in x)
    assert "at crate" in line and "1 of 3" in line                      # s3, a 320 mp3, is not crate-worthy


def test_a_filed_upgrade_is_swapped_into_a_tiered_playlist_that_is_not_a_crate(world, tmp_path):
    """A listening-tier row below its floor is queued like a crate row; once filed, the new song must replace the
    old one in that playlist too, or the row would wait in `verify` forever (Task 8 repoints everywhere)."""
    from sourcing.fake_slskd import FakeSlskdServer
    from tests.test_fetch import GOOD, RESPONSES, good_flac_bytes, new_song, run
    nd, client, store, rec = world["nd"], world["client"], world["store"], world["rec"]
    nd.state.songs["s4"]["bitRate"] = 100                              # under high's 128 floor
    client.update_playlist("pl-2", comment="#tier:high")
    rec.run()
    assert store.find_wanted("s4")["tier"] == "high" and store.find_wanted("s4")["status"] == "needs_source"
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(nd, len(flac))
        r = run(world, srv, approve=True, prefer={"username": RESPONSES[0]["username"], "filename": GOOD})
    assert r.status == "ok", r.reason
    assert [e.id for e in client.playlist("pl-2").entries] == ["s3", "s9", "s5"]
    st = store.track_status_map("pl-2")
    assert st["s9"]["status"] == "ok" and st["s4"]["status"] == "removed"


def test_cli_approve_with_a_tier_on_a_playlist_row_names_the_derived_tier(tmp_path, monkeypatch, capsys):
    from crates.cli import main as crates_main
    from sourcing.fake_slskd import FakeSlskdServer
    from tests.test_tier_rows import _cli_env
    with FakeSubsonicServer() as nd, FakeSlskdServer([], tmp_path / "dl", files={}) as sl:
        _cli_env(monkeypatch, tmp_path, nd, sl)
        assert crates_main(["tier", "pl-1", "high"]) == 0
        capsys.readouterr()
        assert cli.main(["fetch", "--wanted", "s3", "--approve", "--tier", "low"]) == 1
    assert "its tier comes from its playlists (high)" in capsys.readouterr().err
    assert CrateStore(tmp_path / "c.db").approval("s3") is None


def test_adding_a_song_to_a_tiered_playlist_judges_it_at_once(svc):
    from tests.test_service import post
    fake, app, srv = svc
    app.set_tier("pl-3", "high")
    fake.state.songs["s4"]["bitRate"] = 100                                 # under high's 128 floor
    s, _ = post(srv.url + "/api/playlists/pl-3/songs", {"songIds": ["s4"]})
    assert s == 200
    assert app.store.find_wanted("s4")["tier"] == "high" and app.store.find_wanted("s4")["status"] == "needs_source"


# --- Task 5 review
FILED = "filed as A/B/x.flac but Navidrome has not picked it up yet"
IN_FLIGHT = [("sourcing", "downloading x.flac"), ("verify", FILED), ("failed", never_indexed("A/B/x.flac"))]


@pytest.mark.parametrize("status,reason", IN_FLIGHT)
def test_an_in_flight_row_keeps_its_status_whatever_the_new_verdict(env, status, reason):
    srv, client, store, rec = env
    rec.run()
    store.set_track_status("pl-2", "s3", status, reason)              # s3: 320 mp3, needs_source at crate
    client.update_playlist("pl-2", comment="#tier:medium")             # ok at medium
    rec.run()
    assert (row(store, "pl-2", "s3")["status"], row(store, "pl-2", "s3")["reason"]) == (status, reason)


@pytest.mark.parametrize("status,reason", IN_FLIGHT + [("review", "keep both?")])
def test_untiering_keeps_in_flight_rows_reachable(env, status, reason):
    srv, client, store, rec = env
    rec.run()
    store.set_track_status("pl-2", "s4", status, reason)
    client.update_playlist("pl-2", comment="warmup")                   # loses #crate
    rec.run()
    assert (row(store, "pl-2", "s4")["status"], row(store, "pl-2", "s4")["reason"]) == (status, reason)
    assert row(store, "pl-2", "s3")["status"] == "removed"             # the others go
    w = store.find_wanted("s4")
    assert w is not None and w["status"] == status and w["tier"] in TIERS
    assert ("s4" in store.verify_ids()) == (status == "verify")
    store.set_wanted_status("s4", "failed", "download ended: Completed, Errored")
    assert row(store, "pl-2", "s4")["status"] == "failed"              # fetch can still finish it
    rec.run()
    assert row(store, "pl-2", "s4")["status"] == "removed"             # finished: now it goes


def test_set_crate_off_while_sourcing_then_filed_reaches_the_row(env):
    srv, client, store, rec = env
    rec.run()
    store.set_track_status("pl-2", "s4", "sourcing", "downloading x.flac")
    rec.set_crate("pl-2", False)
    assert row(store, "pl-2", "s4")["status"] == "sourcing"
    store.set_wanted_status("s4", "verify", FILED)
    assert row(store, "pl-2", "s4")["status"] == "verify" and store.verify_ids() == ["s4"]


def test_a_download_finished_after_its_crate_was_turned_off_is_not_rechecked_forever(world, tmp_path):
    from sourcing.fake_slskd import FakeSlskdServer
    from tests.test_fetch import GOOD, RESPONSES, good_flac_bytes, header_only, new_song, run
    nd, client, store, rec = world["nd"], world["client"], world["store"], world["rec"]

    def verifier(*a, **k):                                             # Michael un-flags the crate mid-download
        rec.set_crate("pl-2", False)
        return header_only(*a, **k)
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(nd, len(flac))
        r = run(world, srv, approve=True, verifier=verifier)
    assert r.status == "ok", r.reason
    assert row(store, "pl-2", "s4")["status"] == "ok" and store.verify_ids() == []
    assert [e.id for e in client.playlist("pl-2").entries] == ["s3", "s4", "s5"]   # not a tiered playlist: untouched
    rec.run()
    assert row(store, "pl-2", "s4")["status"] == "removed"


HOLD = """
import fcntl, sys, time
fd = open(sys.argv[1], "a")
fcntl.flock(fd, fcntl.LOCK_EX)
print("held", flush=True)
sys.stdin.read()
"""


def test_reconcile_waits_for_another_process_and_gives_up_busy(tmp_path):
    import subprocess
    import sys
    from crates.reconcile import ReconcileBusy
    with FakeSubsonicServer() as srv:
        client = SubsonicClient(srv.url, "demo", "demo")
        store = CrateStore(tmp_path / "crates.db")
        rec = Reconciler(client, store, lock_timeout_s=0.3)
        p = subprocess.Popen([sys.executable, "-c", HOLD, str(tmp_path / "reconcile.lock")],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, encoding="utf-8")
        try:
            assert p.stdout.readline().strip() == "held"
            with pytest.raises(ReconcileBusy):
                rec.run()
            with pytest.raises(ReconcileBusy):
                rec.set_crate("pl-1", True)
            assert srv.state.playlists["pl-1"]["comment"] == ""        # busy: nothing written
        finally:
            p.communicate("")
        rec.run()                                                      # released: runs, nested re-judging included
        assert rec.set_crate("pl-1", True)["crate"] and store.tracks("pl-1")


def test_a_busy_reconcile_is_a_503_in_the_web_client(tmp_path):
    from crates.reconcile import hold_reconcile_lock
    from crates.service import Config, CrateApp, CrateServer
    from tests.test_service import post
    with FakeSubsonicServer() as fake:
        cfg = Config(subsonic_url=fake.url, username="demo", password="demo", db_path=str(tmp_path / "c.db"), port=0,
                     public_url="http://x.example:4533")
        app = CrateApp(cfg, store=CrateStore(tmp_path / "c.db"))
        app.reconciler.lock_timeout_s = 0.2
        with CrateServer(app) as srv, hold_reconcile_lock(tmp_path / "reconcile.lock", 1):
            s, d = post(srv.url + "/api/playlists/pl-1/crate", {"enabled": True})
            assert s == 503 and "busy" in d["error"]
            s, d = post(srv.url + "/api/reconcile", {})
            assert s == 503
        assert fake.state.playlists["pl-1"]["comment"] == ""


def test_worker_skips_a_busy_reconcile_and_ticks_on():
    from crates.reconcile import ReconcileBusy

    class Busy:
        def run(self):
            raise ReconcileBusy("another reconcile holds the lock")
    lines = []
    report = _worker(Busy(), [0.0], lines, reconcile_s=600).tick()
    assert report.approvals == 0 and any("reconcile skipped" in x and "holds the lock" in x for x in lines)


def test_import_into_a_playlist_named_as_a_crate_matches_and_queues_at_crate(env):
    srv, client, store, rec = env
    srv.state.songs["s1"]["title"] = "Good Times (Club Mix)"
    pl = client.create_playlist("Tea tent [crate]", [])
    client.update_playlist(pl.id, comment="#imported")
    rep = ip.import_playlist("Tea tent [crate]", ROWS2, client, store, source="s")
    assert rep.matches[0].status == "matched" and rep.matches[0].song_id == "s1"
    assert [r["tier"] for r in store.external_for_playlist(pl.id)] == ["crate"]


def test_worker_once_no_reconcile(tmp_path, monkeypatch):
    import shutil
    import sourcing.worker
    from sourcing.fake_slskd import FakeSlskdServer
    from tests.test_fetch import RESPONSES
    from tests.test_tier_rows import _cli_env
    seen = []

    class Spy(sourcing.worker.Worker):
        def __init__(self, **kw):
            seen.append(kw["reconcile_s"])
            super().__init__(**kw)
    monkeypatch.setattr(sourcing.worker, "Worker", Spy)
    shutil.copy(cli.DEFAULT_BEETS_CONFIG, tmp_path / "beets.yaml")
    with FakeSubsonicServer() as nd, FakeSlskdServer(RESPONSES, tmp_path / "dl", files={}) as sl:
        _cli_env(monkeypatch, tmp_path, nd, sl)
        monkeypatch.setenv("BEETS_CONFIG", str(tmp_path / "beets.yaml"))
        monkeypatch.setenv("DJ_WORKER", "1")
        monkeypatch.delenv("WORKER_RECONCILE_S", raising=False)
        assert cli.main(["worker", "--once", "--no-reconcile"]) == 0
        assert CrateStore(tmp_path / "c.db").get("pl-2") is None        # the cache was not written
        assert cli.main(["worker", "--once"]) == 0
        assert CrateStore(tmp_path / "c.db").get("pl-2").enabled        # default: reconciles on the first tick
    assert seen == [0.0, 600.0]


def test_crates_cli_reconcile_and_tier_say_busy_and_exit_1(tmp_path, monkeypatch, capsys):
    import functools
    import crates.service
    from crates.cli import main as crates_main
    from crates.reconcile import hold_reconcile_lock
    monkeypatch.setattr(crates.service, "Reconciler", functools.partial(Reconciler, lock_timeout_s=0.2))
    with FakeSubsonicServer() as nd:
        for k, v in dict(SUBSONIC_URL=nd.url, SUBSONIC_USER="demo", SUBSONIC_PASS="demo",
                         CRATES_DB=str(tmp_path / "c.db")).items():
            monkeypatch.setenv(k, v)
        with hold_reconcile_lock(tmp_path / "reconcile.lock", 1):
            assert crates_main(["reconcile"]) == 1
            assert "try again" in capsys.readouterr().err
            assert crates_main(["tier", "pl-1", "high"]) == 1
            assert "try again" in capsys.readouterr().err
        assert nd.state.playlists["pl-1"]["comment"] == ""
