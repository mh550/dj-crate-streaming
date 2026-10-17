"""scripts/duplicate_cleanup (N1, D31): plan reads navidrome.db and music_root only and writes plan.json + report.md;
repoint moves every playlist from each extra to its keeper through crates.playlist_edit, logging the reverse first."""
import json
import sqlite3
from contextlib import closing

import pytest

from crates.playlist_edit import rewrite
from scripts import duplicate_cleanup as dc
from subsonic.client import SubsonicClient
from subsonic.fake_server import FakeSubsonicServer

# The fixture group: s9 is a flac copy of s3 "Move Your Body" (an mp3 in pl-1 and pl-2), so s9 is kept.
S9 = {"id": "s9", "title": "Move Your Body", "artist": "Marshall Jefferson", "album": "The House Music Anthem",
      "duration": 383, "bitRate": 900, "suffix": "flac", "size": 40000000,
      "path": "Marshall Jefferson/The House Music Anthem/01 - Move Your Body.flac"}


def add_song(srv, song, music=None):
    srv.state.songs[song["id"]] = dict(song)
    if music is not None:
        srv.state.songs[song["id"]]["size"] = touch(music, song["path"])
    srv.state.sync()


def touch(music, rel):
    """The song's file; returns its size, which is what navidrome.db's media_file.size says of it."""
    (music / rel).parent.mkdir(parents=True, exist_ok=True)
    (music / rel).write_bytes(b"audio " + rel.encode())
    return (music / rel).stat().st_size


@pytest.fixture
def lib(tmp_path):
    """(fake server with s9 added, navidrome.db path, music root holding every song's file)."""
    music = tmp_path / "music"
    with FakeSubsonicServer(db_path=tmp_path / "navidrome.db") as srv:
        add_song(srv, S9)
        for s in srv.state.songs.values():
            s["size"] = touch(music, s["path"])
        srv.state.sync()
        yield srv, srv.state.db_path, music


def test_flac_copy_is_kept_and_the_mp3_is_the_extra_held_by_both_playlists(lib):
    srv, db, music = lib
    plan = dc.build_plan(db, music)
    [g] = plan["groups"]
    assert g["keep"] == {"id": "s9", "path": S9["path"], "suffix": "flac", "bit_rate": 900,
                         "size": srv.state.songs["s9"]["size"]}
    assert g["extras"] == [{"id": "s3", "path": srv.state.songs["s3"]["path"], "suffix": "mp3", "bit_rate": 192,
                            "size": srv.state.songs["s3"]["size"],
                            "held_by": ["Disco Edits", "Chicago 86"]}]
    assert g["hold"] is None
    assert {p["id"]: (p["name"], p["before"], p["after"]) for p in plan["playlists"]} == {
        "pl-1": ("Disco Edits", ["s1", "s2", "s3"], ["s1", "s2", "s9"]),
        "pl-2": ("Chicago 86", ["s3", "s4", "s5"], ["s9", "s4", "s5"])}


def test_hidden_rows_and_other_owners_count(lib):
    """An extra itself is never hidden (load() skips missing rows); a hidden row beside it stays in `before`."""
    srv, db, music = lib
    srv.state.missing.add("s2")                                         # s2 hidden in pl-1: getPlaylist shows s1, s3
    srv.state.playlists["pl-9"] = {"id": "pl-9", "name": "Theirs", "comment": "", "owner": "other", "public": False,
                                   "songs": ["s3"]}
    srv.state.sync()
    plan = dc.build_plan(db, music)
    assert plan["groups"][0]["extras"][0]["held_by"] == ["Disco Edits", "Chicago 86", "Theirs"]
    pl1 = next(p for p in plan["playlists"] if p["id"] == "pl-1")
    assert (pl1["before"], pl1["after"]) == (["s1", "s2", "s3"], ["s1", "s2", "s9"])


def test_keeper_already_in_the_playlist_drops_the_extra(lib):
    srv, db, music = lib
    srv.state.playlists["pl-1"]["songs"] = ["s9", "s1", "s3", "s3"]
    srv.state.sync()
    plan = dc.build_plan(db, music)
    assert plan["groups"][0]["extras"][0]["held_by"] == ["Disco Edits", "Chicago 86"]
    pl1 = next(p for p in plan["playlists"] if p["id"] == "pl-1")
    assert pl1["after"] == ["s9", "s1"]


def test_two_lossless_copies_are_held_and_repoint_nothing(lib):
    srv, db, music = lib
    flac = dict(S9, id="s10", bitRate=1411, path="Compilations/House/05 - Move Your Body.flac")
    add_song(srv, flac, music)
    plan = dc.build_plan(db, music)
    [g] = plan["groups"]
    assert g["keep"]["id"] == "s9" and [e["id"] for e in g["extras"]] == ["s10", "s3"]
    assert g["hold"] == "both lossless"
    assert plan["playlists"] == []


def test_a_keeper_missing_on_disk_is_held(lib):
    srv, db, music = lib
    (music / S9["path"]).unlink()
    [g] = dc.build_plan(db, music)["groups"]
    assert g["hold"] == "keeper missing on disk"
    assert dc.build_plan(db, music)["playlists"] == []


def second_group(srv, music):
    """s4 "Can You Feel It" (mp3 128, in pl-2) gets a 320 copy s8, which is kept."""
    add_song(srv, dict(srv.state.songs["s4"], id="s8", bitRate=320, path="Mr. Fingers/Other/02 - Can You Feel It.mp3"),
             music)


def test_limit_keeps_the_first_unheld_groups(lib):
    srv, db, music = lib
    second_group(srv, music)
    full = dc.build_plan(db, music)
    assert len(full["groups"]) == 2
    assert [p["after"] for p in full["playlists"] if p["id"] == "pl-2"] == [["s9", "s8", "s5"]]
    one = dc.build_plan(db, music, limit=1)
    assert one["groups"] == full["groups"][:1]
    kept = one["groups"][0]["keep"]["id"]
    assert all(kept in p["after"] for p in one["playlists"])
    assert all(len(set(p["before"]) - set(p["after"])) == 1 for p in one["playlists"])


def test_limit_does_not_count_held_groups(lib):
    srv, db, music = lib
    second_group(srv, music)
    (music / S9["path"]).unlink()                                        # the s3/s9 group is held
    plan = dc.build_plan(db, music, limit=1)
    assert sorted(str(g["hold"]) for g in plan["groups"]) == ["None", "keeper missing on disk"]


def snapshot(srv, db, music):
    return (db.read_bytes(), sorted(p.name for p in db.parent.iterdir() if p.name != "cleanup"),
            json.dumps(srv.state.playlists, sort_keys=True),
            sorted((str(p.relative_to(music)), p.is_file() and p.read_bytes()) for p in music.rglob("*")))


