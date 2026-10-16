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


# ── apply / revert (Task 9): the one path that writes library tags ────────────────────────────────────────────
#
# Rows are built from the files' own facts (what `propose` records), written as a proposal JSON. Every check that
# matters reads the files independently with mutagen (`dump`), not through the code under test.

W1 = "33333333-3333-3333-3333-333333333333"
A1 = "44444444-4444-4444-4444-444444444444"
OTHER = "55555555-5555-5555-5555-555555555555"


def dump(p: Path) -> list:
    """Every tag key and value in the file, as mutagen sees it (ID3 frames by HashKey, Vorbis pairs)."""
    import mutagen
    import mutagen.id3
    tags = mutagen.File(str(p)).tags
    if isinstance(tags, mutagen.id3.ID3):
        return sorted((k, repr(fr)) for k, fr in tags.items())
    return sorted((k.lower(), repr(v)) for k, v in tags.items())


def row_for(music: Path, p: Path, cls="isrc", write=None, **extra) -> dict:
    """A proposal row for p as `propose` would record it now."""
    f = ib.read_facts(music, p)
    pr = ib.Proposal(path=f.path, cls=cls, write=dict(write if write is not None else {"mb_trackid": R1}),
                     accept=cls in ib.ACCEPT, size=f.size, mtime_ns=f.mtime_ns, file=f.tags())
    return {**ib.asdict(pr), **extra}


