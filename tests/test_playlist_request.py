"""S2-07: a playlist in one go. The import as today (sourcing.import_playlist) records a `playlist` request over its
wanted rows (sourcing.requests.add_playlist; add_spotify for a Spotify playlist URL); one approval covers all its open
rows: rows sharing artist and album, 3 or more, go as one album job (sourcing.album_job, S2-05), the rest per track.

The playlist is a copy of the Tea tent embed with six tracks: four of Al Green's "I'm Still in Love With You" (1-4) at
positions 2, 3, 5 and 6, and two others. The embed's playlist shape has no album field, so the rows go through an
Exportify CSV made from it (`rows_from_csv`), a shape that carries the album, as `import-playlist` reads one."""
import csv
import io
import json
import re
from pathlib import Path

import pytest

from sourcing import album_job, cli
from sourcing.fake_slskd import FakeSlskdServer
from sourcing.filer import BeetsFiler
from sourcing.import_playlist import import_playlist
from sourcing.playlist_sources import rows_from_csv
from sourcing.requests import add_playlist, add_spotify
from sourcing.slskd_client import SlskdClient
from tests.helpers import beets_items_db, fake_beet
from tests.test_album_job import ALBUM, DIR, PEER, album_folder, entity as album_entity, flac_bytes, worker
from tests.test_fetch import world, not_in_library  # noqa: F401  (fixtures)
from tests.helpers import load_responses

FIXTURES = Path(__file__).parent.parent / "fixtures"
URL = "https://open.spotify.com/playlist/37i9dQZF1DXtea"
SINGLES = "singlespeer"
SAMPLE = load_responses()


def playlist_entity():
    """Tea tent with six tracks: The Weasil, Al Green 1, 2, Morning Thoughts, Al Green 3, 4."""
    tea = json.loads((FIXTURES / "spotify_embed_tea-tent-1.json").read_text())
    al = album_entity()["trackList"]
    weasil, morning = tea["trackList"][:2]
    green = [dict(t, subtitle="Al Green") for t in al[:4]]
    tea["trackList"] = [weasil, green[0], green[1], morning, green[2], green[3]]
    return tea


def exportify(entity) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Track URI", "Track Name", "Artist Name(s)", "Album Name", "Duration (ms)"])
    for t in entity["trackList"]:
        w.writerow([t["uri"], t["title"], t["subtitle"], ALBUM if t["subtitle"] == "Al Green" else "", t["duration"]])
    return out.getvalue()


def imported(world):
    """The import as `import-playlist` runs it: every row is wanted (nothing of it is in the fake library)."""
    rows = rows_from_csv(exportify(playlist_entity()))
    rep = import_playlist("Tea tent", rows, world["client"], world["store"], source=URL)
    assert (rep.matched, rep.wanted) == (0, 6)
    return rep


def playlist_request(world):
    rep = imported(world)
    req = add_spotify(world["store"], URL, fetch=lambda url: playlist_entity(), playlist_id=rep.playlist_id)
    return rep, req


def test_a_spotify_playlist_import_records_one_playlist_request_over_its_wanted_rows(world):
    store = world["store"]
    rep, req = playlist_request(world)
    assert req["kind"] == "playlist" and req["source"] == URL and req["album"] == "Tea tent"
    assert [(r["title"], r["position"], r["playlist_id"], r["track_no"]) for r in req["rows"]] == [
        ("The Weasil", 1, rep.playlist_id, None), ("I'm Still In Love With You", 2, rep.playlist_id, None),
        ("I'm Glad You're Mine", 3, rep.playlist_id, None), ("Morning Thoughts", 4, rep.playlist_id, None),
        ("Love And Happiness", 5, rep.playlist_id, None), ("What A Wonderful Thing Love Is", 6, rep.playlist_id, None)]
    assert {r["request_id"] for r in req["rows"]} == {req["id"]}
    assert [r["album"] for r in req["rows"]].count(ALBUM) == 4
    assert req["status"] == "open"


def test_the_same_playlist_again_finds_its_request(world):
    store = world["store"]
    rep, req = playlist_request(world)
    again = add_spotify(store, URL + "?si=abc", fetch=lambda url: playlist_entity(), playlist_id=rep.playlist_id)
    assert again["id"] == req["id"] and len(again["rows"]) == 6
    assert len([r for r in store.requests() if r["kind"] == "playlist"]) == 1


