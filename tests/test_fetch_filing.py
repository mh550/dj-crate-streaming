"""fetch files a verified download through beets (D18, D22) and copies Navidrome's names back onto the row."""
import json
import sqlite3
from pathlib import Path

import pytest

from sourcing.fake_slskd import FakeSlskdServer
from sourcing.fetch import fetch
from sourcing.filer import BeetsFiler, FilingError
from sourcing.playlist_sources import rows_from_spotify
from sourcing.requests import add_spotify
from sourcing.slskd_client import SlskdClient, transfer_files
from sourcing.verify import verify
from tests.test_export_playlists import SCHEMA
from tests import test_album_job as aj
from tests.helpers import beets_items_db, fake_beet, make_flac
from tests.test_fetch import GOOD, RESPONSES, good_flac_bytes, new_song, run, world, not_in_library  # noqa: F401  (fixtures)

TARGET = "Chic/Risqué (1979)/03 - Good Times.flac"
TWELVE = 'Good Times (12" Version)'


def make_filer(world, tmp_path, *, tagger=lambda path, names: [], **beet):
    """A filer of our own (the world's one files as Chic — Good Times, as-is, with no tags filled)."""
    lib = beets_items_db(tmp_path / "other-library.db")
    return BeetsFiler(tmp_path / "beets.yaml", library=lib, tagger=tagger,
                      runner=fake_beet(world["music"], lib, TARGET, artist="Chic", title="Good Times", **beet))


def kinds(world, kind):
    return [e for e in world["store"].events(limit=1000) if e["kind"] == kind]


def test_fetch_hands_the_download_to_beets_from_a_fresh_staging_folder(world, tmp_path):
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True)
    assert r.status == "ok", r.reason
    imports = [c for c in world["filer"].runner.calls if "import" in c]
    assert len(imports) == 1
    folder = Path(imports[0][-1])
    assert folder.parent == world["dl"] / ".staging" and folder.name.startswith("s4-")
    assert not folder.exists() and not folder.with_suffix(".log").exists()
    assert [e["detail"] for e in kinds(world, "filed")] == ["beets as-is: Chic/Risqué (1979)/03 - Good Times.flac"]


def test_filed_event_carries_the_note_when_a_match_is_rejected(world, tmp_path):
    lib = beets_items_db(tmp_path / "other-library.db")
    filer = BeetsFiler(tmp_path / "beets.yaml", library=lib, tagger=lambda path, names: [],
                       confirm=lambda item: (False, "Δ79 s"),
                       runner=fake_beet(world["music"], lib, TARGET, artist="Chic", title="Good Times", matched=True))
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True, filer=filer)
    assert r.status == "ok", r.reason
    (detail,) = [e["detail"] for e in kinds(world, "filed")]
    assert "as-is" in detail and "Δ79 s" in detail
    assert len([c for c in filer.runner.calls if "remove" not in c]) == 1   # (+ the replaced copy's `beet remove`)


@pytest.mark.parametrize("outcome", ["ok", "failed"])
def test_no_peer_name_reaches_events_or_row_reasons(world, tmp_path, outcome):
    """Every reason written during the run is recorded as it is written (later statuses overwrite the
    `sourcing` one), for an ok run and for a download that fails verification."""
    store, written = world["store"], []
    set_wanted_status = store.set_wanted_status

    def recording(song_id, status, reason=None):
        written.append((status, reason or ""))
        set_wanted_status(song_id, status, reason)

    store.set_wanted_status = recording
    if outcome == "ok":
        flac = good_flac_bytes(tmp_path)
    else:                                                  # fake lossless: verify rejects it after the download
        flac = make_flac(tmp_path / "bad.flac", total=44100 * 501, pad_bytes=10_000).read_bytes()
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True)
    peer = r.pick.username
    assert r.status == outcome and peer == "vinylhead77"
    details = [e["detail"] or "" for e in store.events(limit=1000)]
    reasons = [x or "" for (x,) in store.db.execute("SELECT reason FROM crate_tracks UNION ALL SELECT reason FROM external_wanted")]
    assert details and not [d for d in details + reasons + [w for _, w in written] if peer in d]
    assert ("sourcing", "downloading 03 - Good Times.flac") in written


