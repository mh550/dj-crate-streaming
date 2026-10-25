import time
from pathlib import Path

import pytest

from crates.reconcile import Reconciler
from crates.store import CrateStore
from sourcing.fake_slskd import FakeSlskdServer
from sourcing.fetch import fetch
from sourcing.filer import BeetsFiler
from sourcing.import_playlist import Match
from sourcing.slskd_client import SlskdClient
from sourcing.verify import verify
from subsonic.client import SubsonicClient, SubsonicError
from subsonic.fake_server import FakeSubsonicServer
from tests.helpers import beets_items_db, fake_beet, load_responses, make_flac

RESPONSES = load_responses()
GOOD = RESPONSES[0]["files"][0]["filename"]      # Chic — Good Times FLAC, 501 s


def good_flac_bytes(tmp_path) -> bytes:
    return make_flac(tmp_path / "src.flac", total=44100 * 501, pad_bytes=501 * 900_000 // 8).read_bytes()


LANDED = ("Risqué (1979) [FLAC]", "03 - Good Times.flac")     # where slskd puts the fixture file


def new_song(nd, size):
    """What Navidrome will 'find' after the rescan: the filed FLAC. The sample library already holds
    s1, a *different* Chic — Good Times FLAC, so size is what tells them apart."""
    nd.state.songs["s9"] = dict(nd.state.songs["s1"], id="s9", title="Good Times", artist="Chic", album="Risqué",
                                suffix="flac", bitRate=880, samplingRate=44100, bitDepth=16, size=size,
                                path="Chic/Risqué (1979)/03 - Good Times.flac")
    nd.state.unscanned.add("s9")


@pytest.fixture
def world(tmp_path):
    """Fake Navidrome whose crate 'Chicago 86' (pl-2) contains s4, a 128 kbps MP3 → needs_source;
    we make the wanted track *Chic — Good Times* by relabelling s4 so the fixture search matches."""
    with FakeSubsonicServer(db_path=tmp_path / "fake-navidrome.db") as nd:
        nd.state.songs["s4"].update(title="Good Times", artist="Chic", album="Risqué", year=1979, track=3, duration=501)
        old = tmp_path / "music" / nd.state.songs["s4"]["path"]       # the old copy a replacement trashes (a stand-in)
        old.parent.mkdir(parents=True)
        old.write_bytes(b"old copy of s4")
        store = CrateStore()
        client = SubsonicClient(nd.url, "demo", "demo")
        rec = Reconciler(client, store)
        rec.set_crate("pl-2", True)
        wanted = [w for w in store.wanted() if w["song_id"] == "s4"]
        assert wanted and wanted[0]["status"] == "needs_source"
        lib = beets_items_db(tmp_path / "library.db")
        filer = BeetsFiler(tmp_path / "beets.yaml", library=lib,
                           runner=fake_beet(tmp_path / "music", lib, "Chic/Risqué (1979)/03 - Good Times.flac",
                                            artist="Chic", title="Good Times"),
                           tagger=lambda path, names: [])
        yield dict(nd=nd, store=store, client=client, rec=rec, music=tmp_path / "music", dl=tmp_path / "dl", filer=filer,
                   trash=tmp_path / "trash")


@pytest.fixture
def not_in_library(monkeypatch):
    """For tests of the download itself: S1-07's library check finds nothing, so fetch downloads. The world's library
    already holds Chic – Good Times (s1, and s4, the crate row's 128 kbps mp3), and some tests list the copy they file
    before the tick; the check has its own tests below (S1-07)."""
    monkeypatch.setattr("sourcing.fetch.match_in_library", lambda client, row, accept=frozenset(): Match(row, "missing"))


def header_only(path, duration, tier=None, reference=None, **kw):
    """These downloads are synthetic header-only FLACs (no frames), so they can't be decoded: check headers only,
    as fetch did before M5. Decoded verification by tier has its own tests (test_verify_*).

    A copy upgrade compared with its reference is recorded as `replaceable`, with the reference file as verify
    records it: this models "the fingerprint matched" (the real flag is tested in test_verify_* and
    test_fetch_intent.py)."""
    v = verify(path, duration)
    if kw.get("intent") == "copy" and reference is not None:
        st = Path(reference).stat()
        v.measurements.update(replaceable=True, reference={"path": str(Path(reference).resolve()), "size": st.st_size,
                                                           "mtime_ns": st.st_mtime_ns})
    return v


def run(world, srv, approve, wanted_id="s4", **kw):
    kw.setdefault("verifier", header_only)
    kw.setdefault("filer", world["filer"])
    kw.setdefault("navidrome_db", world["nd"].state.db_path)
    kw.setdefault("trash_root", world["trash"])
    return fetch(wanted_id, store=world["store"], slskd=SlskdClient(srv.url, srv.api_key), navidrome=world["client"],
                 reconciler=world["rec"], music_root=world["music"], downloads_root=world["dl"],
                 approve=approve, poll_s=0.01, download_timeout_s=kw.pop("download_timeout_s", 1),
                 scan_timeout_s=1, retry_pause_s=kw.pop("retry_pause_s", 0), **kw)


def test_without_approve_only_scores_and_prints_pick(world, tmp_path):
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        r = run(world, srv, approve=False)
    assert r.status == "needs_source" and r.pick.username == "vinylhead77" and "Good Times" in r.explain
    assert srv.enqueued == [] and world["store"].track_status_map("pl-2")["s4"]["status"] == "needs_source"


def test_approved_fetch_runs_to_ok(world, tmp_path):
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True)
    assert r.status == "ok", r.reason
    assert r.filed == world["music"] / "Chic" / "Risqué (1979)" / "03 - Good Times.flac" and r.filed.read_bytes() == flac
    assert r.new_song_id == "s9"                                       # not s1, the library's other copy
    pl = world["client"].playlist("pl-2")
    assert [e.id for e in pl.entries] == ["s3", "s9", "s5"]           # swapped in place
    st = world["store"].track_status_map("pl-2")
    assert st["s9"]["status"] == "ok" and st["s4"]["status"] == "removed"
    assert not (world["dl"] / LANDED[0] / LANDED[1]).exists()