def test_plan_writes_json_and_report_and_touches_nothing_else(lib, tmp_path, capsys):
    srv, db, music = lib
    out = tmp_path / "cleanup"
    before = snapshot(srv, db, music)
    assert dc.main(["plan", "--navidrome-db", str(db), "--music-root", str(music), "--out", str(out)]) == 0
    first = json.loads((out / "plan.json").read_text())
    assert dc.main(["plan", "--navidrome-db", str(db), "--music-root", str(music), "--out", str(out)]) == 0
    second = json.loads((out / "plan.json").read_text())
    assert snapshot(srv, db, music) == before
    first_made = first.pop("made_at")
    assert first_made and second.pop("made_at")
    assert first == second
    # the first plan.json (its holds maybe edited by hand) is kept aside, never overwritten
    assert sorted(p.name for p in out.iterdir()) == ["plan-" + first_made.replace(":", "") + ".json", "plan.json",
                                                     "report.md"]
    report = (out / "report.md").read_text()
    assert S9["path"] in report and "Disco Edits" in report and "Chicago 86" in report
    assert "1 group to act on" in capsys.readouterr().out
    assert srv.state.requests == []                                      # plan never calls Navidrome


def test_report_lists_held_groups_with_the_reason(lib, tmp_path):
    srv, db, music = lib
    (music / S9["path"]).unlink()
    out = tmp_path / "cleanup"
    dc.write_plan(dc.build_plan(db, music), out)
    assert "keeper missing on disk" in (out / "report.md").read_text()


def test_out_defaults_to_cleanup_dir(lib, tmp_path, monkeypatch):
    srv, db, music = lib
    monkeypatch.setenv("CLEANUP_DIR", str(tmp_path / "env-out"))
    assert dc.main(["plan", "--navidrome-db", str(db), "--music-root", str(music)]) == 0
    assert (tmp_path / "env-out" / "plan.json").is_file()


def test_navidrome_db_is_opened_read_only(lib, monkeypatch):
    srv, db, music = lib
    real, uris = sqlite3.connect, []

    def spy(database, *a, **k):
        uris.append(str(database))
        return real(database, *a, **k)
    monkeypatch.setattr(sqlite3, "connect", spy)
    assert dc.build_plan(db, music)["groups"]
    assert uris and all("mode=ro" in u for u in uris)


def test_limit_through_the_cli_and_no_negative_limit(lib, tmp_path):
    srv, db, music = lib
    second_group(srv, music)
    args = ["plan", "--navidrome-db", str(db), "--music-root", str(music), "--out", str(tmp_path / "o")]
    assert dc.main(args + ["--limit", "1"]) == 0
    assert len(json.loads((tmp_path / "o" / "plan.json").read_text())["groups"]) == 1
    with pytest.raises(SystemExit):
        dc.main(args + ["--limit", "-1"])


def test_a_damaged_or_odd_old_plan_is_kept_aside_inside_out(lib, tmp_path):
    srv, db, music = lib
    out = tmp_path / "cleanup"
    out.mkdir()
    (out / "plan.json").write_text('{"made_at": "../../2026"}')
    dc.write_plan(dc.build_plan(db, music), out)
    (out / "plan.json").write_text("not json")
    dc.write_plan(dc.build_plan(db, music), out)
    assert sorted(p.name for p in out.iterdir()) == ["plan-2026.json", "plan-old.json", "plan.json", "report.md"]
    assert not list(tmp_path.glob("*2026*")) and json.loads((out / "plan.json").read_text())["groups"]


# ── repoint (N1-03) ──────────────────────────────────────────────────────────────────────────────────────────

FIXTURE = {"pl-1": ["s1", "s2", "s3"], "pl-2": ["s3", "s4", "s5"]}


def _client(srv):
    return SubsonicClient(srv.url, "demo", "demo")


def updates(srv):
    return [p for m, p in srv.state.requests if m == "updatePlaylist"]


def scans(srv):
    return [m for m, _ in srv.state.requests if m == "startScan"]


def songs(srv):
    return {pid: srv.state.playlists[pid]["songs"] for pid in FIXTURE}


def log_lines(path):
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def run(srv, db, plan, log, **kw):
    return dc.repoint(plan, _client(srv), db, log, poll_s=0, **kw)


def test_repoint_moves_both_playlists_to_the_keeper_logs_the_reverse_and_waits_for_a_scan(lib, tmp_path):
    srv, db, music = lib
    plan, log = dc.build_plan(db, music), tmp_path / "repoint.jsonl"
    srv.state.requests.clear()
    assert run(srv, db, plan, log) == {"s3": "repointed 2 playlists", "(scan)": "done"}
    assert songs(srv) == {"pl-1": ["s1", "s2", "s9"], "pl-2": ["s9", "s4", "s5"]}
    lines = log_lines(log)
    assert [(x["playlist_id"], x["name"], x["extra"], x["keeper"], x["before"], x["after"]) for x in lines] == [
        ("pl-1", "Disco Edits", "s3", "s9", FIXTURE["pl-1"], ["s1", "s2", "s9"]),
        ("pl-2", "Chicago 86", "s3", "s9", FIXTURE["pl-2"], ["s9", "s4", "s5"])]
    assert all(x["ts"] for x in lines)
    assert len(scans(srv)) == 1 and srv.state.requests[-1][0] == "getScanStatus"   # started, then waited for


def test_the_reverse_log_replayed_newest_first_restores_the_playlists(lib, tmp_path):
    srv, db, music = lib
    second_group(srv, music)
    srv.state.playlists["pl-1"]["songs"] = ["s4", "s3", "s1"]          # pl-1 holds extras of both groups
    srv.state.sync()
    before = {pid: list(p["songs"]) for pid, p in srv.state.playlists.items()}
    log = tmp_path / "repoint.jsonl"
    out = run(srv, db, dc.build_plan(db, music), log)
    assert out["s3"] == "repointed 2 playlists" and out["s4"] == "repointed 2 playlists"
    assert srv.state.playlists["pl-1"]["songs"] == ["s8", "s9", "s1"]
    client = _client(srv)
    for x in reversed(log_lines(log)):
        rewrite(client, db, x["playlist_id"], x["after"], x["before"])
    assert {pid: p["songs"] for pid, p in srv.state.playlists.items()} == before


def test_a_hidden_row_refuses_that_playlist_only_and_exits_1(lib, tmp_path, monkeypatch, capsys):
    srv, db, music = lib
    out = tmp_path / "cleanup"
    dc.write_plan(dc.build_plan(db, music), out)
    srv.state.missing.add("s2")                                          # hidden in pl-1
    srv.state.sync()
    _env(monkeypatch, srv, tmp_path / "crates.db")
    assert dc.main(["repoint", "--plan", str(out / "plan.json"), "--navidrome-db", str(db), "--poll-s", "0"]) == 1
    assert srv.state.playlists["pl-1"]["songs"] == FIXTURE["pl-1"]
    assert srv.state.playlists["pl-2"]["songs"] == ["s9", "s4", "s5"]
    assert [p["playlistId"] for p in updates(srv)] == ["pl-2"]
    said = capsys.readouterr().out
    assert "s3: refused: Disco Edits:" in said and "repointed 1 playlist" in said
    [log] = out.glob("repoint-*.jsonl")
    assert [x["playlist_id"] for x in log_lines(log)] == ["pl-2"]       # a refused playlist was never written


def test_a_playlist_edited_after_the_plan_is_repointed_from_its_current_entries(lib, tmp_path):
    srv, db, music = lib
    plan = dc.build_plan(db, music)
    srv.state.playlists["pl-1"]["songs"] = ["s3", "s1"]
    srv.state.sync()
    assert run(srv, db, plan, tmp_path / "r.jsonl")["s3"] == "repointed 2 playlists"
    assert srv.state.playlists["pl-1"]["songs"] == ["s9", "s1"]
    assert log_lines(tmp_path / "r.jsonl")[0]["before"] == ["s3", "s1"]


