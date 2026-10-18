"""deploy/health-push.sh pushes disk health to Gatus' `disk` endpoint; the user units run it every 10 min.

Stub df, mountpoint and curl sit first on PATH and log one line each; nothing here touches a real disk or Gatus.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "deploy" / "health-push.sh"
UNITS = ROOT / "deploy" / "systemd"

STUBS = {
    # df --output=pcent <path>: the percentage comes from PCT_<n> where n is the path's basename
    "df": 'p="$(basename "$2")"; v="PCT_$p"; [ -n "${!v:-}" ] || exit 1; printf "Use%%\\n%3s%%\\n" "${!v}"',
    "mountpoint": 'echo "mountpoint $*" >>"$STUB_LOG"; [ "${MOUNTED:-1}" = 1 ]',
    "curl": 'echo "curl $* stdin=$(cat)" >>"$STUB_LOG"; [ "${CURL_FAIL:-0}" = 0 ]',
}


@pytest.fixture
def box(tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, body in STUBS.items():
        (bin_ / name).write_text("#!/usr/bin/env bash\n" + body + "\n")
        (bin_ / name).chmod(0o755)
    return tmp_path


def _run(box, **env):
    full = {k: v for k, v in os.environ.items() if not k.startswith(("GATUS_", "PCT_"))}
    full.update({
        "PATH": f"{box / 'bin'}:{os.environ['PATH']}",
        "STUB_LOG": str(box / "log"),
        "SRV_PATH": "/x/srv", "BACKUP_PATH": "/x/backup",
        "PCT_srv": "50", "PCT_backup": "50",
        "GATUS_BACKUP_URL": "http://127.0.0.1:4590/", "GATUS_BACKUP_TOKEN": "s3cret",
    })
    full.update(env)
    out = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=full, timeout=30)
    out.log = (box / "log").read_text().splitlines() if (box / "log").exists() else []
    out.curls = [line for line in out.log if line.startswith("curl")]
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
    assert "success=false" in out.curls[0] and "_x_srv_is_85" in out.curls[0].replace("%", "_")
    assert "/x/srv is 85% used" in out.stderr


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
    assert "push to Gatus failed" in out.stderr


def test_the_endpoint_key_can_be_overridden(box):
    out = _run(box, GATUS_DISK_KEY="infra_disk")
    assert "/endpoints/infra_disk/external" in out.curls[0]


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
