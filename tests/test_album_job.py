"""S2-05a: an album request approved as one, run by the worker from its primary folder in one enqueue
(sourcing/album_job.py; fetch's planned mode). The request comes from the Spotify album fixture through
sourcing.requests.add_spotify; slskd is the fake, its one response a 9-track folder (the ext-74 shape).
S2-05b: trouble with a planned file switches the rest of that folder's unfiled rows to another folder (a second
peer's copy of the album, `album_folder(..., peer=PEER_B, directory=DIR_B)`)."""
import json
import re
import time
from pathlib import Path

import pytest

from crates.store import CrateStore
from sourcing import album_job
from sourcing.fake_slskd import FakeSlskdServer
from sourcing.fetch import fetch
from sourcing.filer import BeetsFiler
from sourcing.import_playlist import Match
from sourcing.requests import add_spotify
from sourcing.slskd_client import SlskdClient, transfer_files
from sourcing.worker import Worker
from tests.helpers import beets_items_db, fake_beet, load_responses, make_flac
from tests.test_fetch import header_only, world, not_in_library  # noqa: F401  (fixtures)

FIXTURES = Path(__file__).parent.parent / "fixtures"
SAMPLE = load_responses()
ALBUM = "I'm Still in Love With You"
DIR = "@@music\\Al Green\\I'm Still in Love With You (1972)"
PEER = "soulfolder"                        # the folder's peer: no event, reason or payload may name it
DIR_B = "@@flac\\Al Green\\Al Green - I'm Still in Love With You"      # another peer's rip: no year, so folder 2
PEER_B = "otherpeer"
URL = "https://open.spotify.com/album/2nTlIPIQ7fHOnNN7BRch0Z"


def entity():
    return json.loads((FIXTURES / "spotify_embed_album_al-green-still-in-love.json").read_text())