def test_a_playlist_without_its_import_is_no_request(world):
    assert add_spotify(world["store"], URL, fetch=lambda url: playlist_entity()) is None


def test_an_import_with_no_wanted_row_records_no_request(world):
    store = world["store"]
    assert add_playlist(store, "pl-none", source=URL, name="Tea tent") is None
    assert store.requests() == []


def test_a_re_import_s_new_rows_join_and_dropped_rows_leave(world):
    """The request is the playlist's last import: a track added on Spotify joins, one dropped leaves (unless it is
    being fetched, which a request never takes back)."""
    store = world["store"]
    rep, req = playlist_request(world)
    weasil, morning = req["rows"][0]["song_id"], req["rows"][3]["song_id"]
    store.approve(weasil, "michael", None, "medium")                 # going: stays the request's
    tea = playlist_entity()
    tea["trackList"] = [t for t in tea["trackList"] if t["title"] not in ("Morning Thoughts", "The Weasil")]
    tea["trackList"].append(dict(tea["trackList"][0], title="Simply Beautiful", uri="spotify:track:new", duration=255666))
    import_playlist("Tea tent", rows_from_csv(exportify(tea)), world["client"], store, source=URL)
    again = add_playlist(store, rep.playlist_id, source=URL, name="Tea tent")
    titles = [r["title"] for r in again["rows"]]
    assert "Simply Beautiful" in titles and "Morning Thoughts" not in titles and "The Weasil" in titles
    assert again["id"] == req["id"] and store.external(morning)["request_id"] is None


def test_two_playlists_from_files_of_one_name_are_two_requests(world):
    """A file source is no identity (a new export, a generic report.txt): the playlist's name is."""
    store = world["store"]
    rows = rows_from_csv(exportify(playlist_entity()))
    a = import_playlist("Gym", rows[:3], world["client"], store, source="export.csv")
    b = import_playlist("Chill", rows[3:], world["client"], store, source="export.csv")
    ra = add_playlist(store, a.playlist_id, source="export.csv", name="Gym")
    rb = add_playlist(store, b.playlist_id, source="export.csv", name="Chill")
    assert ra["id"] != rb["id"] and len(store.request(ra["id"])["rows"]) == 3 and len(rb["rows"]) == 3


def test_a_spotify_playlist_url_s_rows_have_no_album_so_every_row_goes_per_track(world, not_in_library):
    """The playlist embed has no album field (rows_from_spotify): its request has no album group. Albums come from
    an Exportify CSV or a SpotiFLAC report of the playlist."""
    from sourcing.playlist_sources import rows_from_spotify
    store = world["store"]
    rep = import_playlist("Tea tent", rows_from_spotify(playlist_entity()), world["client"], store, source=URL)
    req = add_spotify(store, URL, fetch=lambda url: playlist_entity(), playlist_id=rep.playlist_id)
    assert album_job.groups(req) == [] and len(album_job.per_track(req)) == 6
    album_job.approve_request(store, req["id"])
    assert {a["purpose"] for a in store.pending_approvals()} == {"download"}


def test_an_album_asked_for_later_takes_the_playlist_s_rows_not_yet_going(world, not_in_library):
    """A playlist request holds its rows only loosely: an album request takes those not approved yet, so the album
    files as one (S2-06's album tags and path); a row being fetched stays with the playlist."""
    store = world["store"]
    _, req = playlist_request(world)
    held = req["rows"][1]["song_id"]                                 # I'm Still In Love With You, approved already
    store.approve(held, "michael", None, "medium")
    alb = add_spotify(store, "https://open.spotify.com/album/2nTlIPIQ7fHOnNN7BRch0Z", fetch=lambda url: album_entity())
    assert alb["kind"] == "album" and len(alb["rows"]) == 8
    ids = {r["song_id"] for r in alb["rows"]}
    assert {req["rows"][i]["song_id"] for i in (2, 4, 5)} <= ids and held not in ids
    assert [r["track_no"] for r in alb["rows"] if r["title"] == "Love And Happiness"] == [3]
    left = store.request(req["id"])["rows"]
    assert [r["title"] for r in left] == ["The Weasil", "I'm Still In Love With You", "Morning Thoughts"]
    taken = next(r for r in alb["rows"] if r["title"] == "Love And Happiness")
    assert (taken["playlist_id"], taken["position"]) == (req["rows"][4]["playlist_id"], 5)    # placement unchanged


