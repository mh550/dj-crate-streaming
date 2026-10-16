"""The worker (D18, D23): downloads only what has been approved, and re-checks what was filed but not yet indexed.

Before the first tick (`run`, and the CLI's `--once`): `recover` marks approvals a killed worker left
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

import time
from dataclasses import dataclass, field

from .fetch import fetch


@dataclass
class TickReport:
    approvals: int
    rechecked: int
    results: list[str] = field(default_factory=list)       # "<wanted_id>: <status>: <reason>"


class Worker:
    def __init__(self, *, store, slskd, navidrome, reconciler, fetch_kwargs: dict, fetcher=fetch, log=print,
                 recheck_s: float = 0):
        self.store, self.fetcher, self.log, self.recheck_s = store, fetcher, log, recheck_s
        self.common = dict(store=store, slskd=slskd, navidrome=navidrome, reconciler=reconciler, **fetch_kwargs)

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
            try:
                r = self.fetcher(wanted_id, approve=True, **self.common)
                results.append(f"{wanted_id}: {r.status}: {r.reason}")
            except Exception as e:                         # the row is left as fetch left it; the next tick retries
                results.append(f"{wanted_id}: error: {type(e).__name__}: {e}")
                self.log(f"recheck {wanted_id} failed: {type(e).__name__}: {e}")
            rechecked += 1
        claimed = 0
        for a in self.store.pending_approvals():
            if not self.store.claim_approval(a["id"]):         # superseded or taken since this list was read
                self.log(f"skipped {a['wanted_id']}: approval #{a['id']} already used")
                continue
            claimed += 1
            try:
                r = self.fetcher(a["wanted_id"], approve=True, prefer=a["candidate"], **self.common)
                outcome = f"{r.status}: {r.reason}"
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
        try:
            self.recover()
        except Exception as e:                             # e.g. DB locked: the next start recovers
            self.log(f"recover failed: {type(e).__name__}: {e}")
        n = 0
        while ticks is None or n < ticks:
            try:
                self.tick()
            except Exception as e:
                self.log(f"tick failed: {type(e).__name__}: {e}")
            n += 1
            time.sleep(poll_s)