@pytest.mark.parametrize("gone", ["deleted", "missing"])
def test_a_keeper_gone_since_the_plan_is_skipped(lib, tmp_path, gone):
    srv, db, music = lib
    plan = dc.build_plan(db, music)
    if gone == "deleted":
        del srv.state.songs["s9"]
    else:
        srv.state.missing.add("s9")
    srv.state.sync()
    srv.state.requests.clear()
    assert run(srv, db, plan, tmp_path / "r.jsonl") == {"s3": "skipped: keeper missing"}
    assert songs(srv) == FIXTURE and srv.state.requests == [] and not (tmp_path / "r.jsonl").exists()


def test_a_pair_no_longer_one_group_is_skipped(lib, tmp_path):
    srv, db, music = lib
    plan = dc.build_plan(db, music)
    srv.state.songs["s3"]["title"] = "Move Your Body (Dub)"              # retagged since the plan
    srv.state.sync()
    srv.state.requests.clear()
    assert run(srv, db, plan, tmp_path / "r.jsonl") == {"s3": "skipped: no longer a duplicate of s9"}
    assert songs(srv) == FIXTURE and srv.state.requests == []


def test_repoint_twice_sends_no_second_update_but_scans_again(lib, tmp_path):
    """A re-run after a scan that timed out must not exit 0 without a finished scan."""
    srv, db, music = lib
    plan = dc.build_plan(db, music)
    srv.state.scanning = True
    assert dc.failed(run(srv, db, plan, tmp_path / "r1.jsonl", scan_timeout_s=0))
    srv.state.scanning = False
    srv.state.requests.clear()
    assert run(srv, db, plan, tmp_path / "r2.jsonl") == {"s3": "repointed 0 playlists", "(scan)": "done"}
    assert updates(srv) == [] and len(scans(srv)) == 1 and not (tmp_path / "r2.jsonl").exists()


def test_limit_acts_on_the_first_groups_only(lib, tmp_path):
    srv, db, music = lib
    second_group(srv, music)
    plan = dc.build_plan(db, music)
    first = plan["groups"][0]["extras"][0]["id"]
    assert list(run(srv, db, plan, tmp_path / "r.jsonl", limit=1)) == [first, "(scan)"]
    assert {x["extra"] for x in log_lines(tmp_path / "r.jsonl")} == {first}


def test_a_held_group_is_never_touched(lib, tmp_path):
    srv, db, music = lib
    plan = dc.build_plan(db, music)
    plan["groups"][0]["hold"] = "both lossless"
    srv.state.requests.clear()
    assert run(srv, db, plan, tmp_path / "r.jsonl") == {"s3": "skipped: held (both lossless)"}
    assert songs(srv) == FIXTURE and srv.state.requests == []


def test_dry_run_writes_nothing(lib, tmp_path):
    srv, db, music = lib
    plan = dc.build_plan(db, music)
    srv.state.requests.clear()
    assert run(srv, db, plan, tmp_path / "r.jsonl", dry_run=True) == {
        "s3": "dry run: would repoint Disco Edits, Chicago 86"}
    assert updates(srv) == [] and scans(srv) == [] and not (tmp_path / "r.jsonl").exists()
    assert songs(srv) == FIXTURE


def test_the_reverse_line_is_written_before_a_write_that_fails(lib, tmp_path, monkeypatch):
    srv, db, music = lib
    plan, log = dc.build_plan(db, music), tmp_path / "r.jsonl"
    client = _client(srv)

    def boom(pid, **k):
        assert log_lines(log)[-1]["playlist_id"] == pid                  # its reverse line is already on disk
        raise OSError("connection reset")
    monkeypatch.setattr(client, "update_playlist", boom)
    out = dc.repoint(plan, client, db, log, poll_s=0)
    assert out["s3"].startswith("failed: Disco Edits:") and "Chicago 86" in out["s3"]
    assert out["(scan)"] == "done"
    assert [x["before"] for x in log_lines(log)] == [FIXTURE["pl-1"], FIXTURE["pl-2"]]
    assert dc.failed(out)


def test_a_smart_playlist_or_another_owner_is_reported_not_edited(lib, tmp_path):
    srv, db, music = lib
    srv.state.smart.add("pl-2")
    srv.state.playlists["pl-9"] = {"id": "pl-9", "name": "Theirs", "comment": "", "owner": "other", "public": False,
                                   "songs": ["s3"]}
    srv.state.sync()
    out = run(srv, db, dc.build_plan(db, music), tmp_path / "r.jsonl")
    assert out["s3"].startswith("refused: ")
    assert "Chicago 86: skipped: smart playlist" in out["s3"] and "Theirs: owned by other" in out["s3"]
    assert out["s3"].endswith("repointed 1 playlist") and dc.failed(out)
    assert srv.state.playlists["pl-9"]["songs"] == ["s3"] and srv.state.playlists["pl-2"]["songs"] == FIXTURE["pl-2"]


def test_a_scan_that_never_finishes_is_a_failure(lib, tmp_path):
    srv, db, music = lib
    srv.state.scanning = True
    out = run(srv, db, dc.build_plan(db, music), tmp_path / "r.jsonl", scan_timeout_s=0)
    assert out["s3"] == "repointed 2 playlists" and out["(scan)"].startswith("failed: ")
    assert dc.failed(out) and not dc.failed({"s3": "repointed 2 playlists", "(scan)": "done"})


def test_repoint_edits_playlists_only_through_playlist_edit(lib, tmp_path, monkeypatch):
    srv, db, music = lib
    calls = []
    real = dc.repoint_everywhere

    def spy(*a, **k):
        n = len(updates(srv))
        out = real(*a, **k)
        calls.append((a[2:], len(updates(srv)) - n))
        return out
    monkeypatch.setattr(dc, "repoint_everywhere", spy)
    run(srv, db, dc.build_plan(db, music), tmp_path / "r.jsonl")
    assert calls == [(("s3", "s9"), 2)] and len(updates(srv)) == 2      # every updatePlaylist was sent inside it


def test_a_hand_edited_keeper_equal_to_its_extra_is_skipped(lib, tmp_path):
    srv, db, music = lib
    plan = dc.build_plan(db, music)
    plan["groups"][0]["keep"]["id"] = "s3"
    srv.state.requests.clear()
    assert run(srv, db, plan, tmp_path / "r.jsonl") == {"s3": "skipped: no longer a duplicate of s3"}
    assert srv.state.requests == []


def test_an_error_on_one_extra_is_failed_and_the_rest_still_run(lib, tmp_path, monkeypatch):
    srv, db, music = lib
    second_group(srv, music)
    plan = dc.build_plan(db, music)
    first, second = (g["extras"][0]["id"] for g in plan["groups"])
    real = dc.repoint_everywhere

    def locked(client, d, extra, keeper, **k):
        if extra == first:
            raise OSError("database is locked")
        return real(client, d, extra, keeper, **k)
    monkeypatch.setattr(dc, "repoint_everywhere", locked)
    out = run(srv, db, plan, tmp_path / "r.jsonl")
    assert out[first].startswith("failed: ") and "database is locked" in out[first]
    assert out[second] == "repointed 1 playlist" and out["(scan)"] == "done" and dc.failed(out)   # s4: pl-2 only


