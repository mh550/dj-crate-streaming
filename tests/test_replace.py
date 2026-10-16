"""M8 Task 8: a proven better copy replaces the old one everywhere (every playlist repointed), then the old copy goes
to the trash; anything short of proof keeps both. The one code path that removes a file from the library."""
import datetime
import os
from pathlib import Path

import pytest

from crates.playlist_edit import references
from sourcing import replace
from sourcing.fake_slskd import FakeSlskdServer
from sourcing.verify import verify
from sourcing.worker import Worker
from tests.test_fetch import GOOD, RESPONSES, good_flac_bytes, header_only, new_song, run, world  # noqa: F401  (fixture)
from tests.test_worker import worker

OLD_REL = "Mr. Fingers/Washing Machine/02 - Can You Feel It.mp3"     # s4's path in the fake (the stand-in)
NEW_REL = "Chic/Risqué (1979)/03 - Good Times.flac"                  # where the fake beets files the download


def today() -> str:
    return datetime.date.today().isoformat()


def ids(world, pl):
    return [e.id for e in world["client"].playlist(pl).entries]


def db(world) -> Path:
    return world["nd"].state.db_path


def trashed(world) -> list[Path]:
    root = world["trash"]
    return sorted(p for p in root.rglob("*") if p.is_file() and p.name != "MOVES.txt") if root.exists() else []


def events(world, kind):
    return [e for e in reversed(world["store"].events(limit=1000)) if e["kind"] == kind]


def jobs(world) -> list[dict]:
    return [dict(r) for r in world["store"].db.execute("SELECT * FROM replacements ORDER BY id")]


@pytest.fixture
def scan_sees_trash(world, monkeypatch):
    """Navidrome's scan marks a song missing once its file is gone; the fake has no files, so this does it for s4."""
    client, nd, real = world["client"], world["nd"], world["client"].start_scan
    old = world["music"] / OLD_REL

    def start_scan(*a, **kw):
        if not old.exists():
            nd.state.missing.add("s4")
        return real(*a, **kw)
    monkeypatch.setattr(client, "start_scan", start_scan)
    return old


def fetch_copy(world, tmp_path, **kw):
    """Download, verify and file s9, the better copy of s4 (crate pl-2)."""
    flac = good_flac_bytes(tmp_path)
    with FakeSlskdServer(RESPONSES, world["dl"], files={GOOD: flac}) as srv:
        new_song(world["nd"], len(flac))
        return run(world, srv, approve=True, **kw)


def flagged(value):
    """header_only, with measurements["replaceable"] set to `value` (or removed for `missing`)."""
    def verifier(*a, **kw):
        v = header_only(*a, **kw)
        v.measurements.pop("replaceable", None)
        if value != "missing":
            v.measurements["replaceable"] = value
        return v
    return verifier


def ctx(world, **kw) -> replace.Ctx:
    return replace.Ctx(store=world["store"], navidrome=world["client"], navidrome_db=db(world), music_root=world["music"],
                       trash_root=world["trash"], forget=kw.pop("forget", None), reconciler=world["rec"],
                       scan_timeout_s=1, poll_s=0.01, **kw)


def reference_of(path: Path) -> dict:
    st = path.stat()
    return {"path": str(path.resolve()), "size": st.st_size, "mtime_ns": st.st_mtime_ns}


# --- the happy path ---------------------------------------------------------------------------------------------

def test_replaceable_copy_repoints_every_playlist_then_trashes_the_old_file(world, tmp_path, monkeypatch, scan_sees_trash):
    client = world["client"]
    client.update_playlist("pl-1", add_song_ids=["s4"])               # not a crate
    client.update_playlist("pl-3", add_song_ids=["s4"])               # not tiered at all
    seen = []
    real_move = replace.move_to_trash

    def move(*a, **kw):
        seen.append(references(db(world), "s4"))
        return real_move(*a, **kw)
    monkeypatch.setattr(replace, "move_to_trash", move)
    r = fetch_copy(world, tmp_path)
    assert r.status == "ok" and "replaced the old copy in every playlist" in r.reason, r.reason
    assert ids(world, "pl-1") == ["s1", "s2", "s3", "s9"]
    assert ids(world, "pl-2") == ["s3", "s9", "s5"]
    assert ids(world, "pl-3") == ["s2", "s9"]
    assert seen == [[]]                                               # nothing referred to s4 when it moved
    old = world["music"] / OLD_REL
    dst = world["trash"] / today() / OLD_REL
    assert not old.exists() and dst.read_bytes() == b"old copy of s4"
    moves = (world["trash"] / today() / "MOVES.txt").read_text()
    assert moves.startswith("mv ") and str(dst) in moves and str(old) in moves
    assert [(j["state"], j["old_song_id"], j["new_song_id"], j["old_path"], j["new_path"]) for j in jobs(world)] == \
        [("done", "s4", "s9", OLD_REL, NEW_REL)]
    assert jobs(world)[0]["trash_path"] == str(dst)
    assert (world["music"] / NEW_REL).exists()


