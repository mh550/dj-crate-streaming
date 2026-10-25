"""M8 Task 9: a new version never replaces anything (D23). When a tier prefers it (D16: crates prefer 12"/extended), the
system asks: one proposal per playlist slot, "replace X with Y in P at slot n?". So does a better copy that is not
proven the same recording (kind unproven_copy). Accepting edits that one slot through crates.playlist_edit and never
trashes; declining is remembered, so the same question is not asked again."""
import json
import re
import threading
import urllib.error
import urllib.request

import pytest

from crates import proposals as P
from crates.reconcile import Reconciler
from crates.service import Config, CrateApp, CrateServer
from crates.store import CrateStore
from sourcing.fake_slskd import FakeSlskdServer
from sourcing.identity import parse_filename
from sourcing.policy import TIERS
from sourcing.scorer import Candidate, Wanted, score_candidate, version_rank
from sourcing.verify import verify
from subsonic.client import SubsonicClient
from subsonic.fake_server import FakeSubsonicServer
from tests.test_fetch import GOOD, RESPONSES, good_flac_bytes, new_song, run, world, not_in_library  # noqa: F401  (fixtures)
from tests.test_worker import worker

RADIO = {"id": "r1", "title": "My Love Is Free", "artist": "Double Exposure", "album": "Ten Percent", "year": 1976,
         "duration": 459, "bitRate": 320, "suffix": "mp3", "contentType": "audio/mpeg", "size": 18_000_000,
         "samplingRate": 44100, "path": "Double Exposure/Ten Percent/04 - My Love Is Free.mp3"}
TWELVE = {"id": "t12", "title": "My Love Is Free (Tom Moulton 12” Mix)", "artist": "Double Exposure",
          "album": "Salsoul 12s", "year": 1976, "duration": 580, "bitRate": 900, "suffix": "flac",
          "contentType": "audio/flac", "size": 65_000_000, "samplingRate": 44100, "bitDepth": 16,
          "path": "Double Exposure/Salsoul 12s/01 - My Love Is Free (Tom Moulton 12” Mix).flac"}


def song(sid, title, duration, artist="Double Exposure", **kw):
    return dict(TWELVE, id=sid, title=title, duration=duration, artist=artist, path=f"x/{sid}.flac", **kw)


class W:
    """The fake Navidrome (with its navidrome.db mirror), a client, a store and a reconciler over them."""

    def __init__(self, nd):
        self.nd, self.db = nd, nd.state.db_path
        self.client = SubsonicClient(nd.url, "demo", "demo")
        self.store = CrateStore()
        self.rec = Reconciler(self.client, self.store)

    def playlist(self, pid, name, comment, songs):
        self.nd.state.playlists[pid] = {"id": pid, "name": name, "comment": comment, "owner": "demo", "public": False,
                                        "songs": list(songs)}
        self.nd.state.sync()

    def add(self, *songs):
        for s in songs:
            self.nd.state.songs[s["id"]] = dict(s)
        self.nd.state.sync()

    def reconcile(self):
        self.rec.run()
        return self

    def ids(self, pid):
        return [e.id for e in self.client.playlist(pid).entries]

    def edits(self):
        return sum(m == "updatePlaylist" for m, _ in self.nd.state.requests)


@pytest.fixture
def w(tmp_path):
    with FakeSubsonicServer(db_path=tmp_path / "navidrome.db") as nd:
        w = W(nd)
        w.add(RADIO, TWELVE)
        w.playlist("pl-c", "secondset", "#crate", ["s1", "r1", "s2"])
        yield w


# --- creation: what Michael is asked ----------------------------------------------------------------------------

def test_a_preferred_12in_arriving_proposes_a_swap_for_the_crate_slot(w):
    w.reconcile()
    before = w.edits()
    ids = P.version_swaps(w.store, w.db, "t12")
    assert len(ids) == 1
    p = w.store.proposal(ids[0])
    assert (p["kind"], p["playlist_id"], p["position"], p["old_song_id"], p["new_song_id"]) == \
        ("version_swap", "pl-c", 1, "r1", "t12")
    assert p["summary"] == "secondset #2: Double Exposure – My Love Is Free (459 s) → (Tom Moulton 12” Mix) (580 s)"
    assert p["decision"] is None and p["decided_by"] is None
    assert w.edits() == before and w.ids("pl-c") == ["s1", "r1", "s2"]          # asking changes nothing
    assert [e for e in w.store.events(limit=100) if e["kind"] == "proposal"]


def test_no_proposal_when_the_tier_prefers_nothing(w):
    w.playlist("pl-c", "secondset", "#tier:medium", ["s1", "r1", "s2"])
    w.reconcile()
    assert P.version_swaps(w.store, w.db, "t12") == [] and w.store.proposals() == []