def _env(monkeypatch, srv, crates_db=None):
    """SUBSONIC_* for the fake; with `crates_db`, also an empty crates.db there as CRATES_DB."""
    for k, v in (("SUBSONIC_URL", srv.url), ("SUBSONIC_USER", "demo"), ("SUBSONIC_PASS", "demo")):
        monkeypatch.setenv(k, v)
    if crates_db is not None:
        CrateStore(crates_db).db.close()
        monkeypatch.setenv("CRATES_DB", str(crates_db))


def test_main_repoint_dry_run_then_limit_then_all_exit_0(lib, tmp_path, monkeypatch, capsys):
    srv, db, music = lib
    second_group(srv, music)
    out = tmp_path / "cleanup"
    monkeypatch.setenv("CLEANUP_DIR", str(out))
    dc.write_plan(dc.build_plan(db, music), out)
    _env(monkeypatch, srv, tmp_path / "crates.db")
    args = ["repoint", "--navidrome-db", str(db), "--poll-s", "0"]
    srv.state.requests.clear()
    assert dc.main(args + ["--dry-run"]) == 0
    assert "would repoint" in capsys.readouterr().out and updates(srv) == [] and not list(out.glob("repoint-*"))
    assert dc.main(args + ["--limit", "1"]) == 0
    said = capsys.readouterr().out
    assert said.count("repointed 2 playlists") == 1 and "(scan): done" in said and "reverse log:" in said
    assert dc.main(args) == 0
    assert srv.state.playlists["pl-2"]["songs"] == ["s9", "s8", "s5"]


# ── trash (N1-04) ────────────────────────────────────────────────────────────────────────────────────────────

import datetime
import os
import shlex
import shutil

from crates.store import CrateStore
from crates.trash import move_to_trash, restore
from sourcing.worker import hold_lock

S3 = "Marshall Jefferson/The House Music Anthem/01 - Move Your Body.mp3"


@pytest.fixture
def tr(lib, tmp_path):
    """lib after plan and repoint: s3 is in no playlist, its file and s9's are on disk. Yields a namespace whose
    `run(**kw)` calls trash with a recording forget and `forgot` lists what it was called with."""
    srv, db, music = lib
    plan = dc.build_plan(db, music)
    (tmp_path / "cleanup").mkdir()                           # the repoint log beside the trash log: scanned since
    assert dc.repoint(plan, _client(srv), db, tmp_path / "cleanup" / "repoint-1.jsonl", poll_s=0)["s3"] == \
        "repointed 2 playlists"
    assert srv.state.songs["s3"]["path"] == S3
    ns = type("T", (), {})()
    ns.srv, ns.db, ns.music, ns.plan = srv, db, music, plan
    ns.trash_root, ns.lock = tmp_path / "trash", tmp_path / "worker.lock"
    ns.trash_root.mkdir()
    ns.log = tmp_path / "cleanup" / "trash-1.jsonl"
    ns.forgot = []

    def forget(path):
        ns.forgot.append(path)
        return True

    def run(plan=None, **kw):
        kw.setdefault("forget", forget)
        return dc.trash(plan or ns.plan, _client(srv), db, music, ns.trash_root, ns.lock, log_path=ns.log, poll_s=0,
                        **kw)
    ns.run = run
    srv.state.requests.clear()
    return ns


def today():
    return datetime.date.today().isoformat()


def test_trash_moves_the_extra_logs_the_reverse_forgets_it_and_waits_for_a_scan(tr):
    out = tr.run()
    dst = tr.trash_root / today() / S3
    assert out == {"s3": f"moved to {dst}", "(scan)": "done"}
    assert dst.read_bytes() == b"audio " + S3.encode() and not (tr.music / S3).exists()
    assert (tr.trash_root / today() / "MOVES.txt").read_text() == \
        f"mv {shlex.quote(str(dst))} {shlex.quote(str(tr.music / S3))}\n"
    assert tr.forgot == [tr.music / S3]
    assert (tr.music / S9["path"]).read_bytes() == b"audio " + S9["path"].encode()     # the keeper is untouched
    [line] = log_lines(tr.log)
    assert (line["extra"], line["path"], line["keeper"], line["trash_path"]) == ("s3", S3, "s9", str(dst))
    assert line["ts"] and not dc.failed(out)
    assert len(scans(tr.srv)) == 1 and tr.srv.state.requests[-1][0] == "getScanStatus"


def test_before_repoint_the_extra_is_refused_and_nothing_moves(lib, tmp_path):
    srv, db, music = lib
    plan = dc.build_plan(db, music)
    forgot = []
    (tmp_path / "trash").mkdir()
    out = dc.trash(plan, _client(srv), db, music, tmp_path / "trash", tmp_path / "worker.lock", forgot.append,
                   tmp_path / "t.jsonl", poll_s=0)
    assert out == {"s3": "refused: still in 2 playlist entries"} and dc.failed(out)
    assert (music / S3).is_file() and not any((tmp_path / "trash").iterdir()) and forgot == []
    assert not (tmp_path / "t.jsonl").exists() and scans(srv) == []


def test_another_users_playlist_alone_blocks_the_move(tr):
    """Another user's playlist (not ours to see) still counts: navidrome.db playlist_tracks decides."""
    tr.srv.state.playlists["pl-9"] = {"id": "pl-9", "name": "Theirs", "comment": "", "owner": "other",
                                      "public": False, "songs": ["s1", "s3"]}
    tr.srv.state.missing.add("s1")                                      # a hidden row beside it changes nothing
    tr.srv.state.sync()
    assert tr.run() == {"s3": "refused: still in 1 playlist entry"}
    assert (tr.music / S3).is_file() and tr.forgot == [] and not tr.log.exists()


def test_a_running_scan_refuses_before_anything(tr):
    tr.srv.state.scanning = True
    with pytest.raises(dc.CleanupRefused, match="scan"):
        tr.run()
    assert (tr.music / S3).is_file() and not any(tr.trash_root.iterdir()) and not tr.log.exists() and tr.forgot == []


def test_a_scan_that_starts_mid_run_stops_before_the_next_move(tr):
    second_group(tr.srv, tr.music)
    plan = dc.build_plan(tr.db, tr.music)                    # s3/s9 repointed already; s4/s8 still in pl-2
    assert dc.repoint(plan, _client(tr.srv), tr.db, tr.log.parent / "r.jsonl", poll_s=0)["s4"] == "repointed 1 playlist"

    def forget(path):
        tr.forgot.append(path)
        tr.srv.state.scanning = True                          # the hourly scan starts after the first move
        return True
    with pytest.raises(dc.CleanupRefused, match="scan") as e:
        tr.run(plan, forget=forget)
    assert len(tr.forgot) == 1 and len(log_lines(tr.log)) == 1        # the first move is done and logged
    assert sum(v.startswith("moved to ") for v in e.value.results.values()) == 1
    moved = log_lines(tr.log)[0]["extra"]
    other = {"s3": "s4", "s4": "s3"}[moved]
    assert (tr.music / tr.srv.state.songs[other]["path"]).is_file()


