"""deploy/compose.yml (H1-03): navidrome, crates and worker have healthchecks, and crates/worker wait for navidrome.

Reads `docker compose config` (no daemon needed), so it skips where docker compose is missing. The project directory
is a tmp dir, so /srv/docker/.env is never read.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "deploy" / "compose.yml"


def _seconds(go_duration):
    """'1m30s' → 90.0, '10s' → 10.0 (what `docker compose config --format json` prints)."""
    units = {"h": 3600, "m": 60, "s": 1, "ms": 0.001}
    parts = re.findall(r"([\d.]+)(ms|h|m|s)", go_duration)
    assert parts and "".join(n + u for n, u in parts) == go_duration, go_duration
    return sum(float(n) * units[u] for n, u in parts)


@pytest.fixture(scope="module")
def services(tmp_path_factory):
    if not shutil.which("docker") or subprocess.run(["docker", "compose", "version"], capture_output=True).returncode:
        pytest.skip("docker compose is not installed")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path_factory.mktemp("home")),
           "CRATES_SRC": str(ROOT), "GIT_SHA": "test"}
    p = subprocess.run(["docker", "compose", "--project-directory", str(tmp_path_factory.mktemp("proj")),
                        "-f", str(COMPOSE), "config", "--format", "json"],
                       env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)["services"]


@pytest.mark.parametrize("name", ["crates", "worker"])
def test_crates_and_worker_run_the_healthcheck_script(services, name):
    hc = services[name]["healthcheck"]
    assert hc["test"] == ["CMD", "python", "scripts/healthcheck.py", name]
    assert (ROOT / "scripts" / "healthcheck.py").is_file()
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "WORKDIR /app" in dockerfile and "COPY scripts/ scripts/" in dockerfile


def test_navidrome_answers_ping_with_the_wget_in_its_image(services):
    hc = services["navidrome"]["healthcheck"]
    assert hc["test"][0] == "CMD" and hc["test"][1] == "wget"
    assert hc["test"][-1] == "http://127.0.0.1:4533/ping"


@pytest.mark.parametrize("name", ["navidrome", "crates", "worker"])
def test_timings_leave_room_for_the_checks_own_timeouts(services, name):
    hc = services[name]["healthcheck"]
    # healthcheck.py gives up after 5 s per socket operation; Docker must not kill it first
    assert _seconds(hc["timeout"]) >= 10
    assert _seconds(hc["interval"]) >= _seconds(hc["timeout"])
    assert hc["retries"] >= 3
    # healthy as soon as the first check passes: Docker checks every start_interval during start_period
    assert _seconds(hc["start_interval"]) <= 10


def test_the_worker_gets_a_start_period_longer_than_a_first_tick(services):
    assert _seconds(services["worker"]["healthcheck"]["start_period"]) >= 120


@pytest.mark.parametrize("name", ["crates", "worker"])
def test_crates_and_worker_wait_for_a_healthy_navidrome(services, name):
    assert services[name]["depends_on"]["navidrome"]["condition"] == "service_healthy"


def test_the_worker_still_starts_after_gluetun(services):
    assert services["worker"]["depends_on"]["gluetun"]["condition"] == "service_started"
