"""scripts/live-run.sh and scripts/live-check.sh: one-off worker commands in the image the worker was deployed from (R2).

A stub `docker` first on PATH records each call's argv (one JSON line per call, with GIT_SHA from its environment) to
$DOCKER_LOG and answers `inspect` from $STUB_REVISION ($STUB_NO_CONTAINER: no such container) and `image inspect`
from $STUB_NO_IMAGE. Nothing here runs the real one.
"""
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIVE_RUN = ROOT / "scripts" / "live-run.sh"
LIVE_CHECK = ROOT / "scripts" / "live-check.sh"
BASH = shutil.which("bash")      # absolute: one test runs with a PATH that has no docker on it
REV = "0123456789"
CHECK_CMD = "python3 -m scripts.export_playlists export && python3 -m scripts.export_playlists check"

STUB = r"""#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
with open(os.environ["DOCKER_LOG"], "a") as f:
    f.write(json.dumps({"argv": a, "GIT_SHA": os.environ.get("GIT_SHA")}) + "\n")
if a[:1] == ["inspect"]:
    if os.environ.get("STUB_NO_CONTAINER"):
        print("Error: No such object: " + a[-1], file=sys.stderr)
        sys.exit(1)
    print(os.environ.get("STUB_REVISION", ""))
elif a[:2] == ["image", "inspect"]:
    sys.exit(1 if os.environ.get("STUB_NO_IMAGE") else 0)
elif a[:1] == ["compose"]:
    print("compose ran")
    sys.exit(int(os.environ.get("STUB_COMPOSE_EXIT", "0")))
"""


