"""deploy/restic-backup: the nightly backup takes the live lock, snapshots with the installed script, then backs up.

Stub restic, mountpoint, curl and sudo sit first on PATH and append one line each to a log; the env file, the lock,
the snapshot script and the lock wait come from environment variables, so nothing here reads /etc/restic or runs
a real backup.
"""
import fcntl
import os
import stat
import subprocess
import threading
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "restic-backup"

# Each stub logs its name and whether the live lock is held right now (a fresh open conflicts with any holder).
LOCK_STATE = 'if flock -n "$LIVE_LOCK" true 2>/dev/null; then st=free; else st=held; fi'
STUBS = {
    "restic": f'{LOCK_STATE}; echo "restic $1 lock=$st" >>"$STUB_LOG"; [ "${{RESTIC_FAIL:-}}" != "$1" ]',
    "mountpoint": 'echo "mountpoint $*" >>"$STUB_LOG"; [ "${MOUNTED:-1}" = 1 ]',
    "curl": 'echo "curl $* stdin=$(cat)" >>"$STUB_LOG"; [ "${CURL_FAIL:-0}" = 0 ]',
    "sudo": 'echo "sudo $*" >>"$STUB_LOG"; [ "$1" = -u ] && shift 2; exec "$@"',
}
SNAPSHOT = f'{LOCK_STATE}; echo "snapshot lock=$st" >>"$STUB_LOG"; [ "${{SNAPSHOT_FAIL:-0}}" = 0 ]'


def _me():
    return subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()


def _write_exe(path, body):
    path.write_text("#!/usr/bin/env bash\n" + body + "\n")
    path.chmod(0o755)


@pytest.fixture
def box(tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, body in STUBS.items():
        _write_exe(bin_ / name, body)
    _write_exe(tmp_path / "snapshot-crates-db.sh", SNAPSHOT)
    (tmp_path / "env").write_text("RESTIC_REPOSITORY=/nowhere\nRESTIC_PASSWORD_FILE=/nowhere\n")
    (tmp_path / "lockdir").mkdir()
    return tmp_path


def _run(box, env_file_extra="", **env):
    if env_file_extra:
        with open(box / "env", "a") as f:
            f.write(env_file_extra)
    full = {k: v for k, v in os.environ.items() if not k.startswith(("GATUS_", "RESTIC_", "LIVE_LOCK"))}
    full.update({
        "PATH": f"{box / 'bin'}:{os.environ['PATH']}",
        "STUB_LOG": str(box / "log"),
        "RESTIC_ENV_FILE": str(box / "env"),
        "LIVE_LOCK": str(box / "lockdir" / "live.lock"),
        "SNAPSHOT_SCRIPT": str(box / "snapshot-crates-db.sh"),
        "BACKUP_USER": _me(),
    })
    full.update(env)
    start = time.monotonic()
    out = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=full, timeout=60)
    out.took = time.monotonic() - start
    out.log = (box / "log").read_text().splitlines() if (box / "log").exists() else []
    return out


def _names(log):
    return [line.split(" lock=")[0].replace(" -u", "") for line in log if not line.startswith("sudo")]


def test_order_is_lock_snapshot_mount_backup_unlock_then_forget_and_check(box):
    out = _run(box)
    assert out.returncode == 0, out.stderr
    assert out.log == [
        f"sudo -u {_me()} {box / 'snapshot-crates-db.sh'}",
        "snapshot lock=held",
        "mountpoint -q /mnt/backup",
        "restic backup lock=held",
        "restic forget lock=free",     # the lock is released once the backup is written
        "restic check lock=free",
    ]


def test_unmounted_drive_exits_1_and_sends_no_heartbeat(box):
    out = _run(box, "GATUS_BACKUP_URL=http://gatus\nGATUS_BACKUP_TOKEN=t0k\n", MOUNTED="0")
    assert out.returncode == 1
    assert "not mounted" in out.stdout + out.stderr
    assert not any(line.startswith(("restic", "curl")) for line in out.log)


def test_restic_backup_failure_fails_the_run_and_sends_no_heartbeat(box):
    out = _run(box, "GATUS_BACKUP_URL=http://gatus\nGATUS_BACKUP_TOKEN=t0k\n", RESTIC_FAIL="backup")
    assert out.returncode != 0
    assert "restic backup lock=held" in out.log
    assert not any(line.startswith(("curl", "restic forget")) for line in out.log)


@pytest.mark.parametrize("step", ["forget", "check"])
def test_a_failed_forget_or_check_sends_no_heartbeat(box, step):
    out = _run(box, "GATUS_BACKUP_URL=http://gatus\nGATUS_BACKUP_TOKEN=t0k\n", RESTIC_FAIL=step)
    assert out.returncode != 0
    assert not any(line.startswith("curl") for line in out.log)


