"""scripts/deploy.sh: builds from a clean commit; `deploy.sh gatus` installs that commit's Gatus config first (H3-04).

Each test builds a throwaway git repo holding the script and the Gatus config, puts a stub `docker` first on PATH
(it only records its arguments) and points GATUS_DIR into tmp, so nothing under /srv/docker is touched.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FILES = ["scripts/deploy.sh", "deploy/gatus/config.yaml"]


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "repo"
    for f in FILES:
        (repo / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, repo / f)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "first")
    stub = tmp_path / "bin" / "docker"
    stub.parent.mkdir()
    stub.write_text('#!/bin/sh\necho "GATUS_DIR=$GATUS_DIR $*" >> "$DOCKER_LOG"\n')
    stub.chmod(0o755)
    return repo


def _deploy(repo, *services):
    t = repo.parent
    env = {**os.environ, "PATH": f"{t / 'bin'}:{os.environ['PATH']}", "DOCKER_LOG": str(t / "docker.log"),
           "GATUS_DIR": str(t / "gatus")}
    out = subprocess.run(["bash", str(repo / "scripts" / "deploy.sh"), *services], capture_output=True, text=True,
                         env=env, timeout=30)
    out.docker = (t / "docker.log").read_text().splitlines() if (t / "docker.log").exists() else []
    out.config = t / "gatus" / "config" / "config.yaml"
    return out


def test_deploying_gatus_installs_the_commits_config_then_starts_only_gatus(repo):
    out = _deploy(repo, "gatus")
    assert out.returncode == 0, out.stderr
    assert out.config.read_bytes() == (repo / "deploy" / "gatus" / "config.yaml").read_bytes()
    assert sorted(p.name for p in out.config.parent.iterdir()) == ["config.yaml"]     # no temp file left behind
    assert any(line.endswith(" up -d --build gatus") for line in out.docker), out.docker


def test_the_next_gatus_deploy_replaces_the_config_with_the_new_commits(repo):
    assert _deploy(repo, "gatus").returncode == 0
    (repo / "deploy" / "gatus" / "config.yaml").write_text("endpoints: []\n")
    _git(repo, "commit", "-q", "-am", "second")
    out = _deploy(repo, "gatus")
    assert out.returncode == 0, out.stderr
    assert out.config.read_text() == "endpoints: []\n"


def test_compose_gets_the_same_gatus_directory(repo):
    out = _deploy(repo, "gatus")
    assert out.returncode == 0, out.stderr
    assert out.docker and all(line.startswith(f"GATUS_DIR={repo.parent / 'gatus'} ") for line in out.docker)


def test_gatus_is_deployed_on_its_own(repo):
    # a failed crates build after the config copy would leave Gatus checking images that never shipped
    out = _deploy(repo, "crates", "worker", "gatus")
    assert out.returncode == 1
    assert "deploy gatus on its own" in out.stderr
    assert not (repo.parent / "gatus").exists() and out.docker == []


def test_a_config_directory_mh550_cannot_write_is_refused_with_the_fix(repo):
    # Docker makes a missing bind-mount source root's; then only sudo can fix it, so say so and start nothing
    cfg = repo.parent / "gatus" / "config"
    cfg.mkdir(parents=True)
    cfg.chmod(0o555)
    try:
        out = _deploy(repo, "gatus")
    finally:
        cfg.chmod(0o755)
    assert out.returncode == 1
    assert f"{cfg} is not writable" in out.stderr and "sudo chown -R" in out.stderr
    assert out.docker == []


def test_a_dirty_tree_is_refused_before_anything_is_installed_or_started(repo):
    (repo / "deploy" / "gatus" / "config.yaml").write_text("endpoints: []\n")
    out = _deploy(repo, "gatus")
    assert out.returncode == 1
    assert "uncommitted changes" in out.stderr
    assert not out.config.parent.parent.exists() and out.docker == []


def test_a_config_that_cannot_be_written_stops_the_deploy_before_docker(repo):
    (repo.parent / "gatus").write_text("a file where the directory should be")
    out = _deploy(repo, "gatus")
    assert out.returncode != 0
    assert out.docker == []


def test_deploying_crates_and_worker_leaves_gatus_alone(repo):
    out = _deploy(repo)
    assert out.returncode == 0, out.stderr
    assert not (repo.parent / "gatus").exists()
    assert any(line.endswith("up -d --build crates worker") for line in out.docker), out.docker
