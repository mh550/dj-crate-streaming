import csv
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path += ["/usr/share/beets", "/usr/lib/python3/dist-packages"]
from mediafile import MediaFile                                       # noqa: E402

from scripts import dedupe_copies as dc                               # noqa: E402
from subsonic.client import SubsonicClient                            # noqa: E402
from subsonic.fake_server import FakeSubsonicServer                   # noqa: E402


def test_remap_replaces_in_place_and_never_duplicates():
    rep = {"c1": "k1", "c2": "k2"}
    assert dc.remap(["a", "c1", "b"], rep) == ["a", "k1", "b"]
    assert dc.remap(["k1", "a", "c1"], rep) == ["k1", "a"]                 # kept song already there: drop the copy
    assert dc.remap(["c1", "a", "c1"], rep) == ["k1", "a"]                 # the copy twice: one kept entry
    assert dc.remap(["a", "b"], rep) == ["a", "b"]


def _audio(path: Path, freq=440):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration=1", "-ac", "1", "-c:a", "flac", str(path)], check=True)


@pytest.fixture
def world(tmp_path):
    music = tmp_path / "music"
    files = {"Barry White/Staying Power (1999)/01 - Staying Power.flac": ("k1", "Staying Power"),
             "Compilations/Intuition (1981)/01 - Staying Power.flac": ("c1", "Staying Power"),
             "Jamiroquai/Wrong (2022)/03 - Odd.flac": ("c2", "A Different Title"),
             "Butcher Brown/Solar (2023)/03 - Odd.flac": ("k2", "I Can Say To You"),
             "Chic/Risqué (1979)/03 - Good Times.flac": ("g", "Good Times")}
    _audio(music / "Barry White/Staying Power (1999)/01 - Staying Power.flac")
    shutil.copy(music / "Barry White/Staying Power (1999)/01 - Staying Power.flac", music / "Compilations/Intuition (1981)/01 - Staying Power.flac") \
        if (music / "Compilations/Intuition (1981)").mkdir(parents=True) is None else None
    _audio(music / "Butcher Brown/Solar (2023)/03 - Odd.flac", 660)
    (music / "Jamiroquai/Wrong (2022)").mkdir(parents=True)
    shutil.copy(music / "Butcher Brown/Solar (2023)/03 - Odd.flac", music / "Jamiroquai/Wrong (2022)/03 - Odd.flac")
    _audio(music / "Chic/Risqué (1979)/03 - Good Times.flac", 880)
    for rel, (_, title) in files.items():
        m = MediaFile(str(music / rel)); m.title = title; m.save()
    nd = tmp_path / "navidrome.db"
    con = sqlite3.connect(nd)
    con.executescript("""CREATE TABLE media_file (id text primary key, path text, title text, album_artist text, year integer, missing bool default false);
        CREATE TABLE playlist (id text primary key, name text);
        CREATE TABLE playlist_tracks (id integer, playlist_id text, media_file_id text);""")
    con.executemany("INSERT INTO media_file(id,path,title) VALUES(?,?,?)", [(i, rel, t) for rel, (i, t) in files.items()])
    con.executemany("INSERT INTO playlist VALUES(?,?)", [("p1", "firstset？"), ("p2", "Intuition"), ("p3", "clean")])
    con.executemany("INSERT INTO playlist_tracks VALUES(?,?,?)",
                    [(1, "p1", "g"), (2, "p1", "c1"), (3, "p1", "c2"), (1, "p2", "k1"), (2, "p2", "c1"), (1, "p3", "g")])
    con.commit(); con.close()
    lm = tmp_path / "library-map.csv"
    with lm.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["original_path", "folder", "ext", "size", "audio_md5", "new_path", "other_copies"])
        w.writeheader()
        w.writerow(dict(original_path="o/1.flac", folder="f", ext="flac", size=1, audio_md5="h1",
                        new_path="Compilations/Intuition (1981)/01 - Staying Power.flac", other_copies="Barry White/Staying Power (1999)/01 - Staying Power.flac"))
        w.writerow(dict(original_path="o/2.flac", folder="f", ext="flac", size=1, audio_md5="h2",
                        new_path="Jamiroquai/Wrong (2022)/03 - Odd.flac", other_copies="Butcher Brown/Solar (2023)/03 - Odd.flac"))
        w.writerow(dict(original_path="o/3.flac", folder="f", ext="flac", size=1, audio_md5="h3", new_path="Chic/Risqué (1979)/03 - Good Times.flac", other_copies=""))
    return music, nd, lm, tmp_path


def test_plan_trashes_only_identical_audio_with_the_same_title(world):
    music, nd, lm, tmp = world
    plan = dc.plan(lm, music, nd, tmp / "plan.json", tmp / "report.md")
    assert [(t["path"], t["keep_path"]) for t in plan["trash"]] == [
        ("Compilations/Intuition (1981)/01 - Staying Power.flac", "Barry White/Staying Power (1999)/01 - Staying Power.flac")]
    assert plan["person"] == [["Butcher Brown/Solar (2023)/03 - Odd.flac", "Jamiroquai/Wrong (2022)/03 - Odd.flac"]]
    assert {p["name"]: p["after"] for p in plan["playlists"]} == {"firstset？": ["g", "k1", "c2"], "Intuition": ["k1"]}
    assert json.loads((tmp / "plan.json").read_text()) == plan
    report = (tmp / "report.md").read_text()
    assert "Compilations/Intuition (1981)/01 - Staying Power.flac" in report and "## Needs a person" in report