def test_an_album_whose_rows_a_playlist_holds_still_gets_its_own_request(world, not_in_library):
    store = world["store"]
    _, req = playlist_request(world)
    one = album_entity()
    one["trackList"] = one["trackList"][:4]
    alb = add_spotify(store, "https://open.spotify.com/album/2nTlIPIQ7fHOnNN7BRch0Z", fetch=lambda url: one)
    assert alb["id"] != req["id"] and alb["kind"] == "album" and len(alb["rows"]) == 4


def test_ambiguous_rows_are_no_open_rows_of_a_playlist(world, not_in_library):
    """An import's `review` row (ambiguous: the library may have it) is a question no download answers: it counts
    toward no album group and gets no approval."""
    store = world["store"]
    _, req = playlist_request(world)
    for i in (1, 2):
        store.set_wanted_status(req["rows"][i]["song_id"], "review", "ambiguous (several versions): s1, s2")
    req = store.request(req["id"])
    assert album_job.groups(req) == [] and len(album_job.per_track(req)) == 4
    ids = album_job.approve_request(store, req["id"])
    assert len(ids) == 4 and {a["purpose"] for a in store.pending_approvals()} == {"download"}


def test_a_row_another_request_holds_stays_with_it(world):
    store = world["store"]
    rep = imported(world)
    first = store.external_for_playlist(rep.playlist_id)[1]["song_id"]
    other = store.add_request(kind="track", source="x", artist="Al Green", album=None, year=None)
    store.add_external_wanted("Al Green", "I'm Still In Love With You", request_id=other)
    store.commit()
    req = add_playlist(store, rep.playlist_id, source=URL, name="Tea tent")
    assert first not in [r["song_id"] for r in req["rows"]] and len(req["rows"]) == 5
    assert store.external(first)["request_id"] == other


def test_only_the_import_s_last_rows_join(world):
    """A row of an earlier import the playlist no longer lists (import_order replaced) is not the request's."""
    store = world["store"]
    rep = imported(world)
    stray = store.add_external_wanted("Nobody", "Gone", playlist_id=rep.playlist_id, position=9)
    store.commit()
    req = add_playlist(store, rep.playlist_id, source=URL, name="Tea tent")
    assert stray not in [r["song_id"] for r in req["rows"]]


def test_approve_request_groups_three_or_more_rows_of_one_album(world, not_in_library):
    store = world["store"]
    _, req = playlist_request(world)
    ids = album_job.approve_request(store, req["id"])
    assert len(ids) == 6
    purpose = {a["wanted_id"]: a["purpose"] for a in store.pending_approvals()}
    rows = req["rows"]
    assert [purpose[r["song_id"]] for r in rows] == ["download", "album", "album", "download", "album", "album"]
    assert store.request(req["id"])["status"] == "approved"


def test_two_rows_of_one_album_go_per_track(world, not_in_library):
    store = world["store"]
    _, req = playlist_request(world)
    store.set_wanted_status(req["rows"][1]["song_id"], "ok", "already in the library: x (s7)")
    store.set_wanted_status(req["rows"][2]["song_id"], "ok", "already in the library: y (s8)")
    album_job.approve_request(store, req["id"])
    assert {a["purpose"] for a in store.pending_approvals()} == {"download"}


def test_album_and_artist_group_loosely(world, not_in_library):
    """`identity.loose`: case, accents and "&" do not split a group."""
    groups = album_job.groups({"kind": "playlist", "rows": [
        {"song_id": "ext-1", "artist": "Al Green", "album": ALBUM, "status": "needs_source", "reason": None},
        {"song_id": "ext-2", "artist": "AL GREEN", "album": ALBUM.lower(), "status": "needs_source", "reason": None},
        {"song_id": "ext-3", "artist": "Al Green", "album": f"{ALBUM}!", "status": "needs_source", "reason": None},
        {"song_id": "ext-5", "artist": "Beyoncé & Jay-Z", "album": "Café", "status": "needs_source", "reason": None},
        {"song_id": "ext-6", "artist": "Beyonce and Jay Z", "album": "cafe", "status": "needs_source", "reason": None},
        {"song_id": "ext-7", "artist": "BEYONCE & JAY-Z", "album": "Café!", "status": "needs_source", "reason": None},
        {"song_id": "ext-4", "artist": "Chic", "album": None, "status": "needs_source", "reason": None}]})
    assert [[r["song_id"] for r in g["rows"]] for g in groups] == [["ext-1", "ext-2", "ext-3"], ["ext-5", "ext-6", "ext-7"]]


