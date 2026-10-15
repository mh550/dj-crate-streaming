"""tag_cleanup against a real (temporary) beets library built from one-second generated files."""
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path += ["/usr/share/beets", "/usr/lib/python3/dist-packages"]      # Debian's beets
import yaml                                                           # noqa: E402
from mediafile import MediaFile                                       # noqa: E402

from scripts import tag_cleanup as tc                                 # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PSC = "Compilations/pure soul 128"
FILES = {   # relative path → tags as the downloaders left them (what Navidrome/Amperfy show)
    f"{PSC}/16 - Pepe Link - Vem Menina.mp3": dict(title="Pepe Link - Vem Menina", artist="Pepe Link", albumartist="Music For Dreams",
                                                album="Balearic Biscuits, Vol. 4", year=2024, track=16),
    f"{PSC}/00 - September - Ostavi Trag.mp3": dict(title="September - Ostavi Trag", artist="", albumartist="", album="", year=0, track=0),
    f"{PSC}/04 - 122 - Wendell Harrison - Peace Of Mind.mp3.mp3": dict(title="122 - Wendell Harrison - Peace Of Mind.mp3",
                                                artist="122 - Wendell Harrison - Peace Of Mind.mp3", albumartist="", album="Organic Dream", year=1981, track=4),
    f"{PSC}/08 - The Jacksons.mp3": dict(title="The Jacksons", artist="08", albumartist="", album="Le Top De La Disco", year=1989, track=8),
    "Prince/Graffiti (1987)/01 - Baby's Gone - Remastered 1999.flac": dict(title="Baby's Gone - Remastered 1999", artist="Prince",
                                                albumartist="Prince", album="Graffiti", year=1987, track=1),
}


def _audio(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    codec = ["-c:a", "flac"] if path.suffix == ".flac" else ["-b:a", "32k"]
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-ac", "1", *codec,
                    "-f", "flac" if path.suffix == ".flac" else "mp3", str(path)], check=True)


@pytest.fixture
def lib(tmp_path):
    music, state = tmp_path / "music", tmp_path / "beets"
    state.mkdir()
    for rel, tags in FILES.items():
        _audio(music / rel)
        m = MediaFile(str(music / rel))
        for k, v in tags.items():
            setattr(m, k, v or None)
        m.save()
    cfg = yaml.safe_load((REPO / "deploy/beets.yaml").read_text())
    cfg.update(directory=str(music), library=str(state / "library.db"), statefile=str(state / "state.pickle"))
    cfg["import"]["log"] = str(state / "import.log")
    cfg_path = state / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg))
    # Recreate last night's state: one fake "pure soul 128" compilation whose DB fields disagree with the files.
    from beets.library import Item
    beets_lib = tc.open_lib(cfg_path)
    items = {rel: Item.from_path(str(music / rel)) for rel in FILES}
    comp = [items[r] for r in FILES if r.startswith(PSC)]
    album = beets_lib.add_album(comp)
    album.update(dict(album="pure soul 128", albumartist="Various Artists", comp=True, year=0))
    album.store()
    for it in comp:
        it.update(dict(albumartist="Various Artists", comp=True, artist=it.artist or "08"))   # drift: DB ≠ file
        it.store()
    beets_lib.add_album([items["Prince/Graffiti (1987)/01 - Baby's Gone - Remastered 1999.flac"]])
    beets_lib._close()
    return cfg_path, music, state


