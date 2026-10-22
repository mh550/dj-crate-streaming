"""R7-02: the identity picker's API (M9 §5a, plan docs/plans/2026-10-21-r7-identity-picker.md).

`GET /api/identity` serves the proposal rows Michael decides on; `POST /api/identity/choice` records his tap in
`identity-choices.json` beside the proposal and logs an `identity_pick` event. Nothing here writes a library file.

The proposal is made by a real `identity_backfill.propose` over tagged fixture files with the fake MusicBrainz of
tests/test_identity_backfill.py, plus a few rows built with `asdict(Proposal(...))` for the suggestion rule. The
service runs on the fake Navidrome and its navidrome.db mirror. No network, no /srv.
"""
import json
import urllib.error
import urllib.request
from dataclasses import asdict

import pytest

from crates.service import Config, CrateApp, CrateServer
from crates.store import CrateStore
from scripts import identity_backfill as ib
from subsonic.fake_server import FakeSubsonicServer
from tests.test_identity_backfill import R1, R12, RA, RB, FakeMB, rec, tagged, template  # noqa: F401  (fixture)

RN = "33333333-3333-3333-3333-333333333333"
T1 = "44444444-4444-4444-4444-444444444444"
T2 = "55555555-5555-5555-5555-555555555555"
X1 = "66666666-6666-6666-6666-666666666666"
X2 = "77777777-7777-7777-7777-777777777777"
PICKER = ["K/search.flac", "K/tie.flac", "K/near.flac", "K/conflict.flac", "gone.flac"]


def make_proposal(tmp_path, template, monkeypatch):
    """A real propose: one row of every class (confirmed and a bare `none` included), the error row from a file
    that vanished between the walk and the read, so its text is a real exception's with the absolute path."""
    music, ident = tmp_path / "music", tmp_path / "identity"
    k = "Kool & the Gang"
    tagged(music, "K/confirmed.flac", template, artist=k, title="Song", mb_trackid=R1)
    tagged(music, "K/search.flac", template, artist=k, title="Good", album="LP")
    tagged(music, "K/tie.flac", template, artist=k, title="Tie", album="LP")
    tagged(music, "K/near.flac", template, artist="The Gang", title="Celebration", isrc="USPR37900001")
    tagged(music, "K/lost.flac", template, artist=k, title="Lost")
    tagged(music, "K/conflict.flac", template, artist=k, title="Other", mb_trackid=R12)
    real = ib.audio_files
    monkeypatch.setattr(ib, "audio_files", lambda root: real(root) + [root / "gone.flac"])
    mb = FakeMB([rec(R1, "Song", 8.0, works=["w1"]), rec(R12, "Other", 20.0), rec(RA, "Good", 8.0)],
                isrcs={"USPR37900001": [rec(RN, "Celebration", 8.0, releases=("Celebrate!",))]},
                searches={"Good": [rec(RA, "Good", 8.0)],
                          "Tie": [rec(T1, "Tie", 8.0, releases=("Other LP",)), rec(T2, "Tie", 8.0, releases=("Else",))]})
    props = {p.path: p.cls for p in ib.propose(music, ident, mb, log=lambda s: None)}
    assert props == {"K/confirmed.flac": "confirmed", "K/search.flac": "search", "K/tie.flac": "ambiguous",
                     "K/near.flac": "none", "K/lost.flac": "none", "K/conflict.flac": "conflict",
                     "gone.flac": "error"}
    return music, ident


def edit_proposal(ident, change):
    path = ident / ib.PROPOSAL
    doc = json.loads(path.read_text())
    change(doc)
    path.write_text(json.dumps(doc))


def add_rows(ident, *rows):
    edit_proposal(ident, lambda doc: doc["proposals"].extend(asdict(r) for r in rows))


def row(path, cls, album, *recs, size=1, mtime_ns=1):
    return ib.Proposal(path=path, cls=cls, write={}, why="test row", candidates=[r.id for r in recs], size=size,
                       mtime_ns=mtime_ns, file={"artist": "Kool & the Gang", "title": "T", "album": album},
                       candidate_details=[ib._detail(r) for r in recs])


