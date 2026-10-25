## Outcome
Delivered. All 15 of 15 features pass and are verified: V1 (2), V2 (9), V3 (2) and V4 (2). The run made 25 sessions in 9.65 h and cost $165.03 ($11 per feature). Tests went from 1615 to 1757. Four PRs (#23–#26) were proposed, and `merged` is 0 in `summary.json`. The work was docs-only research of SoulSync. Cost was dominated by Opus doc-writing sessions ($129.94, 79%) plus review ($28.68). Verify cost only $3.04.

## Non-passing features by cause
No feature ended "not done". Three verify failures were fixed on one retry each:
- V2-08 (cross-file disagreement): "verify V2 failed step 1 only (no file/citation/holds table)".
- V4-01 and V4-02 (one wrong cite range): the verifier's only V4-02 fail was the `310-341` cite, fixed to `:310-340`.

Causes: 3 model quality or evidence-format slips, 0 other.

## Harness behaviour
- **Guards:** `verify_failed` fired 3 times. Each was a real defect, and each retry passed. There were 0 repairs, 0 red_unpass, 0 limit waits and 0 escalations.
- **Wasted work:** the V4-01/V4-02 retry reran two Opus build sessions, 21 and 14 min, about $17.70 in all. Their first-pass cost was $7.33 and $10.37, so the re-runs were a small share of that. The cause was a one-line cite fix. V2-08's retry cost 13 min.
- **Review spend:** per-milestone review was $28.68 (17%). V3 and V4 had 2 features each. V4-02 is classed as "review" at $10.37 with 2 sessions.
- **Verify re-ran steps:** V1-01 has 11 evidence rows, one per step, with commands and outputs. V1-02 has 5 rows, and V4-02 has rows to step 5. These rows show real `sed`, `gh api` and `wc -l` runs. One row on V4-02 step 5 was marked "yes (intent)" even though the literal wording failed. The verifier accepted it and explained why.
- **Verify cost:** verify ran on Sonnet at $3.04 total, so verify was cheap.

## Proposed harness changes
1. **Skip or cap per-milestone review on milestones of 3 or fewer features, or route it to Sonnet** (driver config). Evidence: V3 and V4 had 2 features each, and review cost $28.68. This is a repeat of at least seven earlier retros. The first was `v2-2026-10-18`, and the latest was `voice-concierge-2026-10-21`. Still unfixed.
2. **Let the verifier or a Sonnet fixer correct trivial one-line defects without re-queueing an Opus build session** (driver verify-fail path). Evidence: V4-01 and V4-02 re-ran as full Opus sessions for a single cite range. This has not been proposed before.
3. **Log the verify failure reason in the `verify_failed` line of `harness-log.md`** (driver). Evidence: this run's log says only "failed the re-check", and I had to dig through `progress.md` for the cause. `rane-one-mixxx-2026-10-19` and `hit_list-2026-10-20` proposed this.