def test_success_pushes_the_heartbeat_to_gatus_with_the_token(box):
    out = _run(box, "GATUS_BACKUP_URL=http://gatus:8080/\nGATUS_BACKUP_TOKEN=t0k\n")
    assert out.returncode == 0, out.stderr
    curl = [line for line in out.log if line.startswith("curl")]
    assert len(curl) == 1 and out.log[-1] == curl[0]          # after forget and check
    args, stdin = curl[0].split(" stdin=")
    assert "-X POST" in args and "-H @-" in args and "t0k" not in args     # ps never shows the token
    assert stdin == "Authorization: Bearer t0k"
    assert args.endswith(" http://gatus:8080/api/v1/endpoints/_backup/external?success=true")
    assert "t0k" not in out.stdout + out.stderr               # the token is never printed


def test_no_gatus_settings_means_no_heartbeat_and_success(box):
    out = _run(box)
    assert out.returncode == 0
    assert not any(line.startswith("curl") for line in out.log)


def test_a_failed_heartbeat_warns_and_the_backup_still_succeeds(box):
    out = _run(box, "GATUS_BACKUP_URL=http://gatus\nGATUS_BACKUP_TOKEN=t0k\n", CURL_FAIL="1")
    assert out.returncode == 0
    assert "WARNING: heartbeat to Gatus failed" in out.stdout + out.stderr


def test_a_failed_snapshot_warns_and_the_backup_still_runs(box):
    out = _run(box, SNAPSHOT_FAIL="1")
    assert out.returncode == 0, out.stderr
    assert "WARNING: DB snapshot failed" in out.stdout + out.stderr
    assert "restic backup lock=held" in out.log


def test_by_default_it_runs_the_installed_snapshot_script_as_mh550(box):
    out = _run(box, SNAPSHOT_SCRIPT="", BACKUP_USER="")
    assert "sudo -u mh550 /usr/local/lib/dj-crates/snapshot-crates-db.sh" in out.log


def test_a_missing_snapshot_script_warns_and_the_backup_still_runs(box):
    out = _run(box, SNAPSHOT_SCRIPT=str(box / "nope.sh"))
    assert out.returncode == 0, out.stderr
    assert "WARNING: DB snapshot failed" in out.stdout + out.stderr
    assert "restic backup lock=held" in out.log


def _hold(lock, release_after=None):
    f = open(lock, "a")
    fcntl.flock(f, fcntl.LOCK_EX)
    if release_after is not None:
        threading.Timer(release_after, lambda: (fcntl.flock(f, fcntl.LOCK_UN), f.close())).start()
    return f


def test_a_held_lock_makes_it_wait_then_it_proceeds(box):
    lock = box / "lockdir" / "live.lock"
    _hold(lock, release_after=1.5)
    out = _run(box, LIVE_LOCK_WAIT_S="30")
    assert out.returncode == 0, out.stderr
    assert out.took >= 1.2
    assert "waiting for" in out.stdout and "backing up anyway" not in out.stdout
    assert "restic backup lock=held" in out.log                  # held by the script itself now


def test_past_the_timeout_it_logs_backing_up_anyway_and_proceeds(box):
    lock = box / "lockdir" / "live.lock"
    holder = _hold(lock)
    try:
        out = _run(box, LIVE_LOCK_WAIT_S="1")
    finally:
        holder.close()
    assert out.returncode == 0, out.stderr
    assert "live.lock held for 1 s; backing up anyway" in out.stdout
    assert _names(out.log)[-3:] == ["restic backup", "restic forget", "restic check"]


def test_the_default_wait_is_30_minutes(box):
    assert 'LIVE_LOCK_WAIT_S:-1800' in SCRIPT.read_text()


def test_a_lock_file_it_creates_belongs_to_the_backup_user_and_is_group_writable(box):
    lock = box / "lockdir" / "live.lock"
    assert not lock.exists()
    out = subprocess.run(["bash", "-c", f"umask 077; exec bash {SCRIPT}"], capture_output=True, text=True,
                         env={**os.environ, "PATH": f"{box / 'bin'}:{os.environ['PATH']}", "STUB_LOG": str(box / "log"),
                              "RESTIC_ENV_FILE": str(box / "env"), "LIVE_LOCK": str(lock),
                              "SNAPSHOT_SCRIPT": str(box / "snapshot-crates-db.sh"), "BACKUP_USER": _me()},
                         timeout=60)
    assert out.returncode == 0, out.stderr
    st = lock.stat()
    assert st.st_uid == os.getuid()
    assert stat.S_IMODE(st.st_mode) == 0o664                  # not root's umask: agents (mh550) can open it
    text = SCRIPT.read_text()
    assert 'install -m 0664 -o "$user" -g "$user"' in text    # as root this is what makes it mh550's


def test_an_existing_lock_file_is_left_as_it_is(box):
    lock = box / "lockdir" / "live.lock"
    lock.write_text("")
    lock.chmod(0o640)
    assert _run(box).returncode == 0
    assert stat.S_IMODE(lock.stat().st_mode) == 0o640


def test_a_lock_it_cannot_open_warns_and_backs_up_anyway(box):
    out = _run(box, LIVE_LOCK=str(box / "missing-dir" / "live.lock"))
    assert out.returncode == 0, out.stderr
    assert "backing up without the lock" in out.stdout + out.stderr
    assert _names(out.log)[-3:] == ["restic backup", "restic forget", "restic check"]
