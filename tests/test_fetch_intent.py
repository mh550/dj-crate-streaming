"""fetch tells verify whether a download is a copy upgrade (same recording, better file) or a new version (M7)."""
import copy
import shutil

import pytest

from sourcing.fake_slskd import FakeSlskdServer
from sourcing.verify import verify
from sourcing.slskd_client import SlskdClient
from subsonic.client import SubsonicError
from tests.helpers import convert, make_audio
from tests.test_fetch import GOOD, RESPONSES, good_flac_bytes, new_song, run, world  # noqa: F401  (world: fixture)

TWELVE_FILE = '@@music\\Chic\\Risqué (1979) [FLAC]\\03 - Good Times (12" Version).flac'


def spy_verifier(seen):
    def spy(path, duration, tier=None, reference=None, **kw):
        seen.update(path=path, duration=duration, tier=tier, reference=reference, kw=kw)
        return verify(path, duration)
    return spy


def only_twelve_inch():
    """The fixture's search results, with Good Times renamed to its 12" version (same 501 s)."""
    responses = copy.deepcopy(RESPONSES)
    responses[0]["files"][0]["filename"] = TWELVE_FILE
    return responses, TWELVE_FILE


def events(world, kind):
    return [e for e in world["store"].events(limit=1000) if e["kind"] == kind]


def test_crate_row_is_verified_as_a_copy(world, tmp_path):
    flac, seen = good_flac_bytes(tmp_path), {}
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True, verifier=spy_verifier(seen))
    assert r.status == "ok", r.reason
    assert seen["kw"]["intent"] == "copy"


def test_external_row_getting_the_same_version_has_no_intent(world, tmp_path):
    ext = world["store"].add_external_wanted("Chic", "Good Times", album="Risqué", duration_s=501, year=1979)
    flac, seen = good_flac_bytes(tmp_path), {}
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True, wanted_id=ext, verifier=spy_verifier(seen))
    assert r.status == "ok", r.reason
    assert seen["kw"]["intent"] is None and seen["duration"] == 501 and seen["reference"] is None
    assert not [e for e in events(world, "pick") if "another version" in e["detail"]]


def test_external_row_getting_another_version_is_verified_as_a_new_version(world, tmp_path):
    ext = world["store"].add_external_wanted("Chic", "Good Times", album="Risqué", duration_s=210, year=1979,
                                             tier="crate")
    responses, name = only_twelve_inch()
    flac, seen = good_flac_bytes(tmp_path), {}
    with FakeSlskdServer(responses, world["dl"], files={name: flac}) as srv:
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True, wanted_id=ext, verifier=spy_verifier(seen))
    assert r.status == "ok", r.reason
    assert seen["kw"]["intent"] == "version" and seen["duration"] is None and seen["reference"] is None
    assert any('another version (12" Version) of Good Times' in e["detail"] for e in events(world, "pick"))


def test_verify_records_intent_and_warns_on_a_copy_without_reference(tmp_path):
    p = make_audio(tmp_path / "a.flac", seconds=4)
    v = verify(p, tier="medium", intent="copy")
    assert v.measurements["intent"] == "copy"
    assert any("copy upgrade without a reference" in w for w in v.warnings)
    assert "intent" not in verify(p, tier="medium").measurements
    with pytest.raises(ValueError, match="a new version has no reference copy"):
        verify(p, tier="medium", intent="version", reference=p)


def test_a_new_version_is_not_given_the_candidates_own_length_to_vouch_for(world, tmp_path):
    ext = world["store"].add_external_wanted("Chic", "Good Times", duration_s=210)
    responses, name = only_twelve_inch()
    flac, seen = good_flac_bytes(tmp_path), {}
    with FakeSlskdServer(responses, world["dl"], files={name: flac}) as srv:
        new_song(world["nd"], len(flac))
        run(world, srv, approve=True, wanted_id=ext, verifier=spy_verifier(seen))
    assert seen["kw"]["intent"] == "version" and seen["duration"] is None      # not 501, not 210


def test_a_copy_upgrade_is_ranked_against_the_owned_files_own_title(world, tmp_path):
    """The crate row says "Good Times" but Navidrome's owned file is the 12": a plain candidate is another version
    and is refused, so only the 12" is offered and fetched."""
    world["nd"].state.songs["s4"]["title"] = 'Good Times (12" Version)'
    world["store"].set_wanted_names("s4", "Chic", "Good Times")          # the row's name lacks the label
    plain = copy.deepcopy(RESPONSES)
    twelve = copy.deepcopy(RESPONSES[0])
    twelve["username"] = "otherpeer"
    twelve["files"] = [dict(twelve["files"][0], filename=TWELVE_FILE)]
    flac, seen = good_flac_bytes(tmp_path), {}
    with FakeSlskdServer([twelve] + plain, world["dl"], files={TWELVE_FILE: flac, GOOD: flac}) as srv:
        r = run(world, srv, approve=False)
        assert r.pick is not None and "12" in r.pick.basename
    with FakeSlskdServer(plain, world["dl"], files={GOOD: flac}) as srv:
        r = run(world, srv, approve=False)
    assert r.status == "needs_source" and "no acceptable candidate" in r.reason     # only the plain version is offered


# ---- replaceable: M8 deletes the old copy only after a verified copy upgrade ----

needs_tools = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("fpcalc")), reason="ffmpeg/fpcalc not on PATH")


