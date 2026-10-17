"""M8 Task 11: play-now (D20). Pressing play on a queued track that is not in the library is Michael's approval for
ONE fast copy at tier `low`; it is filed as a provisional copy, and an upgrade at the row's tier is queued, waiting
for his approval. The upgrade is an ordinary copy replacement of the provisional file (Task 8)."""
import sqlite3
import threading
from pathlib import Path

import pytest

from crates.service import Config, CrateApp, CrateServer
from crates.store import CrateStore, PlayNowRefused
from sourcing import import_playlist as ip
from sourcing.fake_slskd import FakeSlskdServer
from sourcing.fetch import FetchResult
from sourcing.filer import BeetsFiler
from sourcing.playlist_sources import Row
from sourcing.slskd_client import SlskdClient
from sourcing.verify import Verdict
from sourcing.worker import Worker
from subsonic.client import SubsonicClient
from subsonic.fake_server import FakeSubsonicServer
from tests.helpers import beets_items_db, fake_beet, make_flac
from tests.test_fetch import world  # noqa: F401  (fixture)
from tests.test_service import get, post
from tests.test_tiers import FAST_MP3, SLOW_FLAC

PAIR = [FAST_MP3, SLOW_FLAC]
MP3 = FAST_MP3["files"][0]["filename"]
FLAC = SLOW_FLAC["files"][0]["filename"]
MP3_REL = "Chic/Risqué (1979)/03 - Good Times.mp3"            # where the fake beets files the provisional copy
FLAC_REL = "Chic/Risqué (1979)/03 - Good Times.flac"          # ... and the upgrade
MP3_BYTES = b"ID3" + b"\x01" * 4000


