#!/usr/bin/env python3
"""Docker healthchecks (H1): `python3 scripts/healthcheck.py crates|worker`, run inside that container.

  crates  GET http://127.0.0.1:$CRATES_PORT/api/status (4580) answers 200 within 5 s. /api/status asks Navidrome,
          so a Navidrome that is down makes crates unhealthy too (502).
  worker  <dirname(CRATES_DB)>/worker.heartbeat, which the worker touches when a tick ends and while it waits on a
          download or a scan (sourcing.worker), is younger than 3 × WORKER_POLL_S (30), and at least 90 s. A new
          worker removes the old file, so it reads unhealthy until its first tick ends (H1-03: start_period).

Exit 0 healthy, 1 not, with one line saying why. Every failure is 1, a usage error included: Docker reserves 2.
Stdlib only, no imports from this repo, so it runs as a plain file.
"""
from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT_S = 5
MIN_AGE_S = 90


def crates() -> tuple[bool, str]:
    url = f"http://127.0.0.1:{os.environ.get('CRATES_PORT', '4580')}/api/status"
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))     # never via an http_proxy in the env
    try:
        with direct.open(url, timeout=TIMEOUT_S) as r:
            return r.status == 200, f"{url}: {r.status}"
    except urllib.error.HTTPError as e:
        return False, f"{url}: {e.code}"
    except (OSError, ValueError) as e:                     # refused, timed out (socket.timeout is an OSError)
        return False, f"{url}: {getattr(e, 'reason', None) or e}"


def worker() -> tuple[bool, str]:
    db = os.environ.get("CRATES_DB")
    if not db:
        return False, "CRATES_DB is not set (the heartbeat sits beside it)"
    try:
        limit = max(MIN_AGE_S, 3 * float(os.environ.get("WORKER_POLL_S", "30")))
    except ValueError:
        return False, f"WORKER_POLL_S is not a number: {os.environ['WORKER_POLL_S']!r}"
    hb = Path(db).parent / "worker.heartbeat"
    try:
        age = time.time() - hb.stat().st_mtime
    except OSError as e:
        return False, f"no heartbeat at {hb}: {e.strerror}"
    return age < limit, f"heartbeat {age:.0f} s old (limit {limit:.0f} s)"


def main(argv: list[str]) -> int:
    checks = {"crates": crates, "worker": worker}
    if len(argv) != 1 or argv[0] not in checks:
        print("usage: healthcheck.py crates|worker", file=sys.stderr)
        return 1
    ok, why = checks[argv[0]]()
    print(f"{argv[0]}: {'healthy' if ok else 'unhealthy'}: {why}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