@pytest.fixture(scope="module")
def audio(tmp_path_factory):
    d = tmp_path_factory.mktemp("intent")
    return {"true": make_audio(d / "true.flac", seconds=20), "mp3": convert(d / "true.flac", d / "t.mp3", "-b:a", "128k"),
            "other": make_audio(d / "other.flac", seconds=20, seed=9, color="brown")}


@needs_tools
def test_copy_upgrade_without_a_reference_is_ok_but_not_replaceable(audio):
    v = verify(audio["true"], 20, tier="low", intent="copy")
    assert v.ok and v.measurements["reference_compared"] is False and v.measurements["replaceable"] is False
    assert any("copy upgrade without a reference" in w for w in v.warnings)


@needs_tools
def test_copy_upgrade_matching_its_reference_is_replaceable(audio):
    v = verify(audio["mp3"], 20, tier="low", reference=audio["true"], intent="copy")
    assert v.ok and v.measurements["reference_compared"] is True and v.measurements["replaceable"] is True


@needs_tools
def test_truncated_prefix_of_the_reference_matches_but_is_not_replaceable(audio, tmp_path):
    short = convert(audio["true"], tmp_path / "short.flac", "-t", "10")       # the first half: ber over the overlap is 0
    v = verify(short, 10, tier="low", reference=audio["true"], intent="copy")
    assert v.measurements["fingerprint_ber"] <= 0.2 and v.measurements["replaceable"] is False


@needs_tools
def test_a_failing_download_with_a_matching_fingerprint_is_not_replaceable(audio):
    v = verify(audio["mp3"], 99, tier="low", reference=audio["true"], intent="copy")      # wrong expected length
    assert not v.ok and v.measurements["fingerprint_ber"] <= 0.2 and v.measurements["replaceable"] is False


@needs_tools
def test_a_file_is_not_a_replacement_for_itself(audio):
    v = verify(audio["true"], 20, tier="low", reference=audio["true"], intent="copy")
    assert v.ok and v.measurements["reference_compared"] is True and v.measurements["replaceable"] is False


@needs_tools
def test_copy_upgrade_of_a_different_version_fails_hard_and_is_not_replaceable(audio):
    v = verify(audio["other"], 20, tier="low", reference=audio["true"], intent="copy")
    assert not v.ok and "different recording" in v.problems[0] and v.measurements["replaceable"] is False


@needs_tools
def test_copy_upgrade_fingerprints_the_full_length_of_both_files(audio, monkeypatch):
    import sourcing.verify as V
    lengths = []
    real = V.fingerprint
    monkeypatch.setattr(V, "fingerprint", lambda p, length=120: lengths.append(length) or real(p, length))
    verify(audio["mp3"], 20, tier="low", reference=audio["true"], intent="copy")
    verify(audio["mp3"], 20, tier="low", reference=audio["true"])
    assert lengths[:2] == [21, 21] and lengths[2:] == [120, 120]        # the longer file's seconds, else the default


@needs_tools
def test_not_replaceable_when_the_reference_cannot_be_fingerprinted(audio, tmp_path, monkeypatch):
    import sourcing.verify as V
    monkeypatch.setattr(V, "fingerprint", lambda p, length=120: None)
    v = verify(audio["mp3"], 20, tier="low", reference=audio["true"], intent="copy")
    assert v.ok and v.measurements["replaceable"] is False and v.measurements["reference_compared"] is False


# ---- a new version is checked against the peer's listing of that same file ----

@needs_tools
def test_new_version_whose_arrived_length_differs_from_the_listing_fails(audio):
    assert verify(audio["true"], tier="low", intent="version", listed_length_s=20).ok
    assert verify(audio["true"], tier="low", intent="version", listed_length_s=21).ok         # within 10 s
    v = verify(audio["true"], tier="low", intent="version", listed_length_s=60)
    assert not v.ok and "arrived length differs from the peer's listing" in v.problems[0]
    assert verify(audio["true"], tier="low", intent="version").ok                              # no listing: skipped
    assert verify(audio["true"], tier="low", listed_length_s=60).ok                             # only for a new version


def test_fetch_gives_a_new_version_the_listed_length_to_check_against(world, tmp_path):
    ext = world["store"].add_external_wanted("Chic", "Good Times", duration_s=210)
    responses, name = only_twelve_inch()
    flac, seen = good_flac_bytes(tmp_path), {}
    with FakeSlskdServer(responses, world["dl"], files={name: flac}) as srv:
        new_song(world["nd"], len(flac))
        run(world, srv, approve=True, wanted_id=ext, verifier=spy_verifier(seen))
    assert seen["kw"]["listed_length_s"] == 501


# ---- fetch: search cleanup and Navidrome failures ----

def test_owned_title_falls_back_to_the_row_when_navidrome_errors(world, monkeypatch):
    for exc in (SubsonicError(70, "no"), OSError("down"), ValueError("bad json")):
        def boom(song_id, exc=exc):
            raise exc
        monkeypatch.setattr(world["client"], "song", boom)
        with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
            r = run(world, srv, approve=False)
        assert r.status == "needs_source" and r.pick is not None, exc


def test_the_search_is_deleted_even_when_ranking_raises(world, monkeypatch):
    import sourcing.fetch as F
    deleted = []
    monkeypatch.setattr(SlskdClient, "delete_search", lambda self, sid: deleted.append(sid))
    monkeypatch.setattr(F, "rank", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("scorer bug")))
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        with pytest.raises(RuntimeError):
            run(world, srv, approve=False)
    assert len(deleted) == 1
