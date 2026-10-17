"""scripts/duplicate_report: same-recording groups, best copy first; different versions are not duplicates."""
from scripts.duplicate_report import duplicate_groups, keep_rank, other_version_groups


def row(id, title, path, suffix, kbps, dur, artist="Chic"):
    return dict(id=id, artist=artist, title=title, album="A", path=path, suffix=suffix, bit_rate=kbps, duration=dur,
                size=1000, mbz_recording_id="")


def test_flac_beats_mp3_and_the_properly_filed_lossless_wins_a_tie():
    rows = [row("a", "Good Times", "Chic/Risque/03 - Good Times.mp3", "mp3", 320, 501),
            row("b", "Good Times", "Compilations/X/03 - Good Times.flac", "flac", 938, 501),
            row("c", "Good Times", "Chic/Risque/03 - Good Times.flac", "flac", 934, 502)]
    [g] = duplicate_groups(rows)
    assert [r["id"] for r in g] == ["c", "b", "a"]


def test_a_12_inch_is_another_version_not_a_duplicate():
    rows = [row("a", "Good Times", "a.flac", "flac", 900, 230),
            row("b", "Good Times (12\" Version)", "b.flac", "flac", 900, 501)]
    assert duplicate_groups(rows) == []
    assert len(other_version_groups(rows, set())) == 1


def test_lossy_orders_by_bit_rate():
    lo, hi = row("a", "T", "x.mp3", "mp3", 128, 200), row("b", "T", "y.mp3", "mp3", 320, 200)
    assert keep_rank(hi) < keep_rank(lo)