def single(directory: str, artist: str, title: str, seconds: int, tmp_path) -> tuple[dict, dict]:
    """One response from SINGLES with one file `<directory>\\<artist> - <title>.flac`."""
    r = json.loads(json.dumps(SAMPLE[0]))
    r.update(username=SINGLES, hasFreeUploadSlot=True, uploadSpeed=2_000_000)
    name = f"{directory}\\{artist} - {title}.flac"
    data = {name: flac_bytes(tmp_path, seconds)}
    r["files"] = [dict(SAMPLE[0]["files"][0], filename=name, extension="flac", bitRate=900, length=seconds,
                       size=len(data[name]))]
    return r, data


def playlist_filer(world, tmp_path):
    """beets as fake_beet: every file lands in `<artist>/Singles/<title>.flac`, as a playlist request's rows do
    (fetch.album_identity is None for them: no album tags, no album path); an album file is song `alNN` (its number
    in the folder), a single `sg-<n>`. Navidrome then lists it with that file's size."""
    nd, lib = world["nd"], beets_items_db(tmp_path / "playlist-library.db")

    def target(src: Path) -> str:
        m = re.search(r" - (\d\d) - (.+)\.flac$", src.name)
        if m:
            n, title = m.groups()
            sid, artist, album = f"al{n}", "Al Green", ALBUM
        else:
            artist, title = re.fullmatch(r"(.+) - (.+)\.flac", src.name).groups()
            sid, album = f"sg-{len(nd.state.songs)}", None
        rel = f"{artist}/Singles/{title}.flac"
        nd.state.songs[sid] = dict(nd.state.songs["s1"], id=sid, title=title, artist=artist, album=album,
                                   suffix="flac", size=src.stat().st_size, path=rel, duration=0)
        nd.state.unscanned.add(sid)
        return rel

    return BeetsFiler(tmp_path / "beets.yaml", library=lib, runner=fake_beet(world["music"], lib, target),
                      tagger=lambda path, names: [])


def test_a_mixed_playlist_runs_as_one_album_job_and_two_singles(world, tmp_path, not_in_library):
    store = world["store"]
    rep, req = playlist_request(world)
    rows = req["rows"]
    green = [dict(r, track_no=n) for n, r in enumerate((rows[1], rows[2], rows[4], rows[5]), 1)]
    resp, data = album_folder(tmp_path, green)
    weasil, d1 = single("@@music\\Donald Byrd", "Donald Byrd", "The Weasil", rows[0]["duration"], tmp_path)
    morning, d2 = single("@@music\\Gil Scott-Heron", "Gil Scott-Heron", "Morning Thoughts", rows[3]["duration"], tmp_path)
    with FakeSlskdServer([resp, weasil, morning], world["dl"], files=data | d1 | d2) as srv:
        album_job.approve_request(store, req["id"])
        w = worker(world, srv, tmp_path)
        w.common["filer"] = playlist_filer(world, tmp_path)
        report = w.tick()
    assert sorted(srv.posts) == sorted([(PEER, 4), (SINGLES, 1), (SINGLES, 1)])
    assert f"Al Green {ALBUM}" in srv.searched                           # the group's album search
    done = store.request(req["id"])
    assert [r["status"] for r in done["rows"]] == ["ok"] * 6, [(r["status"], r["reason"]) for r in done["rows"]]
    assert done["status"] == "done" and report.approvals == 6
    plans = [e["detail"] for e in store.events(limit=1000) if e["kind"] == "plan"]
    assert plans == [f"#{req['id']} Al Green — {ALBUM}: folder 1: 4 of 4"]
    # N4: the import's placement puts every filed row at its Spotify position
    songs = world["nd"].state.playlists[rep.playlist_id]["songs"]
    ids = [r["library_song_id"] for r in done["rows"]]
    assert ids[1:3] == ["al01", "al02"] and ids[4:] == ["al03", "al04"]
    assert songs == ids
    assert PEER not in json.dumps(report.results) and DIR not in json.dumps(report.results)


