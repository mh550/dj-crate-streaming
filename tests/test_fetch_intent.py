"""fetch tells verify whether a download is a copy upgrade (same recording, better file) or a new version (M7)."""
import copy

import pytest

from sourcing.fake_slskd import FakeSlskdServer
from sourcing.verify import verify
from tests.helpers import make_audio
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