def flac_bytes(tmp_path, seconds: int) -> bytes:
    """A header-only FLAC of `seconds` that header_only's checks pass (good_flac_bytes' recipe, per length)."""
    return make_flac(tmp_path / f"src-{seconds}.flac", total=44100 * seconds, pad_bytes=seconds * 900_000 // 8).read_bytes()


def album_folder(tmp_path, rows, peer=PEER, skip=(), directory=DIR, speed=3_500_000, offset=0):
    """One response from `peer`: the request's tracks as `<directory>\\Al Green - <album> - NN - <title>.flac`, each
    file's bytes a FLAC of the row's length (listed `offset` s longer); `skip` leaves those track numbers out.
    Returns (response, {filename: bytes})."""
    r = json.loads(json.dumps(SAMPLE[0]))
    r.update(username=peer, hasFreeUploadSlot=True, uploadSpeed=speed)
    files, data = [], {}
    for row in rows:
        if row["track_no"] in skip:
            continue
        title = row["title"].replace(" ,", ", ")               # Spotify's "Oh ,Pretty Woman"; a rip spells it right
        name = f"{directory}\\Al Green - {ALBUM} - {row['track_no']:02d} - {title}.flac"
        data[name] = flac_bytes(tmp_path, int(row["duration"]))
        files.append(dict(SAMPLE[0]["files"][0], filename=name, extension="flac", bitRate=900,
                          length=int(row["duration"]) + offset, size=len(data[name])))
    r["files"] = files
    return r, data


def album_filer(world, tmp_path):
    """beets as fake_beet, each import filed at `Al Green/<album> (1972)/NN - <title>.flac`; Navidrome then lists it
    (after the scan) with that file's size, so fetch finds the filed song."""
    nd, lib = world["nd"], beets_items_db(tmp_path / "album-library.db")

    def target(src: Path) -> str:
        n, title = re.search(r" - (\d\d) - (.+)\.flac$", src.name).groups()
        rel = f"Al Green/{ALBUM} (1972)/{n} - {title}.flac"
        sid = f"al{n}"
        nd.state.songs[sid] = dict(nd.state.songs["s1"], id=sid, title=title, artist="Al Green", album=ALBUM,
                                   suffix="flac", size=src.stat().st_size, path=rel, duration=0)
        nd.state.unscanned.add(sid)
        return rel

    return BeetsFiler(tmp_path / "beets.yaml", library=lib, runner=fake_beet(world["music"], lib, target, artist="Al Green"),
                      tagger=lambda path, names: [])


def common(world, srv, tmp_path, **kw):
    return dict(store=world["store"], slskd=SlskdClient(srv.url, srv.api_key), navidrome=world["client"],
                reconciler=world["rec"], music_root=world["music"], downloads_root=world["dl"],
                filer=album_filer(world, tmp_path), verifier=header_only, poll_s=0.01, download_timeout_s=2,
                scan_timeout_s=1, navidrome_db=world["nd"].state.db_path, trash_root=world["trash"],
                retry_pause_s=0) | kw


def worker(world, srv, tmp_path, **kw):
    c = common(world, srv, tmp_path)
    c.pop("store"), c.pop("slskd"), c.pop("navidrome"), c.pop("reconciler")
    return Worker(store=world["store"], slskd=SlskdClient(srv.url, srv.api_key), navidrome=world["client"],
                  reconciler=world["rec"], fetch_kwargs=c, log=lambda line: None, **kw)


def request(world):
    req = add_spotify(world["store"], URL, fetch=lambda url: entity())
    assert len(req["rows"]) == 9
    return req


def no_peer_anywhere(store, *texts):
    for peer in (PEER, PEER_B):
        for e in store.events(limit=1000):
            assert peer not in (e["detail"] or ""), e
        for (result,) in store.db.execute("SELECT result FROM approvals"):
            assert peer not in (result or ""), result
        for t in texts:
            assert peer not in json.dumps(t), t


# --- plan_request / approve_request

def test_plan_request_searches_the_album_once_and_caches_a_public_plan(world, tmp_path, not_in_library):
    store, req = world["store"], request(world)
    resp, data = album_folder(tmp_path, req["rows"])
    with FakeSlskdServer([resp], world["dl"], files=data) as srv:
        shown = album_job.plan_request(store, SlskdClient(srv.url, srv.api_key), req["id"], poll_s=0.01)
    assert srv.searched == [f"Al Green {ALBUM}"] and srv.enqueued == []
    assert [(f["label"], f["covers"]) for f in shown["folders"]] == [("folder 1", "9 of 9")]
    assert [r["basename"] for r in shown["folders"][0]["rows"]][0] == f"Al Green - {ALBUM} - 01 - I'm Still In Love With You.flac"
    assert shown["per_track"] == []
    assert "username" not in json.dumps(shown) and DIR not in json.dumps(shown)
    cached = store.preview(f"req-{req['id']}")
    assert cached["at"] <= time.time() and len(cached["assign"]) == 9
    first = req["rows"][0]["song_id"]
    assert cached["assign"][first]["candidate"]["username"] == PEER and cached["assign"][first]["folder"] == "folder 1"
    plans = [e["detail"] for e in store.events(limit=1000) if e["kind"] == "plan"]
    assert plans == [f"#{req['id']} folder 1: 9 of 9"]
    no_peer_anywhere(store, shown)


def test_approve_request_records_one_album_approval_per_open_row(world, tmp_path, not_in_library):
    store, req = world["store"], request(world)
    resp, data = album_folder(tmp_path, req["rows"], skip={9})
    with FakeSlskdServer([resp], world["dl"], files=data) as srv:
        album_job.plan_request(store, SlskdClient(srv.url, srv.api_key), req["id"], poll_s=0.01)
    ids = album_job.approve_request(store, req["id"])
    assert len(ids) == 9
    pending = {a["wanted_id"]: a for a in store.pending_approvals()}
    assert {a["purpose"] for a in pending.values()} == {"album"}
    rows = req["rows"]
    assert pending[rows[0]["song_id"]]["candidate"]["basename"].endswith(" - 01 - I'm Still In Love With You.flac")
    assert pending[rows[8]["song_id"]]["candidate"] is None              # no planned file: per track
    assert store.request(req["id"])["status"] == "approved"


@pytest.mark.parametrize("status", ["sourcing", "verify"])
def test_approve_request_refuses_while_a_row_is_in_flight(world, not_in_library, status):
    store, req = world["store"], request(world)
    store.set_wanted_status(req["rows"][2]["song_id"], status, "filed as x.flac but Navidrome has not picked it up yet")
    with pytest.raises(ValueError, match="in flight"):
        album_job.approve_request(store, req["id"])
    assert store.pending_approvals() == []


def test_approve_request_refuses_while_the_job_has_claimed_its_rows(world, not_in_library):
    """Rows the running job has not reached yet are still `needs_source`; their approvals are `started`."""
    store, req = world["store"], request(world)
    album_job.approve_request(store, req["id"])
    for a in store.pending_approvals():
        store.claim_approval(a["id"])
    with pytest.raises(ValueError, match="in flight"):
        album_job.approve_request(store, req["id"])
    assert store.pending_approvals() == []


def test_approve_request_skips_rows_already_ok(world, not_in_library):
    store, req = world["store"], request(world)
    store.set_wanted_status(req["rows"][0]["song_id"], "ok", "already in the library: x (s7)")
    assert len(album_job.approve_request(store, req["id"])) == 8


def test_an_unknown_request_is_refused(world):
    with pytest.raises(ValueError, match="no request"):
        album_job.approve_request(world["store"], 999)


# --- the worker runs the album

def test_worker_runs_the_whole_album_from_one_enqueue(world, tmp_path, not_in_library):
    store, req = world["store"], request(world)
    resp, data = album_folder(tmp_path, req["rows"])
    with FakeSlskdServer([resp], world["dl"], files=data) as srv:
        album_job.plan_request(store, SlskdClient(srv.url, srv.api_key), req["id"], poll_s=0.01)
        album_job.approve_request(store, req["id"])
        report = worker(world, srv, tmp_path).tick()
    assert srv.posts == [(PEER, 9)]                                       # one POST, every planned file
    assert len(srv.searched) == 1                                         # the plan's; planned fetches search nothing
    done = store.request(req["id"])
    assert [r["status"] for r in done["rows"]] == ["ok"] * 9, [(r["status"], r["reason"]) for r in done["rows"]]
    assert done["status"] == "done"
    assert [r["library_song_id"] for r in done["rows"]] == [f"al{n:02d}" for n in range(1, 10)]
    assert report.approvals == 9 and len(report.results) == 9
    assert all(a["result"].startswith("ok: ") for a in (store.approval(r["song_id"]) for r in done["rows"]))
    assert [e["detail"] for e in store.events(limit=1000) if e["kind"] == "plan"] == [f"#{req['id']} folder 1: 9 of 9"]
    assert (world["music"] / "Al Green" / f"{ALBUM} (1972)" / "06 - Oh, Pretty Woman.flac").is_file()
    no_peer_anywhere(store, report.results, *(r["reason"] for r in done["rows"]))


def test_a_row_already_in_the_library_is_linked_not_downloaded(world, tmp_path, monkeypatch):
    store, req = world["store"], request(world)
    third = req["rows"][2]

    def match(client, row, accept=frozenset()):
        if row.title == third["title"]:
            return Match(row, "matched", "s7", how="same version", title=third["title"])
        return Match(row, "missing")

    monkeypatch.setattr("sourcing.fetch.match_in_library", match)
    resp, data = album_folder(tmp_path, req["rows"])
    with FakeSlskdServer([resp], world["dl"], files=data) as srv:
        album_job.plan_request(store, SlskdClient(srv.url, srv.api_key), req["id"], poll_s=0.01)
        album_job.approve_request(store, req["id"])
        worker(world, srv, tmp_path).tick()
    assert srv.posts == [(PEER, 8)] and not any(" - 03 - " in f for _, f in srv.enqueued)
    row = store.external(third["song_id"])
    assert (row["status"], row["library_song_id"]) == ("ok", "s7")
    assert store.approval(third["song_id"])["result"] == "ok: in library (s7)"
    assert [e["detail"] for e in store.events(limit=1000) if e["kind"] == "matched" and e["song_id"] == third["song_id"]] \
        == [f"same version: {third['title']}"]
    assert store.request(req["id"])["status"] == "done"


def test_a_stale_plan_is_made_again_before_the_enqueue(world, tmp_path, not_in_library):
    store, req = world["store"], request(world)
    resp, data = album_folder(tmp_path, req["rows"])
    with FakeSlskdServer([resp], world["dl"], files=data) as srv:
        album_job.plan_request(store, SlskdClient(srv.url, srv.api_key), req["id"], poll_s=0.01)
        album_job.approve_request(store, req["id"])
        cached = store.preview(f"req-{req['id']}")
        store.set_preview(f"req-{req['id']}", cached | {"at": time.time() - 7200})
        worker(world, srv, tmp_path, album_plan_max_age_s=3600).tick()
    assert len(srv.searched) == 2 and srv.posts == [(PEER, 9)]
    assert len([e for e in store.events(limit=1000) if e["kind"] == "plan"]) == 2
    assert store.request(req["id"])["status"] == "done"


def test_approved_without_a_plan_the_job_plans_first(world, tmp_path, not_in_library):
    store, req = world["store"], request(world)
    album_job.approve_request(store, req["id"])
    resp, data = album_folder(tmp_path, req["rows"])
    with FakeSlskdServer([resp], world["dl"], files=data) as srv:
        worker(world, srv, tmp_path).tick()
    assert len(srv.searched) == 1 and srv.posts == [(PEER, 9)]
    assert store.request(req["id"])["status"] == "done"


def test_a_lost_claim_is_not_run(world, tmp_path, not_in_library):
    """An approval superseded after the tick read its list (claim_approval False) is skipped, as in _spend."""
    store, req = world["store"], request(world)
    resp, data = album_folder(tmp_path, req["rows"])
    with FakeSlskdServer([resp], world["dl"], files=data) as srv:
        album_job.plan_request(store, SlskdClient(srv.url, srv.api_key), req["id"], poll_s=0.01)
        album_job.approve_request(store, req["id"])
        approvals = store.pending_approvals()
        first = approvals[0]
        assert store.claim_approval(first["id"])                          # someone else took it
        out = album_job.run(req["id"], approvals, **common(world, srv, tmp_path))
    assert first["wanted_id"] not in [a["wanted_id"] for a, _ in out] and len(out) == 8
    assert srv.posts == [(PEER, 8)]


def test_rows_without_a_planned_file_are_fetched_per_track(world, tmp_path, not_in_library):
    """The happy path's last part: a row no folder serves goes through an ordinary fetch (S2-05c caps it)."""
    store, req = world["store"], request(world)
    resp, data = album_folder(tmp_path, req["rows"], skip={9})
    lone, lone_data = album_folder(tmp_path, req["rows"], peer="lonefile", skip=set(range(1, 9)))
    with FakeSlskdServer([resp, lone], world["dl"], files=data | lone_data) as srv:
        album_job.plan_request(store, SlskdClient(srv.url, srv.api_key), req["id"], poll_s=0.01)
        album_job.approve_request(store, req["id"])
        worker(world, srv, tmp_path).tick()
    assert srv.posts == [(PEER, 8), ("lonefile", 1)]
    assert store.request(req["id"])["status"] == "done"
    assert [e["detail"] for e in store.events(limit=1000) if e["kind"] == "plan"] == \
        [f"#{req['id']} folder 1: 8 of 9; 1 row per track"]


# --- fetch's planned mode

def test_planned_fetch_polls_the_jobs_transfer_without_searching_or_enqueueing(world, tmp_path, not_in_library):
    store, req = world["store"], request(world)
    resp, data = album_folder(tmp_path, req["rows"])
    first = req["rows"][0]
    with FakeSlskdServer([resp], world["dl"], files=data) as srv:
        c = common(world, srv, tmp_path)
        album_job.plan_request(store, c["slskd"], req["id"], poll_s=0.01)
        cand = store.preview(f"req-{req['id']}")["assign"][first["song_id"]]["candidate"]
        stale = srv.seed_transfer(PEER, cand["filename"], "Completed, Errored")     # an earlier attempt's record
        before = {t["id"] for t in transfer_files(c["slskd"].downloads(PEER))}
        c["slskd"].enqueue(PEER, [{"filename": cand["filename"], "size": cand["size"]}])
        searched = len(srv.searched)
        r = fetch(first["song_id"], approve=True, planned=True, prefer=cand, enqueued=before, **c)
    assert (r.status, r.new_song_id) == ("ok", "al01"), r.reason
    assert len(srv.searched) == searched and srv.posts == [(PEER, 1)]      # no search, no enqueue of its own
    # `ok` shows the stale `Completed, Errored` record was not taken for this download (S1-04)


def test_planned_fetch_needs_the_records_before_the_enqueue(world, tmp_path, not_in_library):
    store, req = world["store"], request(world)
    with FakeSlskdServer([], world["dl"], files={}) as srv:
        with pytest.raises(ValueError, match="planned mode"):
            fetch(req["rows"][0]["song_id"], approve=True, planned=True, prefer={"filename": "x"}, enqueued=None,
                  **common(world, srv, tmp_path))


def test_a_planned_file_the_policy_now_rejects_is_not_enqueued(world, tmp_path, not_in_library):
    store, req = world["store"], request(world)
    resp, data = album_folder(tmp_path, req["rows"])
    first = req["rows"][0]["song_id"]
    with FakeSlskdServer([resp], world["dl"], files=data) as srv:
        album_job.plan_request(store, SlskdClient(srv.url, srv.api_key), req["id"], poll_s=0.01)
        cached = store.preview(f"req-{req['id']}")
        cached["assign"][first]["candidate"]["is_locked"] = True
        store.set_preview(f"req-{req['id']}", cached)
        album_job.approve_request(store, req["id"])
        worker(world, srv, tmp_path).tick()
    assert srv.posts == [(PEER, 8)] and not any(" - 01 - " in f for _, f in srv.enqueued)
    assert store.external(first)["status"] == "needs_source"
    assert store.approval(first)["result"] == "needs_source: no acceptable candidate"


def test_a_row_ok_since_its_approval_is_not_enqueued(world, tmp_path, not_in_library):
    store, req = world["store"], request(world)
    resp, data = album_folder(tmp_path, req["rows"])
    first = req["rows"][0]["song_id"]
    with FakeSlskdServer([resp], world["dl"], files=data) as srv:
        album_job.plan_request(store, SlskdClient(srv.url, srv.api_key), req["id"], poll_s=0.01)
        album_job.approve_request(store, req["id"])
        store.set_wanted_status(first, "ok", "already in the library: x (s7)")
        worker(world, srv, tmp_path).tick()
    assert srv.posts == [(PEER, 8)] and len(srv.searched) == 1
    assert store.approval(first)["result"] == "ok: already ok; nothing to do"
    assert store.request(req["id"])["status"] == "done"


def test_a_planned_file_its_fetch_did_not_file_is_forgotten(world, tmp_path, not_in_library):
    """A planned fetch that raises (or returns without filing) leaves no transfer of the job's to land unfiled."""
    store, req = world["store"], request(world)
    resp, data = album_folder(tmp_path, req["rows"])
    second = req["rows"][1]["song_id"]

    def fetcher(wanted_id, **kw):
        if wanted_id == second:
            raise RuntimeError("Navidrome went away")
        return fetch(wanted_id, **kw)

    with FakeSlskdServer([resp], world["dl"], files=data) as srv:
        album_job.plan_request(store, SlskdClient(srv.url, srv.api_key), req["id"], poll_s=0.01)
        album_job.approve_request(store, req["id"])
        out = album_job.run(req["id"], store.pending_approvals(), fetcher=fetcher, **common(world, srv, tmp_path))
        left = [t["filename"] for t in srv.transfers]
    assert dict((a["wanted_id"], o) for a, o in out)[second] == "error: RuntimeError: Navidrome went away"
    assert not any(" - 02 - " in f for f in left) and len(left) == 8         # the 8 filed ones keep their records
    assert store.request(req["id"])["status"] == "partly"


def test_an_enqueue_slskd_refuses_fails_no_row_and_leaves_no_approval_started(world, tmp_path, not_in_library):
    store, req = world["store"], request(world)
    resp, data = album_folder(tmp_path, req["rows"])
    with FakeSlskdServer([resp], world["dl"], files=data, fail_enqueue={PEER}) as srv:
        album_job.plan_request(store, SlskdClient(srv.url, srv.api_key), req["id"], poll_s=0.01)
        album_job.approve_request(store, req["id"])
        report = worker(world, srv, tmp_path).tick()
    assert srv.posts == [(PEER, 9)] and srv.transfers == []
    assert report.approvals == 9 and all(": error: SlskdError" in line for line in report.results)
    assert {r["status"] for r in store.request(req["id"])["rows"]} == {"needs_source"}
    assert all(store.approval(r["song_id"])["result"] != "started" for r in req["rows"])
    no_peer_anywhere(store, report.results)


def test_a_plan_that_cannot_be_made_is_every_approvals_outcome(world, tmp_path, not_in_library):
    store, req = world["store"], request(world)
    album_job.approve_request(store, req["id"])                    # no plan cached: the job plans first
    with FakeSlskdServer([], world["dl"], files={}) as srv:
        c = common(world, srv, tmp_path, slskd=SlskdClient("http://127.0.0.1:9", "k"))     # nothing listens there
        out = album_job.run(req["id"], store.pending_approvals(), **c)
    assert len(out) == 9 and all(o.startswith("error: SlskdError") for _, o in out)
    assert store.pending_approvals() == []
    assert all(store.approval(r["song_id"])["result"].startswith("error: ") for r in req["rows"])


def test_spend_runs_each_request_once_and_other_approvals_as_before(world, tmp_path, not_in_library):
    from sourcing.fetch import FetchResult
    store, req = world["store"], request(world)
    plain = store.add_external_wanted("Chic", "Everybody Dance")
    store.commit()
    calls = []

    def spy(wanted_id, **kw):
        calls.append((wanted_id, kw.get("planned", False)))
        return FetchResult("needs_source", "spied")

    resp, data = album_folder(tmp_path, req["rows"])
    with FakeSlskdServer([resp], world["dl"], files=data) as srv:
        album_job.plan_request(store, SlskdClient(srv.url, srv.api_key), req["id"], poll_s=0.01)
        store.approve("s4", "michael", None, "crate")
        album_job.approve_request(store, req["id"])
        store.approve(plain, "michael", None, "crate", purpose="album")     # an album approval of no request
        report = worker(world, srv, tmp_path, fetcher=spy).tick()
    assert report.approvals == 11 and srv.posts == [(PEER, 9)]
    assert calls[0] == ("s4", False) and calls[-1] == (plain, False)
    assert [c for c in calls[1:-1]] == [(r["song_id"], True) for r in req["rows"]]


# --- switching (S2-05b)

def two_folders(tmp_path, rows):
    """A (PEER, DIR: the primary, its folder name has the year) and B (PEER_B, DIR_B, slower: folder 2), 9 files each
    of the same lengths. Returns ([responses], {filename: bytes})."""
    a, a_data = album_folder(tmp_path, rows)
    b, b_data = album_folder(tmp_path, rows, peer=PEER_B, directory=DIR_B, speed=1_000_000)
    return [a, b], a_data | b_data


def a_file(rows, n):
    return f"{DIR}\\Al Green - {ALBUM} - {n:02d} - {rows[n - 1]['title'].replace(' ,', ', ')}.flac"


def basename(filename):
    return filename.rsplit("\\", 1)[1]


def verifier_failing(kind, *tracks, where=DIR):
    """header_only, except that the files of `tracks` from folder `where` (A's by default: they land under its
    folder name) have one `kind` problem."""
    from sourcing.verify import Verdict
    a_folder = where.rsplit("\\", 1)[1]

    def check(path, duration, **kw):
        n = int(re.search(r" - (\d\d) - ", path.name).group(1))
        if path.parent.name == a_folder and n in tracks:
            return Verdict(False, [f"{kind} problem in {path.name}"], None, kinds=[kind])
        return header_only(path, duration, **kw)
    return check


def switches(store):
    """The `switch` events, oldest first."""
    return [e["detail"] for e in store.events(limit=1000) if e["kind"] == "switch"][::-1]


def run_album(world, srv, tmp_path, store, req, **kw):
    album_job.plan_request(store, SlskdClient(srv.url, srv.api_key), req["id"], poll_s=0.01)
    album_job.approve_request(store, req["id"])
    return album_job.run(req["id"], store.pending_approvals(), **common(world, srv, tmp_path, **kw))


def test_an_ordinary_finding_fails_that_row_only(world, tmp_path, not_in_library):
    store, req = world["store"], request(world)
    rows = req["rows"]
    responses, data = two_folders(tmp_path, rows)
    with FakeSlskdServer(responses, world["dl"], files=data) as srv:
        out = run_album(world, srv, tmp_path, store, req, verifier=verifier_failing("duration", 3))
    assert srv.posts == [(PEER, 9)] and len(srv.searched) == 1               # no switch: no fresh search, no POST
    assert switches(store) == []
    assert [d for d in srv.deleted if d[1] != a_file(rows, 3)] == []         # the other 8 keep their A records
    done = store.request(req["id"])
    assert [r["status"] for r in done["rows"]] == ["ok", "ok", "failed"] + ["ok"] * 6
    assert done["rows"][2]["reason"] == f"duration problem in {basename(a_file(rows, 3))}"
    assert dict((a["wanted_id"], o) for a, o in out)[rows[2]["song_id"]].startswith("failed: duration problem")
    assert done["status"] == "partly"


def test_a_transcode_finding_switches_the_folder_s_unfiled_rows(world, tmp_path, not_in_library):
    store, req = world["store"], request(world)
    rows = req["rows"]
    responses, data = two_folders(tmp_path, rows)
    with FakeSlskdServer(responses, world["dl"], files=data) as srv:
        out = run_album(world, srv, tmp_path, store, req, verifier=verifier_failing("transcode", 2))
        left = [(t["username"], t["filename"]) for t in srv.transfers]
    assert srv.posts == [(PEER, 9), (PEER_B, 8)] and len(srv.searched) == 2   # the plan's search, one fresh one
    assert [f for p, f in left if p == PEER] == [a_file(rows, 1)]            # every unfiled A record forgotten
    assert sorted(f for p, f, remove in srv.deleted if p == PEER and remove) == [a_file(rows, n) for n in range(2, 10)]
    assert not any(" - 01 - " in f for p, f in srv.enqueued if p == PEER_B)
    assert switches(store) == [f"#{req['id']} folder 1 distrusted: transcode ({basename(a_file(rows, 2))}); 8 rows → folder 2"]
    done = store.request(req["id"])
    assert [r["status"] for r in done["rows"]] == ["ok"] * 9, [(r["status"], r["reason"]) for r in done["rows"]]
    assert done["status"] == "done"
    first = done["rows"][0]                                                  # filed from A before the switch: stays
    assert (first["status"], first["library_song_id"]) == ("ok", "al01")
    assert store.approval(first["song_id"])["result"] == dict((a["wanted_id"], o) for a, o in out)[first["song_id"]]
    assert all(o.startswith("ok: ") for _, o in out) and len(out) == 9
    assert [e["detail"] for e in store.events(limit=1000) if e["kind"] == "pick" and e["song_id"] == rows[1]["song_id"]] \
        == [f"planned file: {basename(a_file(rows, 2))}"] * 2                 # A's file, then B's (same basename)
    no_peer_anywhere(store, [o for _, o in out], *(r["reason"] for r in done["rows"]))


def test_a_peer_that_never_starts_switches_all_its_rows(world, tmp_path, not_in_library):
    store, req = world["store"], request(world)
    rows = req["rows"]
    responses, data = two_folders(tmp_path, rows)
    with FakeSlskdServer(responses, world["dl"], files=data, stalled_peers={PEER}) as srv:
        t0 = time.time()
        out = run_album(world, srv, tmp_path, store, req, start_timeout_s=0.2)
        left = [t for t in srv.transfers if t["username"] == PEER]
    assert time.time() - t0 < 10
    assert srv.posts == [(PEER, 9), (PEER_B, 9)] and left == []
    assert switches(store) == [f"#{req['id']} folder 1: no transfer started within 0.2 s; 9 rows → folder 2"]
    done = store.request(req["id"])
    assert [r["status"] for r in done["rows"]] == ["ok"] * 9 and done["status"] == "done"
    no_peer_anywhere(store, [o for _, o in out])


def test_a_transfer_error_switches_that_row_and_the_rest_of_the_folder(world, tmp_path, not_in_library):
    """S1-06's `again`: A's first transfer ends `Completed, Errored` (seeded on the fake once the job enqueued)."""
    store, req = world["store"], request(world)
    rows = req["rows"]
    responses, data = two_folders(tmp_path, rows)
    with FakeSlskdServer(responses, world["dl"], files=data) as srv:
        def fetcher(wanted_id, **kw):
            for t in srv.transfers:
                if (t["username"], t["filename"]) == (PEER, a_file(rows, 1)):
                    t["state"] = "Completed, Errored"
            return fetch(wanted_id, **kw)

        out = run_album(world, srv, tmp_path, store, req, fetcher=fetcher)
        left = [t for t in srv.transfers if t["username"] == PEER]
    assert srv.posts == [(PEER, 9), (PEER_B, 9)] and left == []
    assert switches(store) == [f"#{req['id']} folder 1: download ended: Completed, Errored ({basename(a_file(rows, 1))}); "
                               "9 rows → folder 2"]
    assert [e for e in store.events(limit=1000) if e["kind"] == "retry"] == []    # the job switches, not fetch
    done = store.request(req["id"])
    assert [r["status"] for r in done["rows"]] == ["ok"] * 9 and done["status"] == "done"
    assert all(o.startswith("ok: ") for _, o in out)
    no_peer_anywhere(store, [o for _, o in out])


def test_two_failures_in_one_folder_switch_it(world, tmp_path, not_in_library):
    """Two ordinary findings in A: the first failed row and every unfiled row after the second switch to B."""
    store, req = world["store"], request(world)
    rows = req["rows"]
    responses, data = two_folders(tmp_path, rows)
    with FakeSlskdServer(responses, world["dl"], files=data) as srv:
        out = run_album(world, srv, tmp_path, store, req, verifier=verifier_failing("duration", 3, 5))
    assert srv.posts == [(PEER, 9), (PEER_B, 6)]
    assert switches(store) == [f"#{req['id']} folder 1: 2 failures ({basename(a_file(rows, 3))}, {basename(a_file(rows, 5))}); "
                               "6 rows → folder 2"]
    done = store.request(req["id"])
    assert [r["status"] for r in done["rows"]] == ["ok"] * 9 and done["status"] == "done"
    assert [r["library_song_id"] for r in done["rows"]] == [f"al{n:02d}" for n in range(1, 10)]
    assert len(out) == 9 and all(o.startswith("ok: ") for _, o in out)


def test_a_switched_folder_is_never_the_one_that_failed(world, tmp_path, not_in_library):
    """The re-plan runs over the first search's folders plus a fresh search, without the failed folder: with only A
    there is nowhere to switch, and the rows go per track (S2-05c caps them)."""
    store, req = world["store"], request(world)
    rows = req["rows"]
    resp, data = album_folder(tmp_path, rows)
    with FakeSlskdServer([resp], world["dl"], files=data) as srv:
        calls = []

        def fetcher(wanted_id, **kw):
            calls.append((wanted_id, kw.get("planned", False), kw.get("prefer")))
            return fetch(wanted_id, **kw)

        run_album(world, srv, tmp_path, store, req, verifier=verifier_failing("recording", 8), fetcher=fetcher)
    assert switches(store) == [f"#{req['id']} folder 1 distrusted: recording ({basename(a_file(rows, 8))}); "
                               "2 rows per track"]
    assert calls[-2:] == [(rows[7]["song_id"], False, None), (rows[8]["song_id"], False, None)]
    assert srv.posts[0] == (PEER, 9)


def test_one_row_switches_on_its_own(world, tmp_path, not_in_library):
    store, req = world["store"], request(world)
    rows = req["rows"]
    responses, data = two_folders(tmp_path, rows)
    with FakeSlskdServer(responses, world["dl"], files=data) as srv:
        run_album(world, srv, tmp_path, store, req, verifier=verifier_failing("transcode", 9))
    assert srv.posts == [(PEER, 9), (PEER_B, 1)]
    assert switches(store) == [f"#{req['id']} folder 1 distrusted: transcode ({basename(a_file(rows, 9))}); "
                               "1 row → folder 2"]
    assert store.request(req["id"])["status"] == "done"


def test_a_switch_prefers_the_release_already_filed(world, tmp_path, not_in_library):
    """B (faster, but every length 5 s off: another release) would rank first; C has A's lengths and gets the rows."""
    store, req = world["store"], request(world)
    rows = req["rows"]
    a, a_data = album_folder(tmp_path, rows)
    b, b_data = album_folder(tmp_path, rows, peer=PEER_B, directory=DIR_B, speed=2_000_000, offset=5)
    c, c_data = album_folder(tmp_path, rows, peer="thirdpeer", directory="@@x\\Al Green - Still in Love", speed=10)
    with FakeSlskdServer([a, b, c], world["dl"], files=a_data | b_data | c_data) as srv:
        run_album(world, srv, tmp_path, store, req, verifier=verifier_failing("transcode", 2))
    assert srv.posts == [(PEER, 9), ("thirdpeer", 8)]
    assert switches(store) == [f"#{req['id']} folder 1 distrusted: transcode ({basename(a_file(rows, 2))}); "
                               "8 rows → folder 2"]


def test_a_fresh_search_that_fails_plans_over_the_first_one(world, tmp_path, not_in_library, monkeypatch):
    from sourcing.slskd_client import SlskdError
    store, req = world["store"], request(world)
    rows = req["rows"]
    responses, data = two_folders(tmp_path, rows)
    searches = []
    real = album_job._search

    def search(slskd, r, poll_s):
        searches.append(r["id"])
        if len(searches) > 1:
            raise SlskdError("POST", "/searches", 503, "busy")
        return real(slskd, r, poll_s)

    monkeypatch.setattr(album_job, "_search", search)
    with FakeSlskdServer(responses, world["dl"], files=data) as srv:
        run_album(world, srv, tmp_path, store, req, verifier=verifier_failing("transcode", 2))
    assert len(searches) == 2 and srv.posts == [(PEER, 9), (PEER_B, 8)]
    assert store.request(req["id"])["status"] == "done"


def test_a_row_switches_once_then_goes_per_track(world, tmp_path, not_in_library):
    """B fails too: its unfiled rows have had their one switched folder, so they go per track; no third POST of a
    folder."""
    store, req = world["store"], request(world)
    rows = req["rows"]
    responses, data = two_folders(tmp_path, rows)
    a_check, b_check = verifier_failing("transcode", 2), verifier_failing("transcode", 3, where=DIR_B)
    with FakeSlskdServer(responses, world["dl"], files=data) as srv:
        calls = []

        def fetcher(wanted_id, **kw):
            calls.append((wanted_id, kw.get("planned", False)))
            return fetch(wanted_id, **kw)

        def verifier(path, duration, **kw):
            v = a_check(path, duration, **kw)
            return b_check(path, duration, **kw) if v.ok else v

        out = run_album(world, srv, tmp_path, store, req, verifier=verifier, fetcher=fetcher)
    assert switches(store) == [
        f"#{req['id']} folder 1 distrusted: transcode ({basename(a_file(rows, 2))}); 8 rows → folder 2",
        f"#{req['id']} folder 2 distrusted: transcode ({basename(a_file(rows, 3))}); 7 rows per track"]
    assert srv.posts[:2] == [(PEER, 9), (PEER_B, 8)]
    assert [c[0] for c in calls if c[1]] == [rows[0]["song_id"], rows[1]["song_id"],      # A: 1 filed, 2 distrusts
                                             rows[1]["song_id"], rows[2]["song_id"]]      # B: 2 filed, 3 distrusts
    assert [c[0] for c in calls if not c[1]] == [r["song_id"] for r in rows[2:]]          # per track: 3..9
    assert len(out) == 9 and len(set(a["id"] for a, _ in out)) == 9


def test_cli_worker_reads_the_start_timeout_from_the_environment(tmp_path, monkeypatch):
    import shutil
    import sourcing.worker
    from sourcing import cli
    from subsonic.fake_server import FakeSubsonicServer
    from tests.test_tier_rows import _cli_env
    seen = []

    class Spy(Worker):
        def __init__(self, **kw):
            seen.append(kw.get("album_start_timeout_s"))
            super().__init__(**kw)

    monkeypatch.setattr(sourcing.worker, "Worker", Spy)
    shutil.copy(cli.DEFAULT_BEETS_CONFIG, tmp_path / "beets.yaml")
    with FakeSubsonicServer() as nd, FakeSlskdServer(SAMPLE, tmp_path / "dl", files={}) as sl:
        _cli_env(monkeypatch, tmp_path, nd, sl)
        monkeypatch.setenv("DJ_WORKER", "1")
        monkeypatch.delenv("ALBUM_START_TIMEOUT_S", raising=False)
        assert cli.main(["worker", "--once"]) == 0
        monkeypatch.setenv("ALBUM_START_TIMEOUT_S", "30")
        assert cli.main(["worker", "--once"]) == 0
    assert seen == [album_job.ALBUM_START_TIMEOUT_S, 30.0] and album_job.ALBUM_START_TIMEOUT_S == 600


def test_the_worker_passes_its_start_timeout_to_the_job(world, tmp_path, not_in_library):
    store, req = world["store"], request(world)
    responses, data = two_folders(tmp_path, req["rows"])
    with FakeSlskdServer(responses, world["dl"], files=data, stalled_peers={PEER}) as srv:
        album_job.plan_request(store, SlskdClient(srv.url, srv.api_key), req["id"], poll_s=0.01)
        album_job.approve_request(store, req["id"])
        worker(world, srv, tmp_path, album_start_timeout_s=0.1).tick()
    assert switches(store) == [f"#{req['id']} folder 1: no transfer started within 0.1 s; 9 rows → folder 2"]
    assert store.request(req["id"])["status"] == "done"


# --- restart

def test_after_a_restart_the_request_reads_its_rows(world, tmp_path, not_in_library):
    store, req = world["store"], request(world)
    album_job.approve_request(store, req["id"])
    for a in store.pending_approvals():
        assert store.claim_approval(a["id"])
    for r in req["rows"][:3]:
        store.set_wanted_status(r["song_id"], "sourcing", "downloading x.flac")
    with FakeSlskdServer([], world["dl"], files={}) as srv:
        ids = worker(world, srv, tmp_path).recover()
    assert sorted(ids) == sorted(r["song_id"] for r in req["rows"])
    after = store.request(req["id"])
    assert [r["status"] for r in after["rows"][:3]] == ["failed"] * 3
    assert after["rows"][0]["reason"] == "interrupted: worker restarted"
    assert after["status"] == "open"                    # 3 failed, 6 still open: nothing ok yet
    for r in req["rows"][3:]:
        store.set_wanted_status(r["song_id"], "failed", "interrupted: worker restarted")
    assert store.request(req["id"])["status"] == "failed"
    store.set_wanted_status(req["rows"][4]["song_id"], "ok", "filed as x")
    assert store.request(req["id"])["status"] == "partly"


def test_cli_worker_reads_the_plan_age_from_the_environment(tmp_path, monkeypatch):
    import shutil
    import sourcing.worker
    from sourcing import cli
    from subsonic.fake_server import FakeSubsonicServer
    from tests.test_tier_rows import _cli_env
    seen = []

    class Spy(Worker):
        def __init__(self, **kw):
            seen.append(kw.get("album_plan_max_age_s"))
            super().__init__(**kw)

    monkeypatch.setattr(sourcing.worker, "Worker", Spy)
    shutil.copy(cli.DEFAULT_BEETS_CONFIG, tmp_path / "beets.yaml")
    with FakeSubsonicServer() as nd, FakeSlskdServer(SAMPLE, tmp_path / "dl", files={}) as sl:
        _cli_env(monkeypatch, tmp_path, nd, sl)
        monkeypatch.setenv("DJ_WORKER", "1")
        monkeypatch.delenv("ALBUM_PLAN_MAX_AGE_S", raising=False)
        assert cli.main(["worker", "--once"]) == 0
        monkeypatch.setenv("ALBUM_PLAN_MAX_AGE_S", "60")
        assert cli.main(["worker", "--once"]) == 0
    assert seen == [album_job.ALBUM_PLAN_MAX_AGE_S, 60.0] and album_job.ALBUM_PLAN_MAX_AGE_S == 3600
