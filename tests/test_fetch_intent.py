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


# ---- M7 final fixes I1: replaceable needs the decoded length, measured ----

def _truncated(audio, tmp_path):
    """80% of a FLAC's bytes: STREAMINFO still says 20 s, only ~16 s decodes, and the prefix fingerprints clean."""
    good = convert(audio["true"], tmp_path / "new.flac", "-compression_level", "8")
    data = good.read_bytes()
    t = tmp_path / "trunc.flac"
    t.write_bytes(data[: len(data) * 8 // 10])
    return t


@needs_tools
def test_truncated_copy_is_not_replaceable_when_the_decode_timed_out(audio, tmp_path, monkeypatch):
    import subprocess
    import sourcing.verify as V

    def timeout(*a, **k):
        raise subprocess.TimeoutExpired("ffmpeg", 600)
    monkeypatch.setattr(V, "analyse", timeout)
    v = verify(_truncated(audio, tmp_path), 20, tier="crate", reference=audio["true"], intent="copy")
    assert v.measurements["fingerprint_ber"] <= 0.2 and v.measurements["replaceable"] is False
    assert any("not replaceable" in w and "decoded length" in w for w in v.warnings)


@needs_tools
def test_truncated_copy_is_not_replaceable_without_ffmpeg(audio, tmp_path, monkeypatch):
    import sourcing.verify as V
    real = shutil.which
    trunc = _truncated(audio, tmp_path)
    monkeypatch.setattr(V.shutil, "which", lambda n: None if n == "ffmpeg" else real(n))
    v = verify(trunc, 20, tier="crate", reference=audio["true"], intent="copy")
    assert v.measurements["replaceable"] is False
    assert any("not replaceable" in w and "decoded length" in w for w in v.warnings)


@needs_tools
def test_replaceable_compares_the_decoded_length_not_the_header(audio, monkeypatch):
    """A VBR MP3 without a Xing header: its header length is an estimate (not exact), so no `truncated` finding
    fires; only the decoded length shows that half the audio is missing."""
    import dataclasses
    import sourcing.verify as V
    real_probe, real_analyse = V.probe, V.analyse

    def estimate(path):
        info = real_probe(path)
        return dataclasses.replace(info, duration_exact=False) if path == audio["mp3"] else info

    def half(path, sr, d=None):
        a = real_analyse(path, sr, d)
        if path == audio["mp3"]:
            a["samples"] = int(a["samples"] * 0.5)          # the header says 20 s; the decode finds 10 s
        return a
    monkeypatch.setattr(V, "probe", estimate)
    monkeypatch.setattr(V, "analyse", half)
    v = verify(audio["mp3"], tier="low", reference=audio["true"], intent="copy")
    assert v.measurements["decoded_s"] < 15 and v.measurements["replaceable"] is False


# ---- M7 final fixes m7: the record names the exact reference file that was compared (M8 trashes only that) ----

@needs_tools
def test_copy_verification_records_the_compared_reference(audio):
    import json
    st = audio["true"].stat()
    v = verify(audio["mp3"], 20, tier="low", reference=audio["true"], intent="copy")
    assert v.measurements["replaceable"] is True
    assert v.measurements["reference"] == {"path": str(audio["true"]), "size": st.st_size, "mtime_ns": st.st_mtime_ns}
    assert json.loads(json.dumps(v.as_dict("low")))["measurements"]["reference"]["mtime_ns"] == st.st_mtime_ns


# ---- M7 final fixes m2: fetch reads the file name as the scorer does (track number, then file junk) ----

def test_external_row_getting_its_own_label_behind_file_junk_keeps_its_length(world, tmp_path):
    ext = world["store"].add_external_wanted("Chic", "Good Times (Extended Mix)", album="Risqué", duration_s=501,
                                             year=1979)
    responses = copy.deepcopy(RESPONSES)
    name = '@@music\\Chic\\Risqué (1979) [FLAC]\\03 - Good Times (Extended Mix) [FLAC].flac'
    responses[0]["files"][0]["filename"] = name
    flac, seen = good_flac_bytes(tmp_path), {}
    with FakeSlskdServer(responses, world["dl"], files={name: flac}) as srv:
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True, wanted_id=ext, verifier=spy_verifier(seen))
    assert r.pick is not None and "Extended Mix" in r.pick.basename
    assert seen["kw"]["intent"] is None and seen["duration"] == 501


# ---- M7 fix round 2, ruling 4: a version the tier does not accept is never downloaded ----

def test_an_instrumental_row_offered_only_a_vocal_12_inch_downloads_nothing(world, tmp_path):
    ext = world["store"].add_external_wanted("Chic", "Good Times - Instrumental", album="Risqué", duration_s=210,
                                             year=1979, tier="crate")
    name = '@@music\\Chic\\Risqué (1979) [FLAC]\\Chic - Good Times (12" Version).flac'
    peer = copy.deepcopy(RESPONSES[0])
    peer["files"] = [dict(peer["files"][0], filename=name)]                    # the only file offered
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer([peer], world["dl"], files={name: flac}) as srv:
        prefer = {"username": peer["username"], "filename": name}               # even when it was approved earlier
        r = run(world, srv, approve=True, wanted_id=ext, prefer=prefer)
        assert r.status == "needs_source" and "no acceptable candidate" in r.reason
        assert srv.enqueued == []
    assert "not accepted at crate" in r.explain


@needs_tools
def test_the_recorded_reference_path_is_resolved(audio, tmp_path):
    link = tmp_path / "link"
    link.symlink_to(audio["true"].parent)
    v = verify(audio["mp3"], 20, tier="low", reference=link / audio["true"].name, intent="copy")
    assert v.measurements["reference"]["path"] == str(audio["true"].resolve())