@pytest.fixture
def api(tmp_path, template, monkeypatch):
    music, ident = make_proposal(tmp_path, template, monkeypatch)
    with FakeSubsonicServer(db_path=tmp_path / "navidrome.db") as nd:
        nd.state.songs = {"nd-search": {"id": "nd-search", "path": "K/search.flac", "title": "Good"},
                          "nd-tie": {"id": "nd-tie", "path": "K/tie.flac", "title": "Tie"},
                          "nd-near": {"id": "nd-near", "path": "K/near.flac", "title": "Celebration"}}
        nd.state.missing.add("nd-near")
        nd.state.sync()
        cfg = Config(subsonic_url=nd.url, username="demo", password="demo", db_path=":memory:", port=0,
                     navidrome_db=str(tmp_path / "navidrome.db"), identity_dir=str(ident))
        app = CrateApp(cfg, store=CrateStore())
        with CrateServer(app) as srv:
            yield app, srv, ident


def call(url, body=None, raw=None):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    req = urllib.request.Request(url, data=data, method="GET" if data is None else "POST",
                                 headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        r = e
    return r.status, json.loads(r.read() or b"null")


def rows(srv, q=""):
    code, body = call(f"{srv.url}/api/identity{q}")
    assert code == 200, body
    return {r["path"]: r for r in body["rows"]}


def pick(srv, path, action, mbid=None):
    body = {"path": path, "action": action} | ({"mbid": mbid} if mbid is not None else {})
    return call(f"{srv.url}/api/identity/choice", body)


def events(app):
    return [e for e in app.store.events(1000) if e["kind"] == "identity_pick"]


# ── GET ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_config_reads_the_identity_dir_from_the_environment(monkeypatch):
    monkeypatch.delenv("CRATES_IDENTITY_DIR", raising=False)
    assert Config.from_env().identity_dir == "/data/identity"
    monkeypatch.setenv("CRATES_IDENTITY_DIR", "/tmp/somewhere")
    assert Config.from_env().identity_dir == "/tmp/somewhere"


def test_rows_have_the_plan_shape(api, tmp_path):
    app, srv, ident = api
    code, body = call(f"{srv.url}/api/identity")
    assert code == 200
    assert set(body) == {"created", "counts", "rows"}
    assert body["created"] == json.loads((ident / ib.PROPOSAL).read_text())["created"]
    assert body["counts"] == {"search": 1, "ambiguous": 1, "none": 1, "conflict": 1, "error": 1}
    assert [r["path"] for r in body["rows"]] == PICKER                  # class order, then path
    keys = {"path", "cls", "why", "file", "songId", "proposed", "candidates", "suggested", "choice"}
    assert all(set(r) == keys for r in body["rows"])
    by = {r["path"]: r for r in body["rows"]}

    s = by["K/search.flac"]
    assert s["cls"] == "search" and s["candidates"] == [] and s["suggested"] is None and s["choice"] is None
    assert s["proposed"] == {"id": RA, "title": "Good", "length_s": 8.0,
                             "url": f"https://musicbrainz.org/recording/{RA}"}
    assert s["file"]["artist"] == "Kool & the Gang" and s["file"]["title"] == "Good" and s["file"]["album"] == "LP"
    assert abs(s["file"]["length_s"] - 8.0) < 0.2

    t = by["K/tie.flac"]
    assert t["proposed"] is None and [c["id"] for c in t["candidates"]] == [T1, T2]
    assert t["candidates"][0] == {"id": T1, "title": "Tie", "artist": "Kool & the Gang", "length_s": 8.0,
                                  "release": "Other LP", "disambiguation": "",
                                  "url": f"https://musicbrainz.org/recording/{T1}"}
    assert "2 of 2 results fit" in t["why"]
    assert [c["id"] for c in by["K/near.flac"]["candidates"]] == [RN]
    assert by["K/conflict.flac"]["candidates"] == [] and by["K/conflict.flac"]["proposed"] is None

    text = json.dumps(body)
    assert str(tmp_path) not in text and "music_root" not in text
    assert '"/' not in text                                             # no absolute path anywhere


def test_an_error_rows_why_loses_the_music_root(api, tmp_path):
    app, srv, ident = api
    raw = next(r for r in json.loads((ident / ib.PROPOSAL).read_text())["proposals"] if r["path"] == "gone.flac")
    assert str(tmp_path / "music") in raw["why"]                        # the exception named the absolute path
    why = rows(srv)["gone.flac"]["why"]
    assert why.startswith("unreadable: FileNotFoundError") and "gone.flac" in why and str(tmp_path) not in why


def test_confirmed_isrc_acoustid_and_bare_none_rows_are_not_listed(api):
    app, srv, ident = api
    add_rows(ident, ib.Proposal(path="I/isrc.flac", cls="isrc", write={"mb_trackid": RB}),
             ib.Proposal(path="I/acoustid.flac", cls="acoustid", write={"mb_trackid": RB}))
    got = rows(srv)
    assert "K/confirmed.flac" not in got and "K/lost.flac" not in got
    assert "I/isrc.flac" not in got and "I/acoustid.flac" not in got
    assert sorted(got) == sorted(PICKER)


def test_class_filter(api):
    app, srv, ident = api
    code, body = call(f"{srv.url}/api/identity?class=ambiguous")
    assert code == 200 and [r["path"] for r in body["rows"]] == ["K/tie.flac"]
    assert body["counts"]["search"] == 1                                # counts are before the filter
    for bad in ("confirmed", "nonsense"):
        code, body = call(f"{srv.url}/api/identity?class={bad}")
        assert code == 400 and "class" in body["error"], bad


def test_no_proposal_is_404(api):
    app, srv, ident = api
    (ident / ib.PROPOSAL).unlink()
    code, body = call(f"{srv.url}/api/identity")
    assert code == 404 and "propose" in body["error"]
    assert pick(srv, "K/search.flac", "skip")[0] == 404
    assert not (ident / "identity-choices.json").exists()


def test_a_corrupt_proposal_is_503(api):
    app, srv, ident = api
    (ident / ib.PROPOSAL).write_text("{not json")
    assert call(f"{srv.url}/api/identity")[0] == 503
    (ident / ib.PROPOSAL).write_text('{"proposals": "x"}')
    assert call(f"{srv.url}/api/identity")[0] == 503
    assert pick(srv, "K/search.flac", "skip")[0] == 503


def test_suggested_is_the_only_candidate_on_the_files_album(api):
    app, srv, ident = api
    add_rows(ident,
             row("S/one.flac", "ambiguous", "LP", rec(X1, "T", 8.0, releases=("LP",)), rec(X2, "T", 8.0, releases=("B",))),
             row("S/two.flac", "ambiguous", "LP", rec(X1, "T", 8.0, releases=("lp",)), rec(X2, "T", 8.0, releases=("LP",))),
             row("S/nobody.flac", "ambiguous", "LP", rec(X1, "T", 8.0, releases=("A",)), rec(X2, "T", 8.0, releases=("B",))),
             row("S/noalbum.flac", "ambiguous", "", rec(X1, "T", 8.0, releases=("",)), rec(X2, "T", 8.0, releases=("B",))),
             row("S/none.flac", "none", "L.P.", rec(X1, "T", 8.0, releases=("LP",))),
             ib.Proposal(path="S/conflict.flac", cls="conflict", write={}, candidates=[X1],
                         file={"album": "LP"}, candidate_details=[ib._detail(rec(X1, "T", 8.0, releases=("LP",)))]))
    got = rows(srv)
    assert got["S/one.flac"]["suggested"] == X1
    assert got["S/none.flac"]["suggested"] == X1                       # loose: "L.P." is "LP"
    assert got["S/two.flac"]["suggested"] is None
    assert got["S/nobody.flac"]["suggested"] is None
    assert got["S/noalbum.flac"]["suggested"] is None
    assert got["S/conflict.flac"]["suggested"] is None
    assert got["K/search.flac"]["suggested"] is None                  # the search row's album is "LP": never


def test_suggested_uses_every_release_when_the_row_has_them(api):
    app, srv, ident = api
    assert ib._detail(rec(X1, "T", 8.0, releases=("A", "LP")))["releases"] == ["A", "LP"]
    on_second = row("R/new.flac", "ambiguous", "LP", rec(X1, "T", 8.0, releases=("A", "LP")),
                    rec(X2, "T", 8.0, releases=("B",)))
    old = row("R/old.flac", "ambiguous", "LP", rec(X1, "T", 8.0, releases=("A", "LP")),
              rec(X2, "T", 8.0, releases=("B",)))
    for d in old.candidate_details:                                    # a proposal made before `releases` existed
        del d["releases"]
    add_rows(ident, on_second, old)
    got = rows(srv)
    assert got["R/new.flac"]["suggested"] == X1
    assert got["R/old.flac"]["suggested"] is None                      # only the first release: "A"


def test_song_id_from_navidrome_db_by_path(api):
    app, srv, ident = api
    got = rows(srv)
    assert got["K/search.flac"]["songId"] == "nd-search" and got["K/tie.flac"]["songId"] == "nd-tie"
    assert got["K/near.flac"]["songId"] is None                       # missing in Navidrome
    assert got["K/conflict.flac"]["songId"] is None                   # not in Navidrome
    app.cfg.navidrome_db = None
    assert all(r["songId"] is None for r in rows(srv).values())


def test_an_unreadable_navidrome_db_is_503(api, tmp_path):
    app, srv, ident = api
    app.cfg.navidrome_db = str(tmp_path / "nowhere" / "navidrome.db")
    assert call(f"{srv.url}/api/identity")[0] == 503


# ── POST: refusals ───────────────────────────────────────────────────────────────────────────────────────────────

def test_conflict_and_error_rows_refuse_accept_and_choose_with_409(api):
    app, srv, ident = api
    for path, cls in (("K/conflict.flac", "conflict"), ("gone.flac", "error")):
        for action, mbid in (("accept", R12), ("choose", R12)):
            code, body = pick(srv, path, action, mbid)
            assert code == 409 and body["error"] == f"{cls} rows can only be skipped", (path, action)
    assert not (ident / "identity-choices.json").exists() and events(app) == []
    assert pick(srv, "K/conflict.flac", "skip")[0] == 200
    assert pick(srv, "gone.flac", "skip")[0] == 200


def test_choose_outside_the_candidates_is_400(api):
    app, srv, ident = api
    for mbid in (RB, "not-an-id", T1.upper() + " ", 7):
        code, body = pick(srv, "K/tie.flac", "choose", mbid)
        assert code == 400 and "is not one of the row's candidates" in body["error"], mbid
    assert pick(srv, "K/tie.flac", "choose", T2.upper())[0] == 200    # canonical compare
    assert json.loads((ident / "identity-choices.json").read_text())["choices"]["K/tie.flac"]["mbid"] == T2


def test_accept_outside_search_is_400(api):
    app, srv, ident = api
    for path, mbid in (("K/tie.flac", T1), ("K/near.flac", RN)):
        code, body = pick(srv, path, "accept", mbid)
        assert code == 400 and body["error"] == "accept is for search rows; choose a candidate"


def test_accept_needs_the_shown_recording(api):
    app, srv, ident = api
    for mbid in (None, "x"):
        code, body = pick(srv, "K/search.flac", "accept", mbid)
        assert code == 400 and "mbid" in body["error"]


def test_accept_of_another_recording_is_409(api):
    app, srv, ident = api
    shown = rows(srv)["K/search.flac"]["proposed"]["id"]
    def repick(doc):                                                   # a propose finished between load and tap
        r = next(r for r in doc["proposals"] if r["path"] == "K/search.flac")
        r["recording"] = r["write"]["mb_trackid"] = RB
    edit_proposal(ident, repick)
    code, body = pick(srv, "K/search.flac", "accept", shown)
    assert code == 409 and body["error"] == "the proposal changed since the page loaded; reload"
    assert pick(srv, "K/search.flac", "accept", RB)[0] == 200


def test_choose_on_a_search_row_is_400(api):
    app, srv, ident = api
    code, body = pick(srv, "K/search.flac", "choose", RA)
    assert code == 400 and body["error"] == "a search row is accepted or skipped (it has no candidates)"


def test_a_body_that_is_not_an_object_is_400(api):
    app, srv, ident = api
    for raw in (b"[1]", b'"skip"', b"null", b"{bad"):
        code, body = call(f"{srv.url}/api/identity/choice", raw=raw)
        assert code == 400, raw
    code, body = call(f"{srv.url}/api/identity/choice", ["x"])
    assert code == 400 and body["error"] == "body must be a JSON object"


def test_unknown_action_is_400(api):
    app, srv, ident = api
    for action in ("apply", None, ""):
        code, body = pick(srv, "K/tie.flac", action)
        assert code == 400 and body["error"] == "action must be accept, choose or skip"


def test_unknown_path_is_400(api, tmp_path):
    app, srv, ident = api
    for path in ("../../etc/passwd", str(tmp_path / "music" / "K/search.flac"), "/etc/passwd", "K/confirmed.flac",
                 "K/lost.flac", None, 3, ["K/search.flac"]):
        code, body = pick(srv, path, "skip")
        assert code == 400 and body["error"].startswith("not in the identity proposal"), path
    assert not (ident / "identity-choices.json").exists() and events(app) == []


def test_a_corrupt_choices_file_is_503_and_kept(api):
    app, srv, ident = api
    f = ident / "identity-choices.json"
    for bad in (b"{oops", b'{"choices": []}', b"[]"):
        f.write_bytes(bad)
        code, body = pick(srv, "K/tie.flac", "skip")
        assert code == 503 and "identity-choices.json" in body["error"]
        assert f.read_bytes() == bad
        assert call(f"{srv.url}/api/identity")[0] == 503
    assert events(app) == []


def test_a_refused_pick_writes_nothing_and_logs_nothing(api, tmp_path):
    app, srv, ident = api
    before = sorted(p.name for p in ident.iterdir())
    for args in (("K/conflict.flac", "accept", R12), ("K/tie.flac", "choose", RB), ("K/tie.flac", "accept", T1),
                 ("K/search.flac", "choose", RA), ("K/search.flac", "accept", RB), ("nope.flac", "skip"),
                 ("K/tie.flac", "maybe")):
        assert pick(srv, *args)[0] in (400, 409)
    assert sorted(p.name for p in ident.iterdir()) == before and events(app) == []


def test_a_failed_write_is_503_and_logs_nothing(api, monkeypatch):
    app, srv, ident = api
    from crates import identity_view
    def boom(path, text):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(identity_view, "write_atomic", boom)
    code, body = pick(srv, "K/tie.flac", "skip")
    assert code == 503 and body["error"].startswith("could not save the choice") and "/" not in body["error"]
    assert events(app) == []


# ── POST: recorded ───────────────────────────────────────────────────────────────────────────────────────────────

def test_second_click_replaces_the_first(api):
    app, srv, ident = api
    code, body = pick(srv, "K/tie.flac", "choose", T1)
    assert code == 200 and body["path"] == "K/tie.flac"
    assert body["choice"]["action"] == "choose" and body["choice"]["mbid"] == T1
    assert body["choice"]["decided_by"] == "michael" and body["choice"]["stale"] is False
    first = json.loads((ident / "identity-choices.json").read_text())
    code, body = pick(srv, "K/tie.flac", "skip")
    assert code == 200 and body["choice"]["action"] == "skip" and body["choice"]["mbid"] is None
    doc = json.loads((ident / "identity-choices.json").read_text())
    assert doc["created"] == first["created"]
    assert list(doc["choices"]) == ["K/tie.flac"]
    c = doc["choices"]["K/tie.flac"]
    raw = next(r for r in json.loads((ident / ib.PROPOSAL).read_text())["proposals"] if r["path"] == "K/tie.flac")
    assert c == {"action": "skip", "mbid": None, "cls": "ambiguous", "size": raw["size"], "mtime_ns": raw["mtime_ns"],
                 "at": c["at"], "decided_by": "michael"}
    assert rows(srv)["K/tie.flac"]["choice"] == {"action": "skip", "mbid": None, "at": c["at"],
                                                 "decided_by": "michael", "stale": False}


def test_picks_on_several_rows_are_all_kept(api):
    app, srv, ident = api
    assert pick(srv, "K/search.flac", "accept", RA)[0] == 200
    assert pick(srv, "K/near.flac", "choose", RN)[0] == 200
    assert pick(srv, "K/conflict.flac", "skip")[0] == 200
    got = json.loads((ident / "identity-choices.json").read_text())["choices"]
    assert {p: (c["action"], c["mbid"]) for p, c in got.items()} == {
        "K/search.flac": ("accept", RA), "K/near.flac": ("choose", RN), "K/conflict.flac": ("skip", None)}
    for p, c in got.items():
        assert ib.choice_problem(next(r for r in json.loads((ident / ib.PROPOSAL).read_text())["proposals"]
                                      if r["path"] == p), c) == ""


def test_each_pick_logs_identity_pick_with_decided_by_michael(tmp_path, template, monkeypatch):
    music, ident = make_proposal(tmp_path, template, monkeypatch)
    with FakeSubsonicServer(db_path=tmp_path / "navidrome.db") as nd:
        nd.state.songs = {"nd-tie": {"id": "nd-tie", "path": "K/tie.flac", "title": "Tie"}}
        nd.state.sync()
        cfg = Config(subsonic_url=nd.url, username="demo", password="demo", db_path=str(tmp_path / "crates.db"),
                     port=0, navidrome_db=str(tmp_path / "navidrome.db"), identity_dir=str(ident))
        with CrateServer(CrateApp(cfg)) as srv:
            assert pick(srv, "K/tie.flac", "choose", T1)[0] == 200
            assert pick(srv, "K/search.flac", "accept", RA)[0] == 200
            assert pick(srv, "K/conflict.flac", "skip")[0] == 200
            other = CrateStore(tmp_path / "crates.db")                # a second connection: the commit happened
            got = [(e["song_id"], e["detail"]) for e in other.events(100) if e["kind"] == "identity_pick"]
            other.db.close()
    assert got[::-1] == [("nd-tie", f"ambiguous K/tie.flac: choose {T1}; decided_by=michael"),
                         (None, f"search K/search.flac: accept {RA}; decided_by=michael"),
                         (None, "conflict K/conflict.flac: skip; decided_by=michael")]


def test_nothing_is_written_outside_the_identity_dir(api, tmp_path):
    app, srv, ident = api
    def listing():
        return {str(p.relative_to(tmp_path)): p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    before = listing()
    assert pick(srv, "K/tie.flac", "choose", T1)[0] == 200
    assert pick(srv, "K/search.flac", "accept", RA)[0] == 200
    assert pick(srv, "gone.flac", "skip")[0] == 200
    rows(srv)
    after = listing()
    assert set(after) - set(before) == {"identity/identity-choices.json"}
    assert {k: v for k, v in after.items() if k in before} == before   # nothing else changed either


def test_a_choice_goes_stale_when_the_row_changes(api):
    app, srv, ident = api
    assert pick(srv, "K/tie.flac", "choose", T1)[0] == 200
    assert pick(srv, "K/search.flac", "accept", RA)[0] == 200
    assert pick(srv, "K/near.flac", "skip")[0] == 200
    assert not any(r["choice"]["stale"] for r in rows(srv).values() if r["choice"])
    def rewrite(doc):                                                  # a new propose: the files changed since
        for r in doc["proposals"]:
            if r["path"] == "K/tie.flac":
                r["mtime_ns"] += 1
            if r["path"] == "K/search.flac":
                r["recording"] = r["write"]["mb_trackid"] = RB
            if r["path"] == "K/near.flac":
                r["size"] += 1
    edit_proposal(ident, rewrite)
    got = rows(srv)
    assert got["K/tie.flac"]["choice"]["stale"] is True
    assert got["K/search.flac"]["choice"]["stale"] is True
    assert got["K/near.flac"]["choice"]["stale"] is True


# ── choice_problem: the one definition of a choice that no longer fits (apply uses it too, R7-03) ──────────────

def test_choice_problem():
    r = {"path": "a.flac", "cls": "ambiguous", "candidates": [T1, T2], "write": {}, "size": 5, "mtime_ns": 9}
    s = {"path": "s.flac", "cls": "search", "candidates": [], "write": {"mb_trackid": RA}, "size": 5, "mtime_ns": 9}
    c = {"cls": "ambiguous", "size": 5, "mtime_ns": 9, "decided_by": "michael"}
    assert ib.choice_problem(r, c | {"action": "choose", "mbid": T2}) == ""
    assert ib.choice_problem(r, c | {"action": "skip", "mbid": None}) == ""
    assert ib.choice_problem(s, c | {"cls": "search", "action": "accept", "mbid": RA}) == ""
    assert "older proposal row" in ib.choice_problem(r, c | {"action": "choose", "mbid": T2, "size": 6})
    assert "older proposal row" in ib.choice_problem(r, c | {"action": "choose", "mbid": T2, "mtime_ns": 8})
    assert "older proposal row" in ib.choice_problem(r, c | {"action": "choose", "mbid": T2, "cls": "none"})
    assert "older proposal row" in ib.choice_problem(r, c | {"action": "skip", "mbid": None, "size": 6})
    assert "candidates" in ib.choice_problem(r, c | {"action": "choose", "mbid": RB})
    assert "not canonical" in ib.choice_problem(r, c | {"action": "choose", "mbid": T2 + " "})
    assert ib.choice_problem(r, c | {"action": "accept", "mbid": T1})                       # accept on ambiguous
    assert ib.choice_problem(s, c | {"cls": "search", "action": "accept", "mbid": RB})      # no longer the pick
    assert ib.choice_problem(r, c | {"action": "apply", "mbid": T1})                        # unknown action
    assert ib.choice_problem(r, "skip")                                                     # not an entry
    k = {"path": "k.flac", "cls": "conflict", "candidates": [T1], "write": {}, "size": 5, "mtime_ns": 9}
    assert ib.choice_problem(k, c | {"cls": "conflict", "action": "choose", "mbid": T1})
    assert ib.choice_problem(k, c | {"cls": "conflict", "action": "skip", "mbid": None}) == ""


# ── after the review ─────────────────────────────────────────────────────────────────────────────────────────────

def test_a_pick_whose_event_cannot_be_logged_says_so(api, monkeypatch):
    app, srv, ident = api
    import sqlite3
    def locked():
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(app.store, "commit", locked)
    code, body = pick(srv, "K/tie.flac", "choose", T1)
    assert code == 503 and "saved" in body["error"] and "identity_pick" in body["error"]
    assert "Navidrome" not in body["error"]
    assert events(app) == []                                         # rolled back, not left for a later commit
    monkeypatch.undo()
    assert pick(srv, "K/tie.flac", "choose", T1)[0] == 200             # tapping again logs it
    assert len(events(app)) == 1


def test_why_never_shows_an_absolute_path(api):
    app, srv, ident = api
    def edit(doc):
        for r in doc["proposals"]:
            if r["path"] == "K/tie.flac":
                r["why"] = ("search: 2 of 2 results fit; AcoustID failed: PermissionError: [Errno 13] Permission "
                            "denied: '/data/identity/acoustid-cache.jsonl'; AC/DC")
    edit_proposal(ident, edit)
    why = rows(srv)["K/tie.flac"]["why"]
    assert "/data" not in why and "acoustid-cache.jsonl" in why and "AC/DC" in why
    edit_proposal(ident, lambda doc: doc.update(music_root="/"))       # a root of "/" strips nothing else
    assert "AC/DC" in rows(srv)["K/tie.flac"]["why"]


@pytest.mark.parametrize("field,value", [("file", "x"), ("candidates", 5), ("candidate_details", "x"),
                                         ("write", ["x"])])
def test_a_malformed_proposal_row_is_503(api, field, value):
    app, srv, ident = api
    def edit(doc):
        next(r for r in doc["proposals"] if r["path"] == "K/tie.flac")[field] = value
    edit_proposal(ident, edit)
    code, body = call(f"{srv.url}/api/identity")
    assert code == 503 and "not a proposal" in body["error"]
    assert pick(srv, "K/tie.flac", "skip")[0] == 503


def test_choose_without_an_mbid_says_so(api):
    app, srv, ident = api
    code, body = pick(srv, "K/tie.flac", "choose")
    assert code == 400 and body["error"] == "choose needs the mbid of one of the row's candidates"


def test_a_row_skipped_in_the_proposal_is_not_listed(api):
    app, srv, ident = api
    edit_proposal(ident, lambda doc: next(r for r in doc["proposals"] if r["path"] == "K/tie.flac").update(skip=True))
    assert "K/tie.flac" not in rows(srv)
    code, body = pick(srv, "K/tie.flac", "choose", T1)
    assert code == 400 and body["error"].startswith("not in the identity proposal")


def test_a_refused_pick_leaves_an_existing_choices_file_alone(api):
    app, srv, ident = api
    assert pick(srv, "K/near.flac", "choose", RN)[0] == 200
    before = (ident / "identity-choices.json").read_bytes()
    for args in (("K/conflict.flac", "accept", R12), ("K/tie.flac", "choose", RB), ("K/search.flac", "accept", RB),
                 ("nope.flac", "skip"), ("K/near.flac", "maybe")):
        assert pick(srv, *args)[0] in (400, 409)
    assert (ident / "identity-choices.json").read_bytes() == before and len(events(app)) == 1


def test_taps_at_the_same_time_are_all_kept(api, monkeypatch):
    """The service's lock serializes the read-modify-write: without it, two taps read the same file and one is lost."""
    app, srv, ident = api
    import threading
    import time
    from crates import identity_view
    real = identity_view.write_atomic
    def slow(path, text):                                              # widen the window a race would need
        time.sleep(0.2)
        real(path, text)
    monkeypatch.setattr(identity_view, "write_atomic", slow)
    taps = [("K/tie.flac", "choose", T1), ("K/near.flac", "choose", RN), ("K/conflict.flac", "skip"),
            ("K/search.flac", "accept", RA)]
    codes = []
    threads = [threading.Thread(target=lambda a=a: codes.append(pick(srv, *a)[0])) for a in taps]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert codes == [200] * 4
    assert sorted(json.loads((ident / "identity-choices.json").read_text())["choices"]) == sorted(a[0] for a in taps)


def test_choice_problem_reasons():
    r = {"path": "a.flac", "cls": "ambiguous", "candidates": [T1, T2], "write": {}, "size": 5, "mtime_ns": 9}
    s = {"path": "s.flac", "cls": "search", "candidates": [], "write": {"mb_trackid": RA}, "size": 5, "mtime_ns": 9}
    k = {"path": "k.flac", "cls": "conflict", "candidates": [T1], "write": {}, "size": 5, "mtime_ns": 9}
    c = {"cls": "ambiguous", "size": 5, "mtime_ns": 9, "decided_by": "michael"}
    assert "accept is for search rows" in ib.choice_problem(r, c | {"action": "accept", "mbid": T1})
    assert "no longer the row's pick" in ib.choice_problem(s, c | {"cls": "search", "action": "accept", "mbid": RB})
    assert "accept, choose or skip" in ib.choice_problem(r, c | {"action": "apply", "mbid": T1})
    assert "accept, choose or skip" in ib.choice_problem(r, "skip")
    assert "can only be skipped" in ib.choice_problem(k, c | {"cls": "conflict", "action": "choose", "mbid": T1})
    assert "not canonical" in ib.choice_problem(r | {"candidates": [RA]}, c | {"action": "choose", "mbid": RA.upper()})
    assert "not canonical" in ib.choice_problem(s, c | {"cls": "search", "action": "accept", "mbid": RA.upper()})
    assert "a skip has no mbid" in ib.choice_problem(r, c | {"action": "skip", "mbid": T1})
    assert "decided_by" in ib.choice_problem(r, c | {"action": "skip", "mbid": None, "decided_by": "worker"})
    assert "decided_by" in ib.choice_problem(r, {k: v for k, v in c.items() if k != "decided_by"}
                                             | {"action": "skip", "mbid": None})