def test_bad_download_is_failed_and_not_filed(world, tmp_path):
    fake_lossless = make_flac(tmp_path / "bad.flac", total=44100 * 501, pad_bytes=10_000).read_bytes()
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: fake_lossless}) as srv:
        r = run(world, srv, approve=True)
    assert r.status == "failed" and "transcode" in r.reason
    assert world["store"].track_status_map("pl-2")["s4"]["status"] == "failed"
    assert not (world["music"] / "Chic").exists()        # nothing filed (the old copy s4 lives there)
    assert not (world["dl"] / LANDED[0] / LANDED[1]).exists()         # our rejected download is removed


def test_fetch_download_timeout_fails_cleanly(world, tmp_path):
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: b"x"}, complete=False) as srv:
        r = run(world, srv, approve=True, download_timeout_s=0.05)
    assert r.status == "failed" and "timed out" in r.reason
    assert not (world["music"] / "Chic").exists()        # nothing filed (the old copy s4 lives there)


def test_responses_read_empty_after_completion_are_read_again(world):
    """Live slskd (2026-10-21) once answered a finished search ("Completed, ResponseLimitReached", responseCount
    250) with [] on the first read; ext-76 then failed as "no acceptable candidate" in 2 s."""
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        srv.empty_reads = 2
        r = run(world, srv, approve=False)
    assert r.status == "needs_source" and r.pick is not None and r.pick.username == "vinylhead77", r.reason


def test_fetch_no_acceptable_candidate_leaves_needs_source(world):
    locked = [dict(r, files=[dict(f, isLocked=True) for f in r["files"]]) for r in RESPONSES]
    with FakeSlskdServer(locked, world["dl"], files={}) as srv:
        r = run(world, srv, approve=True)
    assert r.status == "needs_source" and "no acceptable candidate" in r.reason and srv.enqueued == []


def test_fetch_filed_but_not_found_after_rescan_then_rerun_recovers(world, tmp_path):
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        r = run(world, srv, approve=True)                  # no s9 registered → Navidrome never sees it
        assert r.status == "verify" and "03 - Good Times.flac" in r.reason
        assert r.filed.exists()
        assert world["store"].track_status_map("pl-2")["s4"]["status"] == "verify"
        # later: Navidrome has indexed it → re-running fetch finishes the job without a new download
        new_song(world["nd"], len(flac))
        r2 = run(world, srv, approve=True)
    assert r2.status == "ok" and r2.new_song_id == "s9" and len(srv.enqueued) == 1
    assert [e.id for e in world["client"].playlist("pl-2").entries] == ["s3", "s9", "s5"]


def test_fetch_swaps_song_in_every_crate(world, tmp_path):
    world["client"].update_playlist("pl-1", add_song_ids=["s4"])   # second crate holding the same song
    world["rec"].set_crate("pl-1", True); world["rec"].run()
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True)
    assert r.status == "ok"
    for pl_id in ("pl-1", "pl-2"):
        ids = [e.id for e in world["client"].playlist(pl_id).entries]
        assert "s9" in ids and "s4" not in ids
        assert world["store"].track_status_map(pl_id)["s9"]["status"] == "ok"


@pytest.mark.usefixtures("not_in_library")
def test_external_wanted_row_files_without_playlist_swap(world, tmp_path):
    ext = world["store"].add_external_wanted("Chic", "Good Times", album="Risqué", duration_s=501, year=1979)
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True, wanted_id=ext)
    assert r.status == "ok" and world["store"].external(ext)["status"] == "ok"
    assert [e.id for e in world["client"].playlist("pl-2").entries] == ["s3", "s4", "s5"]   # untouched


