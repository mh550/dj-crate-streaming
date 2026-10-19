"""The worker (D18, D23): downloads only what has been approved, and re-checks what was filed but not yet indexed.

One worker at a time: `run` and `once` hold an exclusive flock on `lock_path` (the CLI uses
<dirname(CRATES_DB)>/worker.lock) for their whole life, and a second one exits ("worker already running")
before touching anything. Then, before the first tick: `recover` marks approvals a killed worker left
`started` as "interrupted: worker restarted" and fails their rows still in `sourcing`, so neither is stranded.

Each tick:
  0. every `reconcile_s` seconds (WORKER_RECONCILE_S, 600 in the CLI; 0 = never) the reconciler runs: the playlist
     comments are re-read and every song re-judged at its derived tier, so a #crate / #tier: Michael edits in
     Amperfy takes effect without anyone opening the web client. A failed or busy (ReconcileBusy) reconcile is
     logged and the tick goes on;
  1. every `verify` row not updated in the last `recheck_s` seconds (WORKER_RECHECK_S, 300 in the CLI) is
     fetched again with approve=True; that path downloads nothing, it only asks Navidrome (after a rescan)
     whether the filed song has appeared. Each re-check rewrites the row, which restarts its clock, so a row
     costs one rescan per interval rather than one per tick;
  (first) every unused play-now approval (D20), before the reconcile and the re-checks: it is fetched at `low` and
     filed as a provisional copy (sourcing.fetch). Between ticks the worker sleeps in ≤ 1 s steps and wakes as soon
     as a play-now approval is waiting, and a play-now copy Navidrome has not listed yet is re-checked every tick;
  2. every unused approval is claimed first (a conditional UPDATE to `started`: a crash, a second worker, or
     an approval Michael superseded after this tick read its list cannot download it twice; a lost claim is
     skipped), then fetched, preferring the candidate Michael saw while that file is still offered,
     and finally marked with the outcome;
  3. every copy replacement left unfinished before this tick (sourcing.replace: a playlist that could not be
     repointed yet, a crash between steps) is advanced; an error is logged and the job keeps its state;
  3b. every filed external row whose imported playlist does not hold it yet is placed at its Spotify position
     (crates.placement.advance_all, N4, D44; skipped without a navidrome_db): a pair is derived from state, so a
     fetch, a copy upgrade, play-now or the app's accept need no call of their own, and a crash loses nothing. A
     refusal (a hidden row, an edit meanwhile) is retried at most every `recheck_s`, the 12th gives up with a
     `not_placed` event; an error of the step is logged and the tick goes on;
  4. every `export_s` seconds (WORKER_EXPORT_S, 300 in the CLI; 0 = never) the playlists are exported as `.m3u8`
     into <music>/_playlists (scripts.export_playlists rewrites only changed files), so repoints, proposal swaps and
     Michael's own edits reach the files.

Heartbeat (H1): with `heartbeat_path` (the CLI uses <dirname(CRATES_DB)>/worker.heartbeat) the worker touches that
file when a tick ends, and at each poll while a fetch waits on a download or a Navidrome scan (fetch's `sleep`). A
tick that raises (DB locked, a bug) does not beat, so a worker failing every tick goes stale. `run` removes an earlier
heartbeat before its first tick, so a new container is healthy only once it has ticked. `scripts/healthcheck.py
worker` calls the worker healthy while the file is younger than 3 × WORKER_POLL_S (at least 90 s). A heartbeat that
cannot be written is logged once (until it works again) and the tick goes on.

One bad row never stops the tick, and one bad tick (slskd or Navidrome down, DB locked) never stops `run`.
Log lines name wanted ids and file basenames only: stdout is the container log and must not carry Soulseek peers.
"""
from __future__ import annotations

