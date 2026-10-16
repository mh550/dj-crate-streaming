"""D21: the playlist's comment owns #crate and #tier; crates.db only caches them. Every setter writes the comment
first, reads it back, and only then touches the cache."""
import json

import pytest

from crates.reconcile import CommentNotKept, NameMarked, Reconciler
from crates.store import CrateStore
from sourcing import import_playlist as ip
from sourcing.playlist_sources import Row
from subsonic.client import SubsonicClient, SubsonicError
from subsonic.fake_server import FakeSubsonicServer
from tests.test_service import post, svc  # noqa: F401  (the svc fixture)


@pytest.fixture
def env():
    with FakeSubsonicServer() as srv:
        client = SubsonicClient(srv.url, "demo", "demo")
        store = CrateStore()
        yield srv, client, store, Reconciler(client, store)


def comment(srv, pid):
    return srv.state.playlists[pid]["comment"]


class DownOnWrite(SubsonicClient):
    def update_playlist(self, *a, **k):
        raise SubsonicError(0, "down")


class LosesOurToken(SubsonicClient):
    """A Navidrome (or another client, between our write and our read) that does not keep what we wrote."""
    written = False

    def update_playlist(self, *a, **k):
        super().update_playlist(*a, **k)
        self.written = True

    def playlist(self, pid):
        pl = super().playlist(pid)
        if self.written:
            pl.comment = (pl.comment or "").replace("#crate", "").replace("#tier:high", "").strip()
        return pl


def test_toggle_writes_the_comment_before_the_cache(env):
    srv, _, store, _ = env
    rec = Reconciler(DownOnWrite(srv.url, "demo", "demo"), store)
    with pytest.raises(SubsonicError):
        rec.set_crate("pl-1", True)
    assert store.get("pl-1") is None or not store.get("pl-1").enabled
    assert comment(srv, "pl-1") == ""


def test_toggle_keeps_the_rest_of_the_comment(env):
    srv, client, store, rec = env
    client.update_playlist("pl-1", comment="late set\nno vocals")
    assert rec.set_crate("pl-1", True)["crate"]
    assert comment(srv, "pl-1") == "late set\nno vocals #crate" and store.get("pl-1").enabled
    assert not rec.set_crate("pl-1", False)["crate"]
    assert comment(srv, "pl-1") == "late set\nno vocals" and not store.get("pl-1").enabled


def test_comment_wins_over_the_cache_and_the_disagreement_is_logged(env):
    srv, client, store, rec = env
    store.set_attrs("pl-1", "Disco Edits", True, None)
    rep = rec.run()
    assert not store.get("pl-1").enabled
    ev = [e for e in store.events(500) if e["kind"] == "attrs"]
    assert len(ev) == 1 and "comment wins" in ev[0]["detail"] and "Disco Edits" in ev[0]["detail"]
    assert any("Disco Edits" in x for x in rep.attr_changes)
    assert "Disco Edits" in rep.toggled_from_comment


def test_tier_tag_sets_the_cached_tier(env):
    srv, client, store, rec = env
    client.update_playlist("pl-3", comment="#tier:high")
    rec.run()
    assert store.get("pl-3").tier == "high" and not store.get("pl-3").enabled


def test_set_tier_writes_and_clears(env):
    srv, client, store, rec = env
    v = rec.set_tier("pl-3", "high")
    assert comment(srv, "pl-3") == "#tier:high" and v["tier"] == "high" and v["tierTag"] == "high"
    assert store.get("pl-3").tier == "high"
    v = rec.set_tier("pl-3", None)
    assert comment(srv, "pl-3") == "" and v["tier"] is None and store.get("pl-3").tier is None


def test_set_tier_again_does_not_write(env):
    srv, client, store, rec = env
    client.update_playlist("pl-3", comment="a #tier:medium b")
    srv.state.requests.clear()
    rec.set_tier("pl-3", "medium")
    assert comment(srv, "pl-3") == "a #tier:medium b"
    assert not [m for m, _ in srv.state.requests if m == "updatePlaylist"]


def test_tier_crate_is_the_crate_flag(env):
    srv, client, store, rec = env
    v = rec.set_tier("pl-3", "crate")
    assert comment(srv, "pl-3") == "#crate" and v["crate"] and v["tier"] == "crate"
    assert store.get("pl-3").enabled


def test_a_tier_change_keeps_a_crate_spelled_tier_crate(env):
    srv, client, store, rec = env
    client.update_playlist("pl-3", comment="#tier:crate")
    rec.run()
    v = rec.set_tier("pl-3", "high")
    assert v["crate"] and store.get("pl-3").enabled and store.get("pl-3").tier == "high"
    rec.set_tier("pl-3", None)
    assert store.get("pl-3").enabled