def _digest(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def test_plan_reports_every_change_and_touches_nothing(lib, tmp_path):
    cfg, music, state = lib
    before = {p: _digest(p) for p in music.rglob("*") if p.is_file()} | {state / "library.db": _digest(state / "library.db")}
    report = tmp_path / "report.md"
    p = tc.plan(cfg, report)
    assert {p: _digest(p) for p in before} == before                       # no file, no DB byte changed
    text = report.read_text(encoding="utf-8")
    for want in ("Pepe Link/Balearic Biscuits, Vol. 4 (2024)/16 - Vem Menina.mp3", "September/Singles/Ostavi Trag.mp3",
                 "Wendell Harrison/Organic Dream (1981)/04 - Peace Of Mind.mp3", "Prince/Graffiti (1987)/01 - Baby's Gone.flac",
                 "version: Remastered 1999", "| junk, compilation |", "| split, compilation |", "| prefix, compilation |",
                 "## Left in Compilations", f"{PSC}/08 - The Jacksons.mp3"):
        assert want in text, want
    assert p.left == [f"{PSC}/08 - The Jacksons.mp3"]
    assert p.moves == 4 and p.collisions == [] and p.counts["compilation"] == 3 and p.counts["remaster"] == 1


def test_retag_writes_tags_in_place_and_is_idempotent(lib):
    cfg, music, state = lib
    manifest = state / "manifest.json"
    assert tc.retag(cfg, manifest) == 4
    m = MediaFile(str(music / f"{PSC}/16 - Pepe Link - Vem Menina.mp3"))
    assert (m.title, m.artist, m.albumartist, bool(m.comp)) == ("Vem Menina", "Pepe Link", "Pepe Link", False)
    m = MediaFile(str(music / "Prince/Graffiti (1987)/01 - Baby's Gone - Remastered 1999.flac"))
    assert m.title == "Baby's Gone" and "version: Remastered 1999" in m.comments
    assert all((music / rel).exists() for rel in FILES)                    # nothing moved in pass 1
    assert MediaFile(str(music / f"{PSC}/08 - The Jacksons.mp3")).artist == "08"   # not touched
    entries = json.loads(manifest.read_text())
    assert len(entries) == 4 and all(e["path_before"] and e["after"] for e in entries)
    assert (state / "library.db.bak-tag-cleanup").exists()
    assert tc.retag(cfg, manifest) == 0                                     # second run: nothing left to do


def _navidrome(tmp_path, music, rows):
    db = tmp_path / "navidrome.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE media_file (id text primary key, path text, title text, artist text, album_artist text, album text, missing bool default false)")
    con.executemany("INSERT INTO media_file(id,path,title,artist,album_artist,album) VALUES(?,?,?,?,?,?)", rows)
    con.commit(); con.close()
    return db


def test_move_refuses_until_navidrome_has_scanned_pass_one_then_moves(lib, tmp_path):
    cfg, music, state = lib
    manifest = state / "manifest.json"
    tc.retag(cfg, manifest)
    entries = json.loads(manifest.read_text())
    stale = _navidrome(tmp_path, music, [(str(i), str(Path(e["path_before"]).relative_to(music)), e["before"]["title"], e["before"]["artist"],
                                          e["before"]["albumartist"], e["before"]["album"]) for i, e in enumerate(entries)])
    with pytest.raises(tc.NotScanned) as err:
        tc.move(cfg, manifest, stale)
    assert "4 of 4" in str(err.value)
    assert all((music / rel).exists() for rel in FILES)
    stale.unlink()
    # Like live Navidrome 0.64 (2026-10-15): an empty album tag reads "[Unknown Album]", an empty artist "[Unknown Artist]".
    fresh = _navidrome(tmp_path, music, [(str(i), str(Path(e["path_before"]).relative_to(music)), e["after"]["title"],
                                          e["after"]["artist"] or "[Unknown Artist]", e["after"]["albumartist"] or e["after"]["artist"],
                                          e["after"]["album"] or "[Unknown Album]") for i, e in enumerate(entries)])
    moved = tc.move(cfg, manifest, fresh)
    assert len(moved) == 4
    assert (music / "Pepe Link/Balearic Biscuits, Vol. 4 (2024)/16 - Vem Menina.mp3").is_file()
    assert (music / "September/Singles/Ostavi Trag.mp3").is_file()
    assert (music / "Prince/Graffiti (1987)/01 - Baby's Gone.flac").is_file()
    assert [x.name for x in (music / PSC).iterdir()] == ["08 - The Jacksons.mp3"]   # no usable artist: stays put
    assert all(e.get("path_after") for e in json.loads(manifest.read_text()))
    assert tc.move(cfg, manifest, fresh) == []                              # already moved: no-op


# ---------------- Opus M2 review fixes (2026-10-15) ----------------
import mutagen                                                        # noqa: E402
from mutagen.flac import FLAC                                         # noqa: E402
from mutagen.id3 import ID3, TCON, TIT2, TPE1                         # noqa: E402