def test_an_album_approval_whose_row_left_its_group_is_fetched_per_track_without_a_plan(world, tmp_path, not_in_library):
    from sourcing.fetch import FetchResult
    from tests.test_album_job import common
    store = world["store"]
    _, req = playlist_request(world)
    album_job.approve_request(store, req["id"])
    row = req["rows"][1]["song_id"]
    store.db.execute("UPDATE external_wanted SET album=NULL WHERE id=?", (int(row.removeprefix("ext-")),))
    store.commit()
    calls = []

    def spy(wanted_id, **kw):
        calls.append((wanted_id, kw.get("planned", False), kw.get("prefer")))
        return FetchResult("needs_source", "spied")

    [a] = [a for a in store.pending_approvals() if a["wanted_id"] == row]
    with FakeSlskdServer([], world["dl"], files={}) as srv:
        out = album_job.run(req["id"], [a], **common(world, srv, tmp_path, fetcher=spy))
    assert calls == [(row, False, None)] and srv.searched == [] and [o for _, o in out] == ["needs_source: spied"]
    assert not [e for e in store.events(limit=1000) if e["kind"] == "plan"]
    assert store.approval(row)["result"] == "needs_source: spied"


def test_a_playlist_request_s_preview_plans_each_album_group(world, tmp_path, not_in_library):
    store = world["store"]
    _, req = playlist_request(world)
    rows = req["rows"]
    green = [dict(r, track_no=n) for n, r in enumerate((rows[1], rows[2], rows[4], rows[5]), 1)]
    resp, data = album_folder(tmp_path, green)
    with FakeSlskdServer([resp], world["dl"], files=data) as srv:
        shown = album_job.plan_request(store, SlskdClient(srv.url, srv.api_key), req["id"], poll_s=0.01)
    assert srv.searched == [f"Al Green {ALBUM}"] and srv.enqueued == []
    [group] = shown["albums"]
    assert (group["artist"], group["album"]) == ("Al Green", ALBUM)
    assert [(f["label"], f["covers"]) for f in group["folders"]] == [("folder 1", "4 of 4")]
    assert [r["title"] for r in shown["per_track"]] == ["The Weasil", "Morning Thoughts"]
    assert PEER not in json.dumps(shown)
    ids = album_job.approve_request(store, req["id"])                 # the cached plan's files are the candidates
    cand = {a["wanted_id"]: a["candidate"] for a in store.pending_approvals()}
    assert cand[rows[1]["song_id"]]["basename"].endswith(" - 01 - I'm Still In Love With You.flac")
    assert cand[rows[0]["song_id"]] is None and len(ids) == 6


# --- the CLI

def _env(monkeypatch, nd, db):
    monkeypatch.setenv("SUBSONIC_URL", nd.url); monkeypatch.setenv("SUBSONIC_USER", "demo"); monkeypatch.setenv("SUBSONIC_PASS", "demo")
    monkeypatch.setenv("CRATES_DB", str(db))


def test_cli_import_playlist_request_records_the_playlist_request(tmp_path, monkeypatch, capsys):
    from crates.store import CrateStore
    from subsonic.fake_server import FakeSubsonicServer
    db = tmp_path / "crates.db"
    src = tmp_path / "Tea tent.csv"
    src.write_text(exportify(playlist_entity()))
    with FakeSubsonicServer() as nd:
        _env(monkeypatch, nd, db)
        assert cli.main(["import-playlist", "--request", str(src)]) == 0
        out = capsys.readouterr().out
    [req] = CrateStore(db).requests()
    assert req["kind"] == "playlist" and req["album"] == "Tea tent" and len(req["rows"]) == 6
    assert (f"request {req['id']}: Tea tent (6 open rows; approve with sourcing.cli request approve {req['id']})"
            in out)


def test_cli_import_playlist_from_a_spotify_url_keys_the_request_by_its_canonical_url(tmp_path, monkeypatch, capsys):
    from crates.store import CrateStore
    from subsonic.fake_server import FakeSubsonicServer
    db = tmp_path / "crates.db"
    monkeypatch.setattr(cli, "fetch_entity", lambda url: playlist_entity())
    with FakeSubsonicServer() as nd:
        _env(monkeypatch, nd, db)
        assert cli.main(["import-playlist", "--request", URL + "?si=x"]) == 0
    [req] = CrateStore(db).requests()
    assert req["source"] == URL and len(req["rows"]) == 6