@pytest.mark.usefixtures("not_in_library")
def test_names_from_navidrome_go_back_onto_an_external_row(world, tmp_path):
    ext = world["store"].add_external_wanted("Chic", "Good Times", album="Risqué", duration_s=501, year=1979)
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        world["nd"].state.songs["s9"]["title"] = TWELVE
        r = run(world, srv, approve=True, wanted_id=ext)
    assert r.status == "ok", r.reason
    row = world["store"].external(ext)
    assert row["title"] == TWELVE and row["artist"] == "Chic"
    assert (row["asked_artist"], row["asked_title"]) == ("Chic", "Good Times")
    assert [e["detail"] for e in kinds(world, "renamed")] == [f"Chic – Good Times → Chic – {TWELVE}"]


def test_same_names_log_no_rename(world, tmp_path):
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True)
    assert r.status == "ok", r.reason
    assert kinds(world, "renamed") == []


@pytest.mark.usefixtures("not_in_library")
def test_renamed_external_row_is_still_found_by_its_asked_names(world, tmp_path):
    store = world["store"]
    ext = store.add_external_wanted("Chic", "Good Times", album="Risqué", duration_s=501, year=1979)
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        world["nd"].state.songs["s9"]["title"] = TWELVE
        assert run(world, srv, approve=True, wanted_id=ext).status == "ok"
    before = store.external_count()
    assert store.add_external_wanted("Chic", "Good Times") == ext       # re-seeding Spotify: same row
    assert store.external_count() == before


def test_set_wanted_names_on_a_crate_row_renames_its_live_rows(world):
    store = world["store"]
    assert store.set_wanted_names("s4", "Chic", TWELVE) is True
    assert store.track_status_map("pl-2")["s4"]["title"] == TWELVE
    assert store.set_wanted_names("s4", "Chic", TWELVE) is False          # nothing changed: no second event
    assert [e["detail"] for e in kinds(world, "renamed")] == [f"Chic – Good Times → Chic – {TWELVE}"]


def test_nothing_imported_fails_and_keeps_the_file_in_staging(world, tmp_path):
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        r = run(world, srv, approve=True, filer=make_filer(world, tmp_path, import_nothing=True))
    assert r.status == "failed" and "still in" in r.reason
    assert world["store"].track_status_map("pl-2")["s4"]["status"] == "failed"
    kept = list((world["dl"] / ".staging").glob("s4-*/03 - Good Times.flac"))
    assert len(kept) == 1 and kept[0].read_bytes() == flac
    assert not (world["music"] / "Chic").exists()        # nothing filed (the old copy s4 lives there)


def test_filing_error_marks_failed_and_reraises(world, tmp_path):
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        with pytest.raises(FilingError):
            run(world, srv, approve=True, filer=make_filer(world, tmp_path, rc=1))
    st = world["store"].track_status_map("pl-2")["s4"]
    assert st["status"] == "failed" and "FilingError" in st["reason"]


def test_approve_without_a_filer_is_refused(world):
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        r = run(world, srv, approve=True, filer=None)
    assert r.status == "refused" and "no beets filer" in r.reason and srv.enqueued == []
    assert world["store"].track_status_map("pl-2")["s4"]["status"] == "needs_source"


def test_fetch_passes_the_wanted_names_to_the_filer(world, tmp_path):
    seen = []

    def tagger(path, names):
        seen.append(names)
        return ["title"]

    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True, filer=make_filer(world, tmp_path, tagger=tagger))
    assert r.status == "ok", r.reason
    assert seen == [{"artist": "Chic", "title": "Good Times"}]
    tagged = kinds(world, "tagged")
    assert len(tagged) == 1 and "title" in tagged[0]["detail"]


def spy_verifier(seen):
    def spy(path, duration, tier=None, reference=None, intent=None, **kw):
        seen.update(path=path, duration=duration, tier=tier, reference=reference, kw=kw)
        return verify(path, duration)
    return spy


def navidrome_db(path, rows):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany("insert into media_file(id,path,title,artist,duration) values(?,?,?,?,?)", rows)
    con.commit(); con.close()
    return path


def fetched(world, tmp_path, **kw):
    flac = good_flac_bytes(tmp_path)
    seen = {}
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True, verifier=spy_verifier(seen), **kw)
    assert r.status == "ok", r.reason
    return seen


