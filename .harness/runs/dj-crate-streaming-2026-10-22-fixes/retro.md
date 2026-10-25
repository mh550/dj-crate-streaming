## Outcome
Delivered. All 10 features in S1 passed (S1-01 to S1-09, plus the review feature S1-R1) and S1 was verified. The run cost $38.96 ($3.90 per passing feature), took 5.33 h wall and used 12 sessions, none refused or environmental. Tests went from 1615 to 1906. The branch was tagged and PR #27 was proposed, with merged = 0 because the human merges. I found no reason it fell short.

## Non-passing features by cause
There are none: `summary.json` says "Not passing: none" and every cause is null.

## Harness behaviour
- **Guards:** none fired. Repairs, red_unpass, verify_failed, limit_waits and escalations were all 0, which is correct for a clean run.
- **Time and money:**
  - Init ran on Fable and cost $8.01, 21% of the total, for a 10-feature list. `n8n-home-2026-10-22` had the same pattern ($6.86 of $10.82).
  - S1-07 took 67 min against 16–35 min for the others. Its entry is the one to read for the cause.
  - Driver overhead was 0.36 h, small.
  - Opus ran 10 sessions at $30.12. Review cost $6.75 for one review feature, with docs adding $2.58.
- **Verify:** one Sonnet session ($0.83, 0.15 h) re-ran steps for real. Its evidence table cites independent commands, for example building its own ext-74 fixture and running `sourcing.cli rank` on both HEAD and the old commit 307d62b. Its tests of old-code behaviour ran in a separate worktree at 307d62b and failed 4 tests there, which is the right check.
- **Verify evidence gaps:** the first verify commit (`bd48731`, "10 hold") was followed by `4637fe4`, "10 hold, 0 fail (step 6 rows)". So step 6 rows were missing at first, and something prompted a second pass. Every feature has 6 steps (S1-08 has 7), but the first pass did not cover all of them. I did not check whether the driver or the verify session itself caught the gap.

## Proposed harness changes
1. **Reject a verify result when evidence rows are fewer than steps** (verify completion check in the driver, with a nudge in the verify prompt). Evidence: `4637fe4` added missing "step 6 rows" after `bd48731` had already claimed "10 hold". A mechanical row-count check would have caught it in the same session rather than in a follow-up. I found no earlier retro proposing this.
2. **Run init on a cheaper model, or cap its scope, when the list is small** (init role config). Evidence: init cost $8.01 of $38.96 for 10 features, and $6.86 of $10.82 in the `n8n-home` run. I found no earlier retro proposing this. I did not check what init produced beyond the feature list.
3. **Log each session's wall time against a per-feature budget** (driver warning or `harness-log.md` line). Evidence: S1-07 ran 67 min, about 3× the median of the other features. It still passed, so this is for visibility only. The change is low priority and I found no earlier retro proposing it.

I did not open the session transcripts, so the S1-07 cause and the reason for the second verify commit are unconfirmed.