def test_no_proposal_in_an_untiered_playlist(w):
    w.playlist("pl-c", "secondset", "", ["s1", "r1", "s2"])
    w.reconcile()
    assert P.version_swaps(w.store, w.db, "t12") == []


@pytest.mark.parametrize("held, new", [
    (TWELVE, song("x1", TWELVE["title"], 582)),                                    # the same version, ±4 s
    (RADIO, song("x2", "My Love Is Free (Extended Mix)", 600, artist="Inner Life")),   # another song
    (TWELVE, song("x3", "My Love Is Free (Extended Mix)", 610)),                   # no better than what is there
])
def test_no_proposal_for_the_same_version_or_another_song(w, held, new):
    w.add(new)
    w.playlist("pl-c", "secondset", "#crate", [held["id"]])
    w.reconcile()
    assert P.version_swaps(w.store, w.db, new["id"]) == []


@pytest.mark.parametrize("held, new, asked", [
    (song("e1", "My Love Is Free (Extended Mix)", 610), song("e2", "My Love Is Free (12'' Version)", 590), False),
    (song("e1", "My Love Is Free (Extended Mix)", 610), song("c2", "My Love Is Free (Extended Club Mix)", 640), False),
    (song("o1", "My Love Is Free (Original Mix)", 600), song("e2", "My Love Is Free (12'' Version)", 590), True),
    (song("c1", "My Love Is Free (Club Mix)", 610), song("e2", "My Love Is Free (12'' Version)", 590), False),
])
def test_only_a_version_the_tier_ranks_higher_is_proposed(w, held, new, asked):
    """crate prefers extended, club, original: an equal or lower rank is no upgrade worth a question, and a club mix
    is a club mix (a 12" without "club" drops it, as identity.stands_in would not let it stand in either)."""
    w.add(held, new)
    w.playlist("pl-c", "secondset", "#crate", [held["id"]])
    w.reconcile()
    assert bool(P.version_swaps(w.store, w.db, new["id"])) is asked


def test_an_original_mix_of_the_same_length_is_the_same_version(w):
    """'Original Mix' names the plain version (a neutral kind the crate still prefers): no question within ±4 s."""
    w.add(song("om", "My Love Is Free (Original Mix)", 461))
    w.reconcile()
    assert P.version_swaps(w.store, w.db, "om") == []


def test_a_dub_is_not_preferred_as_a_12in(w):
    w.add(song("d12", 'My Love Is Free (12" Dub)', 600))
    w.reconcile()
    assert P.version_swaps(w.store, w.db, "d12") == []


@pytest.mark.parametrize("title", ["My Love Is Free (Instrumental)", "My Love Is Free (Larry Levan Mix)"])
def test_no_proposal_that_drops_what_the_slot_is(w, title):
    """An instrumental is a DJ tool and a credited mix is that mix: a vocal or generic 12" is not an upgrade of it."""
    w.add(song("o1", title, 450))
    w.playlist("pl-c", "secondset", "#crate", ["o1"])
    w.reconcile()
    assert P.version_swaps(w.store, w.db, "t12") == []


def test_no_proposal_when_the_playlist_holds_the_new_version_already(w):
    w.playlist("pl-c", "secondset", "#crate", ["s1", "r1", "t12"])
    w.reconcile()
    assert P.version_swaps(w.store, w.db, "t12") == []


def test_one_proposal_per_slot(w):
    w.playlist("pl-c", "secondset", "#crate", ["s1", "r1", "s2", "s3", "r1"])
    w.playlist("pl-d", "warmup", "#crate", ["r1"])
    w.reconcile()
    ids = P.version_swaps(w.store, w.db, "t12")
    assert sorted((w.store.proposal(i)["playlist_id"], w.store.proposal(i)["position"]) for i in ids) == \
        [("pl-c", 1), ("pl-c", 4), ("pl-d", 0)]


def test_a_hidden_row_does_not_shift_the_proposed_index(w):
    w.playlist("pl-c", "secondset", "#crate", ["s1", "s2", "r1"])
    w.nd.state.missing.add("s1"); w.nd.state.sync()
    w.reconcile()
    [i] = P.version_swaps(w.store, w.db, "t12")
    assert w.store.proposal(i)["position"] == 1                       # the index getPlaylist shows


def test_asking_twice_makes_one_proposal(w):
    w.reconcile()
    assert len(P.version_swaps(w.store, w.db, "t12")) == 1
    assert P.version_swaps(w.store, w.db, "t12") == []
    assert len(w.store.proposals()) == 1