def test_name_marker_counts_but_cannot_be_turned_off_here(env, svc):  # noqa: F811
    srv, client, store, rec = env
    client.update_playlist("pl-3", name="Sunday Listening [crate]")
    rec.run()
    assert store.get("pl-3").enabled
    assert rec.crate_view(client.playlist("pl-3"))["crateByName"] is True
    with pytest.raises(NameMarked):
        rec.set_crate("pl-3", False)
    assert store.get("pl-3").enabled
    fake, app, http = svc
    fake.state.playlists["pl-3"]["name"] = "Sunday Listening [crate]"
    app.reconcile()
    s, r = post(http.url + "/api/playlists/pl-3/crate", {"enabled": False})
    assert s == 409 and "rename" in r["error"]


def test_readback_mismatch_refuses_and_keeps_the_cache(env):
    srv, client, store, _ = env
    rec = Reconciler(LosesOurToken(srv.url, "demo", "demo"), store)
    with pytest.raises(CommentNotKept):
        rec.set_crate("pl-3", True)
    assert store.get("pl-3") is None
    with pytest.raises(CommentNotKept):
        rec.set_tier("pl-3", "high")
    assert store.get("pl-3") is None


def test_readback_mismatch_over_http_is_502(svc, monkeypatch):  # noqa: F811
    fake, app, http = svc
    monkeypatch.setattr(app.reconciler, "client", LosesOurToken(fake.url, "demo", "demo"))
    s, r = post(http.url + "/api/playlists/pl-3/crate", {"enabled": True})
    assert s == 502 and app.store.get("pl-3") is None


def test_unknown_tier_tag_is_reported_not_applied(env):
    srv, client, store, rec = env
    client.update_playlist("pl-3", comment="#tier:hgh")
    srv.state.requests.clear()
    rep = rec.run()
    assert any("Sunday Listening" in p and "hgh" in p for p in rep.problems)
    assert store.get("pl-3") is None or store.get("pl-3").tier is None
    assert comment(srv, "pl-3") == "#tier:hgh"
    assert not [m for m, _ in srv.state.requests if m == "updatePlaylist"]
    assert [e for e in store.events(500) if e["kind"] == "attrs_problem"]


def test_service_tier_endpoint(svc):  # noqa: F811
    fake, app, http = svc
    s, v = post(http.url + "/api/playlists/pl-3/tier", {"tier": "high"})
    assert s == 200 and v["tier"] == "high" and fake.state.playlists["pl-3"]["comment"] == "#tier:high"
    s, r = post(http.url + "/api/playlists/pl-3/tier", {"tier": "hgh"})
    assert s == 400
    s, r = post(http.url + "/api/playlists/pl-3/tier", {"tier": 5})
    assert s == 400
    s, v = post(http.url + "/api/playlists/pl-3/tier", {"tier": None})
    assert s == 200 and v["tier"] is None and fake.state.playlists["pl-3"]["comment"] == ""


def test_crates_cli_tier(env, monkeypatch, tmp_path, capsys):
    srv, _, _, _ = env
    monkeypatch.setenv("SUBSONIC_URL", srv.url); monkeypatch.setenv("SUBSONIC_USER", "demo"); monkeypatch.setenv("SUBSONIC_PASS", "demo")
    monkeypatch.setenv("CRATES_DB", str(tmp_path / "c.db"))
    from crates.cli import main
    assert main(["tier", "pl-3", "medium"]) == 0
    assert json.loads(capsys.readouterr().out)["tier"] == "medium"
    assert comment(srv, "pl-3") == "#tier:medium"
    assert main(["tier", "pl-3", "none"]) == 0 and comment(srv, "pl-3") == ""
    capsys.readouterr()
    srv.state.playlists["pl-3"]["name"] = "Sunday Listening [crate]"
    assert main(["toggle", "pl-3", "off"]) == 1
    assert "rename" in capsys.readouterr().err


ROWS = [Row(1, "Bag Lady", "Erykah Badu", 347, "sp1")]


def _import(c, store, name, **kw):
    return ip.import_playlist(name, ROWS, c, store, source="s", **kw)


def test_import_creates_the_playlist_with_imported_and_tier(env):
    srv, c, store, _ = env
    a = _import(c, store, "Tea tent")
    assert comment(srv, a.playlist_id) == "#imported #tier:medium"
    assert store.get(a.playlist_id).tier == "medium" and not store.get(a.playlist_id).enabled
    b = _import(c, store, "Garden", tier="high")
    assert comment(srv, b.playlist_id) == "#imported #tier:high"
    _import(c, store, "Garden", tier="crate")
    assert comment(srv, b.playlist_id) == "#imported #crate"
    assert store.get(b.playlist_id).enabled
    _import(c, store, "Tea tent")
    assert comment(srv, a.playlist_id) == "#imported #tier:medium"


def test_import_rerun_with_tier_keeps_michaels_text(env):
    srv, c, store, _ = env
    a = _import(c, store, "Tea tent")
    c.update_playlist(a.playlist_id, comment="sunset only\n#imported #tier:medium")
    _import(c, store, "Tea tent", tier="medium")
    assert comment(srv, a.playlist_id) == "sunset only\n#imported #tier:medium"
    _import(c, store, "Tea tent", tier="low")
    assert comment(srv, a.playlist_id) == "sunset only\n#imported #tier:low"