def test_cli_import_playlist_without_request_records_none(tmp_path, monkeypatch, capsys):
    from crates.store import CrateStore
    from subsonic.fake_server import FakeSubsonicServer
    db = tmp_path / "crates.db"
    src = tmp_path / "Tea tent.csv"
    src.write_text(exportify(playlist_entity()))
    with FakeSubsonicServer() as nd:
        _env(monkeypatch, nd, db)
        assert cli.main(["import-playlist", str(src)]) == 0
        assert "request" not in capsys.readouterr().out
        assert cli.main(["import-playlist", "--request", "--dry-run", str(src)]) == 0
        assert "no request recorded" in capsys.readouterr().out
    assert CrateStore(db).requests() == []


def two_albums(world, tmp_path):
    """Tea tent plus three tracks of Al Green's "Call Me" (5-7 in their folder, from another peer). Returns
    (request, [responses], files)."""
    from tests.test_album_job import DIR_B
    store = world["store"]
    tea = playlist_entity()
    more = [dict(t, subtitle="Al Green") for t in album_entity()["trackList"][4:7]]
    tea["trackList"] += more
    text = exportify(tea).splitlines()
    text = text[:7] + [line.replace(f",{ALBUM},", ",Call Me,") for line in text[7:]]
    rep = import_playlist("Tea tent", rows_from_csv("\n".join(text) + "\n"), world["client"], store, source=URL)
    req = add_playlist(store, rep.playlist_id, source=URL, name="Tea tent")
    rows = req["rows"]
    assert [r["album"] for r in rows[6:]] == ["Call Me"] * 3
    first = [dict(r, track_no=n) for n, r in enumerate((rows[1], rows[2], rows[4], rows[5]), 1)]
    second = [dict(r, track_no=n) for n, r in enumerate(rows[6:], 5)]
    a, da = album_folder(tmp_path, first)
    b, db = album_folder(tmp_path, second, peer="callmepeer", directory=DIR_B)
    return req, [a, b], da | db


def test_two_albums_in_one_playlist_are_two_plans(world, tmp_path, not_in_library):
    """Each album group has its own cached plan (`req-<id>:<group>`), so approving takes each row's file from its own."""
    store = world["store"]
    req, responses, files = two_albums(world, tmp_path)
    rows = req["rows"]
    with FakeSlskdServer(responses, world["dl"], files=files) as srv:
        shown = album_job.plan_request(store, SlskdClient(srv.url, srv.api_key), req["id"], poll_s=0.01)
    assert [(g["album"], g["folders"][0]["covers"]) for g in shown["albums"]] == [(ALBUM, "4 of 4"), ("Call Me", "3 of 3")]
    album_job.approve_request(store, req["id"])
    cand = {x["wanted_id"]: x["candidate"] for x in store.pending_approvals()}
    assert cand[rows[1]["song_id"]]["basename"].endswith(" - 01 - I'm Still In Love With You.flac")
    assert cand[rows[6]["song_id"]]["basename"].endswith(" - 05 - Simply Beautiful.flac")


def test_two_albums_in_one_playlist_run_as_two_jobs(world, tmp_path, not_in_library):
    from tests.test_album_job import common
    store = world["store"]
    req, responses, files = two_albums(world, tmp_path)
    album_job.approve_request(store, req["id"])
    albums = [a for a in store.pending_approvals() if a["purpose"] == "album"]
    with FakeSlskdServer(responses, world["dl"], files=files) as srv:
        out = album_job.run(req["id"], albums, **common(world, srv, tmp_path))
    assert sorted(srv.posts) == [("callmepeer", 3), (PEER, 4)]
    assert sorted(srv.searched) == [f"Al Green Call Me", f"Al Green {ALBUM}"]
    assert len(out) == 7 and all(o.startswith("ok: ") for _, o in out), out
    assert sorted(e["detail"] for e in store.events(limit=1000) if e["kind"] == "plan") == [
        f"#{req['id']} Al Green — Call Me: folder 1: 3 of 3", f"#{req['id']} Al Green — {ALBUM}: folder 1: 4 of 4"]


