"""Gatus (H3-02): the service in deploy/compose.yml and its checks in deploy/gatus/config.yaml.

The compose half reads `docker compose config` (no daemon needed) and skips where docker compose is missing; the
project directory is a tmp dir, so /srv/docker/.env is never read. The config half parses the YAML with Debian's
PyYAML. What Gatus itself does with the config (null ages, heartbeats, ntfy) was checked by hand against
twinproduction/gatus:v5.37.0; see the H3-02 progress entry.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.append("/usr/lib/python3/dist-packages")
yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "deploy" / "compose.yml"
CONFIG = ROOT / "deploy" / "gatus" / "config.yaml"
ENV_EXAMPLE = ROOT / "deploy" / ".env.example"
GATUS_VARS = {"GATUS_NTFY_TOPIC", "GATUS_BACKUP_TOKEN"}


def _compose_config(tmp_path_factory, **extra):
    if not shutil.which("docker") or subprocess.run(["docker", "compose", "version"], capture_output=True).returncode:
        pytest.skip("docker compose is not installed")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path_factory.mktemp("home")),
           "CRATES_SRC": str(ROOT), "GIT_SHA": "test", **extra}
    return subprocess.run(["docker", "compose", "--project-directory", str(tmp_path_factory.mktemp("proj")),
                           "-f", str(COMPOSE), "config", "--format", "json"],
                          env=env, capture_output=True, text=True, timeout=60)


@pytest.fixture(scope="module")
def gatus(tmp_path_factory):
    p = _compose_config(tmp_path_factory, GATUS_NTFY_TOPIC="topic-x", GATUS_BACKUP_TOKEN="token-x")
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)["services"]["gatus"]


@pytest.fixture(scope="module")
def config():
    return yaml.safe_load(CONFIG.read_text())


def test_gatus_is_pinned_to_a_v5_release(gatus):
    assert re.fullmatch(r"twinproduction/gatus:v5\.\d+\.\d+", gatus["image"]), gatus["image"]


def test_gatus_publishes_only_on_localhost_4590(gatus):
    assert [(p["host_ip"], p["published"], p["target"]) for p in gatus["ports"]] == [("127.0.0.1", "4590", 8080)]


def test_the_config_is_mounted_read_only_from_the_repo_and_history_from_srv_docker(gatus):
    mounts = {v["target"]: v for v in gatus["volumes"]}
    assert set(mounts) == {"/config", "/data"}
    # a directory, not the file: a git checkout replaces config.yaml (new inode), which a file mount wouldn't see
    assert mounts["/config"]["source"] == str(ROOT / "deploy" / "gatus")
    assert mounts["/config"]["read_only"] is True
    assert mounts["/data"]["source"] == "/srv/docker/gatus"
    assert not mounts["/data"].get("read_only")


def test_gatus_runs_as_mh550_restarts_and_depends_on_nothing(gatus):
    assert gatus["user"] == "1000:1000"                    # /srv/docker/gatus stays mh550's
    assert gatus["restart"] == "unless-stopped"
    assert "depends_on" not in gatus                       # `deploy.sh gatus` recreates no other container
    assert "network_mode" not in gatus                     # on the default network: it reaches services by name
    assert set(gatus.get("networks", {"default": None})) == {"default"}


def test_compose_passes_the_two_gatus_variables_from_the_env_file(gatus):
    assert gatus["environment"] == {"GATUS_NTFY_TOPIC": "topic-x", "GATUS_BACKUP_TOKEN": "token-x"}


def test_compose_still_works_for_the_other_services_when_the_gatus_variables_are_unset(tmp_path_factory):
    p = _compose_config(tmp_path_factory)
    assert p.returncode == 0, p.stderr
    assert {"navidrome", "crates", "worker"} <= set(json.loads(p.stdout)["services"])


# --- deploy/gatus/config.yaml: the spec's table ---

HTTP_CHECKS = {
    "navidrome": ("http://navidrome:4533/ping", ["[STATUS] == 200"]),
    "crates": ("http://crates:4580/api/status", ["[STATUS] == 200", "has([BODY].workerHeartbeatAge) == true",
                                                 "[BODY].workerHeartbeatAge < 180"]),
    "slskd": ("http://gluetun:5030/", ["[CONNECTED] == true", "[STATUS] < 500"]),
}


def test_the_http_checks_are_the_specs_table(config):
    assert {e["name"]: (e["url"], e["conditions"]) for e in config["endpoints"]} == HTTP_CHECKS


@pytest.mark.parametrize("name", sorted(HTTP_CHECKS))
def test_http_checks_run_every_60_s_and_alert_ntfy_after_3_failures_and_on_resolve(config, name):
    ep = next(e for e in config["endpoints"] if e["name"] == name)
    assert ep["interval"] == "60s"
    assert ep["alerts"] == [{"type": "ntfy", "failure-threshold": 3, "send-on-resolved": True}]


def test_the_backup_and_disk_external_endpoints_have_heartbeats_and_alert_at_once(config):
    ext = {e["name"]: e for e in config["external-endpoints"]}
    assert set(ext) == {"backup", "disk"}
    assert ext["backup"]["heartbeat"] == {"interval": "26h"}
    assert ext["disk"]["heartbeat"] == {"interval": "30m"}
    for e in ext.values():
        assert "group" not in e                            # key `_<name>`, what the pushers POST to
        assert e["alerts"] == [{"type": "ntfy", "failure-threshold": 1, "success-threshold": 1,
                                "send-on-resolved": True}]


def test_restic_backup_pushes_to_the_backup_endpoints_key():
    assert "${GATUS_BACKUP_KEY:-_backup}" in (ROOT / "deploy" / "restic-backup").read_text()


def test_alerts_go_to_the_ntfy_topic_from_the_environment(config):
    assert config["alerting"] == {"ntfy": {"topic": "${GATUS_NTFY_TOPIC}"}}
    assert all(e["token"] == "${GATUS_BACKUP_TOKEN}" for e in config["external-endpoints"])


def test_history_is_kept_in_sqlite_under_data(config):
    assert config["storage"] == {"type": "sqlite", "path": "/data/data.db"}


def test_a_broken_config_edit_does_not_stop_gatus(config):
    assert config["skip-invalid-config-update"] is True


def test_no_secret_literals_only_variable_names(config):
    text = CONFIG.read_text()
    # every $ is a ${NAME} reference to one of the two variables (Gatus expands them; $$ would be a literal)
    assert set(re.findall(r"\$\{([A-Z_]+)\}", text)) == GATUS_VARS
    assert text.count("$") == len(re.findall(r"\$\{[A-Z_]+\}", text))

    def secrets(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                yield from secrets(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from secrets(v, f"{path}[{i}]")
        elif re.search(r"(token|topic|password|secret|key|webhook)$", path.rsplit(".", 1)[-1]):
            yield path, node
    found = list(secrets(config))
    assert found and all(re.fullmatch(r"\$\{[A-Z_]+\}", v) for _, v in found), found


def test_env_example_lists_the_gatus_variables():
    names = {line.split("=", 1)[0] for line in ENV_EXAMPLE.read_text().splitlines()
             if "=" in line and not line.startswith("#")}
    assert GATUS_VARS <= names
