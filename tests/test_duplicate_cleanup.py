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
    srv.state.sync()
    if music is not None:
        touch(music, song["path"])


def touch(music, rel):
    (music / rel).parent.mkdir(parents=True, exist_ok=True)
    (music / rel).write_bytes(b"audio " + rel.encode())


@pytest.fixture
def lib(tmp_path):
    """(fake server with s9 added, navidrome.db path, music root holding every song's file)."""
    music = tmp_path / "music"
    with FakeSubsonicServer(db_path=tmp_path / "navidrome.db") as srv:
        add_song(srv, S9)
        for s in srv.state.songs.values():
            touch(music, s["path"])
        yield srv, srv.state.db_path, music


def test_flac_copy_is_kept_and_the_mp3_is_the_extra_held_by_both_playlists(lib):
    srv, db, music = lib
    plan = dc.build_plan(db, music)
    [g] = plan["groups"]
    assert g["keep"] == {"id": "s9", "path": S9["path"], "suffix": "flac", "bit_rate": 900}
    assert g["extras"] == [{"id": "s3", "path": srv.state.songs["s3"]["path"], "suffix": "mp3", "bit_rate": 192,
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
    monkeypatch.setenv("SUBSONIC_URL", srv.url)
    monkeypatch.setenv("SUBSONIC_USER", "demo")
    monkeypatch.setenv("SUBSONIC_PASS", "demo")
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


def _env(monkeypatch, srv):
    for k, v in (("SUBSONIC_URL", srv.url), ("SUBSONIC_USER", "demo"), ("SUBSONIC_PASS", "demo")):
        monkeypatch.setenv(k, v)


def test_main_repoint_dry_run_then_limit_then_all_exit_0(lib, tmp_path, monkeypatch, capsys):
    srv, db, music = lib
    second_group(srv, music)
    out = tmp_path / "cleanup"
    monkeypatch.setenv("CLEANUP_DIR", str(out))
    dc.write_plan(dc.build_plan(db, music), out)
    _env(monkeypatch, srv)
    args = ["repoint", "--navidrome-db", str(db), "--poll-s", "0"]
    srv.state.requests.clear()
    assert dc.main(args + ["--dry-run"]) == 0
    assert "would repoint" in capsys.readouterr().out and updates(srv) == [] and not list(out.glob("repoint-*"))
    assert dc.main(args + ["--limit", "1"]) == 0
    said = capsys.readouterr().out
    assert said.count("repointed 2 playlists") == 1 and "(scan): done" in said and "reverse log:" in said
    assert dc.main(args) == 0
    assert srv.state.playlists["pl-2"]["songs"] == ["s9", "s8", "s5"]