def test_write_minimal_keeps_every_other_tag(tmp_path):
    # Proved live: beets' item.write() collapsed GENRE [Jazz, Latin] to [Jazz], garbled RELEASETYPE and added zero totals.
    f = tmp_path / "a.flac"; _audio(f)
    tags = FLAC(f); tags["TITLE"] = "Old - Remastered"; tags["ARTIST"] = ["Alice", "Bob"]; tags["GENRE"] = ["Jazz", "Latin"]
    tags["RELEASETYPE"] = ["album", "remix"]; tags.save()
    tc.write_minimal(f, {"title": "Old", "albumartist": "Alice", "comp": False})
    t = FLAC(f)
    assert t["TITLE"] == ["Old"] and t["ALBUMARTIST"] == ["Alice"] and t["ARTIST"] == ["Alice", "Bob"]
    assert t["GENRE"] == ["Jazz", "Latin"] and t["RELEASETYPE"] == ["album", "remix"]
    assert not {"DATE", "DISCTOTAL", "TRACKTOTAL", "COMPILATION", "BPM"} & set(t.keys())
    m = tmp_path / "b.mp3"; _audio(m)
    id3 = ID3(); id3.add(TIT2(encoding=3, text="Pepe Link - Vem Menina")); id3.add(TPE1(encoding=3, text="Pepe Link"))
    id3.add(TCON(encoding=3, text=["Jazz", "Latin"])); id3.save(m, v2_version=3)
    tcon_before = ID3(m)["TCON"].text                                     # v2.3 stores it as "Jazz/Latin"
    tc.write_minimal(m, {"title": "Vem Menina"})
    t = ID3(m)
    assert t.version[:2] == (2, 3) and str(t["TIT2"]) == "Vem Menina" and t["TCON"].text == tcon_before
    assert not {"TRCK", "TDRC", "TYER", "USLT"} & {k[:4] for k in t.keys()}


def test_retag_writes_only_intended_fields_and_skips_regroup_only(lib):
    cfg, music, state = lib
    prince = music / "Prince/Graffiti (1987)/01 - Baby's Gone - Remastered 1999.flac"
    t = FLAC(prince); t["GENRE"] = ["Soul", "Funk"]; t.save()
    tc.retag(cfg, state / "manifest.json")
    assert FLAC(prince)["GENRE"] == ["Soul", "Funk"] and "DISCTOTAL" not in FLAC(prince)


def test_retag_crash_keeps_a_manifest_that_a_rerun_completes(lib, monkeypatch):
    cfg, music, state = lib
    manifest, real, calls = state / "manifest.json", tc.write_minimal, []
    def flaky(path, changes):
        calls.append(path)
        if len(calls) == 3:
            raise OSError("not writable")
        real(path, changes)
    monkeypatch.setattr(tc, "write_minimal", flaky)
    with pytest.raises(OSError):
        tc.retag(cfg, manifest)
    entries = json.loads(manifest.read_text())
    assert len(entries) == 4 and sum(1 for e in entries if e["written"]) == 2      # recorded before any file was touched
    first_before = {e["id"]: e["before"] for e in entries}
    monkeypatch.setattr(tc, "write_minimal", real)
    tc.retag(cfg, manifest)
    entries = json.loads(manifest.read_text())
    assert all(e["written"] for e in entries) and {e["id"]: e["before"] for e in entries} == first_before


def _fresh_navidrome(tmp_path, music, entries, path_key="path_before"):
    return _navidrome(tmp_path, music, [(str(i), str(Path(e.get(path_key) or e["path_before"]).relative_to(music)), e["after"]["title"],
                                         e["after"]["artist"] or "[Unknown Artist]", e["after"]["albumartist"] or e["after"]["artist"],
                                         e["after"]["album"] or "[Unknown Album]") for i, e in enumerate(entries)])


def test_move_crash_resumes(lib, tmp_path, monkeypatch):
    cfg, music, state = lib
    manifest = state / "manifest.json"
    tc.retag(cfg, manifest)
    nd = _fresh_navidrome(tmp_path, music, json.loads(manifest.read_text()))
    from beets.library import Item
    real_move, n = Item.move, []
    def flaky(self, *a, **k):
        n.append(1)
        if len(n) == 2:
            raise OSError("disk hiccup")
        return real_move(self, *a, **k)
    monkeypatch.setattr(Item, "move", flaky)
    with pytest.raises(OSError):
        tc.move(cfg, manifest, nd)
    assert sum(1 for e in json.loads(manifest.read_text()) if e.get("path_after")) == 1   # progress saved per move
    monkeypatch.setattr(Item, "move", real_move)
    nd.unlink()
    nd = _fresh_navidrome(tmp_path, music, json.loads(manifest.read_text()), path_key="path_after")   # Navidrome saw the first move
    tc.move(cfg, manifest, nd)
    assert all(e.get("path_after") for e in json.loads(manifest.read_text()))