import fcntl
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from crates import placement
from crates.reconcile import ReconcileBusy
from scripts.export_playlists import export
from . import replace
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
                 recheck_s: float = 0, reconcile_s: float = 0, clock=time.monotonic, lock_path: Path | None = None,
                 export_s: float = 0, exporter=export, heartbeat_path: Path | None = None):
        self.store, self.fetcher, self.log, self.recheck_s = store, fetcher, log, recheck_s
        self.reconciler, self.reconcile_s, self.clock, self._reconciled_at = reconciler, reconcile_s, clock, None
        self.export_s, self.exporter, self._exported_at = export_s, exporter, None
        self.lock_path, self._lock_fd = lock_path, None
        self.heartbeat_path, self._beat_failed = heartbeat_path, False
        self.common = dict(store=store, slskd=slskd, navidrome=navidrome, reconciler=reconciler, **fetch_kwargs)
        if heartbeat_path is not None:
            self.common["sleep"] = self._sleep

    def beat(self) -> None:
        """Touch the heartbeat file (scripts/healthcheck.py worker reads its age). A failure is logged once, until a
        beat works again."""
        if self.heartbeat_path is None:
            return
        try:
            self.heartbeat_path.touch()
            self._beat_failed = False
        except OSError as e:
            if not self._beat_failed:
                self.log(f"heartbeat failed: {type(e).__name__}: {e}")
            self._beat_failed = True

    def _sleep(self, s: float) -> None:
        """fetch's poll wait: a long download or scan keeps the heartbeat fresh."""
        self.beat()
        time.sleep(s)

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

    def reconcile_due(self) -> None:
        """Step 0: run the reconciler when `reconcile_s` has passed since the last run (the first tick always runs)."""
        if not self.reconcile_s:
            return
        now = self.clock()
        if self._reconciled_at is not None and now - self._reconciled_at < self.reconcile_s:
            return
        self._reconciled_at = now                          # a failure waits for the interval too, like a recheck
        try:
            self.reconciler.run()
        except ReconcileBusy as e:                         # the crates service is reconciling: skip this one
            self.log(f"reconcile skipped: {e}")
        except Exception as e:                             # e.g. Navidrome down: the next interval tries again
            self.log(f"reconcile failed: {type(e).__name__}: {e}")

    def _replace_ctx(self) -> replace.Ctx:
        c = self.common
        filer = c.get("filer")
        return replace.Ctx(store=self.store, navidrome=c["navidrome"], navidrome_db=c.get("navidrome_db"),
                           music_root=Path(c["music_root"]), trash_root=c.get("trash_root"),
                           forget=filer.forget if filer is not None else None, reconciler=self.reconciler,
                           rescan_s=self.recheck_s or 300)

    def advance_replacements(self, job_ids: list[int]) -> list[str]:
        """Step 3: the jobs open when the tick began (one fetch finishing now has just advanced its own)."""
        out = []
        for jid in job_ids:
            try:
                state = replace.advance(jid, self._replace_ctx())
                job = self.store.replacement(jid)
                out.append(f"replacement #{jid}: {state}: {job['detail'] or ''}")
            except Exception as e:                         # e.g. Navidrome down: the job keeps its state
                self.store.db.rollback()                   # nothing half-done rides along with a later commit
                out.append(f"replacement #{jid}: error: {type(e).__name__}: {e}")
                self.log(f"replacement #{jid} failed: {type(e).__name__}: {e}")
        return out

    def place_due(self) -> list[str]:
        """Step 3b: after the replacements (one may just have settled an external row `ok`), before the export (so
        it sees the edit). One line per pair tried; a failure of the step itself is logged."""
        c = self.common
        if c.get("navidrome_db") is None:                  # no checked edit without navidrome.db
            return []
        try:
            return placement.advance_all(self.store, c["navidrome"], c["navidrome_db"], self.recheck_s, time.time())
        except Exception as e:                             # e.g. crates.db locked: the next tick derives the same pairs
            self.store.db.rollback()
            self.log(f"placement failed: {type(e).__name__}: {e}")
            return []

    def export_due(self) -> None:
        """Step 4: the `.m3u8` export when `export_s` has passed since the last one (the first tick always runs)."""
        if not self.export_s:
            return
        now = self.clock()
        if self._exported_at is not None and now - self._exported_at < self.export_s:
            return
        self._exported_at = now
        db, music = self.common.get("navidrome_db"), Path(self.common["music_root"])
        try:
            self.exporter(db, music, music / "_playlists")
        except Exception as e:                             # the next interval tries again
            self.log(f"export failed: {type(e).__name__}: {e}")

    def _spend(self, approvals: list[dict], results: list[str]) -> int:
        """Claim and fetch each approval; returns how many were claimed. A play-now approval (D20) is fetched at
        `low` (score_tier: the row keeps its tier) and filed as provisional."""
        claimed = 0
        for a in approvals:
            if not self.store.claim_approval(a["id"]):         # superseded or taken since this list was read
                self.log(f"skipped {a['wanted_id']}: approval #{a['id']} already used")
                continue
            claimed += 1
            extra = {"score_tier": "low", "provisional": True} if a.get("purpose") == "play-now" else {}
            try:
                r = self.fetcher(a["wanted_id"], approve=True, prefer=a["candidate"], **extra, **self.common)
                outcome = r.approval_result or f"{r.status}: {r.reason}"
            except Exception as e:
                outcome = f"error: {type(e).__name__}: {e}"
                self.log(f"fetch {a['wanted_id']} failed: {outcome}")
            self.store.mark_approval_used(a["id"], outcome)
            self.store.commit()
            results.append(f"{a['wanted_id']}: {outcome}")
            self.log(f"{a['wanted_id']}: {outcome}")
        return claimed

    def tick(self) -> TickReport:
        """No `tier` is passed: the row's current tier rules, and an approval's tier only records what was approved.
        Play-now approvals go first, before the reconcile and the re-checks (each may take a while): Michael is
        waiting to hear the track."""
        report = self._tick()
        self.beat()                                        # only a tick that ends: one that raises goes stale
        return report

    def _tick(self) -> TickReport:
        results, rechecked = [], 0
        claimed = self._spend([a for a in self.store.pending_approvals() if a.get("purpose") == "play-now"], results)
        self.reconcile_due()
        open_jobs = [j["id"] for j in self.store.open_replacements()]
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
        claimed += self._spend(self.store.pending_approvals(), results)     # play-now ones that arrived meanwhile first
        for line in self.advance_replacements(open_jobs) + self.place_due():
            results.append(line)
            self.log(line)
        self.export_due()
        self.log(f"tick: {claimed} approvals, {rechecked} rechecked")
        return TickReport(claimed, rechecked, results)

    def run(self, poll_s: float, *, ticks: int | None = None, sleep=time.sleep, now=time.time) -> None:
        """Tick every `poll_s` seconds. The wait between ticks is slept in steps of at most a second, and ends early
        when a play-now approval is waiting (D20: pressing play must not wait up to `poll_s` for the download to
        start). `ticks` ends the loop after that many (tests); `sleep` and `now` are injectable for the same reason."""
        self._lock()                                       # WorkerRunning propagates: the CLI exits non-zero
        try:
            if self.heartbeat_path is not None:            # the last container's beat is not ours
                try:
                    self.heartbeat_path.unlink(missing_ok=True)
                except OSError as e:
                    self.log(f"heartbeat failed: {type(e).__name__}: {e}")
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
                if ticks is None or n < ticks:
                    self._wait(poll_s, sleep, now)
        finally:
            self._unlock()

    def _wait(self, poll_s: float, sleep, now) -> None:
        """Sleep `poll_s`, in steps of at most 1 s, waking after the step in which a play-now approval appears. At
        least one step is always slept, so an approval no tick can spend never turns this into a busy loop."""
        end = now() + poll_s
        while True:
            left = end - now()
            if left <= 0:
                return
            sleep(min(1.0, left))
            try:
                if self.store.has_play_now():
                    return
            except Exception as e:                         # e.g. DB locked: keep waiting, the tick will tell
                self.log(f"play-now check failed: {type(e).__name__}: {e}")