@pytest.fixture
def stub(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(STUB)
    docker.chmod(0o755)
    return tmp_path


def _run(stub, script, *args, **env):
    full = {**os.environ, "PATH": f"{stub / 'bin'}:{os.environ['PATH']}", "DOCKER_LOG": str(stub / "docker.log"),
            "STUB_REVISION": REV}
    for k in ("GIT_SHA", "STUB_NO_CONTAINER", "STUB_NO_IMAGE", "STUB_COMPOSE_EXIT"):
        full.pop(k, None)
    full.update(env)
    out = subprocess.run([BASH, str(script), *args], capture_output=True, text=True, env=full, timeout=30)
    log = stub / "docker.log"
    out.calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    out.compose = [c for c in out.calls if c["argv"][:1] == ["compose"]]
    return out


def test_the_happy_path_runs_compose_in_the_deployed_image_with_the_command_verbatim(stub):
    out = _run(stub, LIVE_RUN, "python3", "-m", "scripts.duplicate_cleanup", "trash", "--dry-run")
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines()[0] == f"live-run: image dj-crates:{REV}"
    assert out.calls[0]["argv"] == ["inspect", "--type", "container", "-f", '{{index .Config.Labels "org.opencontainers.image.revision"}}',
                                    "dj-worker-1"]
    assert ["image", "inspect", f"dj-crates:{REV}"] in [c["argv"] for c in out.calls]
    assert len(out.compose) == 1
    assert out.compose[0]["GIT_SHA"] == REV
    assert out.compose[0]["argv"] == ["compose", "--project-directory", "/srv/docker", "run", "--rm", "--no-deps",
                                      "worker", "python3", "-m", "scripts.duplicate_cleanup", "trash", "--dry-run"]


def test_the_commands_exit_status_is_passed_on(stub):
    out = _run(stub, LIVE_RUN, "true", STUB_COMPOSE_EXIT="3")
    assert out.returncode == 3
    assert len(out.compose) == 1


def test_an_argument_with_spaces_reaches_compose_as_one_argument(stub):
    out = _run(stub, LIVE_RUN, "sh", "-c", "a && b")
    assert out.returncode == 0, out.stderr
    assert out.compose[0]["argv"][-3:] == ["sh", "-c", "a && b"]


def test_a_full_sha_label_is_cut_to_the_10_char_tag_deploy_sh_uses(stub):
    full = "0123456789abcdef0123456789abcdef01234567"
    out = _run(stub, LIVE_RUN, "true", STUB_REVISION=full)
    assert out.returncode == 0, out.stderr
    assert ["image", "inspect", "dj-crates:0123456789"] in [c["argv"] for c in out.calls]
    assert out.compose[0]["GIT_SHA"] == "0123456789"


def test_a_git_sha_in_the_callers_environment_does_not_win(stub):
    out = _run(stub, LIVE_RUN, "true", GIT_SHA="dev")
    assert out.compose[0]["GIT_SHA"] == REV


@pytest.mark.parametrize("env, reason", [
    ({"STUB_NO_CONTAINER": "1"}, "docker inspect dj-worker-1 failed"),
    ({"STUB_REVISION": ""}, "has no org.opencontainers.image.revision label"),
    ({"STUB_REVISION": "<no value>"}, "has no org.opencontainers.image.revision label"),   # Go's missing-key text
    ({"STUB_REVISION": "dev"}, "was built as 'dev'"),
    ({"STUB_NO_IMAGE": "1"}, f"image dj-crates:{REV} is not here"),
])
def test_each_refusal_exits_1_with_its_reason_and_never_calls_compose(stub, env, reason):
    out = _run(stub, LIVE_RUN, "true", **env)
    assert out.returncode == 1
    assert out.compose == []
    lines = out.stderr.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("live-run: refused: ") and reason in lines[0], out.stderr


def test_print_shows_the_exact_command_and_runs_no_compose(stub):
    out = _run(stub, LIVE_RUN, "--print", "sh", "-c", "a && b")
    assert out.returncode == 0, out.stderr
    assert out.compose == []
    line = out.stdout.strip().splitlines()[-1]
    assert shlex.split(line) == [f"GIT_SHA={REV}", "docker", "compose", "--project-directory", "/srv/docker", "run",
                                 "--rm", "--no-deps", "worker", "sh", "-c", "a && b"], line


def test_print_still_refuses_what_a_run_would_refuse(stub):
    out = _run(stub, LIVE_RUN, "--print", "true", STUB_REVISION="dev")
    assert out.returncode == 1
    assert out.compose == []


def test_no_command_is_a_usage_error(stub):
    out = _run(stub, LIVE_RUN)
    assert out.returncode == 2
    assert "usage" in out.stderr
    assert out.calls == []


def test_no_docker_on_path_is_refused(stub):
    (stub / "bin" / "docker").unlink()
    out = _run(stub, LIVE_RUN, "true", PATH=f"{stub / 'bin'}:/nonexistent")
    assert out.returncode == 1
    assert out.stderr.strip().splitlines() == ["live-run: refused: docker is not on PATH"], out.stderr


def test_live_check_runs_export_then_check_through_live_run(stub):
    out = _run(stub, LIVE_CHECK)
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines()[0] == f"live-run: image dj-crates:{REV}"
    assert len(out.compose) == 1
    assert out.compose[0]["GIT_SHA"] == REV
    assert out.compose[0]["argv"] == ["compose", "--project-directory", "/srv/docker", "run", "--rm", "--no-deps",
                                      "worker", "sh", "-c", CHECK_CMD]


def test_live_check_exits_with_the_checks_status(stub):
    out = _run(stub, LIVE_CHECK, STUB_COMPOSE_EXIT="1")
    assert out.returncode == 1
    assert len(out.compose) == 1


def test_live_check_print_runs_no_compose(stub):
    out = _run(stub, LIVE_CHECK, "--print")
    assert out.returncode == 0, out.stderr
    assert out.compose == []
    assert shlex.split(out.stdout.strip().splitlines()[-1])[-3:] == ["sh", "-c", CHECK_CMD]


def test_live_check_refuses_like_live_run(stub):
    out = _run(stub, LIVE_CHECK, STUB_REVISION="dev")
    assert out.returncode == 1
    assert out.compose == []


@pytest.mark.parametrize("args", [("",), ("--print", "junk"), ("--print", ""), ("junk",)])
def test_live_check_refuses_any_argument_but_a_lone_print(stub, args):
    out = _run(stub, LIVE_CHECK, *args)
    assert out.returncode == 2
    assert "usage" in out.stderr
    assert out.calls == []


def test_the_revision_is_read_from_the_container_not_an_image_or_volume_of_that_name(stub):
    out = _run(stub, LIVE_RUN, "true")
    assert out.calls[0]["argv"][:3] == ["inspect", "--type", "container"]


@pytest.mark.parametrize("label", ["development", "v1.2.3", "0123456789 "])
def test_a_label_that_is_not_a_hex_sha_is_refused(stub, label):
    out = _run(stub, LIVE_RUN, "true", STUB_REVISION=label)
    assert out.returncode == 1
    assert out.compose == []
    lines = out.stderr.strip().splitlines()
    assert len(lines) == 1 and "not a commit sha" in lines[0], out.stderr