def test_a_held_worker_lock_refuses(tr):
    fd = hold_lock(tr.lock)
    try:
        with pytest.raises(dc.CleanupRefused, match="stop the worker first"):
            tr.run()
    finally:
        os.close(fd)
    assert (tr.music / S3).is_file() and tr.srv.state.requests == []
    assert tr.run()["s3"].startswith("moved to ")                        # released by the run: free again


def test_dry_run_moves_nothing_and_writes_nothing(tr):
    assert tr.run(dry_run=True) == {"s3": "dry run: would move"}
    assert (tr.music / S3).is_file() and not any(tr.trash_root.iterdir()) and not tr.log.exists() and tr.forgot == []
    assert scans(tr.srv) == []


def test_a_second_run_is_already_gone_and_does_not_forget_again(tr):
    tr.run()
    tr.srv.state.missing.add("s3")                                      # what the scan does in Navidrome
    tr.srv.state.sync()
    tr.srv.state.requests.clear()
    assert tr.run() == {"s3": "already gone"}
    assert len(tr.forgot) == 1 and scans(tr.srv) == [] and len(log_lines(tr.log)) == 1


def test_already_gone_before_the_scan_too(tr):
    tr.run()
    assert tr.run() == {"s3": "already gone"} and len(tr.forgot) == 1


def test_a_crash_between_move_and_forget_heals_on_the_next_run(tr):
    move_to_trash(S3, tr.music, tr.trash_root)                          # moved, then the process died
    assert tr.run() == {"s3": "already gone"}
    assert tr.forgot == [tr.music / S3]
    assert tr.run() == {"s3": "already gone"} and len(tr.forgot) == 1  # a trash line names it now


@pytest.mark.parametrize("which", ["library", "trash"])
def test_an_unmounted_library_or_trash_refuses_before_anything(tr, tmp_path, which):
    """An empty library would make every extra look already gone; a missing trash mount would put files inside
    the container, gone with `run --rm`."""
    empty = tmp_path / "unmounted"
    empty.mkdir()
    music, trash_root = (empty, tr.trash_root) if which == "library" else (tr.music, tmp_path / "nope")
    with pytest.raises(dc.CleanupRefused, match="not mounted"):
        dc.trash(tr.plan, _client(tr.srv), tr.db, music, trash_root, tr.lock, tr.forgot.append, tr.log, poll_s=0)
    assert tr.forgot == [] and not tr.log.exists() and not (tmp_path / "nope").exists()


def test_a_keeper_absent_from_a_mounted_library_is_not_already_gone(tr):
    (tr.music / S9["path"]).unlink()
    (tr.music / S3).unlink()
    assert tr.run() == {"s3": "skipped: keeper missing"} and tr.forgot == [] and not tr.log.exists()


def test_already_gone_but_still_in_a_playlist_needs_michael(tr):
    """A hidden row on the trashed song (a put-back that failed, or a row added after a refused run): never success."""
    move_to_trash(S3, tr.music, tr.trash_root)
    tr.srv.state.missing.add("s3")
    tr.srv.state.playlists["pl-1"]["songs"].append("s3")                 # hidden in pl-1
    tr.srv.state.sync()
    out = tr.run()
    assert out == {"s3": "failed: gone from the library but still in 1 playlist entry"} and dc.failed(out)
    assert tr.forgot == [] and not tr.log.exists()


def test_a_refused_run_still_puts_back_a_moved_file_a_playlist_took(tr):
    second_group(tr.srv, tr.music)
    plan = dc.build_plan(tr.db, tr.music)
    dc.repoint(plan, _client(tr.srv), tr.db, tr.log.parent / "r.jsonl", poll_s=0)

    def forget(path):
        moved = next(sid for sid in ("s3", "s4") if tr.srv.state.songs[sid]["path"] in str(path))
        tr.srv.state.playlists["pl-2"]["songs"].append(moved)         # Amperfy adds it after the move check
        tr.srv.state.sync()
        tr.srv.state.scanning = True                                    # and a scan starts
        return True
    with pytest.raises(dc.CleanupRefused) as e:
        tr.run(plan, forget=forget)
    [(sid, v)] = [(k, v) for k, v in e.value.results.items() if k in ("s3", "s4")]
    assert v.startswith("refused: added to 1 playlist entry after the move; put back")
    assert (tr.music / tr.srv.state.songs[sid]["path"]).is_file()


def test_trash_never_overwrites(tr):
    """A copy put back while the first stays in the trash goes to a "(2)" name; `restore` itself empties the slot."""
    first = tr.run()["s3"].removeprefix("moved to ")
    shutil.copy2(first, tr.music / S3)
    second = tr.run()["s3"].removeprefix("moved to ")
    assert second == str(tr.trash_root / today() / S3.replace(".mp3", " (2).mp3"))
    assert os.path.isfile(first) and os.path.isfile(second)
    restore(second, S3, tr.music)
    assert tr.run()["s3"] == f"moved to {second}"                         # restored: its trash name is free again


def test_a_row_added_during_the_move_puts_the_file_back(tr, monkeypatch):
    real = dc.move_to_trash

    def racing(rel, music_root, trash_root, before=None):
        def hook(dst):
            assert (trash_root / today() / "MOVES.txt").read_text().startswith("mv ")   # the reverse is written
            tr.srv.state.playlists["pl-1"]["songs"].append("s3")                     # Amperfy adds it meanwhile
            tr.srv.state.sync()
        return real(rel, music_root, trash_root, before=hook)
    monkeypatch.setattr(dc, "move_to_trash", racing)
    out = tr.run()
    assert out == {"s3": "refused: added to 1 playlist entry during the move; put back"} and dc.failed(out)
    assert (tr.music / S3).read_bytes() == b"audio " + S3.encode()
    assert tr.forgot == [] and not tr.log.exists() and scans(tr.srv) == []


def test_a_row_added_before_the_scan_ends_puts_the_file_back(tr, monkeypatch):
    def scan(client, timeout_s, poll_s):
        if "s3" not in tr.srv.state.playlists["pl-2"]["songs"]:
            tr.srv.state.playlists["pl-2"]["songs"].append("s3")
        tr.srv.state.sync()
        return ""
    monkeypatch.setattr(dc, "scan_and_wait", scan)
    out = tr.run()
    assert out["s3"].startswith("refused: added to 1 playlist entry after the move; put back") and dc.failed(out)
    assert "beets no longer lists it" in out["s3"]
    assert out["(scan)"] == "done" and (tr.music / S3).is_file()
    assert [x.get("restored") for x in log_lines(tr.log)] == [None, True]
    monkeypatch.undo()
    tr.srv.state.playlists["pl-2"]["songs"].remove("s3")
    tr.srv.state.sync()
    move_to_trash(S3, tr.music, tr.trash_root)                          # trashed again, then the run died
    assert tr.run()["s3"] == "already gone" and len(tr.forgot) == 2     # the restored line does not count as done


def test_a_failed_forget_is_retried_by_the_next_run(tr):
    tr.run(forget=lambda path: False)
    assert tr.run() == {"s3": "already gone"} and tr.forgot == [tr.music / S3]
    assert tr.run() == {"s3": "already gone"} and len(tr.forgot) == 1