# --- S1-03: a row is never renamed onto another song (ext-74) ------------------------------------------

ASKED = "I'm Still In Love With You"
OTHER = "Al Green/Singles/One of These Good Old Days.flac"


def al_green(world, tmp_path, title, rel, nd_title, asked=ASKED):
    """An external row asking for `asked`, one peer offering a file named for it, and a filer that files it at `rel`,
    which Navidrome then lists as `nd_title` (on the Al Green album, so the row's own search finds it)."""
    store = world["store"]
    ext = store.add_external_wanted("Al Green", asked, duration_s=196, playlist_id="pl-1", position=1)
    store.record_import_order("pl-1", [(1, None, ext)])
    flac = make_flac(tmp_path / "al.flac", total=44100 * 196, pad_bytes=196 * 900_000 // 8).read_bytes()
    name = f"@@music\\Al Green\\Singles\\Al Green - {title}.flac"
    resp = [dict(RESPONSES[0], files=[dict(RESPONSES[0]["files"][0], filename=name, size=len(flac), length=196)])]
    lib = beets_items_db(tmp_path / "al-library.db")
    filer = BeetsFiler(tmp_path / "beets.yaml", library=lib, tagger=lambda path, names: [],
                       runner=fake_beet(world["music"], lib, rel, artist="Al Green", title=nd_title, length=196))
    nd = world["nd"]
    nd.state.songs["s9"] = dict(nd.state.songs["s1"], id="s9", title=nd_title, artist="Al Green",
                                album="I'm Still in Love With You", suffix="flac", bitRate=880, samplingRate=44100,
                                bitDepth=16, size=len(flac), duration=196, path=rel)
    nd.state.unscanned.add("s9")                               # listed once fetch's rescan has run
    return ext, resp, {name: flac}, filer


def events_of(world, ext, kind):
    return [e for e in world["store"].events(limit=1000) if e["kind"] == kind and e["song_id"] == ext]


def test_a_file_navidrome_lists_as_another_song_puts_the_row_in_review_not_renamed(world, tmp_path):
    store = world["store"]
    ext, resp, files, filer = al_green(world, tmp_path, ASKED, OTHER, "One of These Good Old Days")
    with FakeSlskdServer(resp, world["dl"], files=files) as srv:
        r = run(world, srv, approve=True, wanted_id=ext, filer=filer)
    why = f"filed One of These Good Old Days as {OTHER}, asked for {ASKED}"
    assert (r.status, r.reason, r.new_song_id) == ("review", why, "s9")
    row = store.external(ext)
    assert (row["status"], row["reason"]) == ("review", why)
    assert (row["artist"], row["title"], row["library_song_id"]) == ("Al Green", ASKED, None)
    assert events_of(world, ext, "renamed") == []
    (wrong,) = events_of(world, ext, "wrong_song")
    assert OTHER in wrong["detail"] and "s9" in wrong["detail"] and "vinylhead77" not in wrong["detail"]
    assert store.due_placements() == []
    assert (world["music"] / OTHER).is_file()                  # the file stays in the library as its own song


@pytest.mark.parametrize("listed", ["Love and Happiness", "Love and Happiness (Live)", "Love And Happiness feat. Bob"])
def test_the_same_song_in_another_spelling_or_version_is_renamed_as_before(world, tmp_path, listed):
    store = world["store"]
    rel = "Al Green/Singles/Love and Happiness.flac"
    ext, resp, files, filer = al_green(world, tmp_path, "Love And Happiness", rel, listed, asked="Love And Happiness")
    with FakeSlskdServer(resp, world["dl"], files=files) as srv:
        r = run(world, srv, approve=True, wanted_id=ext, filer=filer)
    assert r.status == "ok", r.reason
    row = store.external(ext)
    assert (row["status"], row["title"], row["library_song_id"]) == ("ok", listed, "s9")
    assert [e["detail"] for e in events_of(world, ext, "renamed")] == [
        f"Al Green – Love And Happiness → Al Green – {listed}"]
    assert events_of(world, ext, "wrong_song") == []
    assert [p["wanted_id"] for p in store.due_placements()] == [ext]


def test_a_recheck_that_finds_the_file_under_another_song_ends_review_not_ok(world, tmp_path):
    store = world["store"]
    ext, resp, files, filer = al_green(world, tmp_path, ASKED, OTHER, "One of These Good Old Days")
    (world["music"] / OTHER).parent.mkdir(parents=True)
    (world["music"] / OTHER).write_bytes(next(iter(files.values())))
    store.set_external_status(ext, "verify", f"filed as {OTHER} but Navidrome has not picked it up yet")
    store.commit()
    with FakeSlskdServer(resp, world["dl"], files=files) as srv:
        r = run(world, srv, approve=True, wanted_id=ext, filer=filer)
    assert srv.enqueued == []
    row = store.external(ext)
    assert (r.status, row["status"]) == ("review", "review")
    assert row["reason"] == f"filed One of These Good Old Days as {OTHER}, asked for {ASKED}"
    assert (row["title"], row["library_song_id"]) == (ASKED, None) and events_of(world, ext, "renamed") == []


def test_a_play_now_copy_of_another_song_is_review_not_the_rows_provisional_song(world, tmp_path):
    store = world["store"]
    ext, resp, files, filer = al_green(world, tmp_path, ASKED, OTHER, "One of These Good Old Days")
    with FakeSlskdServer(resp, world["dl"], files=files) as srv:
        r = run(world, srv, approve=True, wanted_id=ext, filer=filer, score_tier="low", provisional=True)
    row = store.external(ext)
    assert (r.status, row["status"], row["library_song_id"]) == ("review", "review", None)
    assert events_of(world, ext, "upgrade_queued") == [] and events_of(world, ext, "renamed") == []


def test_a_copy_upgrade_navidrome_lists_as_another_song_replaces_nothing(world, tmp_path):
    """A crate row compares with its own title: the old copy stays, no playlist is touched, no replacement starts."""
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        world["nd"].state.songs["s9"].update(title="Le Freak", album="Good Times (Single)")   # the search finds it
        r = run(world, srv, approve=True)
    assert r.status == "review", r.reason
    st = world["store"].track_status_map("pl-2")["s4"]
    assert st["status"] == "review" and st["title"] == "Good Times" and st["reason"].endswith("asked for Good Times")
    assert [e.id for e in world["client"].playlist("pl-2").entries] == ["s3", "s4", "s5"]
    assert world["store"].db.execute("SELECT COUNT(*) FROM replacements").fetchone()[0] == 0


def test_slskd_failing_on_both_peers_fails_the_row_naming_steps_not_peers(world, tmp_path):
    """The reason names the step and the endpoint (S1-05): no peer name, no URL, no API key. A 500 is the network's or
    the peer's, so a second peer is tried (S1-06) and the row fails, not raises, with both attempts."""
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: b"x"}, fail_enqueue=True, api_key="key-5e1d") as srv:
        r = run(world, srv, approve=True)
    st = world["store"].track_status_map("pl-2")["s4"]
    assert (r.status, st["status"]) == ("failed", "failed") and st["reason"] == r.reason
    err = "SlskdError: slskd POST /transfers/downloads/<peer>: HTTP 500"
    assert r.reason == f"{err} (03 - Good Times.flac); then {err} ({r.pick.basename})", r.reason
    assert r.pick.username != "vinylhead77"
    for p in {c["username"] for c in RESPONSES} | {"@", srv.api_key}:
        assert p not in st["reason"]
        assert not any(p in (e["detail"] or "") for e in world["store"].events(limit=1000))