def test_crate_row_upgrade_passes_the_old_file_as_reference(world, tmp_path):
    old = world["music"] / "Old/s4.mp3"
    old.parent.mkdir(parents=True); old.write_bytes(b"x")
    db = navidrome_db(tmp_path / "navidrome.db", [("s4", "Old/s4.mp3", "Good Times", "Chic", 501.0)])
    seen = fetched(world, tmp_path, navidrome_db=db)
    assert seen["reference"] == old and seen["tier"] == "crate"
    assert kinds(world, "reference") == []


def test_missing_navidrome_db_skips_the_reference_with_a_logged_reason(world, tmp_path):
    seen = fetched(world, tmp_path, navidrome_db=tmp_path / "nope.db")
    assert seen["reference"] is None
    ev = kinds(world, "reference")
    assert len(ev) == 1 and "no reference: navidrome.db not at" in ev[0]["detail"]
    assert not (tmp_path / "nope.db").exists()          # read-only open must not create it


def test_reference_skipped_when_id_or_file_is_missing(world, tmp_path):
    db = navidrome_db(tmp_path / "navidrome.db", [("other", "Old/o.mp3", "T", "A", 1.0)])
    assert fetched(world, tmp_path, navidrome_db=db)["reference"] is None
    assert "s4 not in navidrome.db" in kinds(world, "reference")[0]["detail"]


def test_reference_skipped_when_the_old_file_is_gone(world, tmp_path):
    db = navidrome_db(tmp_path / "navidrome.db", [("s4", "Old/s4.mp3", "T", "A", 1.0)])
    assert fetched(world, tmp_path, navidrome_db=db)["reference"] is None
    assert "Old/s4.mp3 missing on disk" in kinds(world, "reference")[0]["detail"]


def test_lookup_and_recording_id_reach_verify_only_when_a_lookup_is_configured(world, tmp_path):
    assert fetched(world, tmp_path)["kw"] == {}


def test_lookup_is_passed_to_verify_with_no_recording_id_when_navidrome_has_none(world, tmp_path):
    f = lambda p: []
    kw = fetched(world, tmp_path, lookup=f)["kw"]
    assert kw == {"recording_id": None, "lookup": f, "asked_title": "Good Times"}


def test_navidromes_musicbrainz_recording_id_reaches_verify(world, tmp_path):
    world["nd"].state.songs["s4"]["musicBrainzId"] = "rec-9"
    assert fetched(world, tmp_path, lookup=lambda p: [])["kw"]["recording_id"] == "rec-9"


@pytest.mark.usefixtures("not_in_library")
def test_external_row_has_no_reference_and_no_recording_id(world, tmp_path):
    ext = world["store"].add_external_wanted("Chic", "Good Times", album="Risqué", duration_s=501, year=1979)
    f = lambda p: []
    seen = fetched(world, tmp_path, wanted_id=ext, lookup=f, navidrome_db=tmp_path / "nope.db")
    assert seen["reference"] is None and seen["kw"] == {"recording_id": None, "lookup": f, "asked_title": "Good Times"}
    assert kinds(world, "reference") == []


@pytest.mark.usefixtures("not_in_library")
def test_a_request_rows_musicbrainz_recording_reaches_verify(world, tmp_path):
    """S2-03: the release match's recording id makes verify's AcoustID check hard (it would have caught ext-74)."""
    st = world["store"]
    ext = st.add_external_wanted("Chic", "Good Times", album="Risqué", duration_s=501, year=1979)
    st.set_recording_id(ext, "cdac1a50-8ba6-4edd-8137-618928580d38")
    f = lambda p: []
    kw = fetched(world, tmp_path, wanted_id=ext, lookup=f, navidrome_db=tmp_path / "nope.db")["kw"]
    assert kw == {"recording_id": "cdac1a50-8ba6-4edd-8137-618928580d38", "lookup": f, "asked_title": "Good Times"}


def test_a_copy_upgrade_keeps_the_old_copys_recording_over_the_rows(world, tmp_path):
    st = world["store"]
    world["nd"].state.songs["s4"]["musicBrainzId"] = "rec-9"
    ext = st.add_external_wanted("Chic", "Good Times", album="Risqué", duration_s=501, year=1979)
    st.set_library_song(ext, "s4")
    st.set_recording_id(ext, "rec-row")
    assert st.find_wanted(ext)["library_song_id"] == "s4"
    kw = fetched(world, tmp_path, wanted_id=ext, lookup=lambda p: [], navidrome_db=tmp_path / "nope.db")["kw"]
    assert kw["recording_id"] == "rec-9"


