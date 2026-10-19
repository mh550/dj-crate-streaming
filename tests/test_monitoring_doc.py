"""docs/monitoring.md's table of checks matches deploy/gatus/config.yaml (H3-05), so the page can't drift from Gatus."""
import re
import sys
from pathlib import Path

import pytest

sys.path.append("/usr/lib/python3/dist-packages")
try:
    import yaml
except ImportError:                                    # only the config half needs PyYAML
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "monitoring.md"
CONFIG = ROOT / "deploy" / "gatus" / "config.yaml"


@pytest.fixture(scope="module")
def rows():
    """The table's rows by endpoint name: the cells after the first."""
    table = {}
    for line in DOC.read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) == 5 and not set(cells[0]) <= set("-") and cells[0] != "Endpoint":
            table[cells[0]] = cells[1:]
    return table


def _spoken(interval):
    """Gatus' `60s`, `30m`, `26h` as the doc writes them: `60 s`, `30 min`, `26 h`."""
    n, unit = re.fullmatch(r"(\d+)([smh])", interval).groups()
    return f"{n} {dict(s='s', m='min', h='h')[unit]}"


@pytest.fixture(scope="module")
def config():
    if yaml is None:
        pytest.skip("PyYAML missing")
    return yaml.safe_load(CONFIG.read_text())


def test_the_table_names_every_endpoint_in_the_config_and_no_other(rows, config):
    names = [e["name"] for e in config["endpoints"] + config["external-endpoints"]]
    assert sorted(rows) == sorted(names)


def test_each_http_row_has_its_url_interval_and_threshold(rows, config):
    for e in config["endpoints"]:
        how, every, _, alerts = rows[e["name"]]
        assert f"`{e['url']}`" in how
        assert every == _spoken(e["interval"])
        assert alerts == f"{e['alerts'][0]['failure-threshold']} failures in a row"


def test_each_pushed_row_has_its_heartbeat_and_threshold(rows, config):
    for e in config["external-endpoints"]:
        how, every, _, alerts = rows[e["name"]]
        assert "pushed" in how
        assert every == f"heartbeat {_spoken(e['heartbeat']['interval'])}"
        assert alerts.startswith(f"{e['alerts'][0]['failure-threshold']} failure, or no push for "
                                 f"{_spoken(e['heartbeat']['interval'])}")


def test_the_crates_row_states_the_worker_age_limit(rows, config):
    crates = next(e for e in config["endpoints"] if e["name"] == "crates")
    limit = re.search(r"workerHeartbeatAge < (\d+)", " ".join(crates["conditions"])).group(1)
    assert f"< {limit} s" in rows["crates"][2]


def test_the_doc_has_the_specs_sections():
    text = DOC.read_text()
    for heading in ("## What is checked, and how often", "## How alerts reach Michael", "## How to add a check",
                    "## Michael's one-time steps"):
        assert heading in text
    assert "systemctl --user enable --now dj-health-push.timer" in text