def proposal_file(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "out" / "identity-proposal.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"created": "x", "music_root": "m", "proposals": rows}))
    return path


def apply(tmp_path, music, rows, **kw):
    kw.setdefault("log", tmp_path / "out" / "apply.jsonl")
    return ib.apply(proposal_file(tmp_path, rows), music, **kw)


def rich(music, rel, tpl, **tags):
    """A file with the fields beets damaged in M2: two GENREs, an ISRC, album; the id fields empty."""
    return tagged(music, rel, tpl, artist="Kool & the Gang", title="Le Freak", album="C'est Chic",
                  genres=["Disco", "Funk"], isrc="USAT29900609", **tags)


def navidrome(tmp_path, music, rels):
    """navidrome.db (the export test's schema + mbz_recording_id), a playlist of the files, and its .m3u8 export."""
    import sqlite3
    from scripts import export_playlists as ep
    from tests.test_export_playlists import SCHEMA
    db = tmp_path / "navidrome.db"
    con = sqlite3.connect(db)
    con.executescript(SCHEMA + "ALTER TABLE media_file ADD COLUMN mbz_recording_id varchar(255) default '';")
    con.executemany("insert into media_file(id,path,title,artist,duration) values(?,?,?,?,?)",
                    [(f"id{i}", rel, "Le Freak", "Kool & the Gang", 8.0) for i, rel in enumerate(rels)])
    con.execute("insert into playlist(id,name) values('p1','set')")
    con.executemany("insert into playlist_tracks(id,playlist_id,media_file_id) values(?,?,?)",
                    [(i, "p1", f"id{i}") for i in range(len(rels))])
    con.commit()
    con.close()
    ep.export(db, music, music / "_playlists")
    return db


class FakeNavidrome:
    """start_scan reads each file's recording id with mediafile, as Navidrome would; `new_ids` re-keys rows."""

    def __init__(self, db, music, new_ids=None, scanning=False):
        self.db, self.music, self.new_ids, self.scanning, self.scans = db, music, new_ids or {}, scanning, 0

    def start_scan(self):
        import sqlite3
        from mediafile import MediaFile
        self.scans += 1
        con = sqlite3.connect(self.db)
        for mid, path in con.execute("select id, path from media_file").fetchall():
            con.execute("update media_file set mbz_recording_id=? where id=?",
                        (MediaFile(str(self.music / path)).mb_trackid or "", mid))
            if path in self.new_ids:
                con.execute("update media_file set id=? where id=?", (self.new_ids[path], mid))
        con.commit()
        con.close()
        return {"scanning": True}

    def scan_status(self):
        return {"scanning": self.scanning}


def test_apply_writes_only_the_id_fields(tmp_path, template, mp3_template):
    music = tmp_path / "music"
    fl = rich(music, "K/a.flac", template)
    mp = rich(music, "K/b.mp3", mp3_template)
    before = {p: dump(p) for p in (fl, mp)}
    db = navidrome(tmp_path, music, ["K/a.flac", "K/b.mp3"])
    nd = FakeNavidrome(db, music)
    rows = [row_for(music, p, write={"mb_trackid": R1, "mb_workid": W1}) for p in (fl, mp)]
    rep = apply(tmp_path, music, rows, navidrome=nd, navidrome_db=db, poll_s=0)
    assert rep.problems == [] and sorted(rep.written) == ["K/a.flac", "K/b.mp3"] and nd.scans == 1

    def changed(p):
        a, b = dict(before[p]), dict(dump(p))
        return {k for k in a.keys() | b.keys() if a.get(k) != b.get(k)}
    assert changed(fl) == {"musicbrainz_trackid", "musicbrainz_workid"}
    assert changed(mp) == {"UFID:http://musicbrainz.org", "TXXX:MusicBrainz Work Id"}
    from mediafile import MediaFile
    for p in (fl, mp):
        m = MediaFile(str(p))
        assert m.genres == ["Disco", "Funk"] and m.isrc == "USAT29900609"           # the M2 trap
        assert ib.read_ids(p) == {"mb_trackid": [R1], "mb_workid": [W1], "acoustid_id": []}


def test_apply_selects_by_accept_classes_and_skip(tmp_path, template):
    music = tmp_path / "music"
    a, b, c = (rich(music, f"K/{n}.flac", template) for n in "abc")
    rows = [row_for(music, a, "isrc"), row_for(music, b, "search"), row_for(music, c, "isrc", skip=True)]
    shas = sha(music)
    rep = apply(tmp_path, music, rows, dry_run=True)
    assert rep.written == ["K/a.flac"]
    rep = apply(tmp_path, music, rows, classes={"isrc", "search"}, dry_run=True)
    assert rep.written == ["K/a.flac", "K/b.flac"]
    rep = apply(tmp_path, music, rows)
    assert rep.written == ["K/a.flac"] and rep.problems == []
    after = sha(music)
    assert after[str(b)] == shas[str(b)] and after[str(c)] == shas[str(c)]          # untouched, byte for byte
    assert after[str(a)] != shas[str(a)]


def test_classes_outside_the_default_are_never_applied_by_default(tmp_path, template):
    music = tmp_path / "music"
    rows = []
    for cls in ("search", "ambiguous", "none", "conflict", "error"):
        p = rich(music, f"K/{cls}.flac", template)
        rows.append(row_for(music, p, cls, accept=True))                         # even with a hand-set accept
    shas = sha(music)
    rep = apply(tmp_path, music, rows)
    assert rep.written == [] and sha(music) == shas


def test_apply_skips_changed_files_and_never_overwrites_an_id(tmp_path, template, mp3_template):
    import os
    music = tmp_path / "music"
    touched = rich(music, "K/touched.flac", template)
    gained = rich(music, "K/gained.flac", template)
    retitled = rich(music, "K/retitled.flac", template)
    txxx = rich(music, "K/txxx.mp3", mp3_template)
    _id3_txxx(txxx, "MusicBrainz Track Id", OTHER)                     # only in TXXX: mediafile does not see it
    rows = [row_for(music, p) for p in (touched, gained, retitled)]
    t_row = row_for(music, txxx)
    t_row["file"]["mb_trackid"] = ""                                   # as if propose had missed it
    rows.append(t_row)

    st = touched.stat()
    os.utime(touched, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    from scripts.tag_cleanup import write_minimal
    for p, change in ((gained, {"mb_trackid": OTHER}), (retitled, {"title": "Le Freak (Live)"})):
        write_minimal(p, change)
        row = next(r for r in rows if r["path"] == p.relative_to(music).as_posix())
        row["size"], row["mtime_ns"] = p.stat().st_size, p.stat().st_mtime_ns     # a tagger that kept size/mtime
    shas = sha(music)
    rep = apply(tmp_path, music, rows)
    assert rep.written == [] and sha(music) == shas
    why = dict(rep.skipped)
    assert why["K/touched.flac"] == "changed since the proposal"
    assert why["K/gained.flac"] == "already has mb_trackid"
    assert why["K/txxx.mp3"] == "already has mb_trackid"
    assert why["K/retitled.flac"].startswith("tags changed since the proposal") and "title" in why["K/retitled.flac"]
    assert ib.read_ids(gained)["mb_trackid"] == [OTHER] and ib.read_ids(txxx)["mb_trackid"] == [OTHER]


def test_a_length_change_within_half_a_second_is_not_a_change(tmp_path, template):
    music = tmp_path / "music"
    p = rich(music, "K/a.flac", template)
    near, far = row_for(music, p), row_for(music, p)
    near["file"]["length_s"] += 0.4
    far["file"]["length_s"] += 0.6
    assert apply(tmp_path, music, [near], dry_run=True).written == ["K/a.flac"]
    rep = apply(tmp_path, music, [far], dry_run=True)
    assert rep.written == [] and "length_s" in rep.skipped[0][1]


def test_dry_run_writes_nothing(tmp_path, template):
    music = tmp_path / "music"
    p = rich(music, "K/a.flac", template)
    shas = sha(music)
    log = tmp_path / "out" / "apply.jsonl"
    rep = apply(tmp_path, music, [row_for(music, p, write={"mb_trackid": R1, "mb_workid": W1})], dry_run=True, log=log)
    assert rep.written == ["K/a.flac"] and rep.fields == {"K/a.flac": {"mb_trackid": R1, "mb_workid": W1}}
    assert sha(music) == shas and not log.exists()


def test_changed_navidrome_id_is_a_problem(tmp_path, template, capsys):
    music = tmp_path / "music"
    p = rich(music, "K/a.flac", template)
    db = navidrome(tmp_path, music, ["K/a.flac"])
    prop = proposal_file(tmp_path, [row_for(music, p)])
    nd = FakeNavidrome(db, music, new_ids={"K/a.flac": "fresh"})
    rc = ib.main(["apply", str(prop), "--music", str(music), "--navidrome-db", str(db), "--yes",
                  "--log", str(tmp_path / "out" / "a.jsonl"), "--poll", "0"], navidrome=nd)
    out = capsys.readouterr().out
    assert rc == 1 and "id changed: K/a.flac id0 → fresh" in out and "1 written" in out


def test_navidrome_without_the_recording_id_or_a_slow_scan_is_a_problem(tmp_path, template):
    music = tmp_path / "music"
    p = rich(music, "K/a.flac", template)
    db = navidrome(tmp_path, music, ["K/a.flac"])

    class Blind(FakeNavidrome):
        def start_scan(self):
            return {"scanning": True}
    rep = apply(tmp_path, music, [row_for(music, p)], navidrome=Blind(db, music), navidrome_db=db, poll_s=0)
    assert rep.problems == ["Navidrome does not show the recording id for K/a.flac"]

    q = rich(music, "K/b.flac", template)
    rep = apply(tmp_path, music, [row_for(music, q)], navidrome=FakeNavidrome(db, music, scanning=True),
                navidrome_db=db, poll_s=0, scan_timeout_s=0)
    assert any("scan" in x for x in rep.problems)


def test_revert_restores_empty_fields_only_where_still_ours(tmp_path, template, mp3_template):
    music = tmp_path / "music"
    fl = rich(music, "K/a.flac", template)
    mp = rich(music, "K/b.mp3", mp3_template)
    hand = rich(music, "K/c.flac", template)
    before = {p: (dump(p), ib.read_ids(p)) for p in (fl, mp, hand)}
    log = tmp_path / "out" / "apply.jsonl"
    rows = [row_for(music, p, write={"mb_trackid": R1, "mb_workid": W1, "acoustid_id": A1}) for p in (fl, mp, hand)]
    rep = apply(tmp_path, music, rows, log=log)
    assert len(rep.written) == 3 and rep.problems == []
    from scripts.tag_cleanup import write_minimal
    write_minimal(hand, {"mb_trackid": OTHER})                          # Michael fixed one by hand
    assert ib.revert(log, music) == 3
    for p in (fl, mp):
        assert ib.read_ids(p) == before[p][1] and dump(p) == before[p][0]          # every tag as before
    assert ib.read_ids(hand) == {"mb_trackid": [OTHER], "mb_workid": [], "acoustid_id": []}
    assert ib.revert(log, music) == 0                                   # nothing of ours is left


def test_revert_leaves_a_hand_edited_file_alone(tmp_path, template):
    music = tmp_path / "music"
    a, b = rich(music, "K/a.flac", template), rich(music, "K/b.flac", template)
    log = tmp_path / "out" / "apply.jsonl"
    apply(tmp_path, music, [row_for(music, a), row_for(music, b)], log=log)
    from scripts.tag_cleanup import write_minimal
    write_minimal(b, {"mb_trackid": OTHER})
    shas = sha(music)
    assert ib.revert(log, music) == 1
    assert ib.read_ids(a)["mb_trackid"] == [] and ib.read_ids(b)["mb_trackid"] == [OTHER]
    assert sha(music)[str(b)] == shas[str(b)]


def test_the_log_is_written_before_the_write_and_a_failed_write_stops_the_run(tmp_path, template):
    music = tmp_path / "music"
    a, b = rich(music, "K/a.flac", template), rich(music, "K/b.flac", template)
    log = tmp_path / "out" / "apply.jsonl"
    seen = []

    def writer(path, changes):
        seen.append([json.loads(x) for x in log.read_text().splitlines()])
        raise OSError("disk full")
    rep = apply(tmp_path, music, [row_for(music, a), row_for(music, b)], log=log, writer=writer)
    assert len(seen) == 1                                               # stopped after the first failure
    intent = seen[0][-1]
    assert intent["event"] == "write" and intent["path"] == "K/a.flac" and intent["written"] == {"mb_trackid": R1}
    assert intent["prior"] == {"mb_trackid": []} and intent["size"] == a.stat().st_size
    assert rep.written == [] and any("disk full" in x for x in rep.problems)


def test_a_write_that_does_not_read_back_is_reported_and_stops(tmp_path, template):
    music = tmp_path / "music"
    a, b = rich(music, "K/a.flac", template), rich(music, "K/b.flac", template)
    from scripts.tag_cleanup import write_minimal
    calls = []

    def wrong(path, changes):                                           # a writer that writes the wrong value
        calls.append(path)
        write_minimal(path, {k: OTHER for k in changes})
    log = tmp_path / "out" / "apply.jsonl"
    rep = apply(tmp_path, music, [row_for(music, a), row_for(music, b)], log=log, writer=wrong)
    assert len(calls) == 1 and any("reads back" in x for x in rep.problems)
    done = [json.loads(x) for x in log.read_text().splitlines()][-1]
    assert done["event"] == "done" and done["ok"] is False and done["size"] == a.stat().st_size

    def clobber(path, changes):                                         # writes the id but also drops a genre
        write_minimal(path, {**changes, "genres": ["Disco"]})
    rep = apply(tmp_path, music, [row_for(music, b)], writer=clobber)
    assert any("other tags changed" in x for x in rep.problems)


def test_choose_counts_only_a_listed_candidate(tmp_path, template):
    music = tmp_path / "music"
    a, b, c = (rich(music, f"K/{n}.flac", template) for n in "abc")
    rows = [row_for(music, a, "ambiguous", write={}, candidates=[RA, RB], choose=RB),
            row_for(music, b, "ambiguous", write={}, candidates=[RA, RB], choose=OTHER),
            row_for(music, c, "ambiguous", write={}, candidates=[RA, RB], choose=RA, skip=True)]
    rep = apply(tmp_path, music, rows)
    assert rep.written == ["K/a.flac"] and ib.read_ids(a)["mb_trackid"] == [RB]
    assert "not one of the row's candidates" in dict(rep.skipped)["K/b.flac"]
    assert ib.read_ids(b)["mb_trackid"] == [] and ib.read_ids(c)["mb_trackid"] == []


def test_a_chosen_row_gets_the_same_checks(tmp_path, template):
    music = tmp_path / "music"
    a = rich(music, "K/a.flac", template)
    row = row_for(music, a, "ambiguous", write={}, candidates=[RA, RB], choose=RA)
    from scripts.tag_cleanup import write_minimal
    write_minimal(a, {"title": "Something Else"})
    rep = apply(tmp_path, music, [row])
    assert rep.written == [] and dict(rep.skipped)["K/a.flac"] == "changed since the proposal"


def test_hand_edited_rows_cannot_write_other_fields_or_leave_the_library(tmp_path, template):
    music = tmp_path / "music"
    a = rich(music, "K/a.flac", template)
    outside = tmp_path / "elsewhere" / "outside.flac"
    outside.parent.mkdir()
    shutil.copy2(a, outside)                                           # same size, mtime and tags: only the path differs
    rows = [row_for(music, a, write={"title": "x"}), row_for(music, a, write={"mb_trackid": "not-an-id"})]
    esc = row_for(music, a)
    esc["path"] = "../elsewhere/outside.flac"
    rows.append(esc)
    shas = sha(music) | sha(outside.parent)
    rep = apply(tmp_path, music, rows)
    assert rep.written == [] and len(rep.skipped) == 3 and sha(music) | sha(outside.parent) == shas


def test_limit_and_only_pick_a_small_subset(tmp_path, template):
    music = tmp_path / "music"
    paths = [rich(music, f"{d}/{n}.flac", template) for d in "KL" for n in "abc"]
    rows = [row_for(music, p) for p in paths]
    assert apply(tmp_path, music, rows, dry_run=True, limit=2).written == ["K/a.flac", "K/b.flac"]
    assert apply(tmp_path, music, rows, dry_run=True, only=["L/*"]).written == ["L/a.flac", "L/b.flac", "L/c.flac"]
    rep = apply(tmp_path, music, rows, only=["L/*"], limit=1)
    assert rep.written == ["L/a.flac"]
    rep = apply(tmp_path, music, rows, dry_run=True)                    # a second run: what is done says so
    assert dict(rep.skipped)["L/a.flac"].startswith("already written")
    assert len(rep.written) == 5


def test_cli_needs_yes_prints_the_dry_run_and_keeps_the_log_out_of_the_library(tmp_path, template, capsys):
    music = tmp_path / "music"
    a = rich(music, "K/a.flac", template)
    prop = proposal_file(tmp_path, [row_for(music, a, write={"mb_trackid": R1, "mb_workid": W1})])
    shas = sha(music)
    base = ["apply", str(prop), "--music", str(music), "--no-navidrome", "--log", str(tmp_path / "out" / "a.jsonl")]
    assert ib.main(base) == 2 and "--yes" in capsys.readouterr().err
    assert ib.main(base + ["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert f"K/a.flac: mb_trackid={R1} mb_workid={W1}" in out and sha(music) == shas
    inside = ["apply", str(prop), "--music", str(music), "--no-navidrome", "--yes", "--log", str(music / "a.jsonl")]
    assert ib.main(inside) == 2 and "inside the library" in capsys.readouterr().err and sha(music) == shas
    assert ib.main(base + ["--yes"]) == 0
    assert "1 written, 0 skipped, 0 problems" in capsys.readouterr().out
    assert ib.read_ids(a)["mb_trackid"] == [R1]
    assert ib.main(["revert", str(tmp_path / "out" / "a.jsonl"), "--music", str(music)]) == 0
    assert ib.read_ids(a)["mb_trackid"] == [] and "1 file" in capsys.readouterr().out


def test_apply_and_revert_round_trip_an_m4a(tmp_path_factory, tmp_path):
    tpl = make_audio(tmp_path_factory.mktemp("tpl4") / "t.m4a")
    music = tmp_path / "music"
    p = rich(music, "K/a.m4a", tpl)
    before = dump(p), ib.read_ids(p)
    log = tmp_path / "out" / "apply.jsonl"
    rep = apply(tmp_path, music, [row_for(music, p, write={"mb_trackid": R1, "mb_workid": W1, "acoustid_id": A1})],
                log=log)
    assert rep.written == ["K/a.m4a"] and rep.problems == []
    assert ib.read_ids(p) == {"mb_trackid": [R1], "mb_workid": [W1], "acoustid_id": [A1]}
    assert ib.revert(log, music) == 1
    assert (dump(p), ib.read_ids(p)) == before


def test_the_scan_wait_does_not_mistake_a_scan_not_yet_begun_for_a_finished_one(tmp_path, template):
    music = tmp_path / "music"
    p = rich(music, "K/a.flac", template)
    db = navidrome(tmp_path, music, ["K/a.flac"])

    class Lagging(FakeNavidrome):
        """Navidrome reports scanning=false until the scan goroutine starts; lastScan moves when it is done."""
        polls = 0

        def scan_status(self):
            self.polls += 1
            if self.scans and self.polls >= 4:
                return {"scanning": False, "lastScan": "t1"}
            return {"scanning": self.scans > 0 and self.polls == 3, "lastScan": "t0"}

        def start_scan(self):
            self.scans += 1
            return {"scanning": False}

    nd = Lagging(db, music)
    rep = apply(tmp_path, music, [row_for(music, p)], navidrome=nd, navidrome_db=db, poll_s=0, scan_timeout_s=5)
    assert nd.polls == 4
    assert rep.problems == ["Navidrome does not show the recording id for K/a.flac"]   # this fake never scans


# ── review round (Task 9) ────────────────────────────────────────────────────────────────────────────────────

def test_ids_must_be_canonical_and_are_written_lowercase(tmp_path, template):
    music = tmp_path / "music"
    a, b = rich(music, "K/a.flac", template), rich(music, "K/b.flac", template)
    rows = [row_for(music, a, write={"mb_trackid": R1 + "\n"}), row_for(music, b, write={"mb_trackid": RA.upper()})]
    rep = apply(tmp_path, music, rows)
    assert dict(rep.skipped)["K/a.flac"].endswith("refused") and ib.read_ids(a)["mb_trackid"] == []
    assert rep.written == ["K/b.flac"] and rep.fields["K/b.flac"] == {"mb_trackid": RA}
    assert ib.read_ids(b)["mb_trackid"] == [RA]


def test_revert_compares_stripped_values(tmp_path, template):
    music = tmp_path / "music"
    a = rich(music, "K/a.flac", template)
    from scripts.tag_cleanup import write_minimal
    write_minimal(a, {"mb_trackid": R1})
    log = tmp_path / "old.jsonl"                                         # a log line from before canonical ids
    log.write_text(json.dumps({"event": "write", "path": "K/a.flac", "written": {"mb_trackid": R1 + "\n"}}) + "\n")
    assert ib.revert(log, music, say=lambda s: None) == 1 and ib.read_ids(a)["mb_trackid"] == []


def test_a_torn_log_line_is_skipped_with_a_warning(tmp_path, template):
    music = tmp_path / "music"
    a = rich(music, "K/a.flac", template)
    log = tmp_path / "out" / "apply.jsonl"
    apply(tmp_path, music, [row_for(music, a)], log=log)
    with open(log, "a") as fh:
        fh.write('{"ts": "x", "event": "wri')
    said = []
    assert ib.revert(log, music, say=said.append) == 1 and ib.read_ids(a)["mb_trackid"] == []
    assert any("unreadable log line" in s for s in said)


def test_a_log_that_cannot_be_written_stops_before_the_write(tmp_path, template):
    music = tmp_path / "music"
    a = rich(music, "K/a.flac", template)
    log = tmp_path / "out" / "apply.jsonl"
    log.mkdir(parents=True)                                             # open(..., "a") fails like ENOSPC would
    calls = []
    rep = apply(tmp_path, music, [row_for(music, a)], log=log, writer=lambda p, c: calls.append(p))
    assert calls == [] and rep.written == [] and any("revert log" in x for x in rep.problems)


def test_an_unreadable_file_or_a_directory_is_skipped_and_the_run_goes_on(tmp_path, template, capsys):
    import os
    music = tmp_path / "music"
    a, b, c = (rich(music, f"K/{n}.flac", template) for n in "abc")
    rows = [row_for(music, p) for p in (a, b, c)]
    st = a.stat()
    a.write_bytes(b"\0" * st.st_size)
    os.utime(a, ns=(st.st_atime_ns, st.st_mtime_ns))
    b.unlink()
    b.mkdir()
    prop = proposal_file(tmp_path, rows)
    rc = ib.main(["apply", str(prop), "--music", str(music), "--no-navidrome", "--yes",
                  "--log", str(tmp_path / "out" / "a.jsonl")])
    out = capsys.readouterr().out
    assert rc == 0 and "1 written, 2 skipped, 0 problems" in out
    assert ib.read_ids(c)["mb_trackid"] == [R1]


def test_a_write_that_changes_another_id_is_not_confirmed(tmp_path, template):
    music = tmp_path / "music"
    a = rich(music, "K/a.flac", template, mb_workid=W1)
    from scripts.tag_cleanup import write_minimal
    rep = apply(tmp_path, music, [row_for(music, a, write={"mb_trackid": R1})],
                writer=lambda p, c: write_minimal(p, {**c, "mb_workid": OTHER}))
    assert any(x.startswith("WRITE NOT CONFIRMED") and "mb_workid" in x for x in rep.problems)


def test_choose_needs_a_list_of_mbid_candidates_and_an_allowed_class(tmp_path, template):
    music = tmp_path / "music"
    a, b, c, d = (rich(music, f"K/{n}.flac", template) for n in "abcd")
    rows = [row_for(music, a, "ambiguous", write={}, candidates="xx" + RA, choose=RA),
            row_for(music, b, "conflict", write={}, candidates=[RA, RB], choose=RA),
            row_for(music, c, "none", write={}, candidates=[RA], choose=RA),
            row_for(music, d, "error", write={}, candidates=[RA], choose=RA),
            row_for(music, rich(music, "K/e.flac", template), "isrc", write={"mb_trackid": RA}, candidates=[RA, RB],
                    choose=RB)]
    rep = apply(tmp_path, music, rows)
    assert rep.written == ["K/c.flac"] and ib.read_ids(c)["mb_trackid"] == [RA]
    why = dict(rep.skipped)
    assert "not a list" in why["K/a.flac"] and "conflict" in why["K/b.flac"] and "error" in why["K/d.flac"]
    assert "choose is honoured only on" in why["K/e.flac"]


def test_classes_are_only_the_default_ones_search_and_ambiguous(tmp_path, template, capsys):
    music = tmp_path / "music"
    a = rich(music, "K/a.flac", template)
    rows = [row_for(music, a, "none", write={"mb_trackid": R1}, candidates=[R1])]
    for bad in ({"none"}, {"conflict"}, {"error"}):
        with pytest.raises(ValueError):
            apply(tmp_path, music, rows, classes=bad, dry_run=True)
    prop = proposal_file(tmp_path, [row_for(music, a, "error", write={"mb_trackid": R1})])
    rc = ib.main(["apply", str(prop), "--music", str(music), "--no-navidrome", "--yes", "--classes", "error",
                  "--log", str(tmp_path / "out" / "l.jsonl")])
    assert rc == 2 and ib.read_ids(a)["mb_trackid"] == []
    assert apply(tmp_path, music, rows, classes={"search", "ambiguous"}, dry_run=True).written == []


def test_an_unconfirmed_write_stops_before_the_scan_and_says_revert(tmp_path, template):
    music = tmp_path / "music"
    a = rich(music, "K/a.flac", template)
    db = navidrome(tmp_path, music, ["K/a.flac"])
    nd = FakeNavidrome(db, music)
    from scripts.tag_cleanup import write_minimal
    rep = apply(tmp_path, music, [row_for(music, a)], navidrome=nd, navidrome_db=db, poll_s=0,
                writer=lambda p, c: write_minimal(p, {**c, "genres": ["X"]}))
    assert nd.scans == 0 and len(rep.problems) == 1 and "revert" in rep.problems[0]


def test_revert_does_not_resave_or_count_a_file_with_nothing_of_ours_left(tmp_path, mp3_template):
    music = tmp_path / "music"
    b = rich(music, "K/b.mp3", mp3_template)
    log = tmp_path / "out" / "apply.jsonl"
    apply(tmp_path, music, [row_for(music, b)], log=log)
    _id3_txxx(b, "MusicBrainz Track Id", R1)                          # a tagger copied our id into TXXX too
    said = []
    assert ib.revert(log, music, say=said.append) == 1                  # our UFID goes; the TXXX copy is not ours
    shas = sha(music)
    assert ib.revert(log, music, say=said.append) == 0 and sha(music) == shas


# ---- M7 final fixes m6: an existing work id the proposed recording does not have is a conflict ----

def test_an_existing_work_id_outside_the_recordings_works_is_a_conflict(tmp_path, template):
    music = tmp_path / "music"
    p = tagged(music, "a.flac", template, artist="Jamiroquai", title="Virtual Insanity", isrc="GBARL0601475",
               mb_workid="w9")
    mb = FakeMB(isrcs={"GBARL0601475": [rec(RA, "Virtual Insanity", 8.0, artist="Jamiroquai", works=["w1"])]})
    pr = ib.classify(facts(music, p), mb)
    assert pr.cls == "conflict" and pr.write == {} and pr.accept is False
    assert "work id w9 is not among" in pr.why and "w1" in pr.why
    q = tagged(music, "b.flac", template, artist="Kool & the Gang", title="Song", mb_trackid=R1, mb_workid="w9")
    pr = ib.classify(facts(music, q), FakeMB([rec(R1, "Song", 8.0, works=["w1"])]))
    assert pr.cls == "conflict" and pr.write == {} and "work id w9 is not among" in pr.why


def test_an_existing_work_id_among_the_recordings_works_or_with_none_known_is_kept(tmp_path, template):
    music = tmp_path / "music"
    p = tagged(music, "a.flac", template, artist="Jamiroquai", title="Virtual Insanity", isrc="GBARL0601475",
               mb_workid="W1")
    for works in (["w1", "w2"], []):
        mb = FakeMB(isrcs={"GBARL0601475": [rec(RA, "Virtual Insanity", 8.0, artist="Jamiroquai", works=works)]})
        pr = ib.classify(facts(music, p), mb)
        assert pr.cls == "isrc" and pr.write == {"mb_trackid": RA}, works


# ---- M7 final fixes m5: a field that filled in between the check and the write is never written over ----

def test_write_one_refuses_a_field_that_filled_in_since_the_check(tmp_path, template):
    music = tmp_path / "music"
    p = rich(music, "K/a.flac", template)
    from scripts.tag_cleanup import write_minimal
    write_minimal(p, {"mb_trackid": OTHER})                           # the race: another writer, just now
    calls = []
    (tmp_path / "out").mkdir()
    state, why = ib._write_one(p, "K/a.flac", {"cls": "isrc"}, {"mb_trackid": R1}, tmp_path / "out" / "a.jsonl",
                               lambda path, w: calls.append(w))
    assert (state, calls) == ("skipped", []) and "mb_trackid" in why and "since the check" in why
    assert ib.read_ids(p)["mb_trackid"] == [OTHER]


def test_apply_skips_a_row_whose_field_filled_in_since_the_check_and_goes_on(tmp_path, template, monkeypatch):
    music = tmp_path / "music"
    a, b = rich(music, "K/a.flac", template), rich(music, "K/b.flac", template)
    rows = [row_for(music, a), row_for(music, b)]
    real = ib._check

    def racing(row, root):
        got = real(row, root)
        if row["path"] == "K/a.flac":                                  # fills in after the check
            from scripts.tag_cleanup import write_minimal
            write_minimal(a, {"mb_trackid": OTHER})
            row["size"], row["mtime_ns"] = a.stat().st_size, a.stat().st_mtime_ns     # so the re-stat passes too
        return got
    monkeypatch.setattr(ib, "_check", racing)
    rep = apply(tmp_path, music, rows)
    assert rep.written == ["K/b.flac"] and not rep.problems
    assert dict(rep.skipped)["K/a.flac"].startswith("already has mb_trackid")
    assert ib.read_ids(a)["mb_trackid"] == [OTHER]


# ---- M7 final fixes m1: the apply CLI never says "did not start, 0 written" once a write happened ----

def test_cli_reports_the_writes_and_the_revert_log_when_a_post_write_check_raises(tmp_path, template, capsys,
                                                                                    monkeypatch):
    import scripts.export_playlists as ep
    music = tmp_path / "music"
    p = rich(music, "K/a.flac", template)
    db = navidrome(tmp_path, music, ["K/a.flac"])
    prop = proposal_file(tmp_path, [row_for(music, p)])

    def boom(*a, **k):
        raise OSError("playlists dir unreadable")
    monkeypatch.setattr(ep, "check", boom)
    log = tmp_path / "out" / "a.jsonl"
    rc = ib.main(["apply", str(prop), "--music", str(music), "--navidrome-db", str(db), "--yes",
                  "--log", str(log), "--poll", "0"], navidrome=FakeNavidrome(db, music))
    out = capsys.readouterr().out
    assert rc == 1 and ib.read_ids(p)["mb_trackid"] == [R1]
    assert "did not start" not in out and "0 written" not in out
    assert "post-write check failed (OSError: playlists dir unreadable)" in out
    assert "1 written, 0 skipped, 1 problems" in out and f"revert log {log}" in out


def test_cli_prints_the_revert_log_after_a_failed_write(tmp_path, template, capsys, monkeypatch):
    import scripts.tag_cleanup as tc
    music = tmp_path / "music"
    p = rich(music, "K/a.flac", template)
    prop = proposal_file(tmp_path, [row_for(music, p)])

    def disk_full(path, changes):
        raise OSError("disk full")
    monkeypatch.setattr(tc, "write_minimal", disk_full)
    log = tmp_path / "out" / "a.jsonl"
    rc = ib.main(["apply", str(prop), "--music", str(music), "--no-navidrome", "--yes", "--log", str(log)])
    out = capsys.readouterr().out
    assert rc == 1 and "disk full" in out and f"revert log {log}" in out and "did not start" not in out


def test_cli_never_says_0_written_when_apply_raises_after_a_write(tmp_path, template, capsys, monkeypatch):
    music = tmp_path / "music"
    p = rich(music, "K/a.flac", template)
    prop = proposal_file(tmp_path, [row_for(music, p)])
    real = ib._write_one

    def then_crash(*a, **k):
        real(*a, **k)
        raise RuntimeError("bug after the write")
    monkeypatch.setattr(ib, "_write_one", then_crash)
    log = tmp_path / "out" / "a.jsonl"
    rc = ib.main(["apply", str(prop), "--music", str(music), "--no-navidrome", "--yes", "--log", str(log)])
    out = capsys.readouterr().out
    assert rc == 1 and ib.read_ids(p)["mb_trackid"] == [R1]
    assert "did not start" not in out and "0 written" not in out and f"revert log {log}" in out