def test_replacement_rows_and_events(world, tmp_path, scan_sees_trash):
    fetch_copy(world, tmp_path)
    st = world["store"].track_status_map("pl-2")
    assert st["s9"]["status"] == "ok" and st["s4"]["status"] == "removed"
    states = [e["detail"].split(":")[0] for e in events(world, "replace")]
    assert states == ["#1 repoint", "#1 trash", "#1 scan", "#1 done"]
    assert all("vinylhead77" not in (e["detail"] or "") for e in world["store"].events(limit=1000))
    assert world["store"].verification("s4")["reference"] == OLD_REL


def test_trash_forgets_the_old_file_in_beets(world, tmp_path, monkeypatch, scan_sees_trash):
    calls = []
    monkeypatch.setattr(world["filer"], "forget", lambda p: calls.append((p, Path(p).exists())) or True)
    fetch_copy(world, tmp_path)
    assert calls == [((world["music"] / OLD_REL).absolute(), False)]  # once, the original path, after the move


def test_a_failed_forget_is_logged_not_fatal(world, tmp_path, monkeypatch, scan_sees_trash):
    monkeypatch.setattr(world["filer"], "forget", lambda p: False)
    r = fetch_copy(world, tmp_path)
    assert r.status == "ok" and jobs(world)[0]["state"] == "done"
    assert any("beets" in e["detail"] for e in events(world, "replace"))


def test_trash_destination_taken_gets_a_numbered_name(world, tmp_path, scan_sees_trash):
    taken = world["trash"] / today() / OLD_REL
    taken.parent.mkdir(parents=True)
    taken.write_bytes(b"trashed earlier")
    fetch_copy(world, tmp_path)
    assert taken.read_bytes() == b"trashed earlier"                  # never overwritten
    moved = taken.with_name("02 - Can You Feel It (2).mp3")
    assert moved.read_bytes() == b"old copy of s4" and jobs(world)[0]["trash_path"] == str(moved)


# --- no proof: keep both ----------------------------------------------------------------------------------------

def edits(world) -> int:
    return sum(m == "updatePlaylist" for m, _ in world["nd"].state.requests)


def assert_kept_both(world, r, why: str):
    assert r.status == "ok" and "kept both" in r.reason, r.reason
    assert ids(world, "pl-2") == ["s3", "s4", "s5"]
    assert (world["music"] / OLD_REL).read_bytes() == b"old copy of s4" and trashed(world) == []
    assert jobs(world) == []
    row = world["store"].track_status_map("pl-2")["s4"]
    assert row["status"] == "review" and "not proven the same recording" in row["reason"] and why in row["reason"]
    assert row["reason"].startswith(f"kept beside {OLD_REL}")
    assert len(events(world, "kept_both")) == 1


def test_not_replaceable_keeps_both_and_touches_no_playlist(world, tmp_path):
    before = edits(world)
    r = fetch_copy(world, tmp_path, verifier=lambda path, duration, **kw: verify(path, duration))
    assert edits(world) == before
    assert_kept_both(world, r, "no reference compared")


@pytest.mark.parametrize("value", ["missing", "true", 1, False])
def test_only_a_literal_true_replaceable_licenses_the_trash(world, tmp_path, value):
    r = fetch_copy(world, tmp_path, verifier=flagged(value))
    assert_kept_both(world, r, "")