def test_decline_is_remembered_and_not_proposed_again(w):
    w.reconcile()
    [i] = P.version_swaps(w.store, w.db, "t12")
    P.decline(w.store, i, "michael")
    p = w.store.proposal(i)
    assert p["decision"] == "declined" and p["decided_by"] == "michael" and p["decided_at"]
    assert w.store.proposals() == [] and [x["id"] for x in w.store.proposals(open_only=False)] == [i]
    assert P.version_swaps(w.store, w.db, "t12") == []
    w.playlist("pl-c", "secondset", "#crate", ["r1", "s1", "s2"])        # the song moved: still declined
    assert P.version_swaps(w.store, w.db, "t12") == []
    assert w.ids("pl-c") == ["r1", "s1", "s2"]


def test_a_decided_proposal_cannot_be_answered_again(w):
    w.reconcile()
    [i] = P.version_swaps(w.store, w.db, "t12")
    P.decline(w.store, i, "michael")
    with pytest.raises(P.Decided):
        P.apply(w.store, w.client, w.db, i, "michael", w.rec)
    with pytest.raises(P.Decided):
        P.decline(w.store, i, "michael")
    with pytest.raises(KeyError):
        P.apply(w.store, w.client, w.db, 999, "michael", w.rec)


def test_decided_by_uses_the_approver_vocabulary(w):
    w.reconcile()
    [i] = P.version_swaps(w.store, w.db, "t12")
    with pytest.raises(ValueError):
        P.decline(w.store, i, "bob")
    assert w.store.proposal(i)["decision"] is None
    P.decline(w.store, i, "policy:repoint-auto")
    assert w.store.proposal(i)["decided_by"] == "policy:repoint-auto"


# --- accepting: one guarded slot edit, nothing trashed -----------------------------------------------------------

def test_accept_repoints_only_that_slot(w):
    w.playlist("pl-c", "secondset", "#crate", ["s1", "r1", "s2", "s3", "r1"])
    w.nd.state.playlists["pl-1"]["songs"].append("r1"); w.nd.state.sync()        # an untiered playlist holds it too
    w.reconcile()
    ids = P.version_swaps(w.store, w.db, "t12")
    first = next(i for i in ids if w.store.proposal(i)["position"] == 1)
    result = P.apply(w.store, w.client, w.db, first, "michael", w.rec)
    assert w.ids("pl-c") == ["s1", "t12", "s2", "s3", "r1"]
    assert w.ids("pl-1") == ["s1", "s2", "s3", "r1"]
    p = w.store.proposal(first)
    assert p["decision"] == "accepted" and p["decided_by"] == "michael" and p["result"] == result
    assert [w.store.proposal(i)["decision"] for i in ids if i != first] == [None]    # slot 4 is still asked
    st = w.store.track_status_map("pl-c")                                  # the playlist was re-judged
    assert "t12" in st and st["t12"]["status"] != "removed"


def test_accept_of_a_stale_slot_changes_nothing(w):
    w.reconcile()
    [i] = P.version_swaps(w.store, w.db, "t12")
    w.client.update_playlist("pl-c", remove_indexes=[1])                   # Michael removed the radio edit meanwhile
    before = w.edits()
    result = P.apply(w.store, w.client, w.db, i, "michael", w.rec)
    assert w.edits() == before and w.ids("pl-c") == ["s1", "s2"]
    p = w.store.proposal(i)
    assert p["decision"] == "stale" and p["result"] == result and RADIO_NAME in result


def test_accept_follows_a_slot_that_moved(w):
    w.reconcile()
    [i] = P.version_swaps(w.store, w.db, "t12")
    w.playlist("pl-c", "secondset", "#crate", ["s3", "s1", "r1", "s2"])    # reordered: r1 is at index 2 now
    P.apply(w.store, w.client, w.db, i, "michael", w.rec)
    assert w.ids("pl-c") == ["s3", "s1", "t12", "s2"] and w.store.proposal(i)["decision"] == "accepted"


def test_accept_with_several_candidate_slots_is_stale(w):
    w.reconcile()
    [i] = P.version_swaps(w.store, w.db, "t12")
    w.playlist("pl-c", "secondset", "#crate", ["r1", "s3", "s1", "r1"])    # index 1 moved and r1 is there twice
    before = w.edits()
    P.apply(w.store, w.client, w.db, i, "michael", w.rec)
    assert w.edits() == before and w.store.proposal(i)["decision"] == "stale"


def test_accept_on_a_playlist_with_a_hidden_row_is_refused_as_stale(w):
    w.reconcile()
    [i] = P.version_swaps(w.store, w.db, "t12")
    w.nd.state.missing.add("s2"); w.nd.state.sync()                       # getPlaylist and navidrome.db disagree
    before = w.edits()
    result = P.apply(w.store, w.client, w.db, i, "michael", w.rec)
    assert w.edits() == before and w.store.proposal(i)["decision"] == "stale" and "secondset" in result


