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
    curl = stub.parent / "curl"      # Gatus' API: answers once CURL_OK_AFTER calls have failed (unset: never answers)
    curl.write_text('#!/bin/sh\necho "$*" >> "$CURL_LOG"\nn=$(wc -l < "$CURL_LOG")\n'
                    '[ -n "$CURL_OK_AFTER" ] && [ "$n" -gt "$CURL_OK_AFTER" ] && { echo "[]"; exit 0; }\nexit 7\n')
    curl.chmod(0o755)
    return repo


def _deploy(repo, *services, answers_after="0"):
    t = repo.parent
    env = {**os.environ, "PATH": f"{t / 'bin'}:{os.environ['PATH']}", "DOCKER_LOG": str(t / "docker.log"),
           "GATUS_DIR": str(t / "gatus"), "CURL_LOG": str(t / "curl.log"), "GATUS_WAIT": "3"}
    env.pop("CURL_OK_AFTER", None)
    if answers_after is not None:
        env["CURL_OK_AFTER"] = answers_after
    out = subprocess.run(["bash", str(repo / "scripts" / "deploy.sh"), *services], capture_output=True, text=True,
                         env=env, timeout=30)
    out.docker = (t / "docker.log").read_text().splitlines() if (t / "docker.log").exists() else []
    out.config = t / "gatus" / "config" / "config.yaml"
    out.curl = (t / "curl.log").read_text().splitlines() if (t / "curl.log").exists() else []
    return out


def test_deploying_gatus_installs_the_commits_config_then_starts_only_gatus(repo):
    out = _deploy(repo, "gatus")
    assert out.returncode == 0, out.stderr
    assert out.config.read_bytes() == (repo / "deploy" / "gatus" / "config.yaml").read_bytes()
    assert sorted(p.name for p in out.config.parent.iterdir()) == ["config.yaml"]     # no temp file left behind
    assert any(line.endswith(" up -d --build --force-recreate gatus") for line in out.docker), out.docker


def test_the_next_gatus_deploy_replaces_the_config_and_keeps_the_previous_one(repo):
    assert _deploy(repo, "gatus").returncode == 0
    first = (repo / "deploy" / "gatus" / "config.yaml").read_text()
    (repo / "deploy" / "gatus" / "config.yaml").write_text("endpoints: []\n")
    _git(repo, "commit", "-q", "-am", "second")
    out = _deploy(repo, "gatus")
    assert out.returncode == 0, out.stderr
    assert out.config.read_text() == "endpoints: []\n"
    assert (out.config.parent / "config.yaml.prev").read_text() == first


def test_a_config_only_change_still_restarts_gatus_so_a_broken_config_fails_the_deploy(repo):
    # H3-05 review I-A: a plain `up -d` keeps the old process (same service definition), whose API answers at once,
    # and a bad file only fails at the next restart. --force-recreate makes Gatus load the new file now
    assert _deploy(repo, "gatus").returncode == 0
    (repo / "deploy" / "gatus" / "config.yaml").write_text("not: [valid\n")
    _git(repo, "commit", "-q", "-am", "broken")
    out = _deploy(repo, "gatus", answers_after=None)
    assert out.returncode == 1
    assert any(line.endswith(" up -d --build --force-recreate gatus") for line in out.docker), out.docker
    # how to put the last good one back: restore the copy, then recreate so Gatus loads it
    assert f"mv {repo.parent / 'gatus'}/config/config.yaml.prev {repo.parent / 'gatus'}/config/config.yaml" in out.stderr
    assert "up -d --force-recreate gatus" in out.stderr


def test_an_unwritable_gatus_directory_gets_the_chown_hint_not_a_bare_mkdir_error(repo):
    # Docker made /srv/docker/gatus root's before config/ existed: mkdir fails, the hint must still be printed
    g = repo.parent / "gatus"
    g.mkdir()
    g.chmod(0o555)
    try:
        out = _deploy(repo, "gatus")
    finally:
        g.chmod(0o755)
    assert out.returncode == 1
    assert "is not writable" in out.stderr and "sudo chown -R" in out.stderr
    assert out.docker == []


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


def test_a_gatus_deploy_waits_until_gatus_answers(repo):
    out = _deploy(repo, "gatus", answers_after="2")
    assert out.returncode == 0, out.stderr
    assert len(out.curl) == 3 and all("http://127.0.0.1:4590/api/v1/endpoints/statuses" in c for c in out.curl)
    assert "gatus answers" in out.stdout


def test_a_gatus_that_never_answers_fails_the_deploy_with_the_rollback(repo):
    # `up -d` exits 0 even when Gatus exits at start (e.g. GATUS_NTFY_TOPIC/GATUS_BACKUP_TOKEN unset)
    out = _deploy(repo, "gatus", answers_after=None)
    assert out.returncode == 1
    assert len(out.curl) == 3
    assert "did not answer" in out.stderr and "GATUS_BACKUP_TOKEN" in out.stderr
    assert "stop gatus" in out.stderr and "rm -f gatus" in out.stderr


def test_a_crates_deploy_does_not_wait_for_gatus(repo):
    out = _deploy(repo, answers_after=None)
    assert out.returncode == 0, out.stderr
    assert out.curl == []