def test_a_copy_upgrade_of_a_copy_without_a_recording_id_uses_the_rows(world, tmp_path):
    st = world["store"]
    ext = st.add_external_wanted("Chic", "Good Times", album="Risqué", duration_s=501, year=1979)
    st.set_library_song(ext, "s4")                      # Navidrome's s4 has no musicBrainzId
    st.set_recording_id(ext, "rec-row")
    kw = fetched(world, tmp_path, wanted_id=ext, lookup=lambda p: [], navidrome_db=tmp_path / "nope.db")["kw"]
    assert kw["recording_id"] == "rec-row"


@pytest.mark.usefixtures("not_in_library")
def test_a_renamed_external_row_passes_the_title_it_asked_for_not_its_current_name(world, tmp_path):
    """S1-02: verify compares AcoustID's title with what the row asked for; a rename may already have moved it."""
    st = world["store"]
    ext = st.add_external_wanted("Chic", "Good Times", album="Risqué", duration_s=501, year=1979)
    assert st.set_wanted_names(ext, "Chic", "Good times")
    assert st.find_wanted(ext)["title"] == "Good times"
    kw = fetched(world, tmp_path, wanted_id=ext, lookup=lambda p: [], navidrome_db=tmp_path / "nope.db")["kw"]
    assert kw["asked_title"] == "Good Times"


def test_unreadable_navidrome_db_skips_the_reference(world, tmp_path):
    bad = tmp_path / "navidrome.db"
    bad.write_bytes(b"not a database" * 100)
    assert fetched(world, tmp_path, navidrome_db=bad)["reference"] is None
    assert "unreadable" in kinds(world, "reference")[0]["detail"]


# --- once filed, the path is never lost (one copy per version) --------------------------------------

def test_exception_after_filing_keeps_the_filed_path_and_a_recheck_finishes(world, tmp_path, monkeypatch):
    client, calls = world["client"], []
    start_scan = client.start_scan

    def flaky(*a, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("navidrome restarting")
        return start_scan(*a, **kw)

    monkeypatch.setattr(client, "start_scan", flaky)
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        with pytest.raises(RuntimeError):
            run(world, srv, approve=True)
        st = world["store"].track_status_map("pl-2")["s4"]
        assert st["status"] == "verify", st["reason"]
        assert st["reason"] == f"filed as {TARGET} but Navidrome has not picked it up yet (RuntimeError: navidrome restarting)"
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True)                   # the re-check: no second download, no second import
    assert r.status == "ok", r.reason
    assert len(srv.enqueued) == 1
    assert len([c for c in world["filer"].runner.calls if "import" in c]) == 1


def test_beet_write_failure_after_import_keeps_the_filed_path(world, tmp_path):
    lib = beets_items_db(tmp_path / "other-library.db")
    beet = fake_beet(world["music"], lib, TARGET, artist="Chic", title="Good Times", matched=True)

    def write_fails(cmd, **kw):
        done = beet(cmd, **kw)
        return done if "write" not in cmd else type(done)(cmd, 1, "", "disk full")

    write_fails.calls = beet.calls
    filer = BeetsFiler(tmp_path / "beets.yaml", library=lib, tagger=lambda p, n: [], runner=write_fails,
                       confirm=lambda item: (True, "ok"))
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        with pytest.raises(FilingError, match="disk full"):
            run(world, srv, approve=True, filer=filer)
    st = world["store"].track_status_map("pl-2")["s4"]
    assert st["status"] == "verify" and st["reason"].startswith(f"filed as {TARGET} but Navidrome")
    assert "FilingError" in st["reason"]


def test_filing_error_without_an_item_keeps_the_item_the_import_callback_set(world, tmp_path):
    """A FilingError raised after beets filed the file but carrying no item must not erase the path on_imported
    recorded: the row stays `verify` with it, so a re-check (not a second download and import) follows."""
    from sourcing.filer import FiledItem

    class FilesThenFails:
        def file(self, staging, log, names=None, on_imported=None, album=None, on_tagged=None):
            target = world["music"] / TARGET
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x")
            on_imported(FiledItem(target, "Chic", "Good Times", "", False))
            raise FilingError("boom after import")           # no item attached

    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        with pytest.raises(FilingError, match="boom after import"):
            run(world, srv, approve=True, filer=FilesThenFails())
    st = world["store"].track_status_map("pl-2")["s4"]
    assert st["status"] == "verify" and st["reason"].startswith(f"filed as {TARGET} but Navidrome")