def test_the_keeper_and_the_extra_must_be_different_files(tr):
    (tr.music / S3).unlink()
    os.link(tr.music / S9["path"], tr.music / S3)
    assert tr.run() == {"s3": "refused: the same file as the keeper s9"}
    assert (tr.music / S3).is_file() and (tr.music / S9["path"]).is_file() and not any(tr.trash_root.iterdir())


@pytest.mark.parametrize("gone", ["deleted", "missing", "off disk"])
def test_a_keeper_gone_since_the_plan_is_skipped_by_trash(tr, gone):
    if gone == "off disk":
        (tr.music / S9["path"]).unlink()
    else:
        (tr.srv.state.songs.pop("s9") if gone == "deleted" else tr.srv.state.missing.add("s9"))
        tr.srv.state.sync()
    assert tr.run() == {"s3": "skipped: keeper missing"}
    assert (tr.music / S3).is_file() and tr.forgot == []


def test_a_pair_no_longer_one_group_is_not_trashed(tr):
    tr.srv.state.songs["s3"]["title"] = "Move Your Body (Dub)"
    tr.srv.state.sync()
    assert tr.run() == {"s3": "skipped: no longer a duplicate of s9"} and (tr.music / S3).is_file()


def test_an_extra_moved_since_the_plan_is_skipped(tr):
    tr.srv.state.songs["s3"]["path"] = "Elsewhere/01 - Move Your Body.mp3"
    tr.srv.state.sync()
    assert tr.run() == {"s3": "skipped: moved since the plan (now Elsewhere/01 - Move Your Body.mp3)"}
    assert (tr.music / S3).is_file() and tr.forgot == []


def test_a_held_group_is_never_trashed(tr):
    plan = json.loads(json.dumps(tr.plan))
    plan["groups"][0]["hold"] = "both lossless"
    assert tr.run(plan) == {"s3": "skipped: held (both lossless)"} and (tr.music / S3).is_file()


def test_limit_trashes_the_first_groups_only(tr):
    second_group(tr.srv, tr.music)
    plan = dc.build_plan(tr.db, tr.music)
    dc.repoint(plan, _client(tr.srv), tr.db, tr.log.parent / "r.jsonl", poll_s=0)
    out = tr.run(plan, limit=1)
    assert sum(v.startswith("moved to ") for v in out.values()) == 1 and len(tr.forgot) == 1


def test_a_forget_that_fails_is_noted_not_fatal(tr):
    def broken(path):
        raise RuntimeError("beet exploded")
    out = tr.run(forget=broken)
    assert out["s3"].startswith("moved to ") and "beets still lists it" in out["s3"] and not dc.failed(out)
    assert log_lines(tr.log)[0]["forgotten"] is False


@pytest.mark.parametrize("busy", ["external", "approval", "replacement"])
def test_an_extra_in_use_by_crates_db_is_refused(tr, busy, tmp_path):
    store = CrateStore(tmp_path / "crates.db")
    if busy == "external":
        ext = store.add_external_wanted("Marshall Jefferson", "Move Your Body")
        store.set_library_song(ext, "s3")
        store.set_external_status(ext, "verify", "filed")
        want = ext
    elif busy == "approval":
        store.approve("s3", "michael", None, "high")
        want = "approval of s3"
    else:
        job = store.add_replacement(wanted_id="s3", old_song_id="s3", new_song_id="s9", old_path=S3,
                                    new_path=S9["path"], reference=None)
        want = f"replacement #{job}"
    store.commit()
    assert tr.run(crates_db=tmp_path / "crates.db") == {"s3": f"refused: in use by {want}"}
    assert (tr.music / S3).is_file()


def test_a_finished_external_row_does_not_block(tr, tmp_path):
    store = CrateStore(tmp_path / "crates.db")
    ext = store.add_external_wanted("Marshall Jefferson", "Move Your Body")
    store.set_library_song(ext, "s3")
    store.set_external_status(ext, "ok")
    store.commit()
    assert tr.run(crates_db=tmp_path / "crates.db")["s3"].startswith("moved to ")


