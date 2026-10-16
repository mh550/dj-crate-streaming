"""The worker (D18, D23): downloads only what has been approved, and re-checks what was filed but not yet indexed.

One worker at a time: `run` and `once` hold an exclusive flock on `lock_path` (the CLI uses
<dirname(CRATES_DB)>/worker.lock) for their whole life, and a second one exits ("worker already running")
before touching anything. Then, before the first tick: `recover` marks approvals a killed worker left
`started` as "interrupted: worker restarted" and fails their rows still in `sourcing`, so neither is stranded.

Each tick:
  1. every `verify` row not updated in the last `recheck_s` seconds (WORKER_RECHECK_S, 300 in the CLI) is
     fetched again with approve=True; that path downloads nothing, it only asks Navidrome (after a rescan)
     whether the filed song has appeared. Each re-check rewrites the row, which restarts its clock, so a row
     costs one rescan per interval rather than one per tick;
  2. every unused approval is claimed first (a conditional UPDATE to `started`: a crash, a second worker, or
     an approval Michael superseded after this tick read its list cannot download it twice; a lost claim is
     skipped), then fetched, preferring the candidate Michael saw while that file is still offered,
     and finally marked with the outcome.

One bad row never stops the tick, and one bad tick (slskd or Navidrome down, DB locked) never stops `run`.
Log lines name wanted ids and file basenames only: stdout is the container log and must not carry Soulseek peers.
"""
from __future__ import annotations

import fcntl
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .fetch import fetch


class WorkerRunning(Exception):
    """Another worker holds the lock: this one must not recover, claim or fetch anything."""


def hold_lock(path: Path) -> int:
    """An exclusive, non-blocking flock on `path` for the life of the returned fd (closing it, or the process
    ending, releases it). Raises WorkerRunning when another process holds it."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise WorkerRunning(f"worker already running (lock {path} is held)") from None
    return fd


@dataclass
class TickReport:
    approvals: int
    rechecked: int
    results: list[str] = field(default_factory=list)       # "<wanted_id>: <status>: <reason>"


class Worker:
    def __init__(self, *, store, slskd, navidrome, reconciler, fetch_kwargs: dict, fetcher=fetch, log=print,
                 recheck_s: float = 0, lock_path: Path | None = None):
        self.store, self.fetcher, self.log, self.recheck_s = store, fetcher, log, recheck_s
        self.lock_path, self._lock_fd = lock_path, None
        self.common = dict(store=store, slskd=slskd, navidrome=navidrome, reconciler=reconciler, **fetch_kwargs)

    def _lock(self) -> None:
        """One worker at a time (the CLI passes <dirname(CRATES_DB)>/worker.lock). Taken before `recover`, so a
        second worker (`--once` beside the running one) can never mistake a live fetch's `started` approval
        for an interrupted one; raises WorkerRunning, having touched nothing."""
        if self.lock_path is not None and self._lock_fd is None:
            self._lock_fd = hold_lock(self.lock_path)

    def _unlock(self) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    def once(self) -> TickReport:
        """`worker --once`: lock, recover, one tick, unlock."""
        self._lock()
        try:
            self.recover()
            return self.tick()
        finally:
            self._unlock()

    def recover(self) -> list[str]:
        """Once per start, before any tick: see CrateStore.recover_interrupted."""
        ids = self.store.recover_interrupted()
        for wanted_id in ids:
            self.log(f"{wanted_id}: approval interrupted by a worker restart; approve again")
        return ids

    def tick(self) -> TickReport:
        """No `tier` is passed: the row's current tier rules, and an approval's tier only records what was approved."""
        results, rechecked = [], 0
        for wanted_id in self.store.verify_ids(updated_before=time.time() - self.recheck_s):
            reason = (self.store.find_wanted(wanted_id) or {}).get("reason")
            try:
                r = self.fetcher(wanted_id, approve=True, **self.common)
                results.append(f"{wanted_id}: {r.status}: {r.reason}")
            except Exception as e:                         # e.g. Navidrome down: try again after the interval
                results.append(f"{wanted_id}: error: {type(e).__name__}: {e}")
                self.log(f"recheck {wanted_id} failed: {type(e).__name__}: {e}")
                try:                                       # same status and reason, but the clock restarts
                    self.store.set_wanted_status(wanted_id, "verify", reason)
                except Exception as e2:
                    self.log(f"recheck {wanted_id}: could not restart its clock: {type(e2).__name__}: {e2}")
            rechecked += 1
        claimed = 0
        for a in self.store.pending_approvals():
            if not self.store.claim_approval(a["id"]):         # superseded or taken since this list was read
                self.log(f"skipped {a['wanted_id']}: approval #{a['id']} already used")
                continue
            claimed += 1
            try:
                r = self.fetcher(a["wanted_id"], approve=True, prefer=a["candidate"], **self.common)
                outcome = r.approval_result or f"{r.status}: {r.reason}"
            except Exception as e:
                outcome = f"error: {type(e).__name__}: {e}"
                self.log(f"fetch {a['wanted_id']} failed: {outcome}")
            self.store.mark_approval_used(a["id"], outcome)
            self.store.commit()
            results.append(f"{a['wanted_id']}: {outcome}")
            self.log(f"{a['wanted_id']}: {outcome}")
        self.log(f"tick: {claimed} approvals, {rechecked} rechecked")
        return TickReport(claimed, rechecked, results)

    def run(self, poll_s: float, *, ticks: int | None = None) -> None:
        self._lock()                                       # WorkerRunning propagates: the CLI exits non-zero
        try:
            try:
                self.recover()
            except Exception as e:                         # e.g. DB locked: the next start recovers
                self.log(f"recover failed: {type(e).__name__}: {e}")
            n = 0
            while ticks is None or n < ticks:
                try:
                    self.tick()
                except Exception as e:
                    self.log(f"tick failed: {type(e).__name__}: {e}")
                n += 1
                time.sleep(poll_s)
        finally:
            self._unlock()
