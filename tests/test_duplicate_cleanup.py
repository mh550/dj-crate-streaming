"""scripts/duplicate_cleanup (N1, D31): plan reads navidrome.db and music_root only and writes plan.json + report.md."""
import json
import sqlite3
from contextlib import closing

import pytest

from scripts import duplicate_cleanup as dc
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
