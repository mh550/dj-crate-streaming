"""deploy/health-push.sh pushes disk health to Gatus' `disk` endpoint, and the nightly backup's systemd result to
`backup` (I3); the user units run it every 10 min.

Stub df, mountpoint, systemctl and curl sit first on PATH and log one line each; nothing here touches a real disk,
unit or Gatus.
"""
import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "deploy" / "health-push.sh"
UNITS = ROOT / "deploy" / "systemd"

STUBS = {
    # df --output=pcent <path>: the percentage comes from PCT_<n> where n is the path's basename
    "df": 'echo "df $*" >>"$STUB_LOG"; p="$(basename "$2")"; v="PCT_$p"; [ -n "${!v:-}" ] || exit 1; printf "Use%%\\n%3s%%\\n" "${!v}"',
    "mountpoint": 'echo "mountpoint $*" >>"$STUB_LOG"; [ "${MOUNTED:-1}" = 1 ]',
    "curl": 'echo "curl $* stdin=$(cat)" >>"$STUB_LOG"; [ "${CURL_FAIL:-0}" = 0 ]',
    # systemctl show <unit> --timestamp=unix -p …: the unit's state from SC_* (an unset SC_TS: no run since boot)
    "systemctl": 'echo "systemctl $*" >>"$STUB_LOG"; [ "${SC_FAIL:-0}" = 0 ] || exit 1;'
                 ' printf "LoadState=%s\\nActiveState=%s\\nResult=%s\\nExecMainStatus=%s\\nExecMainExitTimestamp=%s\\n"'
                 ' "${SC_LOAD:-loaded}" "${SC_STATE:-inactive}" "${SC_RESULT:-success}" "${SC_STATUS:-0}" "${SC_TS:+@$SC_TS}"',
}

HOUR = 3600


@pytest.fixture
def box(tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, body in STUBS.items():
        (bin_ / name).write_text("#!/usr/bin/env bash\n" + body + "\n")
        (bin_ / name).chmod(0o755)
    return tmp_path


def _run(box, **env):
    """UPTIME: seconds since boot (default 2 h)."""
    full = {k: v for k, v in os.environ.items() if not k.startswith(("GATUS_", "PCT_"))}
    full.update({
        "PATH": f"{box / 'bin'}:{os.environ['PATH']}",
        "STUB_LOG": str(box / "log"),
        "SRV_PATH": "/x/srv", "BACKUP_PATH": "/x/backup",
        "PCT_srv": "50", "PCT_backup": "50",
        "GATUS_BACKUP_URL": "http://127.0.0.1:4590/", "GATUS_BACKUP_TOKEN": "s3cret",
        "SC_TS": str(int(time.time()) - 5 * HOUR), "UPTIME_FILE": str(box / "uptime"),
    })
    full.update(env)
    (box / "uptime").write_text(f"{full.pop('UPTIME', 2 * HOUR)}.25 1234.5\n")
    out = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=full, timeout=30)
    out.log = (box / "log").read_text().splitlines() if (box / "log").exists() else []
    curls = [unquote(line) for line in out.log if line.startswith("curl")]     # error= is percent-encoded
    out.curls = [line for line in curls if "/_backup/" not in line]          # the disk pushes
    out.backup = [line for line in curls if "/_backup/" in line]
    return out


def test_healthy_pushes_success_true_with_the_token_on_stdin(box):
    out = _run(box)
    assert out.returncode == 0, out.stderr
    assert len(out.curls) == 1
    assert "http://127.0.0.1:4590/api/v1/endpoints/_disk/external?success=true" in out.curls[0]
    assert "stdin=Authorization: Bearer s3cret" in out.curls[0]
    assert "s3cret" not in out.curls[0].split(" stdin=")[0]      # never on the command line


def test_a_full_srv_pushes_failure_with_the_reason(box):
    out = _run(box, PCT_srv="85")
    assert out.returncode == 0
    assert "success=false" in out.curls[0] and "error=/x/srv is 85% used (limit 85%)" in out.curls[0]
    assert "/x/srv is 85% used" in out.stderr
    raw = next(line for line in out.log if "/_disk/" in line)            # percent-encoded: curl takes no raw space
    assert "error=%2Fx%2Fsrv%20is%2085%25%20used%20%28limit%2085%25%29 stdin=" in raw


def test_just_under_the_limits_is_healthy(box):
    out = _run(box, PCT_srv="84", PCT_backup="89")
    assert "success=true" in out.curls[0]


def test_a_full_backup_disk_pushes_failure(box):
    out = _run(box, PCT_backup="90")
    assert "success=false" in out.curls[0]
    assert "/x/backup is 90% used" in out.stderr


def test_an_unmounted_backup_disk_pushes_failure_without_reading_df_for_it(box):
    out = _run(box, MOUNTED="0", PCT_backup="")
    assert "success=false" in out.curls[0]
    assert "/x/backup is not mounted" in out.stderr
    assert not any(line.startswith("df") and "/x/backup" in line for line in out.log)
    assert "df failed" not in out.stderr


def test_both_problems_are_reported_together(box):
    out = _run(box, MOUNTED="0", PCT_srv="99")
    assert "/x/srv is 99% used" in out.stderr and "not mounted" in out.stderr
    assert len(out.curls) == 1


def test_a_df_failure_is_a_failure_not_a_pass(box):
    out = _run(box, PCT_srv="")
    assert "success=false" in out.curls[0]


@pytest.mark.parametrize("unset", ["GATUS_BACKUP_URL", "GATUS_BACKUP_TOKEN"])
def test_unset_url_or_token_warns_and_sends_nothing(box, unset):
    out = _run(box, **{unset: ""})
    assert out.returncode == 0
    assert "WARNING" in out.stderr
    assert out.curls == []