def test_scan_guard_needs_equal_values_not_substrings():
    after = {"title": "Rock With You", "artist": "Cameo", "albumartist": "Cameo", "album": "X"}
    assert not tc._scanned(("Rock With You", "Cameo feat. Larry Blackmon", "Cameo feat. Larry Blackmon", "X"), after)
    assert tc._scanned(("Rock With You", "Cameo", "Cameo", "X"), after)
    assert tc._scanned(("Rock With You", "Cameo", "Cameo", "[Unknown Album]"), dict(after, album=""))


def test_plan_lists_untouched_songs_whose_path_would_change(lib, tmp_path):
    cfg, music, state = lib
    from beets.library import Item
    stray = music / "Somewhere Else/odd name.mp3"; _audio(stray)
    m = MediaFile(str(stray)); m.title, m.artist, m.albumartist, m.album, m.year, m.track = "Odd", "Zed", "Zed", "Z", 2001, 3; m.save()
    bl = tc.open_lib(cfg); bl.add_album([Item.from_path(str(stray))]); bl._close()
    report = tmp_path / "r.md"
    p = tc.plan(cfg, report)
    assert p.drift == ["Somewhere Else/odd name.mp3 → Zed/Z (2001)/03 - Odd.mp3"]
    assert "## Untouched songs beets would re-file" in report.read_text()


def test_restore_puts_back_the_original_and_applies_only_the_intended_change(tmp_path):
    original, current = tmp_path / "orig/x.flac", tmp_path / "music/A/x.flac"
    _audio(original); t = FLAC(original); t["TITLE"] = "Song - Remastered"; t["GENRE"] = ["Jazz", "Latin"]; t.save()
    current.parent.mkdir(parents=True); current.write_bytes(original.read_bytes())
    t = FLAC(current); t["TITLE"] = "Song"; t["GENRE"] = ["Jazz"]; t["DISCTOTAL"] = "0"; t.save()     # what beets left
    entry = {"id": 1, "path_before": str(current), "path_after": str(current),
             "before": {"title": "Song - Remastered", "artist": "", "albumartist": "", "album": "", "comp": False, "comments": ""},
             "after": {"title": "Song", "artist": "", "albumartist": "", "album": "", "comp": False, "comments": "version: Remastered"}}
    trash = tmp_path / "trash"
    tc.restore(entry, original, music_root=tmp_path / "music", trash_root=trash)
    t = FLAC(current)
    assert t["TITLE"] == ["Song"] and t["GENRE"] == ["Jazz", "Latin"] and "DISCTOTAL" not in t and t["COMMENT"] == ["version: Remastered"]
    assert FLAC(trash / "A/x.flac")["GENRE"] == ["Jazz"]                          # the damaged copy is kept, not deleted
    assert entry["restored_from"] == str(original)
    assert FLAC(original)["TITLE"] == ["Song - Remastered"]                       # the original is never written


def test_refresh_library_map_follows_the_moves(tmp_path):
    csv_path = tmp_path / "map.csv"
    csv_path.write_text("original_path,folder,ext,size,audio_md5,new_path,other_copies\n"
                        "o/a.mp3,f,mp3,1,m1,Compilations/x/a.mp3,Compilations/y/a.mp3\n"
                        "o/b.mp3,f,mp3,1,m2,Keep/b.mp3,\n", encoding="utf-8")
    manifest = [{"path_before": "/srv/music/Compilations/x/a.mp3", "path_after": "/srv/music/Art/Alb/a.mp3"},
                {"path_before": "/srv/music/Compilations/y/a.mp3", "path_after": "/srv/music/Art/Alb (2)/a.mp3"}]
    assert tc.refresh_library_map(csv_path, manifest, music_root="/srv/music") == 1        # rows changed
    import csv as _csv
    rows = list(_csv.DictReader(csv_path.open(encoding="utf-8")))
    assert rows[0]["new_path"] == "Art/Alb/a.mp3" and rows[0]["other_copies"] == "Art/Alb (2)/a.mp3" and rows[1]["new_path"] == "Keep/b.mp3"