def flac_bytes(tmp_path) -> bytes:
    return make_flac(tmp_path / "up.flac", total=44100 * 501, pad_bytes=501 * 900_000 // 8).read_bytes()


class Spy:
    """A verifier that accepts every file and records the tier it was asked to check at. A copy compared with its
    reference is marked replaceable (as tests.test_fetch.header_only models "the fingerprint matched")."""

    def __init__(self, replaceable=True):
        self.calls, self.replaceable = [], replaceable

    def __call__(self, path, duration, tier=None, reference=None, intent=None, **kw):
        self.calls.append({"tier": tier, "intent": intent, "name": Path(path).name,
                           "reference": str(reference) if reference else None})
        m = {"intent": intent}
        if intent == "copy" and reference is not None and self.replaceable:
            st = Path(reference).stat()
            m.update(replaceable=True, reference={"path": str(Path(reference).resolve()), "size": st.st_size,
                                                  "mtime_ns": st.st_mtime_ns})
        return Verdict(True, [], None, measurements=m)


def filer(world, tmp_path) -> BeetsFiler:
    """The fake beets files an mp3 at MP3_REL and a flac at FLAC_REL (one per test: a restarted worker shares it)."""
    if "pn_filer" in world:
        return world["pn_filer"]
    lib = beets_items_db(tmp_path / "pn-library.db")
    runners = {".mp3": fake_beet(world["music"], lib, MP3_REL, artist="Chic", title="Good Times"),
               ".flac": fake_beet(world["music"], lib, FLAC_REL, artist="Chic", title="Good Times")}

    def run(cmd, **kw):
        if "import" in cmd:
            src = next(p for p in Path(cmd[-1]).iterdir() if p.is_file())
            return runners[src.suffix](cmd, **kw)
        return runners[".mp3"](cmd, **kw)
    world["pn_filer"] = BeetsFiler(tmp_path / "beets.yaml", library=lib, runner=run, tagger=lambda path, names: [])
    return world["pn_filer"]


def lib_song(world, song_id, rel, size, suffix):
    """What Navidrome 'finds' after the rescan (the fake has no files): the filed copy (the mp3 at FAST_MP3's 64 kbps,
    which meets medium's floor and not high's)."""
    nd = world["nd"]
    nd.state.songs[song_id] = dict(nd.state.songs["s1"], id=song_id, title="Good Times", artist="Chic", album="Risqué",
                                   suffix=suffix, size=size, path=rel, duration=501,
                                   **({"bitRate": 64} if suffix == "mp3" else {}))


def worker(world, srv, tmp_path, verifier=None, lines=None, **kw) -> Worker:
    lines = [] if lines is None else lines
    return Worker(store=world["store"], slskd=SlskdClient(srv.url, "k"), navidrome=world["client"],
                  reconciler=world["rec"],
                  fetch_kwargs=dict(music_root=world["music"], downloads_root=world["dl"], filer=filer(world, tmp_path),
                                    verifier=verifier or Spy(), poll_s=0.01, download_timeout_s=1, scan_timeout_s=0.05,
                                    navidrome_db=world["nd"].state.db_path, trash_root=world["trash"]),
                  log=lines.append, **kw)


def ext(world, tier="high") -> str:
    return world["store"].add_external_wanted("Chic", "Good Times", album="Risqué", duration_s=501, year=1979, tier=tier)


@pytest.fixture
def app(world):
    cfg = Config(subsonic_url=world["nd"].url, username="demo", password="demo", db_path=":memory:", port=0,
                 navidrome_db=str(world["nd"].state.db_path))
    return CrateApp(cfg, store=world["store"])


@pytest.fixture
def web(app):
    with CrateServer(app) as srv:
        yield srv


def approvals(store) -> list[dict]:
    return [dict(r) for r in store.db.execute("SELECT * FROM approvals ORDER BY id")]


def events(store, kind) -> list[str]:
    return [e["detail"] for e in reversed(store.events(limit=1000)) if e["kind"] == kind]


def play_now_tick(world, tmp_path, verifier=None, responses=PAIR, files=None):
    """One worker tick with the fake slskd offering `responses`; the provisional mp3 is listed by Navidrome."""
    with FakeSlskdServer(responses, world["dl"], files=files or {MP3: MP3_BYTES}) as srv:
        lib_song(world, "s10", MP3_REL, len(MP3_BYTES), "mp3")
        report = worker(world, srv, tmp_path, verifier).tick()
    return report, srv


# --- the approval ---------------------------------------------------------------------------------------------

def test_play_now_records_michaels_approval_for_one_low_copy(world, web):
    e = ext(world)
    s, a = post(web.url + f"/api/wanted/{e}/play-now", {})
    assert s == 200, a
    assert (a["approved_by"], a["tier"], a["purpose"], a["candidate"], a["used_at"]) == ("michael", "low", "play-now",
                                                                                          None, None)
    assert world["store"].external(e)["tier"] == "high"                  # the row's tier is untouched
    assert [x["wanted_id"] for x in world["store"].pending_approvals()] == [e]
    assert world["store"].has_play_now()


def test_a_plain_approval_is_a_download(world):
    store = world["store"]
    store.approve("s4", "michael", None, "crate")
    assert store.approval("s4")["purpose"] == "download" and not store.has_play_now()


def test_double_tap_is_one_approval(world, web):
    e = ext(world)
    first = post(web.url + f"/api/wanted/{e}/play-now", {})
    second = post(web.url + f"/api/wanted/{e}/play-now", {})
    assert first[0] == 200 and second[0] == 409 and "already" in second[1]["error"]
    assert len(approvals(world["store"])) == 1 and approvals(world["store"])[0]["used_at"] is None


def test_two_devices_tapping_at_once_make_one_approval(world, web):
    e = ext(world)
    out, go = [], threading.Barrier(6)

    def tap():
        go.wait()
        out.append(post(web.url + f"/api/wanted/{e}/play-now", {})[0])
    threads = [threading.Thread(target=tap) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(out) == [200] + [409] * 5
    assert len(approvals(world["store"])) == 1


def test_two_processes_tapping_make_one_approval(tmp_path):
    """The guard is in the INSERT itself, so two connections (the crates service and any other process on the same
    crates.db) cannot both record one."""
    a, b = CrateStore(tmp_path / "crates.db"), CrateStore(tmp_path / "crates.db")
    e = a.add_external_wanted("Chic", "Good Times", tier="medium"); a.commit()
    a.approve(e, "michael", None, "low", purpose="play-now")
    with pytest.raises(PlayNowRefused):
        b.approve(e, "michael", None, "low", purpose="play-now")
    assert b.db.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 1


def test_a_claimed_approval_refuses_a_play_now_in_another_process(tmp_path):
    a, b = CrateStore(tmp_path / "crates.db"), CrateStore(tmp_path / "crates.db")
    e = a.add_external_wanted("Chic", "Good Times", tier="medium"); a.commit()
    assert a.claim_approval(a.approve(e, "michael", None, "medium"))       # the worker is fetching it
    with pytest.raises(PlayNowRefused):
        b.approve(e, "michael", None, "low", purpose="play-now")
    a.mark_approval_used(1, "needs_source: no acceptable candidate")       # done: a tap is a new approval
    assert b.approve(e, "michael", None, "low", purpose="play-now") == 2


def test_a_tap_never_supersedes_a_pending_approval(world, web):
    e = ext(world)
    world["store"].approve(e, "michael", {"username": "u", "filename": "f"}, "medium")
    s, body = post(web.url + f"/api/wanted/{e}/play-now", {})
    assert s == 409 and "approval" in body["error"]
    assert [(a["purpose"], a["used_at"]) for a in approvals(world["store"])] == [("download", None)]


def test_a_tap_while_the_worker_searches_is_refused(world, web):
    """The worker claimed the approval (`started`) and is searching: the row still says needs_source."""
    e = ext(world)
    post(web.url + f"/api/wanted/{e}/play-now", {})
    assert world["store"].claim_approval(approvals(world["store"])[0]["id"])
    assert world["store"].external(e)["status"] == "needs_source"
    s, body = post(web.url + f"/api/wanted/{e}/play-now", {})
    assert s == 409 and "in progress" in body["error"]
    assert len(approvals(world["store"])) == 1


def test_play_now_is_refused_for_owned_in_progress_and_review_rows(world, web):
    store = world["store"]
    cases = {}
    cases["s4"] = "play the library file"                                    # a playlist row: in Navidrome already
    owned = store.add_external_wanted("A", "Owned", tier="medium")
    store.set_external_song(owned, "s1", False); store.set_external_status(owned, "ok", "filed as x.flac")
    cases[owned] = "already in the library: play s1"
    matched = store.add_external_wanted("B", "Matched", tier="medium")
    store.set_external_status(matched, "ok", "in library: s2")             # import-playlist found it (no song id)
    cases[matched] = "already in the library"
    upgrade = store.add_external_wanted("C", "Provisional", tier="medium")
    store.set_external_song(upgrade, "s3", True)
    store.set_external_status(upgrade, "needs_source", "provisional low copy filed as x.mp3; upgrade at medium …")
    cases[upgrade] = "already in the library: play s3"
    for status, reason, why in (("sourcing", "downloading x.mp3", "in progress"),
                                ("verify", "filed as x.mp3 but Navidrome has not picked it up yet", "in progress"),
                                ("failed", "Navidrome never indexed x.mp3; file is in the library", "in progress"),
                                ("review", "ambiguous (length differs): t1, t2", "pick a version first")):
        i = store.add_external_wanted("D", f"Row {status}", tier="medium")
        store.set_external_status(i, status, reason)
        cases[i] = why
    store.commit()
    for wanted_id, why in cases.items():
        s, body = post(web.url + f"/api/wanted/{wanted_id}/play-now", {})
        assert s == 409 and why in body["error"], (wanted_id, s, body)
    assert approvals(store) == []
    assert post(web.url + "/api/wanted/ext-999/play-now", {})[0] == 404
    assert approvals(store) == []


def test_a_failed_download_can_be_played_now(world, web):
    e = ext(world)
    world["store"].set_external_status(e, "failed", "download timed out"); world["store"].commit()
    assert post(web.url + f"/api/wanted/{e}/play-now", {})[0] == 200


def test_get_wanted_row_endpoint(world, web):
    e = ext(world)
    s, _, row = get(web.url + f"/api/wanted/{e}")
    assert s == 200 and row["song_id"] == e and row["approval"] is None and row["library_song_id"] is None
    assert row["provisional"] == 0 and row["verify"] is None and row["filed"] is False
    post(web.url + f"/api/wanted/{e}/play-now", {})
    s, _, row = get(web.url + f"/api/wanted/{e}")
    assert row["approval"]["purpose"] == "play-now" and row["status"] == "needs_source"
    s, _, crate_row = get(web.url + "/api/wanted/s4")
    assert s == 200 and crate_row["song_id"] == "s4" and crate_row["crates"] == ["Chicago 86"]
    assert get(web.url + "/api/wanted/ext-999")[0] == 404
    assert get(web.url + "/api/wanted/nope")[0] == 404


# --- the worker -----------------------------------------------------------------------------------------------

def test_worker_takes_play_now_first(world, tmp_path):
    store, seen = world["store"], []
    first, second = ext(world), store.add_external_wanted("Chic", "Le Freak", tier="medium")
    store.approve(first, "michael", None, "medium")
    store.approve(second, "michael", None, "low", purpose="play-now")
    assert [a["wanted_id"] for a in store.pending_approvals()] == [second, first]

    def fetcher(wanted_id, **kw):
        seen.append((wanted_id, kw.get("score_tier"), kw.get("provisional", False)))
        return FetchResult("needs_source", "no acceptable candidate")
    with FakeSlskdServer([], world["dl"], files={}) as srv:
        worker(world, srv, tmp_path, fetcher=fetcher).tick()
    assert seen == [(second, "low", True), (first, None, False)]


def test_play_now_is_taken_before_a_slow_reconcile_and_rechecks(world, tmp_path):
    store, order = world["store"], []
    e = ext(world)
    store.approve(e, "michael", None, "low", purpose="play-now")
    other = store.add_external_wanted("Chic", "Le Freak", tier="medium")
    store.set_external_status(other, "verify", "filed as y.flac but Navidrome has not picked it up yet"); store.commit()

    class Rec:
        def run(self):
            order.append("reconcile")

    def fetcher(wanted_id, **kw):
        order.append(wanted_id)
        return FetchResult("needs_source", "no acceptable candidate")
    with FakeSlskdServer([], world["dl"], files={}) as srv:
        w = worker(world, srv, tmp_path, fetcher=fetcher, reconcile_s=600)
        w.reconciler = Rec()
        w.tick()
    assert order == [e, "reconcile", other]


def test_play_now_wakes_a_sleeping_worker(world, tmp_path):
    store, clock, starts = world["store"], [1000.0], []
    e = ext(world)

    def sleep(s):
        assert 0 < s <= 1
        clock[0] += s
        if len(starts) == 1 and clock[0] >= 1003:          # Michael taps 3 s into the first 30 s wait
            if not store.has_play_now():
                store.approve(e, "michael", None, "low", purpose="play-now")

    def tick(self):
        starts.append(clock[0])
    with FakeSlskdServer([], world["dl"], files={}) as srv:
        w = worker(world, srv, tmp_path)
        w.tick = tick.__get__(w)
        w.run(30, ticks=2, sleep=sleep, now=lambda: clock[0])
    assert len(starts) == 2 and 1003 <= starts[1] <= 1004


def test_without_play_now_the_worker_sleeps_the_whole_poll(world, tmp_path):
    clock, starts, steps = [0.0], [], []

    def sleep(s):
        steps.append(s)
        clock[0] += s
    with FakeSlskdServer([], world["dl"], files={}) as srv:
        w = worker(world, srv, tmp_path)
        w.tick = (lambda self: starts.append(clock[0])).__get__(w)
        w.run(30, ticks=2, sleep=sleep, now=lambda: clock[0])
    assert starts == [0.0, 30.0] and max(steps) <= 1


def test_play_now_scores_and_verifies_at_low_without_changing_the_row_tier(world, tmp_path):
    store, spy = world["store"], Spy()
    e = ext(world)
    store.approve(e, "michael", None, "low", purpose="play-now")
    report, srv = play_now_tick(world, tmp_path, spy)
    assert srv.enqueued == [("fastpeer", MP3)]                              # the fast mp3, not the slow FLAC
    assert [c["tier"] for c in spy.calls] == ["low"] and spy.calls[0]["intent"] is None
    assert store.external(e)["tier"] == "high"
    assert store.verification(e)["tier"] == "low"


def test_provisional_copy_requeues_the_row_as_an_upgrade_awaiting_approval(world, tmp_path):
    store = world["store"]
    e = ext(world)
    store.approve(e, "michael", None, "low", purpose="play-now")
    report, _ = play_now_tick(world, tmp_path)
    row = store.external(e)
    assert (row["library_song_id"], row["provisional"], row["status"]) == ("s10", 1, "needs_source")
    assert row["reason"] == f"provisional low copy filed as {MP3_REL}; upgrade at high waits for approval"
    assert store.pending_approvals() == []
    assert store.approval(e)["result"] == "ok: filed (provisional); upgrade queued"
    assert events(store, "upgrade_queued") == [f"{MP3_REL} is a provisional low copy; upgrade at high waits for approval"]
    assert (world["music"] / MP3_REL).read_bytes() == MP3_BYTES
    assert e in [w["song_id"] for w in store.wanted()]                     # the upgrade is queued, Michael approves it
    assert all("fastpeer" not in (x["detail"] or "") for x in store.events(limit=1000))


def test_the_provisional_copy_is_never_swapped_into_a_playlist_or_proposed(world, tmp_path):
    store = world["store"]
    e = ext(world, tier="crate")
    store.approve(e, "michael", None, "low", purpose="play-now")
    play_now_tick(world, tmp_path)
    assert store.proposals(open_only=False) == []
    for pl in ("pl-1", "pl-2", "pl-3"):
        assert "s10" not in [x.id for x in world["client"].playlist(pl).entries]
    assert store.external(e)["status"] == "needs_source" and store.external(e)["tier"] == "crate"


def test_no_candidate_at_low_leaves_the_row_queued_and_a_new_tap_allowed(world, tmp_path, app):
    store = world["store"]
    e = ext(world)
    app.play_now(e)
    locked = [dict(r, files=[dict(f, isLocked=True) for f in r["files"]]) for r in PAIR]
    report, srv = play_now_tick(world, tmp_path, responses=locked)
    assert srv.enqueued == []
    row = store.external(e)
    assert (row["status"], row["library_song_id"], row["provisional"]) == ("needs_source", None, 0)
    assert store.approval(e)["result"] == "needs_source: no acceptable candidate"
    assert app.play_now(e)["purpose"] == "play-now"                        # tapping again is a new approval


def test_play_now_rows_are_rechecked_every_tick(world, tmp_path):
    store = world["store"]
    e = ext(world)
    store.approve(e, "michael", None, "low", purpose="play-now")
    with FakeSlskdServer(PAIR, world["dl"], files={MP3: MP3_BYTES}) as srv:
        w = worker(world, srv, tmp_path, recheck_s=300)
        w.tick()                                                           # filed; Navidrome does not list it yet
        assert store.external(e)["status"] == "verify"
        plain = store.add_external_wanted("Chic", "Le Freak", tier="medium")
        store.set_external_status(plain, "verify", "filed as y.flac but Navidrome has not picked it up yet")
        store.commit()
        assert store.verify_ids(updated_before=0) == [e]                  # the plain one waits for its interval
        assert w.tick().rechecked == 1
        lib_song(world, "s10", MP3_REL, len(MP3_BYTES), "mp3")
        w.tick()                                                           # the very next tick finds it
    row = store.external(e)
    assert (row["status"], row["library_song_id"], row["provisional"]) == ("needs_source", "s10", 1)
    assert len(srv.enqueued) == 1


def test_a_worker_restart_during_the_download_lets_michael_tap_again(world, tmp_path, app):
    store = world["store"]
    e = ext(world)
    app.play_now(e)
    aid = store.pending_approvals()[0]["id"]
    assert store.claim_approval(aid)
    store.set_external_status(e, "sourcing", f"downloading {Path(MP3).name}"); store.commit()   # then the kill
    with FakeSlskdServer([], world["dl"], files={}) as srv:
        worker(world, srv, tmp_path).once()
    assert store.external(e)["status"] == "failed"
    assert store.approval(e)["result"] == "interrupted: worker restarted"
    assert app.play_now(e)["purpose"] == "play-now"


def test_a_worker_restart_after_filing_still_ends_provisional(world, tmp_path):
    """Killed after beets filed the low copy, before Navidrome listed it: the re-check after the restart must not
    take the provisional copy for the row's final file."""
    store = world["store"]
    e = ext(world)
    store.approve(e, "michael", None, "low", purpose="play-now")
    with FakeSlskdServer(PAIR, world["dl"], files={MP3: MP3_BYTES}) as srv:
        worker(world, srv, tmp_path).tick()
        assert store.external(e)["status"] == "verify"
        store.db.execute("UPDATE approvals SET result='started'"); store.commit()          # as if killed mid-fetch
        lib_song(world, "s10", MP3_REL, len(MP3_BYTES), "mp3")
        worker(world, srv, tmp_path).once()
    row = store.external(e)
    assert (row["status"], row["library_song_id"], row["provisional"]) == ("needs_source", "s10", 1)
    assert "provisional low copy" in row["reason"] and len(srv.enqueued) == 1


def test_a_plain_download_after_a_failed_play_now_is_not_provisional(world, tmp_path):
    store = world["store"]
    e = ext(world)
    store.approve(e, "michael", None, "low", purpose="play-now")
    with FakeSlskdServer(PAIR, world["dl"], files={MP3: MP3_BYTES}) as srv:
        worker(world, srv, tmp_path).tick()                                # filed, never listed
    (world["music"] / MP3_REL).unlink()                                    # and the file went away
    store.set_external_status(e, "failed", "download timed out"); store.commit()
    store.approve(e, "michael", None, "high")
    flac = flac_bytes(tmp_path)
    with FakeSlskdServer([SLOW_FLAC], world["dl"], files={FLAC: flac}) as srv:
        lib_song(world, "s9", FLAC_REL, len(flac), "flac")
        worker(world, srv, tmp_path).tick()
    row = store.external(e)
    assert (row["status"], row["library_song_id"], row["provisional"]) == ("ok", "s9", 0)


# --- the upgrade ----------------------------------------------------------------------------------------------

def provisional(world, tmp_path) -> str:
    store = world["store"]
    e = ext(world)
    store.approve(e, "michael", None, "low", purpose="play-now")
    play_now_tick(world, tmp_path)
    assert store.external(e)["provisional"] == 1
    return e


def upgrade(world, tmp_path, verifier=None, gone=True):
    """Michael approves the upgrade; the fake slskd offers only the FLAC. With `gone`, Navidrome's scan marks the
    provisional song missing once its file is in the trash."""
    store, nd, client = world["store"], world["nd"], world["client"]
    real = client.start_scan

    def start_scan(*a, **kw):
        if gone and not (world["music"] / MP3_REL).exists():
            nd.state.missing.add("s10")
        return real(*a, **kw)
    client.start_scan = start_scan
    flac = flac_bytes(tmp_path)
    with FakeSlskdServer([SLOW_FLAC], world["dl"], files={FLAC: flac}) as srv:
        lib_song(world, "s9", FLAC_REL, len(flac), "flac")
        report = worker(world, srv, tmp_path, verifier).tick()
    return report


@pytest.mark.parametrize("gone", [True, False], ids=["scan-done", "scan-waiting"])
def test_upgrade_of_a_provisional_copy_is_a_copy_replacement(world, tmp_path, gone):
    store = world["store"]
    e = provisional(world, tmp_path)
    store.approve(e, "michael", None, store.external(e)["tier"])
    spy = Spy()
    upgrade(world, tmp_path, spy, gone=gone)
    assert spy.calls[0]["tier"] == "high" and spy.calls[0]["intent"] == "copy"
    assert spy.calls[0]["reference"] == str(world["music"] / MP3_REL)      # compared with the provisional file
    row = store.external(e)
    assert (row["status"], row["library_song_id"], row["provisional"]) == ("ok", "s9", 0), row["reason"]
    assert not (world["music"] / MP3_REL).exists()
    assert [p.name for p in world["trash"].rglob("*.mp3")] == ["03 - Good Times.mp3"]
    job = [dict(r) for r in store.db.execute("SELECT * FROM replacements")]
    assert [(j["old_song_id"], j["new_song_id"], j["state"]) for j in job] == \
        [("s10", "s9", "done" if gone else "scan")]


def test_an_upgrade_not_proven_the_same_keeps_the_provisional_copy(world, tmp_path):
    store = world["store"]
    e = provisional(world, tmp_path)
    store.approve(e, "michael", None, "high")
    upgrade(world, tmp_path, Spy(replaceable=False))
    row = store.external(e)
    assert row["status"] == "review" and row["reason"].startswith(f"kept beside {MP3_REL}")
    assert (row["library_song_id"], row["provisional"]) == ("s10", 1)       # still provisional: not final quality
    assert (world["music"] / MP3_REL).exists() and not world["trash"].exists()


def test_an_unproven_upgrade_accepted_in_every_slot_ends_the_row_ok(world, tmp_path):
    """Task 9 carry: once every slot holding the provisional copy took the new one, the row is done and names it;
    the provisional file stays (not proven redundant, so never trashed)."""
    from crates import proposals
    store, client = world["store"], world["client"]
    e = provisional(world, tmp_path)
    client.update_playlist("pl-2", add_song_ids=["s10"])                   # e.g. an import re-run added it
    client.update_playlist("pl-2", add_song_ids=["s10"])                   # twice: two slots, two questions
    store.approve(e, "michael", None, "high")                              # approved first: the upgrade is in flight
    world["rec"].run()
    upgrade(world, tmp_path, Spy(replaceable=False))
    qs = store.proposals()
    assert [q["kind"] for q in qs] == ["unproven_copy", "unproven_copy"]
    db = Path(world["nd"].state.db_path)
    proposals.apply(store, client, db, qs[0]["id"], "michael", world["rec"])
    assert store.external(e)["status"] == "review"                         # one slot still asks
    proposals.apply(store, client, db, qs[1]["id"], "michael", world["rec"])
    row = store.external(e)
    assert (row["status"], row["library_song_id"], row["provisional"]) == ("ok", "s9", 0)
    assert FLAC_REL in row["reason"] and MP3_REL in row["reason"]
    assert (world["music"] / MP3_REL).exists() and not world["trash"].exists()


def test_reimport_does_not_close_an_upgrade_row():
    from tests.test_import_playlist import ROWS, _lib
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        first = ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        kiwa = next(r for r in store.external_for_playlist(first.playlist_id) if r["artist"] == "Michael Kiwanuka")
        srv.state.songs["kw"] = dict(srv.state.songs["s1"], id="kw", title="Piano Joint (This Kind Of Love)",
                                     artist="Michael Kiwanuka", duration=232)
        store.set_external_song(kiwa["song_id"], "kw", True)                # play-now filed its provisional copy
        reason = "provisional low copy filed as kw.mp3; upgrade at medium waits for approval"
        store.set_external_status(kiwa["song_id"], "needs_source", reason); store.commit()
        ip.import_playlist("Tea tent", ROWS, c, store, source="s")
        row = store.external(kiwa["song_id"])
        assert (row["status"], row["reason"], row["provisional"]) == ("needs_source", reason, 1)
        assert "kw" in [x.id for x in c.playlist(first.playlist_id).entries]   # the provisional copy plays there


# --- one open request per song; no upgrade when the fast copy already meets the tier (controller rulings) -------

def test_a_fast_copy_that_meets_the_row_tier_queues_no_upgrade(world, tmp_path):
    store = world["store"]
    e = ext(world, tier="medium")                                          # 64 kbps meets medium's floor
    store.approve(e, "michael", None, "low", purpose="play-now")
    play_now_tick(world, tmp_path)
    row = store.external(e)
    assert (row["status"], row["library_song_id"], row["provisional"]) == ("ok", "s10", 0)
    assert row["reason"] == f"filed as {MP3_REL}; provisional copy already meets medium"
    assert events(store, "upgrade_queued") == [] and e not in [w["song_id"] for w in store.wanted()]


def open_requests(store, song_id) -> list[str]:
    """Wanted rows asking for a better file of this song that Michael could approve now."""
    return [w["song_id"] for w in store.wanted() if (w["song_id"] == song_id or w.get("library_song_id") == song_id)
            and w["status"] in ("needs_source", "failed") and not w["filed"]]


def test_a_tiered_playlist_holding_the_provisional_copy_supersedes_the_upgrade_row(world, tmp_path):
    store = world["store"]
    e = provisional(world, tmp_path)
    world["client"].update_playlist("pl-2", add_song_ids=["s10"])         # the crate now holds the fast copy
    world["rec"].run()
    row = store.external(e)
    assert (row["status"], row["reason"]) == ("removed", "superseded by the playlist row — its tier applies")
    assert open_requests(store, "s10") == ["s10"]                          # the playlist row, judged at crate
    assert store.track_status_map("pl-2")["s10"]["status"] == "needs_source"
    world["rec"].run()
    assert store.external(e)["status"] == "removed" and open_requests(store, "s10") == ["s10"]


def test_reimport_adding_the_provisional_song_to_its_tiered_playlist_leaves_one_open_row():
    from crates.reconcile import Reconciler
    from tests.test_import_playlist import ROWS, _lib
    with FakeSubsonicServer() as srv:
        _lib(srv)
        c, store = SubsonicClient(srv.url, "demo", "demo"), CrateStore()
        first = ip.import_playlist("Tea tent", ROWS, c, store, source="s")         # #tier:medium
        kiwa = next(r for r in store.external_for_playlist(first.playlist_id) if r["artist"] == "Michael Kiwanuka")
        srv.state.songs["kw"] = dict(srv.state.songs["s1"], id="kw", title="Piano Joint (This Kind Of Love)",
                                     artist="Michael Kiwanuka", duration=232, suffix="mp3", bitRate=48)
        store.set_external_song(kiwa["song_id"], "kw", True)
        store.set_external_status(kiwa["song_id"], "needs_source", "provisional low copy filed as kw.mp3; upgrade …")
        store.commit()
        ip.import_playlist("Tea tent", ROWS, c, store, source="s")                # adds kw to the playlist
        Reconciler(c, store).run()
        assert store.external(kiwa["song_id"])["status"] == "removed"
        assert open_requests(store, "kw") == ["kw"]


@pytest.mark.parametrize("busy", ["sourcing", "verify", "approved"])
def test_an_upgrade_in_flight_holds_the_playlist_row(world, tmp_path, web, app, busy):
    store, rec = world["store"], world["rec"]
    e = provisional(world, tmp_path)
    if busy == "approved":                                                 # Michael's yes is kept, not superseded
        store.approve(e, "michael", None, "high")
    else:
        store.set_external_status(e, busy, "filed as x.flac but Navidrome has not picked it up yet" if busy == "verify"
                                  else "downloading 03 - Good Times.flac")
    store.commit()
    world["client"].update_playlist("pl-2", add_song_ids=["s10"])
    rec.run()
    held = store.track_status_map("pl-2")["s10"]
    assert (held["status"], held["reason"]) == ("review", f"upgrade in flight as {e}")
    assert store.external(e)["status"] == (busy if busy != "approved" else "needs_source")
    s, body = post(web.url + "/api/wanted/s10/approve", {})
    assert s == 409 and f"approve {e}" in body["error"]
    app.slskd = SlskdClient("http://127.0.0.1:9", "k")                    # never reached: refused first
    with pytest.raises(Exception, match=f"approve {e}"):
        app.preview("s10")
    rec.run()                                                              # still held, re-judged every time
    assert store.track_status_map("pl-2")["s10"]["reason"] == f"upgrade in flight as {e}"
    store.db.execute("UPDATE approvals SET used_at=1, result='ok: x'")
    store.set_external_song(e, "s10", False); store.set_external_status(e, "ok", "filed as x.flac"); store.commit()
    rec.run()                                                              # the external row finished
    assert store.track_status_map("pl-2")["s10"]["status"] == "needs_source"   # judged normally (crate)
    assert store.external(e)["status"] == "ok"


def test_a_superseded_upgrade_row_is_never_downloaded(world, tmp_path):
    """Closed while a worker in another process had just claimed its approval: fetch refuses the closed row."""
    store = world["store"]
    e = provisional(world, tmp_path)
    store.approve(e, "michael", None, "high")
    store.set_external_status(e, "removed", "superseded by the playlist row — its tier applies"); store.commit()
    with FakeSlskdServer([SLOW_FLAC], world["dl"], files={FLAC: flac_bytes(tmp_path)}) as srv:
        report = worker(world, srv, tmp_path).tick()
    assert srv.enqueued == [] and store.approval(e)["result"].startswith("removed:")