def test_a_switch_inside_a_playlist_s_album_searches_that_album_again(world, tmp_path, not_in_library):
    from tests.test_album_job import DIR_B, PEER_B, common, switches, verifier_failing
    store = world["store"]
    _, req = playlist_request(world)
    rows = req["rows"]
    green = [dict(r, track_no=n) for n, r in enumerate((rows[1], rows[2], rows[4], rows[5]), 1)]
    a, da = album_folder(tmp_path, green)
    b, db = album_folder(tmp_path, green, peer=PEER_B, directory=DIR_B, speed=1_000_000)
    album_job.approve_request(store, req["id"])
    albums = [x for x in store.pending_approvals() if x["purpose"] == "album"]
    with FakeSlskdServer([a, b], world["dl"], files=da | db) as srv:
        out = album_job.run(req["id"], albums, **common(world, srv, tmp_path, verifier=verifier_failing("transcode", 2)))
    assert srv.searched == [f"Al Green {ALBUM}"] * 2                     # the plan's, then the switch's fresh one
    [sw] = switches(store)
    assert sw.startswith(f"#{req['id']} Al Green — {ALBUM}: folder 1 distrusted: transcode (") and sw.endswith(
        "; 3 rows → folder 2")
    assert all(o.startswith("ok: ") for _, o in out), out


def test_cli_a_comment_navidrome_did_not_keep_still_records_the_request(tmp_path, monkeypatch, capsys):
    """The import's rows are recorded before CommentNotKept: so is the request, and the CLI says so."""
    from crates.reconcile import CommentNotKept
    from crates.store import CrateStore
    from subsonic.fake_server import FakeSubsonicServer
    import sourcing.import_playlist as ip
    real = ip.import_playlist

    def not_kept(*a, **kw):
        e = CommentNotKept("Tea tent: comment not kept")
        e.report = real(*a, **kw)
        raise e

    monkeypatch.setattr(ip, "import_playlist", not_kept)
    db = tmp_path / "crates.db"
    src = tmp_path / "Tea tent.csv"
    src.write_text(exportify(playlist_entity()))
    with FakeSubsonicServer() as nd:
        _env(monkeypatch, nd, db)
        assert cli.main(["import-playlist", "--request", str(src)]) == 1
        out = capsys.readouterr().out
    [req] = CrateStore(db).requests()
    assert f"request {req['id']}: Tea tent (6 open rows;" in out


def test_a_playlist_request_s_album_group_over_http(world, tmp_path, not_in_library):
    """S3-03: `POST /api/requests/<id>/preview` of a playlist answers each album group's plan and the per-track rows;
    `GET /api/requests/<id>` shows the same; neither names a peer."""
    from crates.service import Config, CrateApp, CrateServer
    from tests.test_service import get, post
    store = world["store"]
    _, req = playlist_request(world)
    rows = req["rows"]
    green = [dict(r, track_no=n) for n, r in enumerate((rows[1], rows[2], rows[4], rows[5]), 1)]
    resp, data = album_folder(tmp_path, green)
    with FakeSlskdServer([resp], world["dl"], files=data) as srv:
        app = CrateApp(Config(subsonic_url=world["nd"].url, username="demo", password="demo", db_path=":memory:",
                              port=0), store=store, slskd=SlskdClient(srv.url, srv.api_key))
        with CrateServer(app) as web:
            s, body = post(web.url + f"/api/requests/{req['id']}/preview", {})
            detail = get(web.url + f"/api/requests/{req['id']}")[2]
    assert s == 200 and detail["preview"] == body["plan"]
    [group] = body["plan"]["albums"]
    assert (group["artist"], group["album"]) == ("Al Green", ALBUM) and group["ts"] > 0
    assert [(f["label"], f["coverage"]) for f in group["folders"]] == [("folder 1", "4 of 4")]
    assert [r["id"] for r in group["folders"][0]["rows"]] == [rows[i]["song_id"] for i in (1, 2, 4, 5)]
    assert group["perTrack"] == []
    assert body["plan"]["perTrack"] == [rows[0]["song_id"], rows[3]["song_id"]]
    assert PEER not in json.dumps(body) and PEER not in json.dumps(detail) and "username" not in json.dumps(body)
