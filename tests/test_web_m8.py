"""M8 Task 10: the web client's tier menu and proposals (Swap / Keep).

There is no JS runner in the suite, so these check what the served files must contain (the ids the script binds
to, the endpoints it calls, the mappings for the error cases) and the API contract the script relies on.
`tests/` cannot see a phone: the screenshots at 375 px were taken by hand (see the commit message)."""
import json
import re
import urllib.error
import urllib.request

import pytest

from crates.service import Config, CrateApp, CrateServer
from crates.store import CrateStore
from subsonic.fake_server import FakeSubsonicServer


@pytest.fixture
def svc():
    with FakeSubsonicServer() as fake:
        cfg = Config(subsonic_url=fake.url, username="demo", password="demo", db_path=":memory:", port=0)
        app = CrateApp(cfg, store=CrateStore())
        with CrateServer(app) as srv:
            yield fake, app, srv


def fetch(url, obj=None):
    req = urllib.request.Request(url, data=None if obj is None else json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"}, method="GET" if obj is None else "POST")
    try:
        r = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        r = e
    return r.status, r.read().decode()


def asset(svc, name):
    return fetch(svc[2].url + "/" + name)[1]


def test_page_has_the_tier_menu_and_the_proposals_list(svc):
    html = asset(svc, "")
    assert re.search(r'<select[^>]*id="detail-tier"', html)
    for tier in ("low", "medium", "high"):
        assert f'value="{tier}"' in html.split('id="detail-tier"')[1].split("</select>")[0]
    assert 'id="detail-tier-note"' in html          # says why the menu is off for a crate
    assert 'id="proposals"' in html
    # the menu sits beside the crate switch, inside the detail head
    assert html.index('id="detail-crate"') < html.index('id="detail-tier"') < html.index('id="detail-summary"')


def test_script_calls_the_tier_and_proposal_endpoints(svc):
    js = asset(svc, "app.js")
    assert "/api/proposals" in js and "/accept" in js and "/decline" in js
    assert "/tier" in js and "detail-tier" in js
    assert "Swap" in js and "Keep" in js


def test_script_names_each_failure_in_the_words_the_brief_gave(svc):
    js = asset(svc, "app.js")
    assert "Navidrome didn't keep the change; nothing was changed here" in js      # 502
    assert "busy, try again" in js                                                  # 503
    assert "remove [crate]" in js                                                   # 409 on a name-marked crate
    assert "applies when crate is off" in js        # crate wins over a stored tier: the menu says so


def test_a_stale_accept_shows_its_reason_not_success(svc):
    js = asset(svc, "app.js")
    assert re.search(r"decision\s*(===|!==|==)\s*[\"']accepted[\"']|decision\s*===\s*[\"']stale[\"']", js)
    assert "r.result" in js or ".result" in js


def test_script_never_shows_a_peer_name(svc):
    js = asset(svc, "app.js")
    assert "username" not in js and ".peer" not in js


def test_wanted_tab_shows_review_rows_with_their_reason_and_no_buttons(svc):
    js = asset(svc, "app.js")
    assert '"review"' in js and "t.reason" in js


def test_phone_first_css(svc):
    css = asset(svc, "app.css")
    assert re.search(r"min-height:\s*(4\d|[5-9]\d)px", css)        # tap targets >= 40 px
    assert "overflow-wrap" in css or "word-break" in css          # long summaries wrap instead of scrolling the page
    assert "#proposals" in css or ".proposal" in css


# --- the API contract the script relies on ------------------------------------------------------------------------

def test_tier_endpoint_returns_the_view_the_menu_renders(svc):
    fake, app, srv = svc
    s, body = fetch(srv.url + "/api/playlists/pl-1/tier", {"tier": "high"})
    v = json.loads(body)
    assert s == 200 and v["tier"] == "high" and v["tierTag"] == "high" and v["crate"] is False
    # crate wins: the view says crate and still carries the stored tag, so the menu can explain itself
    s, body = fetch(srv.url + "/api/playlists/pl-1/crate", {"enabled": True})
    v = json.loads(body)
    assert s == 200 and v["crate"] is True and v["tier"] == "crate" and v["tierTag"] == "high"
    s, body = fetch(srv.url + "/api/playlists/pl-1")
    d = json.loads(body)
    assert d["crate"] is True and d["tier"] == "crate" and d["tierTag"] == "high" and d["crateByName"] is False


def test_a_bad_tier_is_a_400_with_a_message(svc):
    fake, app, srv = svc
    s, body = fetch(srv.url + "/api/playlists/pl-1/tier", {"tier": "ultra"})
    assert s == 400 and "error" in json.loads(body)


def test_proposals_list_is_empty_json_and_unknown_ids_are_errors(svc):
    fake, app, srv = svc
    assert json.loads(fetch(srv.url + "/api/proposals")[1]) == []
    s, body = fetch(srv.url + "/api/proposals/99/decline", {})
    assert s == 404 and "error" in json.loads(body)


def test_declining_twice_is_a_409_so_the_page_reloads(svc):
    fake, app, srv = svc
    pid = app.store.add_proposal(kind="version_swap", playlist_id="pl-1", position=0, old_song_id="s1",
                                 new_song_id="s2", summary="Disco Edits #1: a → b", new_path="x/b.flac")
    s, body = fetch(srv.url + f"/api/proposals/{pid}/decline", {})
    assert s == 200 and json.loads(body)["decision"] == "declined"
    s, body = fetch(srv.url + f"/api/proposals/{pid}/decline", {})
    assert s == 409 and "error" in json.loads(body)