def test_accepting_supersedes_the_other_questions_about_that_slot(w):
    w.add(song("x3", "My Love Is Free (Extended Mix)", 610))
    w.reconcile()
    [a] = P.version_swaps(w.store, w.db, "t12")
    [b] = P.version_swaps(w.store, w.db, "x3")
    P.apply(w.store, w.client, w.db, a, "michael", w.rec)
    pb = w.store.proposal(b)
    assert pb["decision"] == "stale" and f"#{a}" in pb["result"] and w.store.proposals() == []
    assert w.ids("pl-c") == ["s1", "t12", "s2"]


def test_accept_never_takes_a_slot_that_has_its_own_question(w):
    w.playlist("pl-c", "secondset", "#crate", ["s1", "r1", "s2", "s3", "r1"])
    w.reconcile()
    ids = P.version_swaps(w.store, w.db, "t12")
    first = next(i for i in ids if w.store.proposal(i)["position"] == 1)
    other = next(i for i in ids if i != first)
    w.client.update_playlist("pl-c", remove_indexes=[1])                   # the asked slot is gone; r1 left at 4
    before = w.edits()
    result = P.apply(w.store, w.client, w.db, first, "michael", w.rec)
    assert w.edits() == before and w.ids("pl-c") == ["s1", "s2", "s3", "r1"]
    assert w.store.proposal(first)["decision"] == "stale" and "slot changed" in result
    assert w.store.proposal(other)["decision"] is None
    P.apply(w.store, w.client, w.db, other, "michael", w.rec)               # its own question still works
    assert w.ids("pl-c") == ["s1", "s2", "s3", "t12"]


RADIO_NAME = "Double Exposure – My Love Is Free"
TWELVE_NAME = "Double Exposure – My Love Is Free (Tom Moulton 12” Mix)"


def no_ids(text, *ids):
    return not any(re.search(rf"\b{re.escape(i)}\b", text) for i in ids)


def test_results_name_songs_and_1_based_slots_never_ids(w):
    w.reconcile()
    [i] = P.version_swaps(w.store, w.db, "t12")
    p = w.store.proposal(i)
    assert (p["old_name"], p["new_name"]) == (RADIO_NAME, TWELVE_NAME)
    result = P.apply(w.store, w.client, w.db, i, "michael", w.rec)
    assert "slot 2" in result and RADIO_NAME in result and TWELVE_NAME in result
    assert no_ids(result, "t12", "r1", "pl-c")


@pytest.mark.parametrize("change", ["removed", "hidden", "new gone"])
def test_refusals_name_songs_not_ids(w, change):
    w.reconcile()
    [i] = P.version_swaps(w.store, w.db, "t12")
    if change == "removed":
        w.client.update_playlist("pl-c", remove_indexes=[1])
    else:
        w.nd.state.missing.add("s2" if change == "hidden" else "t12"); w.nd.state.sync()
    result = P.apply(w.store, w.client, w.db, i, "michael", w.rec)
    assert w.store.proposal(i)["decision"] == "stale"
    assert no_ids(result, "t12", "r1", "s2", "pl-c"), result
    if change == "removed":
        assert f"slot 2 no longer holds {RADIO_NAME}" in result
    if change == "hidden":
        assert "Donna Summer – I Feel Love" in result


# --- version_rank is the scorer's D16 bonus ---------------------------------------------------------------------

NAMES = ["Good Times.flac", "Good Times (12'' Version).flac", "Good Times (Club Mix).flac",
         "Good Times (Original Mix).flac", 'Good Times (12" Dub).flac', "Good Times (Radio Edit).flac",
         "Good Times (Extended Club Mix).flac", "Good Times (Instrumental).flac"]


@pytest.mark.parametrize("tier", list(TIERS))
@pytest.mark.parametrize("name", NAMES)
def test_version_rank_matches_the_scorer_bonus(tier, name):
    policy = TIERS[tier]
    c = Candidate("p", f"Music\\Chic\\{name}", 50_000_000, "flac", 900, 44100, 16, 501, False, True, 0, 3_000_000)
    score_candidate(c, Wanted("Chic", name.rsplit(".", 1)[0], duration_s=501), policy)   # asked for that very version
    bonus = [r for r in c.reasons if r.startswith("prefers ")]
    rank = version_rank(parse_filename(name, "Chic"), policy)
    assert c.rejected is None
    assert bonus == ([] if rank is None else [f"prefers {policy.prefer_versions[rank]} +{max(2, 6 - 2 * rank)}"])


def test_version_rank_examples():
    crate = TIERS["crate"]
    assert version_rank(parse_filename("My Love Is Free (Tom Moulton 12” Mix).flac"), crate) == 0
    assert version_rank(parse_filename('My Love Is Free (12" Dub).flac'), crate) is None
    assert version_rank(parse_filename("My Love Is Free.flac"), crate) is None
    assert version_rank(parse_filename("My Love Is Free (12'' Mix).flac"), TIERS["medium"]) is None