def test_failed_fingerprint_reads_as_such(world, tmp_path):
    def verifier(*a, **kw):
        v = header_only(*a, **kw)
        v.measurements.update(replaceable=False, reference_compared=True, fingerprint_ber=0.31)
        return v
    assert_kept_both(world, fetch_copy(world, tmp_path, verifier=verifier), "fingerprint differs (BER 0.31)")


@pytest.mark.parametrize("change", ["mtime", "size"])
def test_old_copy_changed_on_disk_since_verify_keeps_both(world, tmp_path, change):
    def verifier(path, duration, reference=None, **kw):
        v = header_only(path, duration, reference=reference, **kw)
        if change == "mtime":
            st = reference.stat()
            os.utime(reference, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        else:
            reference.write_bytes(b"retagged old copy of s4, longer")
        return v
    r = fetch_copy(world, tmp_path, verifier=verifier)
    assert r.status == "ok" and "kept both" in r.reason and "changed since verification" in r.reason
    assert ids(world, "pl-2") == ["s3", "s4", "s5"] and trashed(world) == [] and jobs(world) == []


def test_identity_saying_another_version_keeps_both(world, tmp_path):
    def verifier(*a, **kw):
        world["nd"].state.songs["s9"]["title"] = 'Good Times (12" Version)'   # what Navidrome will call the new song
        return header_only(*a, **kw)
    r = fetch_copy(world, tmp_path, verifier=verifier)
    assert r.status == "ok" and "kept both" in r.reason and "another version" in r.reason, r.reason
    assert ids(world, "pl-2") == ["s3", "s4", "s5"] and trashed(world) == [] and jobs(world) == []


def test_licensed_needs_a_literal_true_and_the_reference_compared():
    ref = {"path": "/srv/music/a.mp3", "size": 1, "mtime_ns": 2}
    good = {"ok": True, "measurements": {"replaceable": True, "reference": ref, "intent": "copy"}}
    assert replace.licensed(good)
    for bad in (None, {}, dict(good, ok=False),
                {"ok": True, "measurements": {"replaceable": True}},
                {"ok": True, "measurements": {"replaceable": True, "reference": None}},
                {"ok": True, "measurements": {"replaceable": True, "reference": {"path": "/a"}}},
                {"ok": True, "measurements": {"replaceable": "true", "reference": ref}},
                {"ok": True, "measurements": {"replaceable": 1, "reference": ref}},
                {"ok": True, "measurements": {"replaceable": True, "reference": ref, "intent": "version"}}):
        assert not replace.licensed(bad), bad


# --- blocked after the repoint ----------------------------------------------------------------------------------

def test_old_copy_moved_since_verification_blocks_the_trash(world, tmp_path, monkeypatch):
    real = replace.playlist_edit.repoint_everywhere

    def repoint(*a, **kw):
        out = real(*a, **kw)
        world["nd"].state.songs["s4"]["path"] = "Elsewhere/02 - Can You Feel It.mp3"     # moved by another tool
        world["nd"].state.sync()
        return out
    monkeypatch.setattr(replace.playlist_edit, "repoint_everywhere", repoint)
    r = fetch_copy(world, tmp_path)
    assert r.status == "ok" and "blocked" in r.reason, r.reason
    assert ids(world, "pl-2") == ["s3", "s9", "s5"]                   # repointed
    assert (world["music"] / OLD_REL).exists() and trashed(world) == []
    job = jobs(world)[0]
    assert job["state"] == "blocked" and "moved since verification" in job["detail"]


def test_old_copy_rewritten_after_the_repoint_blocks_the_trash(world, tmp_path, monkeypatch):
    real = replace.playlist_edit.repoint_everywhere
    old = world["music"] / OLD_REL

    def repoint(*a, **kw):
        out = real(*a, **kw)
        st = old.stat()
        os.utime(old, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))    # retagged in place meanwhile
        return out
    monkeypatch.setattr(replace.playlist_edit, "repoint_everywhere", repoint)
    fetch_copy(world, tmp_path)
    job = jobs(world)[0]
    assert job["state"] == "blocked" and "changed since verification" in job["detail"]
    assert old.exists() and trashed(world) == []


