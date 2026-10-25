""".harness/check.sh: the sandboxed suite. Without HARNESS_SCRATCH it makes its own temp sandbox and removes it."""
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / ".harness" / "check.sh"


def _run(tmp_path, status, scratch=None):
    """check.sh with a stub pytest that records the sandbox it was given and exits with `status`."""
    stub = tmp_path / "pytest"
    stub.write_text(f'#!/bin/sh\necho "$MUSIC_ROOT" > "{tmp_path}/seen"\nexit {status}\n')
    stub.chmod(0o755)
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "HARNESS_SCRATCH"}
    env.update(PYTEST=str(stub), TMPDIR=str(tmpdir))
    if scratch:
        env["HARNESS_SCRATCH"] = str(scratch)
    out = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    return out, Path((tmp_path / "seen").read_text().strip()), tmpdir


def test_its_own_temp_sandbox_is_removed_and_the_status_kept(tmp_path):
    out, music, tmpdir = _run(tmp_path, 3)
    assert out.returncode == 3
    assert music.is_relative_to(tmpdir) and music.name == "music"
    assert list(tmpdir.iterdir()) == []


def test_a_harness_scratch_sandbox_is_left_for_the_harness(tmp_path):
    scratch = tmp_path / "scratch"
    out, music, _ = _run(tmp_path, 0, scratch)
    assert out.returncode == 0
    assert music == scratch / "sandbox" / "music" and music.is_dir()