# --- the fetch hooks (fake slskd, fake Navidrome, fake beets) ---------------------------------------------------

def file_external_as_version(world, tmp_path, **kw):
    """An external row asks for Chic — Good Times; Navidrome indexes the filed file as s9 'Good Times (Extended
    Version)', another version of s4, which the crate pl-2 holds at index 1."""
    ext = world["store"].add_external_wanted("Chic", "Good Times", album="Risqué", duration_s=501, year=1979)
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        world["nd"].state.songs["s9"].update(title="Good Times (Extended Version)", duration=600)
        return ext, run(world, srv, approve=True, wanted_id=ext, **kw)


@pytest.mark.usefixtures("not_in_library")
def test_filing_an_external_row_proposes_the_swaps_its_song_earns(world, tmp_path):
    ext, r = file_external_as_version(world, tmp_path)
    assert r.status == "ok" and world["store"].external(ext)["status"] == "ok"
    [p] = world["store"].proposals()
    assert (p["kind"], p["playlist_id"], p["position"], p["old_song_id"], p["new_song_id"]) == \
        ("version_swap", "pl-2", 1, "s4", "s9")
    assert [e.id for e in world["client"].playlist("pl-2").entries] == ["s3", "s4", "s5"]    # nothing swapped


@pytest.mark.usefixtures("not_in_library")
def test_a_failing_hook_never_fails_the_fetch(world, tmp_path, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("navidrome.db locked")
    monkeypatch.setattr(P, "version_swaps", boom)
    ext, r = file_external_as_version(world, tmp_path)
    assert r.status == "ok" and world["store"].external(ext)["status"] == "ok"
    assert any(e["kind"] == "proposal" and "navidrome.db locked" in (e["detail"] or "")
               for e in world["store"].events(limit=1000))


@pytest.mark.usefixtures("not_in_library")
def test_proposals_are_never_approvals(world, tmp_path):
    file_external_as_version(world, tmp_path)
    store = world["store"]
    used = len(store.db.execute("SELECT * FROM approvals").fetchall())
    [p] = store.proposals()
    P.apply(store, world["client"], world["nd"].state.db_path, p["id"], "michael", world["rec"])
    assert [e.id for e in world["client"].playlist("pl-2").entries] == ["s3", "s9", "s5"]
    assert store.pending_approvals() == [] and len(store.db.execute("SELECT * FROM approvals").fetchall()) == used
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        report = worker(world, srv).tick()
    assert report.approvals == 0 and srv.enqueued == []


OLD_REL = "Mr. Fingers/Washing Machine/02 - Can You Feel It.mp3"     # s4's file (test_replace's stand-in)
NEW_REL = "Chic/Risqué (1979)/03 - Good Times.flac"


def keep_both(world, tmp_path):
    """s9, a better copy of s4 that verify could not prove is the same recording: fetch keeps both."""
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True, verifier=lambda path, duration, **kw: verify(path, duration))
    assert "kept both" in r.reason, r.reason
    return r


def test_unproven_copy_becomes_a_proposal_per_slot_and_accepting_never_trashes(world, tmp_path):
    client, store, db = world["client"], world["store"], world["nd"].state.db_path
    client.update_playlist("pl-3", add_song_ids=["s4"])                  # pl-3: s2 s4, made a #tier:medium playlist
    client.update_playlist("pl-1", add_song_ids=["s4"])                  # untiered: no question about it
    world["rec"].set_tier("pl-3", "medium")
    keep_both(world, tmp_path)
    ps = store.proposals()
    assert sorted((p["kind"], p["playlist_id"], p["position"], p["old_song_id"], p["new_song_id"], p["wanted_id"])
                  for p in ps) == [("unproven_copy", "pl-2", 1, "s4", "s9", "s4"),
                                   ("unproven_copy", "pl-3", 1, "s4", "s9", "s4")]
    assert all(NEW_REL in p["summary"] and "not proven" in p["summary"] for p in ps)
    for p in ps:
        P.apply(store, client, db, p["id"], "michael", world["rec"])
    assert [e.id for e in client.playlist("pl-2").entries] == ["s3", "s9", "s5"]
    assert [e.id for e in client.playlist("pl-3").entries] == ["s2", "s9"]
    assert "s4" in [e.id for e in client.playlist("pl-1").entries]
    assert (world["music"] / OLD_REL).read_bytes() == b"old copy of s4"           # never trashed
    assert store.db.execute("SELECT COUNT(*) FROM replacements").fetchone()[0] == 0
    assert store.find_wanted("s4") is None                                         # its rows left with the slots
    assert store.track_status_map("pl-2")["s9"]["status"] == "ok"
    assert store.track_status_map("pl-3")["s9"]["status"] == "ok"