def test_crates_db_is_opened_only_under_the_worker_lock(tr, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(dc, "CrateStore", lambda path: opened.append(path))
    fd = hold_lock(tr.lock)
    try:
        with pytest.raises(dc.CleanupRefused):
            tr.run(crates_db=tmp_path / "crates.db")
    finally:
        os.close(fd)
    assert opened == []


def test_main_trash_dry_run_then_all(tr, monkeypatch, capsys):
    out = tr.log.parent
    dc.write_plan(tr.plan, out)
    _env(monkeypatch, tr.srv)
    monkeypatch.setenv("CLEANUP_DIR", str(out))
    monkeypatch.setenv("CRATES_DB", str(tr.lock.parent / "nowhere.db"))
    monkeypatch.delenv("DJ_WORKER", raising=False)
    args = ["trash", "--navidrome-db", str(tr.db), "--music-root", str(tr.music), "--trash-root", str(tr.trash_root),
            "--poll-s", "0"]
    assert dc.main(args + ["--dry-run"]) == 2                            # never a stray crates.db
    assert "CRATES_DB" in capsys.readouterr().err and not (tr.lock.parent / "nowhere.db").exists()
    CrateStore(tr.lock.parent / "crates.db").db.close()
    monkeypatch.setenv("CRATES_DB", str(tr.lock.parent / "crates.db"))
    assert dc.main(args + ["--dry-run"]) == 0
    assert "s3: dry run: would move" in capsys.readouterr().out and (tr.music / S3).is_file()
    fd = hold_lock(tr.lock.parent / "worker.lock")
    try:
        assert dc.main(args) == 1
        assert "stop the worker first" in capsys.readouterr().out
    finally:
        os.close(fd)
    tr.srv.state.scanning = True
    assert dc.main(args) == 1 and "refused: a Navidrome scan is running" in capsys.readouterr().out
    tr.srv.state.scanning = False
    assert dc.main(args) == 0
    said = capsys.readouterr().out
    assert "s3: moved to " in said and "(scan): done" in said and "trash log:" in said
    assert not (tr.music / S3).exists() and len(list(out.glob("trash-*.jsonl"))) == 1


# ── events, main() from the worker's environment, end to end (N1-05) ──────────────────────────────────────────

def cleanup_events(db_path):
    store = CrateStore(db_path)
    try:
        return [(e["playlist_id"], e["song_id"], e["detail"]) for e in reversed(store.events(100))
                if e["kind"] == "cleanup"]
    finally:
        store.db.close()


def test_each_repointed_playlist_is_a_cleanup_event(lib, tmp_path):
    srv, db, music = lib
    store = CrateStore(tmp_path / "crates.db")
    plan = dc.build_plan(db, music)
    srv.state.missing.add("s2")                                         # pl-1 is refused: no event for it
    srv.state.sync()
    assert dc.repoint(plan, _client(srv), db, tmp_path / "r.jsonl", poll_s=0, store=store)["s3"].startswith("refused")
    store.db.close()
    assert cleanup_events(tmp_path / "crates.db") == [("pl-2", "s3", "repointed Chicago 86 to s9")]


def test_a_dry_run_repoint_is_no_event(lib, tmp_path):
    srv, db, music = lib
    store = CrateStore(tmp_path / "crates.db")
    dc.repoint(dc.build_plan(db, music), _client(srv), db, tmp_path / "r.jsonl", dry_run=True, poll_s=0, store=store)
    store.db.close()
    assert cleanup_events(tmp_path / "crates.db") == []


def test_each_move_and_put_back_is_a_cleanup_event_with_the_trash_relative_path(tr, tmp_path, monkeypatch):
    CrateStore(tmp_path / "crates.db").db.close()
    assert tr.run(crates_db=tmp_path / "crates.db")["s3"].startswith("moved to ")
    rel = f"{today()}/{S3}"
    assert cleanup_events(tmp_path / "crates.db") == [(None, "s3", f"trashed to {rel}")]
    assert str(tr.music) not in str(cleanup_events(tmp_path / "crates.db"))

    restore(tr.trash_root / rel, S3, tr.music)                           # put back by hand; then a late row
    def scan(client, timeout_s, poll_s):
        tr.srv.state.playlists["pl-2"]["songs"].append("s3")
        tr.srv.state.sync()
        return ""
    monkeypatch.setattr(dc, "scan_and_wait", scan)
    assert tr.run(crates_db=tmp_path / "crates.db")["s3"].startswith("refused: added to 1 playlist entry after")
    assert cleanup_events(tmp_path / "crates.db")[1:] == [
        (None, "s3", f"trashed to {rel}"), (None, "s3", f"put back from {rel}: in 1 playlist entry after the move")]


def test_a_dry_run_trash_is_no_event(tr, tmp_path):
    CrateStore(tmp_path / "crates.db").db.close()
    tr.run(crates_db=tmp_path / "crates.db", dry_run=True)
    assert cleanup_events(tmp_path / "crates.db") == []


def test_end_to_end_plan_repoint_trash_from_the_worker_environment_then_the_playlist_check(lib, tmp_path,
                                                                                            monkeypatch, capsys):
    """The commands as the runbook runs them, every path from the worker's environment, then export + check."""
    from scripts import export_playlists as ep
    srv, db, music = lib
    second_group(srv, music)
    trash_root, cleanup, crates_db = tmp_path / "trash", tmp_path / "cleanup", tmp_path / "data" / "crates.db"
    trash_root.mkdir()
    crates_db.parent.mkdir()
    CrateStore(crates_db).db.close()
    _env(monkeypatch, srv)
    for k, v in (("NAVIDROME_DB", db), ("MUSIC_ROOT", music), ("TRASH_ROOT", trash_root), ("CLEANUP_DIR", cleanup),
                 ("CRATES_DB", crates_db)):
        monkeypatch.setenv(k, str(v))
    monkeypatch.delenv("DJ_WORKER", raising=False)
    exports = tmp_path / "exports"
    ep.export(db, music, exports)
    assert ep.check(db, music, exports) == []

    assert dc.main(["plan"]) == 0 and (cleanup / "plan.json").is_file()
    assert dc.main(["repoint", "--poll-s", "0"]) == 0
    assert dc.main(["trash", "--poll-s", "0"]) == 0                    # the fake marks nothing missing on its scan
    said = capsys.readouterr().out
    assert "s3: moved to " in said and "s4: moved to " in said
    assert not (music / S3).exists() and (trash_root / today() / S3).is_file()
    assert (music / S9["path"]).is_file() and (music / srv.state.songs["s8"]["path"]).is_file()
    assert songs(srv) == {"pl-1": ["s1", "s2", "s9"], "pl-2": ["s9", "s8", "s5"]}
    assert [d for _, _, d in cleanup_events(crates_db)] == [
        "repointed Disco Edits to s9", "repointed Chicago 86 to s9", "repointed Chicago 86 to s8",
        f"trashed to {today()}/{S3}", f"trashed to {today()}/{srv.state.songs['s4']['path']}"]
    assert len(list(cleanup.glob("repoint-*.jsonl"))) == 1 and len(list(cleanup.glob("trash-*.jsonl"))) == 1
    ep.export(db, music, exports)
    assert ep.check(db, music, exports) == []


def test_repoint_and_trash_need_an_existing_crates_db(lib, tmp_path, monkeypatch, capsys):
    srv, db, music = lib
    dc.write_plan(dc.build_plan(db, music), tmp_path / "cleanup")
    _env(monkeypatch, srv)
    monkeypatch.setenv("CLEANUP_DIR", str(tmp_path / "cleanup"))
    monkeypatch.setenv("NAVIDROME_DB", str(db))
    monkeypatch.setenv("CRATES_DB", str(tmp_path / "nowhere.db"))
    for cmd in ("repoint", "trash"):
        assert dc.main([cmd, "--dry-run"]) == 2
        assert "CRATES_DB" in capsys.readouterr().err
    assert not (tmp_path / "nowhere.db").exists() and srv.state.playlists["pl-1"]["songs"] == FIXTURE["pl-1"]


class LockedStore:
    """crates.db busy (the crates service writing): every event fails."""
    def log(self, *a):
        raise sqlite3.OperationalError("database is locked")

    def commit(self):
        pass

    def song_in_use(self, song_id):
        return None


def test_an_event_that_cannot_be_written_never_fails_the_repoint_or_the_move(tr, lib, tmp_path, monkeypatch, capsys):
    srv, db, music = lib
    second_group(srv, music)
    plan = dc.build_plan(db, music)
    out = dc.repoint(plan, _client(srv), db, tmp_path / "r2.jsonl", poll_s=0, store=LockedStore())
    assert out["s4"] == "repointed 1 playlist" and not dc.failed(out)
    monkeypatch.setattr(dc, "CrateStore", lambda path: type("S", (LockedStore,), {"db": sqlite3.connect(":memory:")})())
    out = tr.run(plan, crates_db=tmp_path / "crates.db")
    assert out["s3"].startswith("moved to ") and out["s4"].startswith("moved to ") and not dc.failed(out)
    assert "event not logged" in capsys.readouterr().err


def test_crates_db_must_be_named_not_defaulted(lib, tmp_path, monkeypatch, capsys):
    """Config.from_env falls back to ./data/crates.db; a stray one there must not pass for the worker's."""
    srv, db, music = lib
    dc.write_plan(dc.build_plan(db, music), tmp_path / "cleanup")
    _env(monkeypatch, srv)
    monkeypatch.delenv("CRATES_DB", raising=False)
    monkeypatch.setenv("CLEANUP_DIR", str(tmp_path / "cleanup"))
    monkeypatch.setenv("NAVIDROME_DB", str(db))
    (tmp_path / "data").mkdir()
    CrateStore(tmp_path / "data" / "crates.db").db.close()
    monkeypatch.chdir(tmp_path)
    assert dc.main(["repoint", "--dry-run"]) == 2 and "CRATES_DB" in capsys.readouterr().err


def test_a_dry_run_repoint_does_not_open_crates_db(lib, tmp_path, monkeypatch):
    srv, db, music = lib
    dc.write_plan(dc.build_plan(db, music), tmp_path / "cleanup")
    _env(monkeypatch, srv, tmp_path / "crates.db")
    monkeypatch.setenv("CLEANUP_DIR", str(tmp_path / "cleanup"))
    monkeypatch.setenv("NAVIDROME_DB", str(db))
    monkeypatch.setattr(dc, "CrateStore", lambda path: pytest.fail("opened crates.db"))
    assert dc.main(["repoint", "--dry-run"]) == 0


def test_a_put_back_after_the_closing_scan_scans_again(tr, monkeypatch):
    """The first scan marked the extra missing; without another one its playlist row stays hidden."""
    calls = []

    def scan(client, timeout_s, poll_s):
        calls.append(1)
        if len(calls) == 1:
            tr.srv.state.playlists["pl-2"]["songs"].append("s3")
            tr.srv.state.sync()
        return ""
    monkeypatch.setattr(dc, "scan_and_wait", scan)
    out = tr.run()
    assert out["s3"].startswith("refused: added to 1 playlist entry after the move") and len(calls) == 2
    assert out["(scan)"] == "done"


# ── N1F-01: a scan after the newest repoint (review I1), the file on disk is the planned file (review I2) ───────

def newer_repoint_log(tr, seconds):
    """A repoint log in the trash log's folder whose last write is `seconds` after the fake's lastScan."""
    log = tr.log.parent / "repoint-2.jsonl"
    log.write_text('{"playlist_id": "pl-1"}\n')
    t = tr.srv.state.last_scan.timestamp() + seconds
    os.utime(log, (t, t))
    return log


def test_trash_refuses_unless_a_scan_finished_after_the_newest_repoint_log(tr):
    newer_repoint_log(tr, 1)                                  # repointed again after the last scan
    with pytest.raises(dc.CleanupRefused, match="no Navidrome scan finished after the newest repoint log "
                                                "repoint-2.jsonl") as e:
        tr.run()
    assert "lastScan" in str(e.value) and e.value.results == {}
    assert (tr.music / S3).is_file() and not any(tr.trash_root.iterdir()) and not tr.log.exists()
    assert tr.forgot == [] and scans(tr.srv) == []
    with pytest.raises(dc.CleanupRefused, match="no Navidrome scan finished"):
        tr.run(dry_run=True)                                  # the dry run says what the real run will do
    _client(tr.srv).start_scan()
    tr.srv.state.last_scan += datetime.timedelta(seconds=2)    # that scan ended after the log's last write
    assert tr.run()["s3"].startswith("moved to ")


def test_a_scan_after_the_newest_repoint_log_lets_trash_proceed(tr):
    newer_repoint_log(tr, -1)
    assert tr.run()["s3"].startswith("moved to ")


def test_trash_refuses_after_a_repoint_when_navidrome_reports_no_lastscan(tr, monkeypatch):
    monkeypatch.setattr(SubsonicClient, "scan_status", lambda self: {"scanning": False})
    with pytest.raises(dc.CleanupRefused, match="no Navidrome scan finished.*lastScan None"):
        tr.run()
    assert (tr.music / S3).is_file()


def test_without_a_repoint_log_lastscan_is_not_needed(tr, monkeypatch):
    for f in tr.log.parent.glob("repoint-*.jsonl"):
        f.unlink()
    monkeypatch.setattr(SubsonicClient, "scan_status", lambda self: {"scanning": False})
    monkeypatch.setattr(dc, "scan_and_wait", lambda *a: "")
    assert tr.run()["s3"].startswith("moved to ")


def test_main_trash_exits_1_naming_the_scan(tr, monkeypatch, capsys):
    out = tr.log.parent
    dc.write_plan(tr.plan, out)
    _env(monkeypatch, tr.srv)
    monkeypatch.setenv("CLEANUP_DIR", str(out))
    CrateStore(tr.lock.parent / "crates.db").db.close()
    monkeypatch.setenv("CRATES_DB", str(tr.lock.parent / "crates.db"))
    monkeypatch.delenv("DJ_WORKER", raising=False)
    newer_repoint_log(tr, 1)
    args = ["trash", "--navidrome-db", str(tr.db), "--music-root", str(tr.music), "--trash-root", str(tr.trash_root),
            "--poll-s", "0"]
    assert dc.main(args) == 1
    assert "refused: no Navidrome scan finished after the newest repoint log" in capsys.readouterr().out
    assert (tr.music / S3).is_file() and not list(out.glob("trash-*.jsonl"))


@pytest.mark.parametrize("text, expect", [
    ("2026-10-17T14:03:12.123456789+02:00", "2026-10-17T12:03:12.123456+00:00"),
    ("2026-10-17T12:03:12Z", "2026-10-17T12:03:12+00:00"),
    ("2026-10-17T12:03:12.5Z", "2026-10-17T12:03:12.500000+00:00"),
    ("0001-01-01T00:00:00Z", "0001-01-01T00:00:00+00:00")])           # Go's zero time: never scanned
def test_lastscan_is_read_as_go_writes_it(text, expect):
    assert dc._scan_time(text) == pytest.approx(datetime.datetime.fromisoformat(expect).timestamp(), abs=1e-6)


@pytest.mark.parametrize("text", [None, "", "yesterday", "2026-10-17 12:03:12", "2026-10-17T12:03:12"])
def test_an_odd_lastscan_is_no_time(text):
    assert dc._scan_time(text) is None


def test_an_extra_whose_file_on_disk_is_not_the_planned_file_is_refused(tr):
    """A new download filed at the extra's path after the scan: its size is not navidrome.db's media_file.size."""
    second_group(tr.srv, tr.music)
    plan = dc.build_plan(tr.db, tr.music)
    assert dc.repoint(plan, _client(tr.srv), tr.db, tr.log.parent / "repoint-2.jsonl", poll_s=0)["s4"] == \
        "repointed 1 playlist"
    size = tr.srv.state.songs["s3"]["size"]
    (tr.music / S3).write_bytes(b"a new download, filed at the same path")
    out = tr.run(plan)
    assert out["s3"] == (f"refused: {S3} is 38 bytes on disk, navidrome.db says {size}, the plan says {size}: "
                         f"not the planned file")
    assert dc.failed(out) and (tr.music / S3).read_bytes() == b"a new download, filed at the same path"
    s4 = tr.srv.state.songs["s4"]["path"]
    assert out["s4"] == f"moved to {tr.trash_root / today() / s4}" and out["(scan)"] == "done"
    assert [x["extra"] for x in log_lines(tr.log)] == ["s4"] and tr.forgot == [tr.music / s4]
    assert tr.run(plan, dry_run=True)["s3"].startswith(f"refused: {S3} is 38 bytes on disk")


def test_a_new_file_scanned_since_the_plan_is_refused_by_the_plans_size(tr):
    """A new download at the extra's path, and a scan after it: navidrome.db's size agrees with the new file (same
    path, same id), the plan's does not."""
    size = tr.srv.state.songs["s3"]["size"]
    (tr.music / S3).write_bytes(b"a new download, filed at the same path")
    tr.srv.state.songs["s3"]["size"] = 38
    tr.srv.state.sync()
    out = tr.run()
    assert out == {"s3": f"refused: {S3} is 38 bytes on disk, the plan says {size}: not the planned file"}
    assert (tr.music / S3).read_bytes() == b"a new download, filed at the same path" and tr.forgot == []


def test_a_plan_without_sizes_checks_navidrome_db_only(tr):
    """A plan written before sizes were recorded (N1) still trashes; the size on disk is checked against the db."""
    plan = json.loads(json.dumps(tr.plan))
    for g in plan["groups"]:
        for f in [g["keep"], *g["extras"]]:
            del f["size"]
    assert tr.run(plan)["s3"].startswith("moved to ")
