"""fetch files a verified download through beets (D18, D22) and copies Navidrome's names back onto the row."""
import sqlite3
from pathlib import Path

import pytest

from sourcing.fake_slskd import FakeSlskdServer
from sourcing.filer import BeetsFiler, FilingError
from sourcing.verify import verify
from tests.test_export_playlists import SCHEMA
from tests.helpers import beets_items_db, fake_beet, make_flac
from tests.test_fetch import GOOD, RESPONSES, good_flac_bytes, new_song, run, world  # noqa: F401  (world: fixture)

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
    assert len(filer.runner.calls) == 1


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
    assert not world["music"].exists()


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
    def spy(path, duration, tier=None, reference=None, **kw):
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
    assert kw["lookup"] is f and kw["recording_id"] is None


def test_navidromes_musicbrainz_recording_id_reaches_verify(world, tmp_path):
    world["nd"].state.songs["s4"]["musicBrainzId"] = "rec-9"
    assert fetched(world, tmp_path, lookup=lambda p: [])["kw"]["recording_id"] == "rec-9"


def test_external_row_has_no_reference_and_no_recording_id(world, tmp_path):
    ext = world["store"].add_external_wanted("Chic", "Good Times", album="Risqué", duration_s=501, year=1979)
    f = lambda p: []
    seen = fetched(world, tmp_path, wanted_id=ext, lookup=f, navidrome_db=tmp_path / "nope.db")
    assert seen["reference"] is None and seen["kw"] == {"recording_id": None, "lookup": f}
    assert kinds(world, "reference") == []


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
        assert [e["kind"] for e in other.events(limit=1)] == ["reference"]   # committed, so visible here
        other.log(None, "s4", "approved", "while the download is verified"); other.commit()
        wrote.append(1)
        return verify(path, duration)

    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        r = run(dict(world, store=store, rec=rec), srv, approve=True, verifier=verifier, navidrome_db=tmp_path / "nope.db")
    assert r.status == "ok", r.reason
    assert wrote == [1]
