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
                 "version: Remastered 1999", "| junk, compilation |", "| split, compilation |", "| prefix, compilation |"):
        assert want in text, want
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
    fresh = _navidrome(tmp_path, music, [(str(i), str(Path(e["path_before"]).relative_to(music)), e["after"]["title"], e["after"]["artist"],
                                          e["after"]["albumartist"], e["after"]["album"]) for i, e in enumerate(entries)])
    moved = tc.move(cfg, manifest, fresh)
    assert len(moved) == 4
    assert (music / "Pepe Link/Balearic Biscuits, Vol. 4 (2024)/16 - Vem Menina.mp3").is_file()
    assert (music / "September/Singles/Ostavi Trag.mp3").is_file()
    assert (music / "Prince/Graffiti (1987)/01 - Baby's Gone.flac").is_file()
    assert not (music / PSC).exists()                                       # emptied folder pruned
    assert all(e.get("path_after") for e in json.loads(manifest.read_text()))
    assert tc.move(cfg, manifest, fresh) == []                              # already moved: no-op