def test_new_path_equal_to_old_path_is_never_trashed(world):
    old = world["music"] / OLD_REL
    c = ctx(world)
    jid = replace.start(world["store"], wanted_id="s4", old_song_id="s4", new_song_id="s1", old_path=OLD_REL,
                        new_path=OLD_REL, reference=reference_of(old))
    assert replace.advance(jid, c) == "blocked"
    assert "is the old file" in world["store"].replacement(jid)["detail"]
    assert ids(world, "pl-2") == ["s3", "s4", "s5"] and old.exists() and trashed(world) == []


def test_a_reference_naming_another_file_never_trashes(world, tmp_path):
    old, other = world["music"] / OLD_REL, tmp_path / "elsewhere.mp3"
    other.write_bytes(old.read_bytes())
    os.utime(other, ns=(old.stat().st_atime_ns, old.stat().st_mtime_ns))     # same size and mtime, another file
    world["nd"].state.sync()
    jid = replace.start(world["store"], wanted_id="s4", old_song_id="s4", new_song_id="s1", old_path=OLD_REL,
                        new_path=NEW_REL, reference=reference_of(other))
    assert replace.advance(jid, ctx(world)) == "blocked"
    assert "not the file verification compared" in world["store"].replacement(jid)["detail"]
    assert old.exists() and trashed(world) == [] and ids(world, "pl-2") == ["s3", "s4", "s5"]


def test_a_job_without_a_reference_never_trashes(world):
    old = world["music"] / OLD_REL
    jid = replace.start(world["store"], wanted_id="s4", old_song_id="s4", new_song_id="s1", old_path=OLD_REL,
                        new_path=NEW_REL, reference=None)
    assert replace.advance(jid, ctx(world)) == "blocked"
    assert old.exists() and trashed(world) == [] and ids(world, "pl-2") == ["s3", "s4", "s5"]


# --- a reference left behind: wait, never trash -----------------------------------------------------------------

def assert_waiting(world, why: str):
    job = jobs(world)[0]
    assert job["state"] == "repoint" and why in job["detail"], job["detail"]
    assert (world["music"] / OLD_REL).exists() and trashed(world) == []


def test_hidden_missing_entry_blocks_the_repoint_and_nothing_is_trashed(world, tmp_path, scan_sees_trash):
    nd = world["nd"]
    nd.state.missing.add("s5"); nd.state.sync()                       # pl-2 now hides its third entry
    r = fetch_copy(world, tmp_path)
    assert r.status == "ok" and "continues in the worker" in r.reason, r.reason
    assert_waiting(world, "getPlaylist hides it")
    assert references(db(world), "s4") == [("pl-2", 2)]
    row = world["store"].track_status_map("pl-2")["s4"]
    assert row["status"] == "review" and "replacement #1" in row["reason"]
    nd.state.missing.discard("s5"); nd.state.sync()                   # fixed by hand
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        worker(world, srv).tick()
    assert jobs(world)[0]["state"] == "done" and ids(world, "pl-2") == ["s3", "s9", "s5"]
    assert not (world["music"] / OLD_REL).exists() and len(trashed(world)) == 1
    st = world["store"].track_status_map("pl-2")
    assert st["s4"]["status"] == "removed" and st["s9"]["status"] == "ok"


def test_smart_playlist_holding_the_old_song_blocks_the_trash(world, tmp_path):
    world["client"].update_playlist("pl-3", add_song_ids=["s4"])
    world["nd"].state.smart.add("pl-3"); world["nd"].state.sync()
    fetch_copy(world, tmp_path)
    assert ids(world, "pl-2") == ["s3", "s9", "s5"]
    assert_waiting(world, "smart playlist")


def test_another_users_playlist_holding_the_old_song_blocks_the_trash(world, tmp_path):
    world["client"].update_playlist("pl-3", add_song_ids=["s4"])
    world["nd"].state.playlists["pl-3"]["owner"] = "amperfy"; world["nd"].state.sync()
    fetch_copy(world, tmp_path)
    assert_waiting(world, "owned by amperfy")
    assert ids(world, "pl-3") == ["s2", "s4"]