def test_a_failed_push_exits_nonzero(box):
    out = _run(box, CURL_FAIL="1")
    assert out.returncode == 1
    assert "push of disk to Gatus failed" in out.stderr


def test_the_endpoint_key_can_be_overridden(box):
    out = _run(box, GATUS_DISK_KEY="infra_disk")
    assert "/endpoints/infra_disk/external" in out.curls[0]


# --- the backup, from systemd (I3: Gatus' own 26 h heartbeat restarts with Gatus) ---

def test_a_recent_successful_backup_pushes_success_to_backup_with_the_token_on_stdin(box):
    out = _run(box)
    assert out.returncode == 0, out.stderr
    assert len(out.backup) == 1
    assert "http://127.0.0.1:4590/api/v1/endpoints/_backup/external?success=true" in out.backup[0]
    assert "stdin=Authorization: Bearer s3cret" in out.backup[0]
    assert "s3cret" not in out.backup[0].split(" stdin=")[0]
    assert any(line.startswith("systemctl show restic-backup.service") for line in out.log)


def test_a_failed_backup_pushes_failure_with_its_exit_status(box):
    out = _run(box, SC_STATUS="1")
    assert "success=false" in out.backup[0] and "error=last backup exited 1" in out.backup[0]
    assert "last backup exited 1" in out.stderr
    assert "success=true" in out.curls[0]                                    # the disk push is independent


def test_a_backup_older_than_26_h_pushes_failure(box):
    out = _run(box, SC_TS=str(int(time.time()) - 27 * HOUR))
    assert "success=false" in out.backup[0]
    assert "last backup ended 27 h ago" in out.stderr


def test_a_backup_just_under_26_h_is_success(box):
    out = _run(box, SC_TS=str(int(time.time()) - 26 * HOUR + 60))
    assert "success=true" in out.backup[0]


def test_the_age_limit_can_be_overridden(box):
    out = _run(box, SC_TS=str(int(time.time()) - 3 * HOUR), BACKUP_MAX_AGE_H="2")
    assert "success=false" in out.backup[0]


def test_a_backup_killed_or_timed_out_is_a_failure(box):
    out = _run(box, SC_RESULT="timeout", SC_STATUS="0")
    assert "success=false" in out.backup[0]
    assert "timeout" in out.stderr


def test_no_run_since_a_boot_over_26_h_ago_is_a_failure(box):
    out = _run(box, SC_TS="", UPTIME=str(27 * HOUR))
    assert "success=false" in out.backup[0]
    assert "no run of restic-backup.service since boot" in out.stderr


def test_an_unknown_unit_is_a_failure_not_no_run_since_boot(box):
    out = _run(box, SC_LOAD="not-found", SC_TS="")
    assert "success=false" in out.backup[0]
    assert "restic-backup.service is not-found" in out.stderr


def test_a_systemctl_failure_is_a_failure_not_silence(box):
    out = _run(box, SC_FAIL="1")
    assert "success=false" in out.backup[0]
    assert "systemctl show restic-backup.service failed" in out.stderr


# systemd clears ExecMain* when a run starts, and after a boot: no result yet, so restic-backup's own push and the
# 26 h heartbeat decide
@pytest.mark.parametrize("env", [{"SC_STATE": "activating", "SC_STATUS": "1"}, {"SC_TS": ""}],
                         ids=["running", "no-run-since-a-recent-boot"])
def test_no_backup_push_when_systemd_has_no_result_yet(box, env):
    out = _run(box, **env)
    assert out.returncode == 0, out.stderr
    assert out.backup == []
    assert "success=true" in out.curls[0]


def test_the_backup_key_is_restic_backups_override(box):
    out = _run(box, GATUS_BACKUP_KEY="infra_backup", GATUS_DISK_KEY="infra_disk")
    curls = [unquote(line) for line in out.log if line.startswith("curl")]     # error= is percent-encoded
    assert any("/endpoints/infra_backup/external?success=true" in c for c in curls)


def test_a_failed_backup_push_exits_nonzero_after_the_disk_push(box):
    out = _run(box, CURL_FAIL="1")
    assert out.returncode == 1
    assert len(out.curls) == 1 and len(out.backup) == 1


def test_the_script_is_executable():
    assert os.access(SCRIPT, os.X_OK)


@pytest.mark.skipif(not shutil.which("systemd-analyze"), reason="systemd-analyze missing")
def test_the_units_pass_systemd_analyze_verify(tmp_path):
    # The service's ExecStart is the installed copy, which doesn't exist in a test; point it at the script.
    svc = (UNITS / "dj-health-push.service").read_text()
    exec_line = next(line for line in svc.splitlines() if line.startswith("ExecStart="))
    (tmp_path / "dj-health-push.service").write_text(svc.replace(exec_line, f"ExecStart={SCRIPT}"))
    shutil.copy(UNITS / "dj-health-push.timer", tmp_path)
    out = subprocess.run(["systemd-analyze", "--user", "verify", str(tmp_path / "dj-health-push.service"),
                          str(tmp_path / "dj-health-push.timer")], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


def test_the_timer_runs_every_10_minutes_and_the_service_reads_the_env_file():
    assert "OnUnitActiveSec=10min" in (UNITS / "dj-health-push.timer").read_text()
    svc = (UNITS / "dj-health-push.service").read_text()
    assert "Type=oneshot" in svc and "EnvironmentFile=-%h/.config/dj-health-push.env" in svc
    assert "TimeoutStartSec=2min" in svc                   # a hung df on a dying HDD mustn't stop the timer for good
