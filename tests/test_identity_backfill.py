"""identity_backfill propose: read-only id proposals by confidence class, and the report Michael reviews.

Real tagged audio files (make_audio, then the same write_minimal that `apply` will use); MusicBrainz is a small fake
returning `Recording`s, or the real client with a fixture opener for the CLI/cache path. No network, no /srv.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path += ["/usr/share/beets", "/usr/lib/python3/dist-packages"]      # Debian's beets + mediafile

from scripts import identity_backfill as ib                             # noqa: E402
from sourcing.musicbrainz import MusicBrainzError, Recording            # noqa: E402
from tests.helpers import FIXTURES, make_audio                          # noqa: E402

R12 = "11111111-1111-1111-1111-111111111111"
R90 = "22222222-2222-2222-2222-222222222222"
RA = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
RB = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
R1 = "01010101-0101-0101-0101-010101010101"


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    """One 8 s FLAC; every test file is a copy of it, tagged afresh."""
    return make_audio(tmp_path_factory.mktemp("tpl") / "t.flac")


def tagged(music: Path, rel: str, template: Path, **tags) -> Path:
    from scripts.tag_cleanup import write_minimal
    p = music / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, p)
    write_minimal(p, tags)
    return p


class FakeMB:
    """`recording`/`isrc`/`search` from dicts; `fail` titles raise MusicBrainzError; every call is recorded."""

    def __init__(self, recordings=(), isrcs=None, searches=None, fail=(), merged=None):
        self.recs = {r.id: r for r in recordings} | (merged or {})     # merged: old id -> the surviving recording
        self.isrcs = isrcs or {}
        self.searches = searches or {}
        self.fail = set(fail)
        self.calls = []

    def recording(self, mbid):
        self.calls.append(("recording", mbid))
        return self.recs.get(mbid)

    def isrc(self, isrc):
        self.calls.append(("isrc", isrc))
        return list(self.isrcs.get(isrc, []))

    def search(self, artist, title, limit=100):
        self.calls.append(("search", artist, title))
        if title in self.fail:
            raise MusicBrainzError("MusicBrainz HTTP 400: recording")
        return list(self.searches.get(title, []))


def rec(id, title, length, artist="Kool & the Gang", works=(), isrcs=(), releases=(), disambiguation="", video=False):
    return Recording(id=id, title=title, length_s=length, artist=artist, work_ids=tuple(works), isrcs=tuple(isrcs),
                     releases=tuple(releases), disambiguation=disambiguation, video=video)


def facts(music, path):
    return ib.read_facts(music, path)


def test_read_facts_reads_the_tags_and_a_relative_path(tmp_path, template):
    music = tmp_path / "music"
    p = tagged(music, "Kool/Song.flac", template, artist="Kool & the Gang", title="Song", album="LP",
               mb_trackid=R1, isrc="USABC1234567")
    import mutagen
    m = mutagen.File(p)
    m["VERSION"] = "2003"
    m.save()
    f = facts(music, p)
    assert f.path == "Kool/Song.flac" and f.artist == "Kool & the Gang" and f.title == "Song" and f.album == "LP"
    assert f.mb_trackid == R1 and f.isrc == "USABC1234567" and f.mb_workid == "" and f.acoustid_id == ""
    assert f.version_tag == "2003"
    assert abs(f.length_s - 8.0) < 0.2 and f.size == p.stat().st_size and f.mtime_ns == p.stat().st_mtime_ns


def test_existing_id_is_confirmed_and_gains_only_the_work(tmp_path, template):
    music = tmp_path / "music"
    p = tagged(music, "a.flac", template, artist="Kool & the Gang", title="Song", mb_trackid=R1)
    mb = FakeMB([rec(R1, "Song", 8.0, works=["w1"])])
    pr = ib.classify(facts(music, p), mb)
    assert pr.cls == "confirmed" and pr.write == {"mb_workid": "w1"} and pr.accept is True
    assert pr.recording == R1


def test_existing_id_with_a_far_length_is_a_conflict(tmp_path, template):
    music = tmp_path / "music"
    p = tagged(music, "a.flac", template, artist="Kool & the Gang", title="Song", mb_trackid=R1)
    pr = ib.classify(facts(music, p), FakeMB([rec(R1, "Song", 20.0, works=["w1"])]))
    assert pr.cls == "conflict" and pr.write == {} and pr.accept is False
    assert "20" in pr.why and "8" in pr.why


def test_existing_id_without_a_length_or_with_another_label_is_never_confirmed(tmp_path, template):
    music = tmp_path / "music"
    p = tagged(music, "a.flac", template, artist="Kool & the Gang", title="Song (Original 12'' Version)",
               mb_trackid=R1)
    for r in (rec(R1, "Song (Original 12'' Version)", None, works=["w1"]),       # M6: no length is no proof
              rec(R1, "Song (Get Down in the 90's-mix)", 8.0, works=["w1"]),    # the file's id names another version
              None):
        pr = ib.classify(facts(music, p), FakeMB([r] if r else []))
        assert pr.cls == "conflict" and pr.write == {} and pr.accept is False, pr


def test_isrc_with_one_fitting_recording(tmp_path, template):
    music = tmp_path / "music"
    p = tagged(music, "a.flac", template, artist="Jamiroquai", title="Virtual Insanity", isrc="GBARL0601475")
    mb = FakeMB(isrcs={"GBARL0601475": [rec(RA, "Virtual Insanity", 8.0, artist="Jamiroquai", works=["w1"]),
                                        rec(RB, "Virtual Insanity", 30.0, artist="Jamiroquai", works=["w2"])]})
    pr = ib.classify(facts(music, p), mb)
    assert pr.cls == "isrc" and pr.write == {"mb_trackid": RA, "mb_workid": "w1"} and pr.accept is True
    assert not [c for c in mb.calls if c[0] == "search"]


def test_isrc_with_another_artist_or_label_does_not_fit(tmp_path, template):
    music = tmp_path / "music"
    p = tagged(music, "a.flac", template, artist="Jamiroquai", title="Virtual Insanity", isrc="GBARL0601475")
    mb = FakeMB(isrcs={"GBARL0601475": [rec(RA, "Virtual Insanity", 8.0, artist="Someone Else"),
                                        rec(RB, "Virtual Insanity (Radio Edit)", 8.0, artist="Jamiroquai"),
                                        rec(R1, "Virtual Insanity", 8.0, artist="")]})     # no credit: never fits
    pr = ib.classify(facts(music, p), mb)
    assert pr.cls == "none" and pr.write == {}
    assert ("search", "Jamiroquai", "Virtual Insanity") in mb.calls


def test_search_uses_the_base_title_and_the_label(tmp_path, template):
    music = tmp_path / "music"
    p = tagged(music, "a.flac", template, artist="Kool & the Gang feat. Someone",
               title="Get Down Saturday Night (Original 12'' Version)")
    mb = FakeMB([rec(R12, "Get Down Saturday Night (Original 12\" Version)", 8.0, works=["w1"])],
                searches={"Get Down Saturday Night": [
                    rec(R90, "Get Down Saturday Night (Get Down in the 90's-mix)", 8.0),
                    rec(R12, "Get Down Saturday Night (Original 12\" Version)", 8.0),
                    rec(RA, "Get Down Saturday Night", 8.0)]})
    pr = ib.classify(facts(music, p), mb)
    assert ("search", "Kool & the Gang", "Get Down Saturday Night") in mb.calls
    assert pr.cls == "search" and pr.recording == R12 and pr.accept is False
    assert pr.write == {"mb_trackid": R12, "mb_workid": "w1"}


def test_a_length_less_recording_never_fits(tmp_path, template):
    music = tmp_path / "music"
    p = tagged(music, "a.flac", template, artist="Kool & the Gang", title="Song")
    pr = ib.classify(facts(music, p), FakeMB(searches={"Song": [rec(RA, "Song", None)]}))
    assert pr.cls == "none" and pr.write == {}


def test_duplicate_recordings_are_ambiguous_unless_a_tie_break_decides(tmp_path, template):
    music = tmp_path / "music"
    p = tagged(music, "a.flac", template, artist="Double Exposure", title="My Love Is Free", album="Salsoul Classics")
    two = [rec(RA, "My Love Is Free", 8.0, artist="Double Exposure", releases=["Ten Percent"]),
           rec(RB, "My Love Is Free", 9.5, artist="Double Exposure", releases=["Disco Boogie"])]
    pr = ib.classify(facts(music, p), FakeMB(searches={"My Love Is Free": two}))
    assert pr.cls == "ambiguous" and sorted(pr.candidates) == [RA, RB] and pr.accept is False and pr.write == {}

    two[1] = rec(RB, "My Love Is Free", 9.5, artist="Double Exposure", releases=["Disco", "Salsoul Classics"])
    pr = ib.classify(facts(music, p), FakeMB(searches={"My Love Is Free": two}))
    assert pr.cls == "search" and pr.recording == RB and pr.write == {"mb_trackid": RB}


def test_the_files_isrc_breaks_a_search_tie(tmp_path, template):
    music = tmp_path / "music"
    p = tagged(music, "a.flac", template, artist="Double Exposure", title="My Love Is Free", isrc="USSA49310048")
    two = [rec(RA, "My Love Is Free", 8.0, artist="Double Exposure"),
           rec(RB, "My Love Is Free", 8.0, artist="Double Exposure", isrcs=["USSA49310048"])]
    pr = ib.classify(facts(music, p), FakeMB(searches={"My Love Is Free": two}))
    assert pr.cls == "search" and pr.recording == RB

    # the ISRC narrows to two, then the album decides among those two (not among all three)
    p = tagged(music, "b.flac", template, artist="Double Exposure", title="My Love Is Free", isrc="USSA49310048",
               album="Salsoul Classics")
    three = [rec(RA, "My Love Is Free", 8.0, artist="Double Exposure", isrcs=["USSA49310048"], releases=["Other"]),
             rec(RB, "My Love Is Free", 8.0, artist="Double Exposure", isrcs=["USSA49310048"],
                 releases=["Salsoul Classics"]),
             rec(R1, "My Love Is Free", 8.0, artist="Double Exposure", releases=["Salsoul Classics"])]
    pr = ib.classify(facts(music, p), FakeMB(searches={"My Love Is Free": three}))
    assert pr.cls == "search" and pr.recording == RB and "album" in pr.why


def test_acoustid_upgrades_an_ambiguous_row(tmp_path, template):
    music = tmp_path / "music"
    p = tagged(music, "a.flac", template, artist="Double Exposure", title="My Love Is Free")
    two = [rec(RA, "My Love Is Free", 8.0, artist="Double Exposure", works=["w1"]),
           rec(RB, "My Love Is Free", 8.0, artist="Double Exposure")]
    seen = []

    def lookup(path):
        seen.append(path)
        return [{"id": RB, "title": "My Love Is Free", "score": 0.9, "acoustid": "a-1"}]
    pr = ib.classify(facts(music, p), FakeMB(two, searches={"My Love Is Free": two}), lookup)
    assert seen == [p]
    assert pr.cls == "acoustid" and pr.recording == RB and pr.accept is True
    assert pr.write == {"mb_trackid": RB, "acoustid_id": "a-1"}


def test_acoustid_disagreeing_with_a_search_pick_is_a_conflict(tmp_path, template):
    music = tmp_path / "music"
    p = tagged(music, "a.flac", template, artist="Kool & the Gang", title="Song")
    mb = FakeMB(searches={"Song": [rec(RA, "Song", 8.0)]})
    pr = ib.classify(facts(music, p), mb, lambda path: [{"id": RB, "title": "Other", "score": 0.9, "acoustid": "a"}])
    assert pr.cls == "conflict" and pr.write == {} and pr.accept is False and RB in pr.why


def test_an_acoustid_failure_is_noted_and_changes_nothing(tmp_path, template):
    music = tmp_path / "music"
    p = tagged(music, "a.flac", template, artist="Kool & the Gang", title="Song")

    def boom(path):
        raise ValueError("fpcalc gave no fingerprint (exit 1)")
    pr = ib.classify(facts(music, p), FakeMB(searches={"Song": [rec(RA, "Song", 8.0)]}), boom)
    assert pr.cls == "search" and "AcoustID" in pr.why and "fpcalc" in pr.why


def test_one_failing_file_does_not_stop_the_run(tmp_path, template):
    music, out = tmp_path / "music", tmp_path / "out"
    tagged(music, "A/bad.flac", template, artist="Kool & the Gang", title="Bad")
    tagged(music, "B/good.flac", template, artist="Kool & the Gang", title="Good")
    mb = FakeMB(searches={"Good": [rec(RA, "Good", 8.0)]}, fail={"Bad"})
    props = {p.path: p for p in ib.propose(music, out, mb, log=lambda *a: None)}
    assert props["A/bad.flac"].cls == "error" and "MusicBrainzError" in props["A/bad.flac"].why
    assert props["A/bad.flac"].write == {}
    assert props["B/good.flac"].cls == "search"


def sha(root: Path) -> dict:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def test_propose_never_writes_a_library_file(tmp_path, template):
    music, out = tmp_path / "music", tmp_path / "out"
    tagged(music, "Kool/confirmed.flac", template, artist="Kool & the Gang", title="Song", mb_trackid=R1)
    tagged(music, "Kool/12.flac", template, artist="Kool & the Gang", title="Get Down Saturday Night (Original 12'' Version)")
    tagged(music, "Kool/12 copy.flac", template, artist="Kool & the Gang", title="Get Down Saturday Night (Original 12'' Version)")
    tagged(music, "Kool/lost.flac", template, artist="Kool & the Gang", title="Mary Jane (All Night Long)")
    tagged(music, "_playlists/x.flac", template, artist="Kool & the Gang", title="Not Walked")
    (music / "cover.jpg").write_bytes(b"\xff\xd8")
    before = sha(music)
    mb = FakeMB([rec(R1, "Song", 8.0, works=["w1"]), rec(R12, "Get Down Saturday Night (Original 12\" Version)", 8.0)],
                searches={"Get Down Saturday Night": [rec(R12, "Get Down Saturday Night (Original 12\" Version)", 8.0)]})
    logged = []
    props = ib.propose(music, out, mb, log=logged.append)
    assert sha(music) == before
    assert sorted(p.path for p in props) == ["Kool/12 copy.flac", "Kool/12.flac", "Kool/confirmed.flac", "Kool/lost.flac"]

    data = json.loads((out / "identity-proposal.json").read_text())
    assert data["counts"]["confirmed"] == 1 and data["counts"]["search"] == 2 and data["counts"]["none"] == 1
    assert data["music_root"] == str(music) and len(data["proposals"]) == 4
    row = next(r for r in data["proposals"] if r["path"] == "Kool/confirmed.flac")
    assert row["write"] == {"mb_workid": "w1"} and row["accept"] is True and row["skip"] is False
    assert row["size"] == (music / "Kool/confirmed.flac").stat().st_size and row["mtime_ns"] > 0

    report = (out / "identity-backfill-report.md").read_text()
    assert "Copies of one version" in report and "Version labels identity reads" in report
    assert "Kool/12 copy.flac" in report.split("Copies of one version")[1]
    labels = report.split("Version labels identity reads")[1]
    assert "Mary Jane (All Night Long)" in labels and "extended" in labels
    assert "apply --classes" in report and '"skip": true' in report
    assert any("4/4" in str(line) for line in logged)


def test_propose_logs_progress_and_honours_the_limit(tmp_path, template):
    music, out = tmp_path / "music", tmp_path / "out"
    for i in range(3):
        tagged(music, f"{i}.flac", template, artist="Kool & the Gang", title=f"Song {i}")
    logged = []
    props = ib.propose(music, out, FakeMB(), limit=2, log=logged.append)
    assert [p.path for p in props] == ["0.flac", "1.flac"] and all(p.cls == "none" for p in props)
    assert any("2/2" in line and "none=2" in line for line in logged)


def test_search_text_drops_lucene_operators_but_keeps_the_words():
    assert ib.search_text('Fade to Grey (Re-Edit) [12"] AC/DC: what?! ~ ^ * \\') == "Fade to Grey Re Edit 12 AC DC what"
    assert ib.search_text("Earth, Wind & Fire") == "Earth, Wind & Fire"


# ── the CLI path: real MusicBrainz client, fixture opener, cache on disk ──────────────────────────────────────

class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def fixture_opener(calls):
    """Answers from the live captures, with the lengths moved to 8 s (make_audio's files)."""
    isrc = fixture("musicbrainz_isrc.sample.json")
    isrc["recordings"][0]["length"] = 8000
    search = fixture("musicbrainz_search.sample.json")
    search["recordings"][4]["length"] = 8100                    # af09e6b5: the one that fits
    work = fixture("musicbrainz_recording_work.sample.json")

    def opener(req, timeout=None):
        calls.append(req.full_url)
        path = req.full_url.split("/ws/2/")[1].split("?")[0]
        if path.startswith("isrc/"):
            return FakeResponse(isrc)
        if path == "recording":
            return FakeResponse(search)
        return FakeResponse(dict(work, id=path.split("/")[1]))
    return opener


def test_rerun_reads_the_cache_not_the_network(tmp_path, template, monkeypatch):
    monkeypatch.delenv("ACOUSTID_KEY", raising=False)
    music, out = tmp_path / "music", tmp_path / "out"
    tagged(music, "J/vi.flac", template, artist="Jamiroquai", title="Virtual Insanity", isrc="GBARL0601475")
    tagged(music, "D/free.flac", template, artist="Double Exposure", title="My Love Is Free")
    tagged(music, "D/none.flac", template, artist="Nobody Known", title="Unfindable (Club Mix)")
    first = []
    argv = ["propose", "--music", str(music), "--out", str(out)]
    assert ib.main(argv, opener=fixture_opener(first), sleep=lambda s: None) == 0
    assert first and (out / "mb-cache.jsonl").exists()
    data1 = json.loads((out / "identity-proposal.json").read_text())
    by = {r["path"]: r for r in data1["proposals"]}
    assert by["J/vi.flac"]["cls"] == "isrc" and by["J/vi.flac"]["recording"].startswith("470a364c")
    assert by["J/vi.flac"]["write"]["mb_workid"] == "769c5c09-7179-310f-b092-77af2ed3462b"
    assert by["D/free.flac"]["cls"] == "search" and by["D/free.flac"]["recording"].startswith("af09e6b5")
    assert by["D/free.flac"]["write"]["mb_workid"] == "6815e26f-f6b2-30f0-962b-419d35fc2091"
    # the search fixture answers every query; nothing by "Nobody Known" in it fits
    assert by["D/none.flac"]["cls"] == "none"

    second = []
    assert ib.main(argv, opener=fixture_opener(second), sleep=lambda s: None) == 0
    assert second == []
    data2 = json.loads((out / "identity-proposal.json").read_text())
    assert data2["proposals"] == data1["proposals"] and data2["counts"] == data1["counts"]


def test_cli_uses_acoustid_only_with_a_key_and_never_prints_it(tmp_path, template, monkeypatch, capsys):
    music, out = tmp_path / "music", tmp_path / "out"
    tagged(music, "D/free.flac", template, artist="Double Exposure", title="My Love Is Free")
    made = []

    def make_lookup(key):
        made.append(key)

        def lookup(path):
            raise RuntimeError(f"AcoustID said no to client={key}")
        return lookup
    monkeypatch.setattr(ib.acoustid, "make_lookup", make_lookup)
    monkeypatch.setenv("ACOUSTID_KEY", "s3cret-key")
    assert ib.main(["propose", "--music", str(music), "--out", str(out)], opener=fixture_opener([]),
                   sleep=lambda s: None) == 0
    assert made == ["s3cret-key"]
    text = capsys.readouterr().out + (out / "identity-proposal.json").read_text() + \
        (out / "identity-backfill-report.md").read_text()
    assert "s3cret-key" not in text
    row = json.loads((out / "identity-proposal.json").read_text())["proposals"][0]
    assert row["cls"] == "search" and "AcoustID" in row["why"]


# ── review round (Task 8 review): AcoustID confidence, raw ids, disambiguation, lead artist, guards ────────────

def test_acoustid_counts_only_the_confident_top_result(tmp_path, template):
    music = tmp_path / "music"
    p = tagged(music, "s.flac", template, artist="Kool & the Gang", title="Good Times")
    mb = FakeMB([rec(RA, "Good Times", 8.0)], searches={"Good Times": [rec(RA, "Good Times", 8.0)]})
    # probe C: the pick is only in a weak result; the confident top result is another recording
    pr = ib.classify(facts(music, p), mb, lambda path: [
        {"id": RB, "title": "Good Times (Live)", "score": 0.97, "acoustid": "top"},
        {"id": RA, "title": "Good Times", "score": 0.21, "acoustid": "weak"}])
    assert pr.cls == "conflict" and pr.write == {} and pr.accept is False
    # the pick is in a confident result that is not the top one: still not "acoustid"
    pr = ib.classify(facts(music, p), mb, lambda path: [
        {"id": RB, "title": "x", "score": 0.97, "acoustid": "top"},
        {"id": RA, "title": "Good Times", "score": 0.9, "acoustid": "second"}])
    assert pr.cls == "conflict"
    # only weak results: no evidence either way
    pr = ib.classify(facts(music, p), mb, lambda path: [{"id": RB, "title": "x", "score": 0.5, "acoustid": "w"}])
    assert pr.cls == "search" and "AcoustID" in pr.why
    # the pick is in the confident top result
    pr = ib.classify(facts(music, p), mb, lambda path: [
        {"id": RB, "title": "x", "score": 0.95, "acoustid": "top"},
        {"id": RA, "title": "Good Times", "score": 0.95, "acoustid": "top"}])
    assert pr.cls == "acoustid" and pr.write == {"mb_trackid": RA, "acoustid_id": "top"}


def test_a_weak_acoustid_match_does_not_resolve_an_ambiguous_row(tmp_path, template):
    music = tmp_path / "music"
    p = tagged(music, "a.flac", template, artist="Kool & the Gang", title="I Want Your Love")
    two = [rec(RA, "I Want Your Love", 8.0), rec(RB, "I Want Your Love", 8.5)]
    pr = ib.classify(facts(music, p), FakeMB(two, searches={"I Want Your Love": two}),
                     lambda path: [{"id": RB, "title": "x", "score": 0.2, "acoustid": "w"}])   # probe D
    assert pr.cls == "ambiguous" and pr.write == {} and pr.accept is False


def _id3_txxx(p, desc, value):
    import mutagen.id3
    m = mutagen.id3.ID3(p)
    m.add(mutagen.id3.TXXX(encoding=3, desc=desc, text=[value]))
    m.save()


@pytest.fixture(scope="module")
def mp3_template(tmp_path_factory):
    return make_audio(tmp_path_factory.mktemp("tpl3") / "t.mp3")


def test_an_mp3_recording_id_in_txxx_is_the_files_id(tmp_path, mp3_template):
    music = tmp_path / "music"
    p = tagged(music, "A/txxx.mp3", mp3_template, artist="Kool & the Gang", title="Le Freak", isrc="USAT29900609")
    _id3_txxx(p, "MusicBrainz Track Id", R1)                 # probe A: Navidrome reads it, mediafile does not
    assert ib.read_ids(p)["mb_trackid"] == [R1]
    f = facts(music, p)
    assert f.mb_trackid == R1
    mb = FakeMB([rec(R1, "Le Freak", 8.0, works=["w1"])], isrcs={"USAT29900609": [rec(RA, "Le Freak", 8.0)]})
    pr = ib.classify(f, mb)
    assert pr.cls == "confirmed" and pr.recording == R1 and "mb_trackid" not in pr.write
    assert not [c for c in mb.calls if c[0] == "isrc"]


def test_ufid_and_txxx_that_disagree_are_a_conflict(tmp_path, mp3_template):
    music = tmp_path / "music"
    p = tagged(music, "A/both.mp3", mp3_template, artist="Kool & the Gang", title="Le Freak", mb_trackid=R1)
    _id3_txxx(p, "MusicBrainz Track Id", RA)
    assert sorted(ib.read_ids(p)["mb_trackid"]) == sorted([R1, RA])
    pr = ib.classify(facts(music, p), FakeMB([rec(R1, "Le Freak", 8.0), rec(RA, "Le Freak", 8.0)]))
    assert pr.cls == "conflict" and pr.write == {} and R1 in pr.why and RA in pr.why


def test_read_ids_sees_work_and_acoustid_ids_however_they_are_spelled(tmp_path, mp3_template, template):
    music = tmp_path / "music"
    p = tagged(music, "w.mp3", mp3_template, artist="A", title="T")
    _id3_txxx(p, "MUSICBRAINZ WORK ID", "w-1")
    _id3_txxx(p, "ACOUSTID ID", "a-1")
    assert ib.read_ids(p) == {"mb_trackid": [], "mb_workid": ["w-1"], "acoustid_id": ["a-1"]}
    q = tagged(music, "w.flac", template, artist="A", title="T", mb_workid="w-2")
    assert ib.read_ids(q) == {"mb_trackid": [], "mb_workid": ["w-2"], "acoustid_id": []}


def test_disambiguation_and_video_rule_recordings_out(tmp_path, template):
    music = tmp_path / "music"
    plain = tagged(music, "plain.flac", template, artist="Kool & the Gang", title="Song")
    explicit = tagged(music, "explicit.flac", template, artist="Kool & the Gang", title="Song (Explicit)")
    clean_and_explicit = [rec(RA, "Song", 8.0, disambiguation="clean"), rec(RB, "Song", 8.0, disambiguation="explicit")]
    # a plain file fits neither: MusicBrainz names the version only in the disambiguation
    pr = ib.classify(facts(music, plain), FakeMB(searches={"Song": clean_and_explicit}))
    assert pr.cls == "none" and pr.write == {}
    # "Song (Explicit)" never takes the clean recording
    recs = [rec(RA, "Song (Explicit)", 8.0, disambiguation="clean"), rec(RB, "Song (Explicit)", 8.0, disambiguation="explicit")]
    pr = ib.classify(facts(music, explicit), FakeMB(recs, searches={"Song": recs}))
    assert pr.cls == "search" and pr.recording == RB
    # a disambiguation that is not a label is no obstacle; a video never fits
    pr = ib.classify(facts(music, plain), FakeMB(searches={"Song": [rec(RA, "Song", 8.0, disambiguation="US disco band"),
                                                                    rec(RB, "Song", 8.0, video=True)]}))
    assert pr.cls == "search" and pr.recording == RA


def test_confirm_checks_the_lead_artist(tmp_path, template):
    music = tmp_path / "music"
    p = tagged(music, "k.flac", template, artist="Chic", title="Le Freak", mb_trackid=RA)
    pr = ib.classify(facts(music, p), FakeMB([rec(RA, "Le Freak", 8.0, artist="Someone Else", works=["w9"])]))
    assert pr.cls == "conflict" and pr.write == {} and "Someone Else" in pr.why          # probe K
    pr = ib.classify(facts(music, p), FakeMB([rec(RA, "Le Freak", 8.0, artist="Chic feat. Nile Rodgers", works=["w9"])]))
    assert pr.cls == "confirmed" and pr.write == {"mb_workid": "w9"}


def test_the_lead_artist_must_be_equal_and_a_near_miss_is_listed_for_review(tmp_path, template):
    music = tmp_path / "music"
    g = tagged(music, "g.flac", template, artist="The Gang", title="Celebration", isrc="USPR37900001")
    pr = ib.classify(facts(music, g), FakeMB(isrcs={"USPR37900001": [rec(RA, "Celebration", 8.0)]}))   # probe E
    assert pr.cls == "none" and pr.write == {} and pr.accept is False
    assert pr.candidates == [RA] and "lead artist" in pr.why and "Kool & the Gang" in pr.why
    n = tagged(music, "n.flac", template, artist="Nile Rodgers", title="Le Freak", isrc="USAT29900610")
    pr = ib.classify(facts(music, n), FakeMB(isrcs={"USAT29900610": [rec(RA, "Le Freak", 8.0, artist="Chic feat. Nile Rodgers")]}))
    assert pr.cls == "none" and pr.write == {}


def test_a_merged_recording_id_is_followed(tmp_path, template):
    music = tmp_path / "music"
    p = tagged(music, "m.flac", template, artist="Kool & the Gang", title="Song")
    mb = FakeMB(searches={"Song": [rec(RA, "Song", 8.0)]}, merged={RA: rec(RB, "Song", 8.0, works=["w1"])})
    pr = ib.classify(facts(music, p), mb)
    assert pr.cls == "search" and pr.recording == RB and pr.write == {"mb_trackid": RB, "mb_workid": "w1"}
    assert "merged" in pr.why and RA in pr.why


def test_out_inside_the_library_is_refused(tmp_path, template, capsys):
    music = tmp_path / "music"
    tagged(music, "a.flac", template, artist="Kool & the Gang", title="Song")
    with pytest.raises(ValueError):
        ib.propose(music, music / "identity", FakeMB(), log=lambda s: None)
    assert ib.main(["propose", "--music", str(music), "--out", str(music / "identity")],
                   opener=lambda *a, **k: pytest.fail("no request"), sleep=lambda s: None) == 2
    assert not (music / "identity").exists()


def test_rows_carry_the_files_tags_and_a_vanished_file_is_an_error(tmp_path, template, monkeypatch):
    music, out = tmp_path / "music", tmp_path / "out"
    p = tagged(music, "a.flac", template, artist="Kool & the Gang", title="Song (Club Mix)", album="LP",
               isrc="USABC1234567")
    real = ib.audio_files
    monkeypatch.setattr(ib, "audio_files", lambda root: real(root) + [root / "gone.flac"])
    props = {x.path: x for x in ib.propose(music, out, FakeMB(), log=lambda s: None)}
    assert props["gone.flac"].cls == "error" and "FileNotFoundError" in props["gone.flac"].why
    row = next(r for r in json.loads((out / "identity-proposal.json").read_text())["proposals"] if r["path"] == "a.flac")
    assert row["file"]["artist"] == "Kool & the Gang" and row["file"]["title"] == "Song (Club Mix)"
    assert row["file"]["isrc"] == "USABC1234567" and row["file"]["version_tag"] == ""
    assert abs(row["file"]["length_s"] - 8.0) < 0.2 and row["file"]["mb_trackid"] == ""


def test_the_report_reads_on_a_phone(tmp_path, template):
    music, out = tmp_path / "music", tmp_path / "out"
    tagged(music, "D/free.flac", template, artist="Double Exposure", title="My Love Is Free")
    tagged(music, "K/song.flac", template, artist="Kool & the Gang", title="Song")
    two = [rec(RA, "My Love Is Free", 8.0, artist="Double Exposure", releases=["Ten Percent", "Later"]),
           rec(RB, "My Love Is Free", 9.0, artist="Double Exposure", releases=["Salsoul Jam 2000"],
               disambiguation="US disco band session")]
    ib.propose(music, out, FakeMB(two, searches={"My Love Is Free": two, "Song": [rec(R1, "Song", 8.0)]}),
               log=lambda s: None)
    report = (out / "identity-backfill-report.md").read_text()
    tables = [ln for ln in report.splitlines() if ln.startswith("|---")]
    assert len(tables) == 1                                   # only the counts table; rows are bullet blocks
    assert '"choose": "<mbid>"' in report
    amb = report.split("## ambiguous")[1].split("\n## ")[0]
    assert "Double Exposure – My Love Is Free" in amb and "D/free.flac" in amb
    assert "0:08" in amb and "0:09" in amb and "Ten Percent" in amb and "Salsoul Jam 2000" in amb
    assert "US disco band session" in amb
    row = json.loads((out / "identity-proposal.json").read_text())["proposals"][0]
    assert row["cls"] == "ambiguous" and sorted(row["candidates"]) == [RA, RB]