def test_import_adopting_with_merge_adds_the_marker_and_the_tier(env):
    srv, c, store, _ = env
    existing = c.create_playlist("Tea tent", [])
    c.update_playlist(existing.id, comment="mine")
    _import(c, store, "Tea tent", merge=True)
    assert comment(srv, existing.id) == "mine #imported"
    c.update_playlist(existing.id, comment="mine")
    _import(c, store, "Tea tent", merge=True, tier="high")
    assert comment(srv, existing.id) == "mine #imported #tier:high"


# ---- Task 3 review

def _lossy(monkeypatch):
    """A Navidrome that stores the comment without our tokens: the read-back must catch it."""
    from crates import attrs
    real = SubsonicClient.update_playlist

    def lossy(self, pid, **k):
        if k.get("comment"):
            k["comment"] = attrs.write(k["comment"], crate=False, tier=None)
        return real(self, pid, **k)
    monkeypatch.setattr(SubsonicClient, "update_playlist", lossy)


ROWS2 = [Row(1, "Good Times", "Chic", None, "sp1"), Row(2, "Nope", "Nobody", None, "sp2")]


def test_import_create_whose_comment_is_not_kept_raises_but_keeps_our_own_facts(env, monkeypatch):
    srv, c, store, _ = env
    _lossy(monkeypatch)
    with pytest.raises(CommentNotKept) as e:
        ip.import_playlist("Tea tent", ROWS2, c, store, source="s")
    pid = e.value.report.playlist_id
    assert comment(srv, pid) == "#imported" and store.get(pid) is None            # nothing cached
    assert store.imported(pid) == {"s1"}                                           # our own DB facts are recorded
    assert [(x["title"], x["position"]) for x in store.external_for_playlist(pid)] == [("Nope", 2)]


def test_import_rerun_with_tier_whose_comment_is_not_kept_raises_and_keeps_the_cache(env, monkeypatch):
    srv, c, store, _ = env
    a = ip.import_playlist("Tea tent", ROWS2, c, store, source="s")
    assert store.get(a.playlist_id).tier == "medium" and not store.get(a.playlist_id).enabled
    _lossy(monkeypatch)
    with pytest.raises(CommentNotKept):
        ip.import_playlist("Tea tent", ROWS2, c, store, source="s", tier="high")
    assert store.get(a.playlist_id).tier == "medium"


def test_sourcing_cli_import_reports_a_comment_not_kept_and_exits_1(tmp_path, monkeypatch, capsys):
    from sourcing import cli
    db = tmp_path / "c.db"
    report = tmp_path / "r.txt"; report.write_text("[SUCCESS] Good Times - Chic\n[SUCCESS] Nope - Nobody\n")
    with FakeSubsonicServer() as nd:
        for k, v in dict(SUBSONIC_URL=nd.url, SUBSONIC_USER="demo", SUBSONIC_PASS="demo", CRATES_DB=str(db)).items():
            monkeypatch.setenv(k, v)
        _lossy(monkeypatch)
        assert cli.main(["import-playlist", str(report), "--name", "T"]) == 1
    out = capsys.readouterr()
    assert "1 matched, 1 wanted" in out.out and "Navidrome now has" in out.err
    assert [w["title"] for w in CrateStore(db).wanted()] == ["Nope"]


def test_a_standing_problem_is_logged_once(env):
    srv, client, store, rec = env
    client.update_playlist("pl-3", comment="#tier:hgh #tier:low #tier:high")
    for _ in range(3):
        assert len(rec.run().problems) == 2
    assert len([e for e in store.events(500) if e["kind"] == "attrs_problem"]) == 2
    client.update_playlist("pl-3", comment="")
    rec.run()
    client.update_playlist("pl-3", comment="#tier:hgh")
    rec.run(); rec.run()
    assert len([e for e in store.events(500) if e["kind"] == "attrs_problem"]) == 3   # it came back: logged again


def test_a_stale_snapshot_does_not_undo_a_toggle_made_after_it(env):
    srv, client, store, rec = env
    snap = client.playlists()
    rec.set_crate("pl-3", True)

    class Stale(SubsonicClient):
        def playlists(self):
            return snap
    rep = Reconciler(Stale(srv.url, "demo", "demo"), store).run()
    assert store.get("pl-3").enabled and rep.attr_changes == []
    assert "Sunday Listening" not in rep.toggled_from_comment
    assert not [e for e in store.events(500) if e["kind"] == "attrs"]


def test_a_crate_keeps_its_stored_tier_visible(env):
    srv, client, store, rec = env
    rec.set_crate("pl-3", True)
    v = rec.set_tier("pl-3", "high")
    assert (v["crate"], v["tier"], v["tierTag"]) == (True, "crate", "high")
    assert store.get("pl-3").tier == "high"
    v = rec.set_crate("pl-3", False)
    assert (v["crate"], v["tier"], v["tierTag"]) == (False, "high", "high")
