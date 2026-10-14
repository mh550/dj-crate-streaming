import json
from pathlib import Path

from sourcing import playlist_sources as ps
from tests.helpers import FIXTURES


def test_spotify_rows_keep_order_duration_and_id():
    entity = json.loads((FIXTURES / "spotify_embed_tea-tent-2.json").read_text())
    rows = ps.rows_from_spotify(entity)
    assert len(rows) == 27 and [r.position for r in rows] == list(range(1, 28))
    r = rows[0]
    assert r.title == "Piano Joint (This Kind Of Love)" and r.artist == "Michael Kiwanuka"
    assert r.duration_s == 232 and r.spotify_id == "1I44zWi6wdcWcnd2B68Hio"


def test_spotify_subtitle_nbsp_is_normalised():
    entity = json.loads((FIXTURES / "spotify_embed_secondset.json").read_text())
    r = ps.rows_from_spotify(entity)[0]
    assert r.artist == "Roy Ayers, Dee Dee Bridgewater, Wayne Garfield"     # fixture has ",\xa0"


def test_report_rows_cover_success_skipped_and_errors():
    text = (FIXTURES / "spotiflac_report_nothin_to_it.head30.txt").read_text()
    rows = ps.rows_from_report(text)
    assert [r.position for r in rows] == [1, 2, 3, 4, 5, 6, 7]
    assert rows[0].title == "FIND YOUR WINGS (feat. Roy Ayers, Sydney Bennett & Kali Uchis)"
    assert rows[0].artist == "Tyler, The Creator; Roy Ayers; Syd; Kali Uchis" and rows[0].note == "success"
    err = rows[6]
    assert err.title == "World's Famous" and err.artist == "DJ KOCO aka SHIMOKITA; 45trio"
    assert err.album == "World's Famous" and err.spotify_id == "2sdU23lpqA9LamR7TWSlI7"
    assert err.note.startswith("error: This is normal") and err.duration_s is None


def test_report_title_with_dashes_splits_on_the_last_one():
    rows = ps.rows_from_report("Download Report - x\n---\n\n[SUCCESS] Catendé - Live - Vinícius de Moraes; Maria Creuza; Toquinho\n[SKIPPED] One - Three Dog Night\n")
    assert rows[0].title == "Catendé - Live" and rows[0].artist == "Vinícius de Moraes; Maria Creuza; Toquinho"
    assert rows[1].title == "One" and rows[1].artist == "Three Dog Night" and rows[1].note == "skipped"


def test_perfect_songs_head_parses_27_successes():
    rows = ps.rows_from_report((FIXTURES / "spotiflac_report_perfect_songs.head30.txt").read_text())
    assert len(rows) == 27 and rows[24].artist == "Earth, Wind & Fire" and rows[24].title == "After the Love Has Gone"


EXPORTIFY = (
    "Track URI,Track Name,Album Name,Artist Name(s),Release Date,Duration (ms),Popularity,Explicit,Added By,Added At,Genres,Record Label,Danceability\n"
    "spotify:track:4qZ1OgsTZMAgZA776w3USt,The Weasil,Fancy Free,Donald Byrd,1970,540626,40,false,spotify:user:x,2024-01-01T00:00:00Z,jazz,Blue Note,0.5\n"
    "spotify:track:abc,After the Love Has Gone,I Am,\"Earth, Wind & Fire\",1979,278000,60,false,spotify:user:x,2024-01-01T00:00:00Z,soul,Columbia,0.6\n"
)
SOCKSEEK = "Artist,Title,Length\nChic,Good Times,501\n"


def test_csv_exportify_and_sockseek_shapes():
    rows = ps.rows_from_csv(EXPORTIFY)
    assert rows[0] == ps.Row(1, "The Weasil", "Donald Byrd", 541, "4qZ1OgsTZMAgZA776w3USt", "Fancy Free")
    assert rows[1].artist == "Earth, Wind & Fire" and rows[1].duration_s == 278
    assert ps.rows_from_csv(SOCKSEEK) == [ps.Row(1, "Good Times", "Chic", 501)]


def test_concat_renumbers_positions():
    a = [ps.Row(1, "a", "x", None), ps.Row(2, "b", "x", None)]
    b = [ps.Row(1, "c", "x", None)]
    assert [r.position for r in ps.concat([a, b])] == [1, 2, 3] and ps.concat([a, b])[2].title == "c"