def test_all_slots_accepted_never_fails_the_row_even_before_a_reconcile(world, tmp_path):
    class Busy:
        def reconcile_playlist(self, pl):
            raise RuntimeError("reconcile busy")
    keep_both(world, tmp_path)
    [p] = world["store"].proposals()
    P.apply(world["store"], world["client"], world["nd"].state.db_path, p["id"], "michael", Busy())
    assert world["store"].proposal(p["id"])["decision"] == "accepted"
    assert world["store"].track_status_map("pl-2")["s4"]["status"] == "review"    # left for the next reconcile
    assert any("reconcile busy" in (e["detail"] or "") for e in world["store"].events(limit=1000))


def test_decline_of_the_last_unproven_copy_leaves_the_row_in_review_naming_the_new_copy(world, tmp_path):
    """Not `failed`: reconcile would re-queue a failed row for a download nobody asked for (review ruling)."""
    client, store = world["client"], world["store"]
    client.update_playlist("pl-3", add_song_ids=["s4"])
    world["rec"].set_tier("pl-3", "medium")
    keep_both(world, tmp_path)
    a, b = (p["id"] for p in store.proposals())
    P.decline(store, a, "michael")
    assert store.track_status_map("pl-2")["s4"]["reason"].startswith("kept beside")     # one question still open
    P.decline(store, b, "michael")
    world["rec"].run()
    for pl in ("pl-2", "pl-3"):
        row = store.track_status_map(pl)["s4"]
        assert row["status"] == "review"
        assert row["reason"] == (f"declined replacement #{b}; approve a different candidate to retry "
                                 f"(the new copy stays in the library as {NEW_REL})")
    assert (world["music"] / OLD_REL).exists() and (world["music"] / NEW_REL).exists()
    assert [e.id for e in client.playlist("pl-2").entries] == ["s3", "s4", "s5"]


def test_a_stale_unproven_copy_leaves_the_row_in_review_with_the_reason(world, tmp_path):
    keep_both(world, tmp_path)
    store = world["store"]
    [p] = store.proposals()
    world["client"].update_playlist("pl-2", add_song_ids=["s4", "s4"])      # s4 thrice, then not at the asked slot
    world["client"].update_playlist("pl-2", remove_indexes=[1])
    result = P.apply(store, world["client"], world["nd"].state.db_path, p["id"], "michael", world["rec"])
    assert store.proposal(p["id"])["decision"] == "stale"
    world["rec"].run()
    row = store.track_status_map("pl-2")["s4"]
    assert row["status"] == "review"
    assert row["reason"].startswith(f"replacement #{p['id']} not made: ") and result in row["reason"]
    assert "approve a different candidate to retry" in row["reason"] and NEW_REL in row["reason"]


def test_an_unproven_copy_superseded_by_a_swap_settles_its_row(world, tmp_path):
    client, store, db = world["client"], world["store"], world["nd"].state.db_path
    client.update_playlist("pl-3", add_song_ids=["s4"])
    world["rec"].set_tier("pl-3", "medium")
    keep_both(world, tmp_path)
    u2, u3 = (next(p["id"] for p in store.proposals() if p["playlist_id"] == pl) for pl in ("pl-2", "pl-3"))
    P.decline(store, u3, "michael")
    v = store.add_proposal(kind="version_swap", playlist_id="pl-2", position=1, old_song_id="s4", new_song_id="s1",
                           summary="another version for that slot")
    P.apply(store, client, db, v, "michael", world["rec"])
    assert store.proposal(u2)["decision"] == "stale" and store.proposal(u2)["result"] == f"superseded by #{v}"
    row = store.track_status_map("pl-3")["s4"]
    assert row["status"] == "review" and row["reason"].startswith(f"declined replacement #{u3}; ")


@pytest.mark.usefixtures("not_in_library")
def test_the_not_asked_event_names_the_filed_file_by_its_library_path(world, tmp_path):
    flac = good_flac_bytes(tmp_path)
    ext = world["store"].add_external_wanted("Chic", "Good Times", album="Risqué", duration_s=501, year=1979)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        r = run(world, srv, approve=True, wanted_id=ext, navidrome_db=tmp_path / "nowhere.db")
    assert r.status == "ok"
    [e] = [e for e in world["store"].events(limit=1000) if e["kind"] == "proposal"]
    assert NEW_REL in e["detail"] and str(tmp_path) not in e["detail"]


# --- HTTP and CLI ------------------------------------------------------------------------------------------------