def test_stale_completed_record_does_not_short_circuit_a_retry(world, tmp_path):
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        srv.seed_transfer("vinylhead77", GOOD, "Completed, Errored")   # left over from an earlier attempt
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True)
    assert r.status == "ok", r.reason
    assert len(srv.enqueued) == 1


def test_a_retry_tells_its_own_transfer_from_a_stale_record_of_the_same_file(world, tmp_path):
    """slskd 0.26.1 keeps a record on a plain DELETE and its listing order isn't ours to rely on: the stale `Errored`
    record of an earlier attempt sorts last ("~"), so `mine[-1]` would read it. Fetch must forget it for real
    (remove=true) and follow only the record whose id wasn't there before its enqueue."""
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        srv.seed_transfer("vinylhead77", GOOD, "Completed, Errored", transfer_id="~stale")
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True)
    assert r.status == "ok", r.reason
    assert len(srv.enqueued) == 1 and [t for t in srv.transfers if t["id"] == "~stale"] == []


def test_a_stale_succeeded_record_is_not_taken_for_this_download(world, tmp_path, monkeypatch):
    """The old record says `Completed, Succeeded` and survives the forget (here the forget doesn't take), but this
    download never finishes: the row times out instead of filing the old attempt's file."""
    monkeypatch.setattr(SlskdClient, "remove_download", lambda self, user, tid: None)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: b"x"}, complete=False) as srv:
        for tid in ("!stale", "~stale"):                  # sort before and after any uuid: no index picks ours
            srv.seed_transfer("vinylhead77", GOOD, "Completed, Succeeded", transfer_id=tid)
        world["dl"].joinpath(*LANDED).parent.mkdir(parents=True)
        world["dl"].joinpath(*LANDED).write_bytes(b"left by the earlier attempt")
        r = run(world, srv, approve=True, download_timeout_s=0.2)
    assert (r.status, r.reason) == ("failed", "download timed out")
    assert len(srv.enqueued) == 1


