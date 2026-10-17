"""scripts/healthcheck.py (H1-02): Docker healthchecks for the crates and worker containers, run as a subprocess."""
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from crates.service import Config, CrateApp, CrateServer
from crates.store import CrateStore
from subsonic.fake_server import FakeSubsonicServer

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "healthcheck.py"


def check(*args, **env):
    full = {k: v for k, v in os.environ.items() if k not in ("CRATES_DB", "CRATES_PORT", "WORKER_POLL_S")}
    full.update(env)
    t0 = time.monotonic()
    p = subprocess.run([sys.executable, str(SCRIPT), *args], env=full, capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout + p.stderr, time.monotonic() - t0


def _closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# --- worker: the heartbeat's age ---

def _heartbeat(tmp_path, age_s):
    hb = tmp_path / "worker.heartbeat"
    hb.touch()
    t = time.time() - age_s
    os.utime(hb, (t, t))
    return dict(CRATES_DB=str(tmp_path / "crates.db"))


def test_worker_fresh_heartbeat_is_healthy(tmp_path):
    code, out, _ = check("worker", WORKER_POLL_S="30", **_heartbeat(tmp_path, 5))
    assert code == 0 and re.search(r"heartbeat [56] s old \(limit 90 s\)", out)


def test_worker_stale_heartbeat_is_unhealthy(tmp_path):
    code, out, _ = check("worker", WORKER_POLL_S="30", **_heartbeat(tmp_path, 95))
    assert code == 1 and re.search(r"heartbeat 9[5-9] s old \(limit 90 s\)", out)


def test_worker_missing_heartbeat_is_unhealthy(tmp_path):
    code, out, _ = check("worker", WORKER_POLL_S="30", CRATES_DB=str(tmp_path / "crates.db"))
    assert code == 1 and "no heartbeat" in out and str(tmp_path / "worker.heartbeat") in out


@pytest.mark.parametrize("poll, age, healthy", [("60", 170, True), ("60", 185, False),   # 3 × 60 s = 180 s
                                                ("5", 80, True), ("5", 95, False),       # at least 90 s
                                                (None, 80, True), (None, 95, False)])    # unset: 30, as the worker
def test_worker_limit_is_three_polls_and_at_least_90_s(tmp_path, poll, age, healthy):
    env = _heartbeat(tmp_path, age)
    if poll is not None:
        env["WORKER_POLL_S"] = poll
    assert check("worker", **env)[0] == (0 if healthy else 1)


def test_worker_without_crates_db_or_with_a_bad_poll_is_unhealthy_not_2(tmp_path):
    """Docker reserves exit 2: every failure, a usage error included, is 1."""
    code, out, _ = check("worker")
    assert code == 1 and "CRATES_DB" in out
    code, out, _ = check("worker", WORKER_POLL_S="soon", **_heartbeat(tmp_path, 1))
    assert code == 1 and "WORKER_POLL_S" in out
    code, out, _ = check("nonsense")
    assert code == 1 and "usage" in out
    assert check()[0] == 1


# --- crates: /api/status answers 200 within 5 s ---

def test_crates_is_healthy_when_status_answers_200():
    with FakeSubsonicServer() as fake:
        cfg = Config(subsonic_url=fake.url, username="demo", password="demo", db_path=":memory:", port=0)
        with CrateServer(CrateApp(cfg, store=CrateStore())) as srv:
            code, out, _ = check("crates", CRATES_PORT=str(srv.httpd.server_address[1]))
    assert code == 0 and "200" in out


def test_crates_ignores_a_proxy_in_the_environment():
    """127.0.0.1 is asked directly, even when Docker or the host sets http_proxy without no_proxy."""
    with FakeSubsonicServer() as fake:
        cfg = Config(subsonic_url=fake.url, username="demo", password="demo", db_path=":memory:", port=0)
        with CrateServer(CrateApp(cfg, store=CrateStore())) as srv:
            dead = f"http://127.0.0.1:{_closed_port()}"
            code, out, _ = check("crates", CRATES_PORT=str(srv.httpd.server_address[1]), http_proxy=dead,
                                 HTTP_PROXY=dead, no_proxy="", NO_PROXY="")
    assert code == 0, out


def test_crates_closed_port_is_unhealthy_within_6_s():
    code, out, took = check("crates", CRATES_PORT=str(_closed_port()))
    assert code == 1 and took < 6 and "/api/status" in out


def test_crates_502_is_unhealthy():
    """/api/status asks Navidrome: Navidrome down makes crates unhealthy too."""
    cfg = Config(subsonic_url=f"http://127.0.0.1:{_closed_port()}", username="x", password="y", db_path=":memory:", port=0)
    with CrateServer(CrateApp(cfg, store=CrateStore())) as srv:
        code, out, _ = check("crates", CRATES_PORT=str(srv.httpd.server_address[1]))
    assert code == 1 and "502" in out


def test_crates_that_never_answers_is_unhealthy_within_6_s():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)                                                         # accepts the connection, never answers
    held = []
    t = threading.Thread(target=lambda: held.append(s.accept()), daemon=True)
    t.start()
    try:
        code, out, took = check("crates", CRATES_PORT=str(s.getsockname()[1]))
    finally:
        s.close()
        for conn, _ in held:
            conn.close()
    assert code == 1 and took < 6 and "timed out" in out