def test_old_song_added_back_during_the_repoint_waits_and_the_next_advance_repoints_it(world, tmp_path, monkeypatch,
                                                                                    scan_sees_trash):
    real = replace.playlist_edit.repoint_everywhere
    calls = []

    def repoint(*a, **kw):
        out = real(*a, **kw)
        if not calls:
            world["client"].update_playlist("pl-1", add_song_ids=["s4"])  # Michael adds the old song meanwhile
        calls.append(out)
        return out
    monkeypatch.setattr(replace.playlist_edit, "repoint_everywhere", repoint)
    fetch_copy(world, tmp_path)
    assert_waiting(world, "still in")
    assert replace.advance(jobs(world)[0]["id"], ctx(world)) == "done"
    assert len(calls) == 2 and ids(world, "pl-1") == ["s1", "s2", "s3", "s9"]
    assert references(db(world), "s4") == [] and len(trashed(world)) == 1


def test_the_trash_step_rechecks_references_first(world, monkeypatch, scan_sees_trash):
    """A job resumed at `trash` while a playlist holds the old song again goes back to the repoint first."""
    old, seen = world["music"] / OLD_REL, []
    real_move = replace.move_to_trash
    monkeypatch.setattr(replace, "move_to_trash", lambda *a, **kw: seen.append(references(db(world), "s4")) or real_move(*a, **kw))
    store = world["store"]
    world["nd"].state.sync()                                          # navidrome.db learns s4's relabelled names
    jid = replace.start(store, wanted_id="s4", old_song_id="s4", new_song_id="s1", old_path=OLD_REL, new_path=NEW_REL,
                        reference=reference_of(old))
    store.set_replacement(jid, "trash", "repointed earlier")
    assert replace.advance(jid, ctx(world)) == "done", store.replacement(jid)["detail"]
    assert seen == [[]] and ids(world, "pl-2") == ["s3", "s1", "s5"] and not old.exists()
    states = [e["detail"].split(":")[0] for e in events(world, "replace")]
    assert states == ["#1 repoint", "#1 trash", "#1 repoint", "#1 trash", "#1 scan", "#1 done"]


# --- resumable --------------------------------------------------------------------------------------------------

def test_a_crash_between_steps_resumes_in_the_worker(world, tmp_path, monkeypatch, scan_sees_trash):
    real, calls = replace.move_to_trash, []

    def move(*a, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("disk went away")
        return real(*a, **kw)
    monkeypatch.setattr(replace, "move_to_trash", move)
    r = fetch_copy(world, tmp_path)
    assert r.status == "ok" and "continues in the worker" in r.reason and "disk went away" in r.reason, r.reason
    assert jobs(world)[0]["state"] == "trash" and (world["music"] / OLD_REL).exists() and trashed(world) == []
    assert ids(world, "pl-2") == ["s3", "s9", "s5"]
    lines = []
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        worker(world, srv, lines).tick()
    assert jobs(world)[0]["state"] == "done"
    assert not (world["music"] / OLD_REL).exists() and len(trashed(world)) == 1
    assert world["store"].open_replacements() == []


def test_a_crash_after_the_move_is_not_a_second_move(world, tmp_path, monkeypatch, scan_sees_trash):
    """Killed after the file moved but before the job said so: the resumed step finds it gone and goes on."""
    real = replace.move_to_trash

    def move(*a, **kw):
        real(*a, **kw)
        raise RuntimeError("killed after the move")
    monkeypatch.setattr(replace, "move_to_trash", move)
    fetch_copy(world, tmp_path)
    assert jobs(world)[0]["state"] == "trash" and len(trashed(world)) == 1
    monkeypatch.setattr(replace, "move_to_trash", real)
    assert replace.advance(jobs(world)[0]["id"], ctx(world)) == "done"
    assert len(trashed(world)) == 1 and "already gone" in " ".join(e["detail"] for e in events(world, "replace"))


def test_worker_exports_playlists_on_its_interval(world):
    calls, now = [], [1000.0]
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        wk = worker(world, srv, export_s=300, clock=lambda: now[0],
                    exporter=lambda nd_db, music, out: calls.append((nd_db, music, out)))
        wk.tick()
        now[0] += 299; wk.tick()
        assert calls == [(db(world), world["music"], world["music"] / "_playlists")]
        now[0] += 1; wk.tick()
    assert len(calls) == 2


def test_worker_without_export_interval_never_exports(world):
    calls = []
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        worker(world, srv, exporter=lambda *a: calls.append(a)).tick()
    assert calls == []
