## Outcome
17 of 33 features pass. N1, N1F, H1 and H2 (14 features) are verified and merged. H3 has 3 of 5 passing and is not verified or merged. N2–N5 (14 features) never ran. The run stopped at 21:09 with "blocked: the remaining features wait on H3-04 (given up; needs Michael)". H3-04 needs the two Gatus vars from Michael in INBOX, and nothing could be done without them. Cost was $52.19 over 52 sessions (24 real, 28 environmental), at $3.07 per passing feature.

## Non-passing features by cause
- **H3-04** (2 sessions, 41 min, $2.43): permission or input. The detail reads "Gatus isn't deployed because the INBOX still has no 'gatus vars set' from you". The H3-03 review had already written "H3-04 is blocked until Michael sets the two vars", so the feature was scheduled with a known human dependency.
- **H3-05**: depends on a failed feature ("waits on H3-04").
- **N2-01 to N5-02** (14 features): `summary.json` labels these "usage limit", with 2 refusals each. These are leftovers from the 05:23 first segment, when all remaining features were refused (5/19 passing). In the final segment they were never attempted, because they sit behind the blocked H3. `limit_waits` is 0. The honest cause is depends on a failed feature, by milestone ordering.

## Harness behaviour
- **Guards:** repairs, red_unpass, verify_failed and verify_escalations are all 0. There were 4 milestone merges, all correct.
- **Wrong end reason:** `summary.json` says `end_reason: "no feature left to try"`, but `harness-log.md` says "blocked on H3-04". The summary also reports stale usage-limit causes.
- **Blocked work was not skipped:** N2–N5 had no declared dependency on H3-04 (per the "blocked" cause on H3-05). The driver stopped anyway, so about 14 features and ~5 h of possible work went unused. The milestone order forced this, not the dependency graph.
- **Wasted H3-04 retry:** H3-04 got a second session (9 min) to re-check INBOX after the first had already reached the same conclusion.
- **Verify depth is thin:** verify sessions ran 39–96 s, which is 7–9 turns. They re-ran the suite (green, 1,227–1,315 tests) and read test assertions. They explicitly skipped live checks: "Live checks: not run", "I did not redeploy or re-run the live Check". So verify is a suite re-run plus a read, not a re-run of each step. The cost is small ($0.81 in total).
- **Time:** 28 environmental sessions and 1.02 h of driver time, against 6.83 h of sessions.

## Proposed harness changes
1. **Skip blocked features instead of ending the run** (`driver`: scheduler). When a feature is given up on a human dependency, continue with features whose declared dependencies are met, such as N2–N5. Evidence: 14 features were left unattempted behind H3-04. No earlier retro proposed it; the only other retro this day (pathways/threads-2026-10-17) mentions blocking.
2. **Fix the summary's end reason and cause attribution** (`summary` generator). Use the last driver event for `end_reason`. Never carry a "usage limit" cause from an earlier segment onto features that were not attempted in the final one. Evidence: the "no feature left to try" label against "blocked on H3-04", and 14 features marked "usage limit" with 0 limit waits. Not proposed before.
3. **Check human-gate preconditions before scheduling a feature** (`feature_list` and the planner). A feature whose precondition is an INBOX answer should be held until that answer exists. Evidence: H3-04 spent 41 min and $2.43 on a gate the H3-03 review had already flagged. Not proposed before.