def test_reference_event_is_committed_before_the_verifier_runs(world, tmp_path):
    """The verifier decodes for minutes: crates.db must not hold a write transaction open meanwhile, or the web
    service's writes (an approval, a crate toggle) fail with `database is locked`."""
    from crates.reconcile import Reconciler
    from crates.store import CrateStore
    db = tmp_path / "crates.db"
    store = CrateStore(db)
    rec = Reconciler(world["client"], store)
    rec.set_crate("pl-2", True)
    other = CrateStore(db)                                     # the web service's connection
    other.db.execute("PRAGMA busy_timeout = 100")
    wrote = []

    def verifier(path, duration, tier=None, reference=None, **kw):
        assert "reference" in [e["kind"] for e in other.events(limit=5)]       # committed, so visible here (a "checking" status follows it)
        other.log(None, "s4", "approved", "while the download is verified"); other.commit()
        wrote.append(1)
        return verify(path, duration)

    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        r = run(dict(world, store=store, rec=rec), srv, approve=True, verifier=verifier, navidrome_db=tmp_path / "nope.db")
    assert r.status == "ok", r.reason
    assert wrote == [1]


# --- re-checks: the filed file's own names, and a limit -------------------------------------------------

def test_recheck_searches_navidrome_by_the_filed_files_own_names(world, tmp_path, monkeypatch):
    """The wanted row often carries Spotify's names, which Navidrome's search may never match; the file's tags are
    what Navidrome indexed. mediafile is Debian's on the host (the worker image pip-installs it)."""
    import subprocess
    import sys
    monkeypatch.setattr(sys, "path", sys.path + ["/usr/share/beets", "/usr/lib/python3/dist-packages"])
    store = world["store"]
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        r = run(world, srv, approve=True)
        assert r.status == "verify", r.reason
        subprocess.run(["metaflac", "--set-tag=ARTIST=Chic", f"--set-tag=TITLE={TWELVE}", str(r.filed)], check=True,
                       stdin=subprocess.DEVNULL)
        store.db.execute("UPDATE crate_tracks SET title='Good Times - 2018 Remaster' WHERE song_id='s4'"); store.commit()
        new_song(world["nd"], r.filed.stat().st_size)
        world["nd"].state.songs["s9"]["title"] = TWELVE
        r2 = run(world, srv, approve=True)
    assert r2.status == "ok" and r2.new_song_id == "s9", r2.reason


def test_recheck_counts_and_gives_up_after_the_limit(world, tmp_path):
    from sourcing.fetch import RECHECK_LIMIT
    assert RECHECK_LIMIT == 12
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        assert run(world, srv, approve=True).status == "verify"
        reasons = []
        for _ in range(RECHECK_LIMIT):
            r = run(world, srv, approve=True)
            reasons.append(world["store"].find_wanted("s4")["reason"])
    assert reasons[0] == f"filed as {TARGET} but Navidrome has not picked it up yet (check 1)"
    assert reasons[RECHECK_LIMIT - 2].endswith(f"(check {RECHECK_LIMIT - 1})")
    assert r.status == "failed" and reasons[-1] == f"Navidrome never indexed {TARGET}; file is in the library"
    assert world["store"].find_wanted("s4")["status"] == "failed"
    assert len(srv.enqueued) == 1 and (world["music"] / TARGET).exists()


# --- fix round 2: a filed file is never forgotten ------------------------------------------------------------

@pytest.mark.parametrize("status,reason", [
    ("failed", f"Navidrome never indexed {TARGET}; file is in the library"),
    ("verify", f"filed as {TARGET} but Navidrome has not picked it up yet (check 2)")])
def test_preview_of_a_filed_row_touches_nothing(world, tmp_path, status, reason):
    """Preview runs in the crates container, which does not mount the library: it must not re-check (and so
    must not decide the file is gone), and must not call Navidrome."""
    store = world["store"]
    store.set_wanted_status("s4", status, reason)
    before = store.find_wanted("s4")
    world["nd"].state.requests.clear()
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        r = run(dict(world, music=tmp_path / "not-mounted"), srv, approve=False)
    assert (r.status, r.reason) == (status, f"already filed as {TARGET}; the worker re-checks it")
    after = store.find_wanted("s4")
    assert (after["status"], after["reason"], after["updated_at"]) == (status, reason, before["updated_at"])
    assert world["nd"].state.requests == [] and srv.enqueued == []