def test_rows_in_flight_or_done_are_reported_not_refetched(world, tmp_path):
    world["store"].set_track_status("pl-2", "s4", "sourcing", "downloading"); world["store"].commit()
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        r = run(world, srv, approve=True)
        assert r.status == "sourcing" and "in flight" in r.reason and srv.enqueued == []
        world["store"].set_track_status("pl-2", "s4", "ok", None); world["store"].commit()
        r = run(world, srv, approve=True)
    assert r.status == "ok" and "already" in r.reason


def test_the_row_says_checking_before_the_verifier_runs(world, tmp_path):
    """The web's progress strip (downloading → checking) reads the row's reason: it must change, and be committed,
    before the minutes-long verifier starts, not after."""
    seen = {}

    def spy(path, duration, tier=None, reference=None, **kw):
        row = world["store"].find_wanted("s4")
        seen.update(status=row["status"], reason=row["reason"], in_tx=world["store"].db.in_transaction)
        return header_only(path, duration, tier=tier, reference=reference, **kw)

    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True, verifier=spy)
    assert r.status == "ok", r.reason
    assert seen == {"status": "sourcing", "reason": "checking 03 - Good Times.flac", "in_tx": False}


def test_the_download_wait_polls_through_the_given_sleep(world):
    """The worker passes a `sleep` that beats its heartbeat (H1-02): a long download must not look like a dead worker."""
    world["store"].approve("s4", "michael", None, "crate"); world["store"].commit()
    calls = []
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: b"x"}, complete=False) as srv:
        r = run(world, srv, True, download_timeout_s=0.2, sleep=calls.append)
    assert (r.status, r.reason) == ("failed", "download timed out") and calls and set(calls) == {0.01}


# S1-06: one more source on a transfer error. p-vpn is ranked first (faster) and its transfer errors (a VPN drop);
# p-ok offers the fixture file.
VPN = "@@vpn\\Chic - Risqué (1979) [FLAC]\\Chic - Good Times.flac"     # scores as GOOD; listed first


def two_peers(*more: str) -> list[dict]:
    first = dict(RESPONSES[0], username="p-vpn", uploadSpeed=9_000_000, files=[dict(RESPONSES[0]["files"][0], filename=VPN)])
    return [first, dict(RESPONSES[0], username="p-ok", files=[RESPONSES[0]["files"][0]])] + [
        dict(RESPONSES[0], username=u, uploadSpeed=100, files=[dict(RESPONSES[0]["files"][0], filename=f"@@{u}\\Chic\\Good Times.flac")])
        for u in more]


def _no_peer_names(world, *peers):
    texts = [st["reason"] or "" for st in world["store"].track_status_map("pl-2").values()]
    texts += [e["detail"] or "" for e in world["store"].events(limit=1000)]
    assert not any(p in t for p in peers for t in texts)


def _retries(world):
    return [e["detail"] for e in world["store"].events(limit=1000) if e["kind"] == "retry"]


@pytest.mark.parametrize("state", ["Completed, Errored", "Completed, TimedOut", "Completed, Rejected", "Completed, Cancelled"])
def test_a_transfer_error_tries_the_next_peer_once(world, tmp_path, state):
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(two_peers(), world["dl"], files={GOOD: flac}, errored_peers={"p-vpn"}) as srv:
        srv.error_state = state
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True)
    assert r.status == "ok", r.reason
    assert srv.enqueued == [("p-vpn", VPN), ("p-ok", GOOD)]
    assert _retries(world) == [f"Chic - Good Times.flac: download ended: {state}; trying another peer"]
    _no_peer_names(world, "p-vpn", "p-ok")


def test_the_second_source_waits_out_a_vpn_drop_through_the_given_sleep(world, tmp_path):
    """slskd is logged out of Soulseek for about 10 s after a gluetun drop: switching at once would meet the same drop
    (S1-R1 review I-2). The pause goes through `sleep`, so the worker's heartbeat keeps beating."""
    flac = good_flac_bytes(tmp_path)
    calls = []
    def sleep(s):
        calls.append((s, len(srv.enqueued)))
        time.sleep(min(s, 0.01))
    with FakeSlskdServer(two_peers(), world["dl"], files={GOOD: flac}, errored_peers={"p-vpn"}) as srv:
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True, sleep=sleep, retry_pause_s=7)
    assert r.status == "ok", r.reason
    assert (7, 1) in calls and srv.enqueued == [("p-vpn", VPN), ("p-ok", GOOD)]


