"""deploy/install-backup.sh: Michael's sudo install of the nightly backup, from a clean commit on main only.

Each test builds a throwaway git repo holding the three files (with a bare origin), and points the install targets
into tmp.
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FILES = ["deploy/install-backup.sh", "deploy/restic-backup", "scripts/snapshot-crates-db.sh"]


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "repo"
    for f in FILES:
        (repo / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, repo / f)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "first")
    _git(tmp_path, "clone", "-q", "--bare", str(repo), str(tmp_path / "origin.git"))
    _git(repo, "remote", "add", "origin", str(tmp_path / "origin.git"))
    _git(repo, "fetch", "-q", "origin")
    return repo


def _commit(repo, msg, push=True):
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-am", msg)
    if push:
        _git(repo, "push", "-q", "origin", "HEAD:main")


def _run(repo, answer="y\n"):
    t = repo.parent / "target"
    env = {**os.environ, "RESTIC_BACKUP_TARGET": str(t / "sbin" / "restic-backup"),
           "SNAPSHOT_TARGET": str(t / "lib" / "dj-crates" / "snapshot-crates-db.sh")}
    out = subprocess.run(["bash", str(repo / "deploy" / "install-backup.sh")], input=answer, capture_output=True,
                         text=True, env=env, timeout=30)
    out.backup = t / "sbin" / "restic-backup"
    out.snapshot = t / "lib" / "dj-crates" / "snapshot-crates-db.sh"
    return out


def test_clean_main_shows_the_diff_asks_and_installs_both_files(repo):
    out = _run(repo)
    assert out.returncode == 0, out.stderr
    assert "+set -euo pipefail" in out.stdout                  # a diff against nothing installed yet
    assert "install these? [y/N]" in out.stdout + out.stderr
    for installed, src in ((out.backup, "deploy/restic-backup"), (out.snapshot, "scripts/snapshot-crates-db.sh")):
        assert installed.read_bytes() == (repo / src).read_bytes()
        assert stat.S_IMODE(installed.stat().st_mode) == 0o755
    assert _git(repo, "rev-parse", "--short=10", "HEAD") in out.stdout.splitlines()[-1]


def test_the_diff_is_against_what_is_installed(repo):
    _run(repo)
    with open(repo / "deploy" / "restic-backup", "a") as f:
        f.write("echo new-line\n")
    _commit(repo, "second")
    out = _run(repo)
    assert out.returncode == 0, out.stderr
    assert "+echo new-line" in out.stdout
    assert "snapshot-crates-db.sh: unchanged" in out.stdout
    assert out.backup.read_text().endswith("echo new-line\n")


def test_a_capital_y_installs(repo):
    assert _run(repo, answer="Y\n").returncode == 0


def test_answering_no_installs_nothing(repo):
    out = _run(repo, answer="n\n")
    assert out.returncode == 1
    assert not out.backup.exists() and not out.snapshot.exists()


def test_no_answer_installs_nothing(repo):
    out = _run(repo, answer="")
    assert out.returncode == 1
    assert not out.backup.exists()


def test_nothing_to_do_when_already_installed(repo):
    _run(repo)
    out = _run(repo, answer="")
    assert out.returncode == 0
    assert "already installed" in out.stdout
    assert "[y/N]" not in out.stdout + out.stderr


def test_a_target_whose_mode_changed_is_installed_again(repo):
    # Same content but group-writable: whoever can write it can change what root runs nightly.
    first = _run(repo)
    first.backup.chmod(0o775)
    out = _run(repo)
    assert out.returncode == 0, out.stderr
    assert "already installed" not in out.stdout
    assert stat.S_IMODE(first.backup.stat().st_mode) == 0o755


@pytest.mark.parametrize("dirt", ["modified", "untracked"])
def test_a_dirty_tree_is_refused_before_any_diff(repo, dirt):
    if dirt == "modified":
        with open(repo / "deploy" / "restic-backup", "a") as f:
            f.write("echo loose-edit\n")
    else:
        (repo / "stray.txt").write_text("x")
    out = _run(repo)
    assert out.returncode == 1
    assert "uncommitted" in out.stderr
    assert "loose-edit" not in out.stdout and not out.backup.exists()


def test_a_commit_not_on_main_is_refused(repo):
    _git(repo, "checkout", "-q", "-b", "harness/x")
    with open(repo / "deploy" / "restic-backup", "a") as f:
        f.write("echo branch-only\n")
    _commit(repo, "branch", push=False)
    out = _run(repo)
    assert out.returncode == 1
    assert "not a commit on origin/main" in out.stderr
    assert not out.backup.exists()


def test_an_unpushed_commit_on_local_main_is_refused(repo):
    with open(repo / "deploy" / "restic-backup", "a") as f:
        f.write("echo unreviewed\n")
    _commit(repo, "local only", push=False)
    out = _run(repo)
    assert out.returncode == 1
    assert "not a commit on origin/main" in out.stderr
    assert not out.backup.exists()


def test_an_older_main_commit_may_be_installed_to_roll_back(repo):
    first = _git(repo, "rev-parse", "HEAD")
    with open(repo / "deploy" / "restic-backup", "a") as f:
        f.write("echo newer\n")
    _commit(repo, "second")
    _git(repo, "checkout", "-q", first)
    out = _run(repo)
    assert out.returncode == 0, out.stderr
    assert "echo newer" not in out.backup.read_text()


def test_it_never_rewrites_gits_index(repo):
    """Under sudo in mh550's checkout, a status that refreshes the index could leave .git/index owned by root."""
    index = repo / ".git" / "index"
    os.utime(index, (1_000_000_000, 1_000_000_000))
    os.utime(repo / "deploy" / "restic-backup")           # same content, newer stat: a plain status would refresh
    before = index.stat().st_mtime_ns
    assert _run(repo).returncode == 0
    assert index.stat().st_mtime_ns == before