def test_a_stop_during_confirm_leaves_the_row_verify_with_the_path(world, tmp_path):
    lib = beets_items_db(tmp_path / "other-library.db")

    def stop(item):
        raise SystemExit(143)                              # SIGTERM while MusicBrainz is being asked

    filer = BeetsFiler(tmp_path / "beets.yaml", library=lib, tagger=lambda p, n: [], confirm=stop,
                       runner=fake_beet(world["music"], lib, TARGET, artist="Chic", title="Good Times", matched=True))
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        with pytest.raises(SystemExit):
            run(world, srv, approve=True, filer=filer)
    row = world["store"].find_wanted("s4")
    assert (row["status"], row["reason"]) == ("verify", f"filed as {TARGET} but Navidrome has not picked it up yet")


def test_reseeding_a_never_indexed_row_finds_the_same_row(world):
    store = world["store"]
    ext = store.add_external_wanted("Chic", "Good Times", duration_s=501)
    store.set_wanted_status(ext, "failed", f"Navidrome never indexed {TARGET}; file is in the library")
    assert store.add_external_wanted("Chic", "Good Times") == ext
    other = store.add_external_wanted("Chic", "Le Freak")
    store.set_wanted_status(other, "failed", "download timed out")
    assert store.add_external_wanted("Chic", "Le Freak") != other          # an ordinary failure still re-queues


# --- album rows (S2-06b): the request's identity on the staged file, `--set dj_album=1`, one `tagged` record each

def album_tags(path: Path) -> dict:
    mf = pytest.importorskip("mediafile")
    m = mf.MediaFile(str(path))
    return {k: getattr(m, k) for k in ("album", "albumartist", "track", "tracktotal", "year", "mb_albumid")}


def album_events(store) -> list[dict]:
    return [json.loads(e["detail"]) for e in reversed(store.events(limit=1000))
            if e["kind"] == "tagged" and (e["detail"] or "").startswith("{")]


def fetch_planned_row(world, tmp_path, req, n=1, wrap=None):
    """fetch's planned mode for the request's track `n` (the album job's call), with the job's enqueue done here;
    `wrap(runner)` replaces the album filer's fake beet."""
    resp, data = aj.album_folder(tmp_path, req["rows"])
    row = next(r for r in req["rows"] if r["track_no"] == n)
    with FakeSlskdServer([resp], world["dl"], files=data) as srv:
        c = aj.common(world, srv, tmp_path)
        if wrap is not None:
            c["filer"].runner = wrap(c["filer"].runner)
        aj.album_job.plan_request(world["store"], c["slskd"], req["id"], poll_s=0.01)
        cand = world["store"].preview(f"req-{req['id']}")["assign"][row["song_id"]]["candidate"]
        before = {t["id"] for t in transfer_files(c["slskd"].downloads(aj.PEER))}
        c["slskd"].enqueue(aj.PEER, [{"filename": cand["filename"], "size": cand["size"]}])
        return row, fetch(row["song_id"], approve=True, planned=True, prefer=cand, enqueued=before, **c), c["filer"]


def test_every_track_of_an_album_request_carries_its_identity(world, tmp_path, not_in_library):
    store, req = world["store"], aj.request(world)
    resp, data = aj.album_folder(tmp_path, req["rows"])
    with FakeSlskdServer([resp], world["dl"], files=data) as srv:
        aj.album_job.plan_request(store, SlskdClient(srv.url, srv.api_key), req["id"], poll_s=0.01)
        aj.album_job.approve_request(store, req["id"])
        w = aj.worker(world, srv, tmp_path)
        w.tick()
    assert store.request(req["id"])["status"] == "done"
    imports = [c for c in w.common["filer"].runner.calls if "import" in c]
    assert len(imports) == 9 and all(c[c.index("--set") + 1] == "dj_album=1" for c in imports)
    for row in store.request(req["id"])["rows"]:
        filed = next((world["music"] / "Al Green" / f"{aj.ALBUM} (1972)").glob(f"{row['track_no']:02d} - *.flac"))
        assert album_tags(filed) == {"album": aj.ALBUM, "albumartist": "Al Green", "track": row["track_no"],
                                     "tracktotal": 9, "year": None, "mb_albumid": None}
    fresh = {"album": None, "albumartist": None, "track": None, "tracktotal": None}
    assert album_events(store) == [fresh] * 9
    details = [e["detail"] for e in store.events(limit=1000) if e["kind"] == "tagged"]
    assert details[0] == json.dumps(fresh, sort_keys=True)