def test_our_own_timeout_cancels_and_forgets_our_transfer(world):
    """A transfer still running when we give up must not land later, unfiled, nor be invisible to the next approval
    of the same file (S1-04 follows only new ids): it is cancelled and forgotten (S1-R1 review I-3). A record from
    before our enqueue is not ours and stays."""
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: b"x"}, complete=False) as srv:
        srv.seed_transfer("vinylhead77", GOOD, "InProgress", transfer_id="earlier")
        r = run(world, srv, approve=True, download_timeout_s=0.05)
    assert (r.status, r.reason) == ("failed", "download timed out")
    assert len(srv.enqueued) == 1 and [t["id"] for t in srv.transfers] == ["earlier"]


def test_a_second_transfer_error_fails_with_both_attempts_and_tries_no_third(world, tmp_path):
    with FakeSlskdServer(two_peers("p-3"), world["dl"], files={GOOD: b"x"}, errored_peers={"p-vpn", "p-ok", "p-3"}) as srv:
        r = run(world, srv, approve=True)
    assert r.status == "failed"
    assert r.reason == ("download ended: Completed, Errored (Chic - Good Times.flac); "
                        "then download ended: Completed, Errored (03 - Good Times.flac)")
    assert world["store"].track_status_map("pl-2")["s4"]["reason"] == r.reason
    assert [u for u, _ in srv.enqueued] == ["p-vpn", "p-ok"] and len(_retries(world)) == 1
    _no_peer_names(world, "p-vpn", "p-ok", "p-3")


def test_no_other_peer_fails_with_the_first_reason(world):
    with FakeSlskdServer(two_peers()[:1], world["dl"], files={}, errored_peers={"p-vpn"}) as srv:
        r = run(world, srv, approve=True)
    assert (r.status, r.reason) == ("failed", "download ended: Completed, Errored") and len(srv.enqueued) == 1
    assert _retries(world) == []


def test_a_verify_failure_is_not_retried_on_another_peer(world, tmp_path):
    fake_lossless = make_flac(tmp_path / "bad.flac", total=44100 * 501, pad_bytes=10_000).read_bytes()
    with FakeSlskdServer(two_peers(), world["dl"], files={VPN: fake_lossless, GOOD: good_flac_bytes(tmp_path)}) as srv:
        r = run(world, srv, approve=True)
    assert r.status == "failed" and "transcode" in r.reason
    assert srv.enqueued == [("p-vpn", VPN)] and _retries(world) == []


def test_a_5xx_from_the_enqueue_tries_the_next_peer(world, tmp_path):
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(two_peers(), world["dl"], files={GOOD: flac}, fail_enqueue={"p-vpn"}) as srv:
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True)
    assert r.status == "ok", r.reason
    assert srv.enqueued == [("p-ok", GOOD)]
    assert _retries(world) == ["Chic - Good Times.flac: SlskdError: slskd POST /transfers/downloads/<peer>: HTTP 500; "
                               "trying another peer"]
    _no_peer_names(world, "p-vpn", "p-ok")


def test_a_connection_error_during_the_poll_tries_the_next_peer(world, tmp_path, monkeypatch):
    from sourcing.slskd_client import SlskdError
    real = SlskdClient.downloads
    polls = {"p-vpn": 0}

    def flaky(self, username=None):
        if username == "p-vpn":
            polls["p-vpn"] += 1
            if polls["p-vpn"] == 3:                       # after the forget and the `before` read: the VPN blips
                raise SlskdError("GET", "/transfers/downloads/<peer>", None, "Connection refused")
        return real(self, username)

    monkeypatch.setattr(SlskdClient, "downloads", flaky)
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(two_peers(), world["dl"], files={GOOD: flac}, errored_peers={"p-vpn"}) as srv:
        srv.error_state = "InProgress"                    # p-vpn's transfer is still running when we lose slskd
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True)
    assert r.status == "ok", r.reason
    assert [u for u, _ in srv.enqueued] == ["p-vpn", "p-ok"]
    assert [t for t in srv.transfers if t["username"] == "p-vpn"] == []   # cancelled and forgotten: it can't land later
    assert _retries(world) == ["Chic - Good Times.flac: SlskdError: slskd GET /transfers/downloads/<peer>: "
                               "Connection refused; trying another peer"]


def test_a_4xx_from_slskd_does_not_switch_peers(world, monkeypatch):
    from sourcing.slskd_client import SlskdError

    def refuse(self, username, files):
        raise SlskdError("POST", "/transfers/downloads/<peer>", 404, "HTTP 404")

    monkeypatch.setattr(SlskdClient, "enqueue", refuse)
    with FakeSlskdServer(two_peers(), world["dl"], files={}) as srv:
        with pytest.raises(SlskdError):
            run(world, srv, approve=True)
    st = world["store"].track_status_map("pl-2")["s4"]
    assert (st["status"], st["reason"]) == ("failed", "SlskdError: slskd POST /transfers/downloads/<peer>: HTTP 404")
    assert _retries(world) == []