def test_repoint_applies_in_order_refuses_changed_playlists_and_is_idempotent(world):
    music, nd, lm, tmp = world
    plan = dc.plan(lm, music, nd, tmp / "plan.json", tmp / "report.md")
    with FakeSubsonicServer() as srv:
        st = srv.state
        for i in ("g", "c1", "c2", "k1"):
            st.songs[i] = dict(st.songs["s1"], id=i)
        st.playlists["p1"] = {"id": "p1", "name": "firstset？", "comment": "", "owner": "demo", "public": True, "songs": ["g", "c1", "c2"]}
        st.playlists["p2"] = {"id": "p2", "name": "Intuition", "comment": "", "owner": "demo", "public": True, "songs": ["k1", "c1", "g"]}  # edited since the plan
        c = SubsonicClient(srv.url, "demo", "demo")
        done, refused = dc.repoint(plan, c)
        assert done == ["firstset？"] and refused == ["Intuition"]
        assert [e.id for e in c.playlist("p1").entries] == ["g", "k1", "c2"]
        assert dc.repoint(plan, c) == ([], ["Intuition"])                     # second run: nothing left to do


def test_trash_refuses_while_referenced_then_moves_logs_and_updates_the_map(world, monkeypatch):
    music, nd, lm, tmp = world
    plan = dc.plan(lm, music, nd, tmp / "plan.json", tmp / "report.md")
    trash = tmp / "trash"
    removed = []
    monkeypatch.setattr(dc, "_forget_in_beets", lambda paths, config: removed.extend(paths))
    with pytest.raises(dc.StillReferenced):
        dc.trash(plan, music, trash, nd, lm, config=None)
    con = sqlite3.connect(nd)                                                 # as if repoint + rescan happened
    con.execute("UPDATE playlist_tracks SET media_file_id='k1' WHERE media_file_id='c1' AND playlist_id='p1'")
    con.execute("DELETE FROM playlist_tracks WHERE media_file_id='c1'"); con.commit(); con.close()
    moved = dc.trash(plan, music, trash, nd, lm, config=None)
    rel = "Compilations/Intuition (1981)/01 - Staying Power.flac"
    assert moved == [rel] and not (music / rel).exists() and (trash / rel).is_file()
    assert f"mv '{trash / rel}' '{music / rel}'" in (trash / "MOVES.txt").read_text()
    assert removed == [str(music / rel)]
    rows = list(csv.DictReader(lm.open()))
    assert rows[0]["new_path"] == "Barry White/Staying Power (1999)/01 - Staying Power.flac" and rows[0]["other_copies"] == ""
    assert dc.trash(plan, music, trash, nd, lm, config=None) == []           # already done


@pytest.mark.parametrize("keep, other", [
    # (path, album artist as Navidrome shows it, year) — real pairs from the live dry run, 2026-10-15
    (("Butcher Brown/Solar Music (2023)/03 - I Can Say To You.flac", "Butcher Brown", 2023),
     ("Jamiroquai/Virtual Insanity (Bklava Remix) (2022)/03 - I Can Say To You.flac", "Butcher Brown", 2023)),   # folder ≠ its own tag
    (("Chloé Caillet/Doudou (Edit) (2022)/01 - Doudou (Edit).flac", "Chloé Caillet", 2022),
     ("Chloé Caillet Kassav' Jean-Claude Naimro/Doudou (Edit) (2022)/01 - Doudou - Edit.flac", "Chloé Caillet Kassav' Jean-Claude Naimro", 2022)),
    (("Idris Muhammad/Could Heaven (2022)/01 - x.flac", "Idris Muhammad • Walker & Royce • Chris Lorenzo", 2022),
     ("Idris Muhammad Walker & Royce Chris Lorenzo/Could Heaven (2022)/01 - x.flac", "Idris Muhammad Walker & Royce Chris Lorenzo", 2022)),
    (("Marvin Gaye/Midnight Love (1982)/02 - Sexual Healing.flac", "Marvin Gaye", 1982),
     ("Marvin Gaye/Gold (2005)/15 - Sexual Healing.flac", "Marvin Gaye", 2005)),                                   # the original release
    (("Dawn Penn/Vintage 2 (2012)/02 - Chilling.flac", "Dawn Penn", 2012),
     ("Dawn Penn/Vintage 2/00 - Chilling.flac", "Dawn Penn", 0)),                                                    # unknown year last
    (("Barry White/Staying Power (1999)/01 - Staying Power.flac", "Barry White", 1999),
     ("Compilations/Intuition (1981)/01 - Staying Power.flac", "Barry White", 1999)),                              # catch-all folder last
    (("Durand Jones & The Indications/Private Space (2021)/02 - Witchoo.flac", "Durand Jones & The Indications", 2021),
     ("Durand Jones & The Indications/Private Space (2021)/02 - Witchoo.1.flac", "Durand Jones & The Indications", 2021)),  # beets' .1 last
])
def test_keep_rank_prefers_the_properly_filed_copy(keep, other):
    assert dc.keep_rank(*keep) < dc.keep_rank(*other)