@pytest.fixture
def svc(tmp_path):
    with FakeSubsonicServer(db_path=tmp_path / "navidrome.db") as nd:
        w = W(nd)
        w.add(RADIO, TWELVE, song("x3", "My Love Is Free (Extended Mix)", 610))
        w.playlist("pl-c", "secondset", "#crate", ["s1", "r1", "s2"])
        w.playlist("pl-d", "warmup", "#crate", ["r1"])
        cfg = Config(subsonic_url=nd.url, username="demo", password="demo", db_path=":memory:", port=0,
                     navidrome_db=str(w.db))
        app = CrateApp(cfg, store=w.store)
        app.reconcile()
        with CrateServer(app) as srv:
            yield w, app, srv


def call(url, method="GET"):
    req = urllib.request.Request(url, data=b"{}" if method == "POST" else None, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        r = e
    return r.status, json.loads(r.read() or b"null")


def test_api_accept_and_decline(svc):
    w, app, srv = svc
    P.version_swaps(w.store, w.db, "t12")
    code, body = call(f"{srv.url}/api/proposals")
    assert code == 200 and len(body) == 2
    assert {p["playlist_name"] for p in body} == {"secondset", "warmup"}
    a = next(p["id"] for p in body if p["playlist_id"] == "pl-c")
    b = next(p["id"] for p in body if p["playlist_id"] == "pl-d")
    code, got = call(f"{srv.url}/api/proposals/{a}/accept", "POST")
    assert code == 200 and got["decision"] == "accepted" and got["decided_by"] == "michael"
    assert w.ids("pl-c") == ["s1", "t12", "s2"]
    assert call(f"{srv.url}/api/proposals/{a}/accept", "POST")[0] == 409
    assert call(f"{srv.url}/api/proposals/{a}/decline", "POST")[0] == 409
    code, got = call(f"{srv.url}/api/proposals/{b}/decline", "POST")
    assert code == 200 and got["decision"] == "declined" and w.ids("pl-d") == ["r1"]
    assert call(f"{srv.url}/api/proposals")[1] == []
    assert len(call(f"{srv.url}/api/proposals?all=1")[1]) == 2
    assert call(f"{srv.url}/api/proposals/999/accept", "POST")[0] == 404
    assert call(f"{srv.url}/api/proposals/x/accept", "POST")[0] == 400


def test_api_accept_without_navidrome_db_is_refused(svc):
    w, app, srv = svc
    [a, _] = P.version_swaps(w.store, w.db, "t12")
    app.cfg.navidrome_db = None
    code, body = call(f"{srv.url}/api/proposals/{a}/accept", "POST")
    assert code == 503 and "navidrome.db" in body["error"]
    assert w.store.proposal(a)["decision"] is None and w.ids("pl-c") == ["s1", "r1", "s2"]


def test_cli_lists_and_accepts(tmp_path, monkeypatch, capsys):
    from crates.cli import main
    with FakeSubsonicServer(db_path=tmp_path / "navidrome.db") as nd:
        w = W(nd)
        w.add(RADIO, TWELVE)
        w.playlist("pl-c", "secondset", "#crate", ["s1", "r1", "s2"])
        for k, v in (("SUBSONIC_URL", nd.url), ("SUBSONIC_USER", "demo"), ("SUBSONIC_PASS", "demo"),
                     ("CRATES_DB", str(tmp_path / "c.db")), ("NAVIDROME_DB", str(w.db))):
            monkeypatch.setenv(k, v)
        store = CrateStore(tmp_path / "c.db")
        Reconciler(w.client, store).run()
        [i] = P.version_swaps(store, w.db, "t12")
        store.db.close()
        assert main(["proposals"]) == 0
        out = capsys.readouterr().out
        assert f"#{i}" in out and "secondset" in out and "580 s" in out
        assert main(["proposals", "accept", str(i)]) == 0
        assert w.ids("pl-c") == ["s1", "t12", "s2"]
        assert "accepted" in capsys.readouterr().out
        assert main(["proposals", "accept", str(i)]) == 1                      # already decided
        assert "already" in capsys.readouterr().err
        assert main(["proposals"]) == 0 and "nothing to decide" in capsys.readouterr().out
        assert main(["proposals", "--all"]) == 0 and "accepted by michael" in capsys.readouterr().out
        with pytest.raises(SystemExit):
            main(["proposals", "decline"])


def test_api_double_tap_accepts_once(svc):
    w, app, srv = svc
    P.version_swaps(w.store, w.db, "t12")
    a = next(p["id"] for p in w.store.proposals() if p["playlist_id"] == "pl-c")
    before, res = w.edits(), []
    ts = [threading.Thread(target=lambda: res.append(call(f"{srv.url}/api/proposals/{a}/accept", "POST")))
          for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sorted(r[0] for r in res) == [200, 409, 409, 409] and w.edits() - before == 1


def test_api_an_answer_from_elsewhere_during_accept_is_409(svc, monkeypatch):
    w, app, srv = svc
    P.version_swaps(w.store, w.db, "t12")
    a = next(p["id"] for p in w.store.proposals() if p["playlist_id"] == "pl-c")
    real = P.replace_slot

    def raced(*args, **kw):
        real(*args, **kw)
        w.store.decide(a, "declined", "agent:other", "answered in another process")
    monkeypatch.setattr(P, "replace_slot", raced)
    code, body = call(f"{srv.url}/api/proposals/{a}/accept", "POST")
    assert code == 409 and "already answered" in body["error"] and "still edited it" in body["error"]
    assert any("after it was answered elsewhere" in (e["detail"] or "") for e in w.store.events(limit=100))


def test_api_accept_on_a_deleted_playlist_is_stale(svc):
    w, app, srv = svc
    P.version_swaps(w.store, w.db, "t12")
    a = next(p["id"] for p in w.store.proposals() if p["playlist_id"] == "pl-c")
    del w.nd.state.playlists["pl-c"]; w.nd.state.sync()
    code, body = call(f"{srv.url}/api/proposals/{a}/accept", "POST")
    assert code == 200 and body["decision"] == "stale" and "no longer exists" in body["result"]


def test_api_unreadable_navidrome_db_is_a_503_and_listing_still_works(svc):
    w, app, srv = svc
    P.version_swaps(w.store, w.db, "t12")
    a = next(p["id"] for p in w.store.proposals() if p["playlist_id"] == "pl-c")
    w.client.update_playlist("pl-c", remove_indexes=[1])                   # would be pruned if the db were readable
    app.cfg.navidrome_db = str(w.db.parent / "nowhere" / "navidrome.db")
    code, body = call(f"{srv.url}/api/proposals/{a}/accept", "POST")
    assert code == 503 and body["error"] == "Navidrome's database can't be read right now"
    assert w.store.proposal(a)["decision"] is None
    code, body = call(f"{srv.url}/api/proposals")
    assert code == 200 and len(body) == 2


def test_api_listing_marks_questions_whose_slot_is_gone_stale(svc):
    w, app, srv = svc
    w.playlist("pl-e", "moved", "#crate", ["s3", "r1"])
    w.playlist("pl-f", "untiered later", "#crate", ["r1"])
    app.reconcile()
    P.version_swaps(w.store, w.db, "t12")
    by = {p["playlist_id"]: p["id"] for p in w.store.proposals()}
    assert sorted(by) == ["pl-c", "pl-d", "pl-e", "pl-f"]
    w.client.update_playlist("pl-c", remove_indexes=[1])                   # slot gone
    del w.nd.state.playlists["pl-d"]; w.nd.state.sync()                    # playlist gone
    w.playlist("pl-e", "moved", "#crate", ["r1", "s3"])                     # moved: apply can still follow it
    w.playlist("pl-f", "untiered later", "", ["r1"]); app.reconcile()       # no longer tiered
    code, body = call(f"{srv.url}/api/proposals")
    assert code == 200 and [p["playlist_id"] for p in body] == ["pl-e"]
    for pl, why in (("pl-c", "no longer holds"), ("pl-d", "no longer exists"), ("pl-f", "no longer tiered")):
        p = w.store.proposal(by[pl])
        assert p["decision"] == "stale" and p["decided_by"].startswith("policy:") and why in p["result"], p
        assert no_ids(p["result"], "t12", "r1", pl)


def test_cli_an_answer_from_elsewhere_during_accept_exits_1(tmp_path, monkeypatch, capsys):
    from crates.cli import main
    with FakeSubsonicServer(db_path=tmp_path / "navidrome.db") as nd:
        w = W(nd)
        w.add(RADIO, TWELVE)
        w.playlist("pl-c", "secondset", "#crate", ["s1", "r1", "s2"])
        for k, v in (("SUBSONIC_URL", nd.url), ("SUBSONIC_USER", "demo"), ("SUBSONIC_PASS", "demo"),
                     ("CRATES_DB", str(tmp_path / "c.db")), ("NAVIDROME_DB", str(w.db))):
            monkeypatch.setenv(k, v)
        store = CrateStore(tmp_path / "c.db")
        Reconciler(w.client, store).run()
        [i] = P.version_swaps(store, w.db, "t12")
        real = P.replace_slot

        def raced(*args, **kw):
            real(*args, **kw)
            store.decide(i, "declined", "agent:other", "answered in another process")   # another connection
        monkeypatch.setattr(P, "replace_slot", raced)
        assert main(["proposals", "accept", str(i)]) == 1
        err = capsys.readouterr().err
        assert "already answered" in err and "Traceback" not in err
