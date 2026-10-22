# .harness/config.sh — dj-crate-streaming settings for the agent harness (~/projects/agent-harness, `harness start`).
# Everything else is detected (check = .harness/check.sh) or a harness default; the live protocol's commands are in CLAUDE.md → "Live system".
POLICY=build-only
MERGE_POLICY=auto   # night of 2026-10-21 only (Michael): verified milestones self-merge; remove with POLICY back to live-staged
LIVE_LOCK=/srv/docker/crates/live.lock   # shared with the nightly backup job (one writer at a time)
