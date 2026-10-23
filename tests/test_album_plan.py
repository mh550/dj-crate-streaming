"""S2-04: the album-first plan (sourcing/album.py) on synthetic responses in the shape of
fixtures/search_responses.sample.json (a copied response dict; only existing keys are changed)."""
import json
from pathlib import Path

import pytest

from sourcing import album
from sourcing.album import AlbumPlan, FolderPick, plan_album

FIX = json.loads((Path(__file__).parent.parent / "fixtures" / "search_responses.sample.json").read_text())

ALBUM = "I'm Still in Love With You"
DIR = "@@music\\Al Green\\I'm Still in Love With You (1972)"
TITLES = ["I'm Still in Love With You", "I'm Glad You're Mine", "Love and Happiness", "What Is This Feeling",
          "Simply Beautiful", "Oh, Pretty Woman", "For the Good Times", "Look What You Done for Me",
          "One of These Good Old Days"]
LENGTHS = [193, 178, 302, 236, 223, 225, 383, 183, 213]


def folder(peer, dirpath, titles, lengths, fmt="flac", bitrate=900, free=True, speed=3_500_000):
    """One response from `peer` whose files are `<dirpath>\\Al Green - I'm Still in Love With You - NN - <title>.<fmt>`,
    NN the title's track number on the album (the ext-74 shape)."""
    r = json.loads(json.dumps(FIX[0]))
    r.update(username=peer, hasFreeUploadSlot=free, uploadSpeed=speed)
    name = lambda t: f"{dirpath}\\Al Green - {ALBUM} - {TITLES.index(t) + 1:02d} - {t}.{fmt}"
    r["files"] = [dict(FIX[0]["files"][0], filename=name(t), extension=fmt, bitRate=bitrate, length=n, size=bitrate * 1000 // 8 * n)
                  for t, n in zip(titles, lengths)]
    return r


def rows(n=9, duration=True):
    """The request's rows, as wanted_row dicts carry them."""
    return [{"id": f"ext-{i + 1}", "artist": "Al Green", "title": TITLES[i], "album": ALBUM, "year": 1972,
             "duration": LENGTHS[i] if duration else None, "track_no": i + 1} for i in range(n)]


def track_nos(pairs):
    return sorted(row["track_no"] for row, _ in pairs)


def test_one_folder_with_the_whole_album_is_the_primary_and_nothing_else():
    plan = plan_album([folder("alpha", DIR, TITLES, LENGTHS)], rows())
    assert isinstance(plan, AlbumPlan) and isinstance(plan.primary, FolderPick)
    assert (plan.primary.username, plan.primary.directory) == ("alpha", DIR)
    assert track_nos(plan.primary.rows) == list(range(1, 10))
    assert plan.secondary is None and plan.per_track == [] and plan.alternates == []
    for row, cand in plan.primary.rows:            # each row gets its own track, the title track included (S1-01)
        assert cand.basename.endswith(f" - {row['track_no']:02d} - {row['title']}.flac"), (row, cand.basename)
    assert plan.primary.score == pytest.approx(sum(c.score for _, c in plan.primary.rows))
    assert [r["track_no"] for r, _ in plan.assignments()] == list(range(1, 10))


def test_seven_of_nine_plus_a_folder_with_the_other_two():
    plan = plan_album([folder("bravo", DIR, TITLES[7:], LENGTHS[7:]),
                       folder("alpha", DIR, TITLES[:7], LENGTHS[:7])], rows())
    assert plan.primary.username == "alpha" and track_nos(plan.primary.rows) == list(range(1, 8))
    assert plan.secondary.username == "bravo" and track_nos(plan.secondary.rows) == [8, 9]
    assert plan.per_track == [] and plan.alternates == []
    assert [r["track_no"] for r, _ in plan.assignments()] == list(range(1, 10))   # primary rows, then secondary


def test_two_same_named_folders_from_two_peers_the_better_one_is_primary_the_other_the_first_alternate():
    plan = plan_album([folder("alpha", DIR, TITLES, LENGTHS, bitrate=900),
                       folder("bravo", DIR, TITLES, LENGTHS, bitrate=1000)], rows())
    assert plan.primary.username == "bravo" and len(plan.primary.rows) == 9
    assert plan.secondary is None and plan.per_track == []
    assert [(f.username, f.directory) for f in plan.alternates] == [("alpha", DIR)]


def test_a_better_score_beats_a_higher_bitrate():
    plan = plan_album([folder("alpha", DIR, TITLES, LENGTHS, bitrate=1000, free=False),
                       folder("bravo", DIR, TITLES, LENGTHS, bitrate=900)], rows())
    assert plan.primary.username == "bravo" and plan.primary.score > plan.alternates[0].score


def test_all_rows_win_outright_over_a_better_scored_partial_folder():
    plan = plan_album([folder("fast", DIR, TITLES[:8], LENGTHS[:8], speed=9_000_000),
                       folder("slow", DIR, TITLES, LENGTHS, free=False, speed=100_000)], rows())
    assert plan.primary.username == "slow" and len(plan.primary.rows) == 9
    assert plan.secondary is None and [f.username for f in plan.alternates] == ["fast"]


@pytest.mark.parametrize("case", ["shared track", "listed lengths"])
def test_a_folder_of_another_release_loses_to_a_same_release_secondary(case):
    """C has the 2 missing tracks of another release (lengths 20 s off) and a better score (a fast peer with a free
    slot); D has them within 2 s. With shared track 7, the primary's own listing tells them apart; with only the
    two missing tracks, the MusicBrainz release's lengths do."""
    off = [n + 20 for n in LENGTHS]
    near = [n + 1 for n in LENGTHS]
    first = 6 if case == "shared track" else 7
    responses = [folder("alpha", DIR, TITLES[:7], LENGTHS[:7]),
                 folder("charlie", DIR + " [remaster]", TITLES[first:], off[first:], speed=9_000_000),
                 folder("delta", DIR, TITLES[first:], near[first:], free=False, speed=100_000)]
    listed = {i + 1: n for i, n in enumerate(LENGTHS)} if case == "listed lengths" else None
    plan = plan_album(responses, rows(), listed_lengths=listed)
    assert plan.primary.username == "alpha"
    assert plan.secondary.username == "delta" and track_nos(plan.secondary.rows) == [8, 9]
    assert [f.username for f in plan.alternates] == ["charlie"]
    assert plan.per_track == []
    charlie = plan.alternates[0]
    assert sum(c.score for r, c in charlie.rows if r["track_no"] > 7) > sum(c.score for _, c in plan.secondary.rows)


def test_another_release_is_still_the_secondary_when_it_is_the_only_one():
    plan = plan_album([folder("alpha", DIR, TITLES[:7], LENGTHS[:7]),
                       folder("charlie", DIR, TITLES[7:], [n + 20 for n in LENGTHS[7:]])], rows(),
                      listed_lengths={i + 1: n for i, n in enumerate(LENGTHS)})
    assert plan.secondary.username == "charlie" and plan.per_track == []


def test_more_missing_rows_beat_the_same_release():
    """The spec's order: the secondary covers the most rows the primary lacks; the same release only decides between
    folders covering as many."""
    plan = plan_album([folder("alpha", DIR, TITLES[:5], LENGTHS[:5]),
                       folder("same", DIR, TITLES[5:7], LENGTHS[5:7]),
                       folder("other", DIR, TITLES[5:], [n + 20 for n in LENGTHS[5:]])], rows(),
                      listed_lengths={i + 1: n for i, n in enumerate(LENGTHS)})
    assert plan.secondary.username == "other" and track_nos(plan.secondary.rows) == [6, 7, 8, 9]
    assert plan.per_track == [] and [f.username for f in plan.alternates] == ["same"]


def test_files_at_a_share_root_are_one_folder_and_slash_paths_group_too():
    r = folder("alpha", DIR, TITLES[:3], LENGTHS[:3])
    for f in r["files"]:
        f["filename"] = f["filename"].rsplit("\\", 1)[1]
    s = folder("bravo", DIR, TITLES[3:], LENGTHS[3:])
    for f in s["files"]:
        f["filename"] = f["filename"].replace("\\", "/")
    plan = plan_album([s, r], rows())
    assert (plan.primary.username, plan.primary.directory, len(plan.primary.rows)) == \
        ("bravo", DIR.replace("\\", "/"), 6)
    assert (plan.secondary.username, plan.secondary.directory, len(plan.secondary.rows)) == ("alpha", "", 3)


def test_a_folder_counts_its_own_files_not_the_peers_whole_response():
    """The scorer's "peer has N matching files (album?)" bonus reads fileCount: per folder, the folder's files."""
    a = folder("alpha", DIR, TITLES[:2], LENGTHS[:2])
    a["files"] += folder("alpha", "@@music\\Other\\Thing", TITLES[2:], LENGTHS[2:])["files"]
    plan = plan_album([a], rows(2))
    assert all(c.file_count == 2 and not any("album?" in x for x in c.reasons) for _, c in plan.primary.rows)


def test_full_ties_are_ordered_by_peer_and_directory_not_by_arrival():
    one = [folder("bravo", DIR, TITLES, LENGTHS), folder("alpha", DIR, TITLES, LENGTHS)]
    assert plan_album(one, rows()).primary.username == plan_album(one[::-1], rows()).primary.username == "alpha"


def test_the_same_row_dict_twice_is_not_lost():
    rs = rows(3)
    rs.append(rs[2])
    plan = plan_album([folder("alpha", DIR, TITLES[:3], LENGTHS[:3])], rs)
    assert len(plan.primary.rows) + len(plan.per_track) == 4


def test_another_format_family_loses_to_the_same_family():
    """An mp3 album's missing tracks come from another mp3 folder, not a flac one (which scores higher)."""
    plan = plan_album([folder("alpha", DIR, TITLES[:7], LENGTHS[:7], fmt="mp3", bitrate=320),
                       folder("flacs", DIR, TITLES[7:], LENGTHS[7:], speed=9_000_000),
                       folder("mp3s", DIR, TITLES[7:], LENGTHS[7:], fmt="mp3", bitrate=320, free=False)], rows())
    assert plan.primary.username == "alpha"
    assert plan.secondary.username == "mp3s" and [f.username for f in plan.alternates] == ["flacs"]
    assert plan.alternates[0].score > plan.secondary.score


def test_nine_peers_with_one_track_each_is_all_per_track():
    plan = plan_album([folder(f"peer{i}", DIR, [t], [n]) for i, (t, n) in enumerate(zip(TITLES, LENGTHS))], rows())
    assert plan.primary is None and plan.secondary is None and plan.alternates == []
    assert [r["track_no"] for r in plan.per_track] == list(range(1, 10))
    assert plan.assignments() == []


def test_a_folder_covering_one_missing_row_is_not_a_secondary():
    plan = plan_album([folder("alpha", DIR, TITLES[:8], LENGTHS[:8]),
                       folder("bravo", DIR, TITLES[8:], LENGTHS[8:])], rows())
    assert plan.primary.username == "alpha" and plan.secondary is None
    assert [r["track_no"] for r in plan.per_track] == [9]


def test_the_title_track_row_never_takes_track_09_and_a_title_track_folder_is_not_needed():
    """ext-74: the folder lacks track 01; the title-track row stays uncovered rather than taking another song."""
    plan = plan_album([folder("alpha", DIR, TITLES[1:], LENGTHS[1:])], rows())
    assert track_nos(plan.primary.rows) == list(range(2, 10))
    assert [r["track_no"] for r in plan.per_track] == [1]


def test_files_group_by_peer_and_directory():
    """One peer sharing the album twice (two directories) is two folders; one directory spread over two responses of
    the same peer is one."""
    a = folder("alpha", DIR, TITLES[:5], LENGTHS[:5])
    b = folder("alpha", DIR, TITLES[5:], LENGTHS[5:])
    plan = plan_album([a, b], rows())
    assert plan.primary.directory == DIR and len(plan.primary.rows) == 9
    plan = plan_album([folder("alpha", DIR, TITLES[:5], LENGTHS[:5]),
                       folder("alpha", DIR + " (2)", TITLES[5:], LENGTHS[5:])], rows())
    assert (len(plan.primary.rows), len(plan.secondary.rows)) == (5, 4)
    assert plan.primary.username == plan.secondary.username == "alpha"


def test_each_file_serves_at_most_one_row():
    """Two rows with the same title (a reprise): one file serves only one of them, the other goes per-track."""
    rs = rows(3) + [dict(rows(3)[2], id="ext-10", track_no=10)]
    plan = plan_album([folder("alpha", DIR, TITLES[:3], LENGTHS[:3])], rs)
    files = [c.filename for _, c in plan.primary.rows]
    assert len(files) == len(set(files)) == 3
    assert [r["id"] for r in plan.per_track] == ["ext-10"]


def test_a_rejected_file_covers_nothing():
    plan = plan_album([folder("alpha", DIR, TITLES, LENGTHS, fmt="ogg")], rows())
    assert plan.primary is None and len(plan.per_track) == 9


def test_no_responses_and_no_rows():
    assert plan_album([], rows(2)).per_track == rows(2)
    plan = plan_album([folder("alpha", DIR, TITLES, LENGTHS)], [])
    assert plan.primary is None and plan.per_track == [] and plan.alternates == []


def test_describe_names_folders_by_number_never_by_peer():
    plan = plan_album([folder("alpha_peer", DIR, TITLES[:7], LENGTHS[:7]),
                       folder("bravo_peer", DIR, TITLES[7:], LENGTHS[7:]),
                       folder("charlie_peer", DIR, TITLES[:3], LENGTHS[:3])], rows() + [
                           {"id": "ext-99", "artist": "Al Green", "title": "Hidden Track", "track_no": 10}])
    text = album.describe(plan)
    for peer in ("alpha_peer", "bravo_peer", "charlie_peer"):
        assert peer not in text
    assert "folder 1" in text and "7 of 10" in text
    assert "folder 2" in text and "2 of 10" in text
    assert "folder 3" in text                                  # the alternate
    assert f"Al Green - {ALBUM} - 08 - Look What You Done for Me.flac" in text
    assert "Hidden Track" in text and "per track" in text
    assert "alpha_peer" in album.describe(plan, peers=True)


def test_plan_album_does_not_change_its_inputs():
    responses, rs = [folder("alpha", DIR, TITLES, LENGTHS)], rows()
    before = json.dumps([responses, rs])
    plan_album(responses, rs)
    assert json.dumps([responses, rs]) == before