def test_a_4xx_on_the_second_peer_still_names_both_attempts(world, monkeypatch):
    from sourcing.slskd_client import SlskdError
    real = SlskdClient.enqueue

    def refuse_p_ok(self, username, files):
        if username == "p-ok":
            raise SlskdError("POST", "/transfers/downloads/<peer>", 400, "HTTP 400")
        return real(self, username, files)

    monkeypatch.setattr(SlskdClient, "enqueue", refuse_p_ok)
    with FakeSlskdServer(two_peers(), world["dl"], files={}, errored_peers={"p-vpn"}) as srv:
        r = run(world, srv, approve=True)
    assert (r.status, r.reason) == ("failed", "download ended: Completed, Errored (Chic - Good Times.flac); then "
                                              "SlskdError: slskd POST /transfers/downloads/<peer>: HTTP 400 (03 - Good Times.flac)")
    assert world["store"].track_status_map("pl-2")["s4"]["reason"] == r.reason


# --- S1-07: ask the library before downloading (ext-81's second copy) -------------------------------------

GOOD_OLD = "One of These Good Old Days"


def good_old_days(world, tmp_path, duration=195):
    """Navidrome already lists Al Green's `One of These Good Old Days` (as if ext-74 had filed it), and one peer offers
    a file named for it, so a search would find and download it."""
    nd = world["nd"]
    nd.state.songs["s7"] = dict(nd.state.songs["s1"], id="s7", title=GOOD_OLD, artist="Al Green",
                                album="I'm Still in Love With You", suffix="flac", duration=duration,
                                path=f"Al Green/Singles/{GOOD_OLD}.flac")
    flac = make_flac(tmp_path / "old-days.flac", total=44100 * 197, pad_bytes=197 * 900_000 // 8).read_bytes()
    name = f"@@music\\Al Green\\Singles\\Al Green - {GOOD_OLD}.flac"
    resp = [dict(RESPONSES[0], files=[dict(RESPONSES[0]["files"][0], filename=name, size=len(flac), length=197)])]
    return resp, {name: flac}


def counting_searches(monkeypatch) -> list[str]:
    asked: list[str] = []
    real = SlskdClient.search

    def search(self, text, *a, **kw):
        asked.append(text)
        return real(self, text, *a, **kw)

    monkeypatch.setattr(SlskdClient, "search", search)
    return asked


@pytest.mark.parametrize("approve", [True, False])
def test_a_song_already_in_the_library_is_linked_not_downloaded(world, tmp_path, monkeypatch, approve):
    store = world["store"]
    ext = store.add_external_wanted("Al Green", "One Of These Good Old Days", duration_s=197, playlist_id="pl-1",
                                    position=1)
    store.record_import_order("pl-1", [(1, None, ext)])
    store.commit()
    resp, files = good_old_days(world, tmp_path)
    searched = counting_searches(monkeypatch)
    with FakeSlskdServer(resp, world["dl"], files=files) as srv:
        r = run(world, srv, approve=approve, wanted_id=ext)
    assert srv.enqueued == [] and searched == []
    assert (r.status, r.reason, r.new_song_id, r.pick) == ("ok", "already in the library; nothing downloaded", "s7", None)
    row = store.external(ext)
    assert row["status"] == "ok" and row["reason"] == f"already in the library: {GOOD_OLD} (s7)"
    assert (row["library_song_id"], row["provisional"]) == ("s7", 0)
    assert [e["detail"] for e in events_of(world, ext, "matched")] == [f"same version: {GOOD_OLD}"]
    assert [(p["wanted_id"], p["playlist_id"], p["song_id"]) for p in store.due_placements()] == [(ext, "pl-1", "s7")]
    assert not (world["music"] / "Al Green").exists()            # nothing filed


def test_a_library_hit_is_kept_after_a_restart(world, tmp_path):
    """The row's `ok` is committed: a second CrateStore on the same file reads it (the worker's and the web's)."""
    db = tmp_path / "crates.db"
    store = CrateStore(db)
    ext = store.add_external_wanted("Al Green", "One Of These Good Old Days", duration_s=197)
    store.commit()
    resp, files = good_old_days(world, tmp_path)
    with FakeSlskdServer(resp, world["dl"], files=files) as srv:
        r = fetch(ext, store=store, slskd=SlskdClient(srv.url, srv.api_key), navidrome=world["client"],
                  reconciler=world["rec"], music_root=world["music"], downloads_root=world["dl"], approve=False)
    assert r.status == "ok"
    assert CrateStore(db).external(ext)["library_song_id"] == "s7"


def test_another_song_by_the_artist_in_the_library_does_not_stop_the_download(world, tmp_path):
    """ext-74's case: only `One of These Good Old Days` is in the library, `I'm Still In Love With You` is asked."""
    ext, resp, files, filer = al_green(world, tmp_path, ASKED, OTHER, "One of These Good Old Days")
    with FakeSlskdServer(resp, world["dl"], files=files) as srv:
        run(world, srv, approve=True, wanted_id=ext, filer=filer)
    assert len(srv.enqueued) == 1
    assert events_of(world, ext, "matched") == []


def test_the_same_title_at_another_length_is_searched_as_before(world, tmp_path):
    """`import_playlist.choose` calls it ambiguous ("length differs"): a doubt is a download offer, never a link."""
    store = world["store"]
    ext = store.add_external_wanted("Al Green", "One Of These Good Old Days", duration_s=240)
    resp, files = good_old_days(world, tmp_path)
    with FakeSlskdServer(resp, world["dl"], files=files) as srv:
        r = run(world, srv, approve=False, wanted_id=ext)
    assert r.status == "needs_source" and r.pick is not None, r.reason
    row = store.external(ext)
    assert (row["status"], row["library_song_id"]) == ("needs_source", None)
    assert events_of(world, ext, "matched") == []


@pytest.mark.parametrize("error", [OSError("Connection refused"), SubsonicError(0, "boom"), ValueError("not JSON")])
def test_a_navidrome_outage_during_the_check_searches_and_says_so(world, tmp_path, monkeypatch, error):
    store = world["store"]
    ext = store.add_external_wanted("Al Green", "One Of These Good Old Days", duration_s=197)
    resp, files = good_old_days(world, tmp_path)

    def down(self, *a, **kw):
        raise error

    monkeypatch.setattr(SubsonicClient, "search_songs", down)
    with FakeSlskdServer(resp, world["dl"], files=files) as srv:
        r = run(world, srv, approve=False, wanted_id=ext)
    assert r.status == "needs_source" and r.pick is not None, r.reason
    (ev,) = events_of(world, ext, "matched")
    assert ev["detail"].startswith(f"library not asked: {type(error).__name__}")
    assert store.external(ext)["status"] == "needs_source"


def test_a_bad_navidrome_url_does_not_put_its_token_into_the_event(world, tmp_path, monkeypatch):
    """urllib's text for a URL without a scheme is the whole URL, Subsonic's salted token and salt included (S1-R1
    review M-1): an OSError or ValueError is named by its type only."""
    store = world["store"]
    ext = store.add_external_wanted("Al Green", "One Of These Good Old Days", duration_s=197)
    resp, files = good_old_days(world, tmp_path)

    def bad(self, *a, **kw):
        raise ValueError("unknown url type: 'navidrome:4533/rest/search3?u=michael&t=5f4dcc3b&s=a1b2c3'")

    monkeypatch.setattr(SubsonicClient, "search_songs", bad)
    with FakeSlskdServer(resp, world["dl"], files=files) as srv:
        run(world, srv, approve=False, wanted_id=ext)
    (ev,) = events_of(world, ext, "matched")
    assert ev["detail"] == "library not asked: ValueError"


def test_a_crate_row_is_not_asked_about(world, tmp_path, monkeypatch):
    """A playlist row is a copy upgrade of its own song (copy_of): the library has it, which is why it is asked for."""
    asked = []
    real = SubsonicClient.search_songs
    monkeypatch.setattr(SubsonicClient, "search_songs", lambda self, *a, **kw: asked.append(a) or real(self, *a, **kw))
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        r = run(world, srv, approve=False)
    assert r.status == "needs_source" and r.pick is not None and asked == []


def test_a_provisional_copy_is_upgraded_not_linked_to_itself(world, tmp_path, monkeypatch):
    """A play-now row with its provisional low copy (s7) filed is a copy upgrade (copy_of is s7): the library check
    would find that very copy as the same version and end the upgrade, so it is never asked (S1-R1 review M-5)."""
    store = world["store"]
    ext = store.add_external_wanted("Al Green", GOOD_OLD, duration_s=195)
    resp, files = good_old_days(world, tmp_path)
    store.set_external_song(ext, "s7", True)
    store.set_external_status(ext, "needs_source", "provisional low copy filed; upgrade at medium")
    store.commit()
    asked = []
    real = SubsonicClient.search_songs
    monkeypatch.setattr(SubsonicClient, "search_songs", lambda self, *a, **kw: asked.append(a) or real(self, *a, **kw))
    with FakeSlskdServer(resp, world["dl"], files=files) as srv:
        r = run(world, srv, approve=False, wanted_id=ext)
    assert r.status == "needs_source" and r.pick is not None and asked == [], r.reason
    assert events_of(world, ext, "matched") == []
    assert (store.external(ext)["library_song_id"], store.external(ext)["provisional"]) == ("s7", 1)
