"""R5-03: the playlist-health banner (M9 §7).

After each export the worker stores, per playlist, how many entries point at a missing file (R5-01); `/api/status`
carries them as `playlistHealth`. The page shows one line per playlist under the header and hides the banner when the
list is empty. There is no JS runner in the suite: the static tests check what the served files must contain, and the
pure function that words the lines is run under node when it is installed (as tests/test_web_play_now.py does). The
375 px screenshot is docs/screenshots/r5-health-banner.png."""
import json
import re
import shutil
import subprocess
import urllib.request

import pytest

from crates.service import Config, CrateApp, CrateServer
from crates.store import CrateStore
from sourcing.fake_slskd import FakeSlskdServer
from sourcing.slskd_client import SlskdClient
from sourcing.worker import Worker
from subsonic.fake_server import FakeSubsonicServer
from tests.test_fetch import RESPONSES, header_only, world  # noqa: F401  (world: fixture)


@pytest.fixture
def svc():
    with FakeSubsonicServer() as fake:
        cfg = Config(subsonic_url=fake.url, username="demo", password="demo", db_path=":memory:", port=0)
        app = CrateApp(cfg, store=CrateStore())
        with CrateServer(app) as srv:
            yield fake, app, srv


def asset(svc, name):
    return urllib.request.urlopen(svc[2].url + "/" + name).read().decode()


def test_page_has_a_hidden_health_banner_under_the_header(svc):
    html = asset(svc, "")
    assert '<div id="health" class="banner hidden"></div>' in html
    assert html.index("</header>") < html.index('id="health"') < html.index('<nav class="tabs">')


def test_script_fills_the_banner_from_playlist_health_in_the_worker_words(svc):
    js = asset(svc, "app.js")
    load = js[js.index("async function loadStatus"):js.index("// ---- playlists")]
    assert "playlistHealth" in load and "#health" in load
    assert "point at missing files" in js and "points at a missing file" in js
    assert 'toggle("hidden", !lines.length)' in load                   # hidden again once the list empties
    assert "HTML" not in load                                          # playlist names are text, never markup


def test_status_reloads_when_the_page_comes_back(svc):
    """The worker recounts every export; a phone tab left open picks up the new count when it is shown again."""
    js = asset(svc, "app.js")
    assert re.search(r'addEventListener\("visibilitychange",[^\n]*visibilityState === "visible"[^\n]*loadStatus\(\)', js)


def test_banner_css_is_full_width_and_wraps(svc):
    css = asset(svc, "app.css")
    rule = re.search(r"\.banner\s*\{([^}]*)\}", css)
    assert rule, "no .banner rule"
    assert "overflow-wrap:anywhere" in rule.group(1).replace(" ", "")     # a long name never scrolls sideways
    assert not re.search(r"\.banner[^{]*\{[^}]*(?<![-\w])width:\s*\d+px", css)


node = shutil.which("node")


def health_lines(svc, rows):
    js = asset(svc, "app.js")
    src = js[js.index("// health:begin"):js.index("// health:end")]          # the pure function, no DOM
    prog = src + f"\nconsole.log(JSON.stringify(healthLines({json.dumps(rows)})));"
    out = subprocess.run([node, "-e", prog], capture_output=True, encoding="utf-8", stdin=subprocess.DEVNULL, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(node is None, reason="node not installed")
def test_one_line_per_playlist_singular_for_one_entry(svc):
    rows = [{"id": "pl-1", "name": "Tea tent", "missing": 2}, {"id": "pl-2", "name": "Chicago 86", "missing": 1}]
    assert health_lines(svc, rows) == ["2 entries in Tea tent point at missing files",
                                       "1 entry in Chicago 86 points at a missing file"]
    assert health_lines(svc, []) == []
    assert health_lines(svc, None) == []                                # a status from before R5-01 has no key


def test_status_after_a_worker_export_carries_the_two_rows(world):
    world["nd"].state.missing = {"s2"}
    world["nd"].state.sync()
    with FakeSlskdServer(RESPONSES, world["dl"], files={}) as srv:
        Worker(store=world["store"], slskd=SlskdClient(srv.url, "k"), navidrome=world["client"], reconciler=world["rec"],
               fetch_kwargs=dict(music_root=world["music"], downloads_root=world["dl"], filer=world["filer"],
                                 verifier=header_only, poll_s=0.01, download_timeout_s=1, scan_timeout_s=1,
                                 navidrome_db=world["nd"].state.db_path, trash_root=world["trash"]),
               log=lambda line: None, export_s=300, clock=lambda: 1000.0).tick()
    cfg = Config(subsonic_url=world["nd"].url, username="demo", password="demo", db_path=":memory:", port=0)
    with CrateServer(CrateApp(cfg, store=world["store"])) as srv:
        status = json.loads(urllib.request.urlopen(srv.url + "/api/status").read())
    assert status["playlistHealth"] == [{"id": "pl-1", "name": "Disco Edits", "missing": 1},
                                        {"id": "pl-3", "name": "Sunday Listening", "missing": 1}]