def test_the_requests_year_and_release_id_are_written_and_tracktotal_is_the_highest_track(world, tmp_path, not_in_library):
    store, req = world["store"], aj.request(world)
    store.set_release_id(req["id"], "rel-1")
    store.db.execute("UPDATE requests SET year=1972 WHERE id=?", (req["id"],))
    store.db.execute("UPDATE external_wanted SET request_id=NULL WHERE request_id=? AND track_no=5", (req["id"],))
    store.commit()                                       # 8 rows left, the highest track still 9
    row, r, _ = fetch_planned_row(world, tmp_path, store.request(req["id"]), n=3)
    assert r.status == "ok", r.reason
    filed = next((world["music"] / "Al Green" / f"{aj.ALBUM} (1972)").glob("03 - *.flac"))
    assert album_tags(filed) == {"album": aj.ALBUM, "albumartist": "Al Green", "track": 3, "tracktotal": 9,
                                 "year": 1972, "mb_albumid": "rel-1"}



def test_tracktotal_stays_the_albums_when_its_last_track_is_held_by_another_request(world, tmp_path, not_in_library):
    """add_external_wanted keeps a row's first request: track 9 queued earlier under a track request is not this
    album's row, yet the album still has 9 tracks (the tracklist's highest number, stored on the request)."""
    store = world["store"]
    last = rows_from_spotify(aj.entity())[-1]
    held = store.add_request(kind="track", source="search", artist="Al Green", album=None, year=None)
    store.add_external_wanted("Al Green", last.title, duration_s=last.duration_s, request_id=held)
    store.commit()
    req = add_spotify(store, aj.URL, fetch=lambda url: aj.entity())
    assert max(r["track_no"] for r in req["rows"]) == 8 and req["tracktotal"] == 9
    row, r, _ = fetch_planned_row(world, tmp_path, req, n=3)
    assert r.status == "ok", r.reason
    filed = next((world["music"] / "Al Green" / f"{aj.ALBUM} (1972)").glob("03 - *.flac"))
    assert album_tags(filed)["tracktotal"] == 9

def test_a_playlist_requests_row_gets_no_album_tags(world, tmp_path, not_in_library):
    store, req = world["store"], aj.request(world)
    store.db.execute("UPDATE requests SET kind='playlist' WHERE id=?", (req["id"],))
    store.commit()
    row, r, filer = fetch_planned_row(world, tmp_path, req)
    assert r.status == "ok", r.reason
    assert not [c for c in filer.runner.calls if "--set" in c] and album_events(store) == []
    filed = next((world["music"] / "Al Green" / f"{aj.ALBUM} (1972)").glob("01 - *.flac"))
    assert album_tags(filed)["album"] is None


def test_a_plain_row_is_filed_without_album_tags(world, tmp_path):
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        assert run(world, srv, approve=True).status == "ok"
    assert not [c for c in world["filer"].runner.calls if "--set" in c]
    assert album_events(world["store"]) == []


def test_the_tagged_record_is_committed_before_beets_runs(world, tmp_path, not_in_library):
    """A kill while beets imports (up to 600 s) keeps the record of the write already made: the event is committed
    before the write, so the rollback a kill amounts to cannot lose it."""
    store, req = world["store"], aj.request(world)
    seen = []

    def wrap(runner):
        def killed(cmd, **kw):
            if "import" in cmd:
                seen.append((store.db.in_transaction, album_events(store)))
                raise KeyboardInterrupt
            return runner(cmd, **kw)
        return killed
    with pytest.raises(KeyboardInterrupt):
        fetch_planned_row(world, tmp_path, req, wrap=wrap)
    store.db.rollback()
    fresh = {"album": None, "albumartist": None, "track": None, "tracktotal": None}
    assert seen == [(False, [fresh])]
    assert album_events(store) == [fresh]