def test_load_dispatches_and_names(tmp_path):
    rep = tmp_path / "nothin to it.txt"
    rep.write_text((FIXTURES / "spotiflac_report_nothin_to_it.head30.txt").read_text())
    name, rows = ps.load(str(rep))
    assert name == "nothin to it" and len(rows) == 7
    csv_path = tmp_path / "secondset.csv"; csv_path.write_text(SOCKSEEK)
    assert ps.load(str(csv_path)) == ("secondset", [ps.Row(1, "Good Times", "Chic", 501)])
    entity = json.loads((FIXTURES / "spotify_embed_tea-tent-1.json").read_text())
    name, rows = ps.load("https://open.spotify.com/playlist/0wPBj1mjvAJcmr6zdaz228", fetch=lambda url: entity)
    assert name == "Tea tent" and len(rows) == 99 and rows[0].title == "The Weasil"


def test_lead_artist_resolves_commas_via_track_embed_and_semicolons_locally():
    assert ps.lead_artist(ps.Row(1, "t", "Donald Byrd", None)) == "Donald Byrd"
    assert ps.lead_artist(ps.Row(1, "t", "Tyler, The Creator; Roy Ayers", None)) == "Tyler, The Creator"   # report: ';' is the separator
    calls = []
    def resolve(sid): calls.append(sid); return "Earth, Wind & Fire"
    assert ps.lead_artist(ps.Row(1, "t", "Earth, Wind & Fire", 278, spotify_id="abc"), resolve=resolve) == "Earth, Wind & Fire"
    assert calls == ["abc"]
    assert ps.lead_artist(ps.Row(1, "t", "Roy Ayers, Dee Dee Bridgewater", 1, spotify_id="z"), resolve=lambda s: None) == "Roy Ayers"   # lookup failed → first segment


def test_report_rows_keep_comma_band_names_whole():
    # Live run 2026-10-14: "[SUCCESS] After the Love Has Gone - Earth, Wind & Fire" produced lead artist "Earth".
    # Report rows separate artists with ';', so a comma there is part of one name.
    row = ps.rows_from_report("[SUCCESS] After the Love Has Gone - Earth, Wind & Fire\n")[0]
    assert ps.lead_artist(row, resolve=lambda sid: (_ for _ in ()).throw(AssertionError("no lookup for report rows"))) == "Earth, Wind & Fire"


def test_report_error_entry_strips_nested_album_parenthetical():
    # Live run 2026-10-14: nested parens in the album were not stripped, so the artist became
    # "Digable Planets (Reachin' (A New Refutation Of Time And Space))".
    text = ("1. Where I'm From - Digable Planets (Reachin' (A New Refutation Of Time And Space))\n"
            "   Error: x\n   ID: 2GJMHPV3vqakgxdZXsGyfd\n"
            "2. Free - Deniece Williams (This Is Niecy (Expanded Edition))\n   Error: y\n   ID: 1eY5skETdGlVupvvx1X2V0\n")
    rows = ps.rows_from_report(text)
    assert (rows[0].artist, rows[0].album) == ("Digable Planets", "Reachin' (A New Refutation Of Time And Space)")
    assert (rows[1].artist, rows[1].title, rows[1].album) == ("Deniece Williams", "Free", "This Is Niecy (Expanded Edition)")


def test_csv_with_utf8_bom_still_parses(tmp_path):
    # Excel / Windows Exportify exports start with a BOM; the first header must still be recognised.
    f = tmp_path / "x.csv"; f.write_text("\ufeff" + EXPORTIFY, encoding="utf-8")
    name, rows = ps.load(str(f))
    assert rows[0].spotify_id == "4qZ1OgsTZMAgZA776w3USt"
    f2 = tmp_path / "y.csv"; f2.write_bytes(("\ufeff" + SOCKSEEK).encode("utf-8"))
    assert ps.load(str(f2))[1] == [ps.Row(1, "Good Times", "Chic", 501)]


def test_track_lead_swallows_network_errors(monkeypatch):
    import urllib.error
    def boom(path): raise urllib.error.URLError("no route")
    monkeypatch.setattr(ps, "_next_data", boom)
    assert ps._track_lead("abc") is None
