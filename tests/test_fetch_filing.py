"""fetch files a verified download through beets (D18, D22) and copies Navidrome's names back onto the row."""
from pathlib import Path

import pytest

from sourcing.fake_slskd import FakeSlskdServer
from sourcing.filer import BeetsFiler, FilingError
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
