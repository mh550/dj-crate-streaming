"""M8 Task 12: play-now in the web client (D20).

Pressing play on a queued track that is not in the library is Michael's approval for one fast copy, so the page must
say that it downloads, show progress (queued, downloading, checking, filed, playing), play when the file lands, say why
when it cannot, send exactly one request per tap, and poll gently. There is no JS runner in the suite: the static
tests check what the served files must contain, and the two pure functions the page polls with (the phase of a row,
the back-off) are run under node when it is installed. The screenshots at 375 px are taken by hand."""
import json
import re
import shutil
import subprocess
import textwrap
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


def get(url):
    try:
        r = urllib.request.urlopen(url)
    except urllib.error.HTTPError as e:
        r = e
    return r.status, r.read().decode()


def asset(svc, name):
    return get(svc[2].url + "/" + name)[1]


def test_script_posts_play_now_and_polls_the_row(svc):
    js = asset(svc, "app.js")
    assert "/play-now" in js
    assert re.search(r"api\(`/api/wanted/\$\{[^}]+\}`\)", js)            # GET /api/wanted/<id>
    assert "setTimeout" in js and "library_song_id" in js
    assert "playTrack(" in js                                             # the song that lands is streamed (/api/stream/)


def test_script_names_the_progress_states_in_order(svc):
    js = asset(svc, "app.js")
    m = re.search(r"const PN_STEPS = \[([^\]]*)\]", js)
    assert m and re.findall(r'"(\w+)"', m.group(1)) == ["queued", "downloading", "checking", "filed", "playing"]
    assert "fetching" in js


def test_the_tap_says_it_downloads(svc):
    js, css = asset(svc, "app.js"), asset(svc, "app.css")
    assert re.search(r"downloads a (quick|fast) copy", js)
    assert "aria-label" in js
    assert ".pn" in css                                                  # the progress strip is styled


def test_one_request_per_tap(svc):
    js = asset(svc, "app.js")
    assert "btn.disabled = true" in js                                    # disabled before the request is awaited
    assert re.search(r"if \(pn\[id\] && pn\[id\]\.active\) return", js)    # a second tap is dropped, never sent


def test_a_refusal_and_a_failure_are_shown_in_the_row(svc):
    js = asset(svc, "app.js")
    assert "e.status === 409" in js and "e.status === 404" in js
    assert "Not started" in js and "Couldn't reach" in js
    assert "alert(" not in js[js.index("// pn:begin"):js.index("// pn:end")]   # a message in the row, never a popup


def test_provisional_tracks_are_marked(svc):
    js = asset(svc, "app.js")
    assert "provisional" in js and "better copy" in js
    assert "t.provisional" in js


def test_polling_backs_off_and_stops_when_the_page_is_hidden(svc):
    js = asset(svc, "app.js")
    assert "visibilitychange" in js and "document.hidden" in js
    assert "function pnDelay" in js and "PN_GIVE_UP_MS" in js


def test_the_page_never_shows_a_peer_name(svc):
    js = asset(svc, "app.js")
    assert "username" not in js and ".peer" not in js


def test_audio_is_unlocked_on_the_tap_so_playback_can_start_later(svc):
    """A phone browser only lets a page start audio from a tap; the file lands seconds later, so the tap primes the
    audio element, and a refusal at playback time is said out loud (not a silent nothing)."""
    js = asset(svc, "app.js")
    assert "unlockAudio" in js and "data:audio/wav" in js
    assert "tap ▶ to play" in js


# --- the two pure functions, run for real ------------------------------------------------------------------------

node = shutil.which("node")


def run_js(svc, body: str):
    js = asset(svc, "app.js")
    src = js[js.index("// pn:begin"):js.index("// pn:pure-end")]      # only the functions with no DOM in them
    prog = src + "\n" + textwrap.dedent(body)
    out = subprocess.run([node, "-e", prog], capture_output=True, encoding="utf-8", errors="replace",
                         stdin=subprocess.DEVNULL, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def phases(svc, rows):
    return run_js(svc, f"console.log(JSON.stringify({json.dumps(rows)}.map(pnPhase)));")


@pytest.mark.skipif(node is None, reason="node not installed")
def test_phase_of_a_row(svc):
    pending = {"id": 1, "used_at": None, "result": None, "purpose": "play-now"}
    started = {"id": 1, "used_at": 5, "result": "started", "purpose": "play-now"}
    rows = [
        {"status": "needs_source", "approval": pending},                                         # just tapped
        {"status": "sourcing", "approval": started, "reason": "downloading x.mp3"},
        {"status": "needs_source", "approval": started},                                         # claimed, status not yet written
        {"status": "verify", "approval": started, "reason": "checking the download", "filed": False},
        {"status": "verify", "approval": started, "reason": "filed as x.mp3; waiting", "filed": True},
        {"status": "needs_source", "library_song_id": "s9", "provisional": 1, "approval": started},
        {"status": "failed", "reason": "no acceptable candidate", "approval": dict(started, result="failed: x")},
        {"status": "needs_source", "reason": "nothing found", "approval": dict(started, result="ok: nothing found")},
        {"status": "review", "reason": "ambiguous: pick a version"},
        {"status": "ok"},
        {"status": "needs_source", "approval": None},
        {"status": "sourcing", "approval": started, "reason": "checking x.mp3"},      # if the worker ever says so
    ]
    got = phases(svc, rows)
    assert [g["phase"] for g in got] == ["queued", "downloading", "downloading", "checking", "filed", "playing",
                                         "ended", "checking", "ended", "ended", "ended", "checking"]
    assert "no acceptable candidate" in got[6]["message"]
    assert "ambiguous" in got[8]["message"]
    assert got[10]["message"]                                                                    # never an empty reason


@pytest.mark.skipif(node is None, reason="node not installed")
def test_poll_delay_starts_at_two_seconds_and_stops_growing_at_ten(svc):
    d = run_js(svc, "console.log(JSON.stringify([0,1,2,3,4,5,20].map(pnDelay)));")
    assert d[0] == 2000 and d[-1] == 10000 and d == sorted(d) and max(d) == 10000
    assert 1 <= len([x for x in d if x < 10000]) <= 6
