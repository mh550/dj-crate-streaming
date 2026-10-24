# .harness/config.sh — dj-crate-streaming settings for the agent harness (~/projects/agent-harness, `harness start`).
# Everything else is detected (check = .harness/check.sh) or a harness default; the live protocol's commands are in CLAUDE.md → "Live system".
POLICY=build-only   # 2026-10-21 and 2026-10-22 runs: build-only; back to live-staged when Michael says
LIVE_LOCK=/srv/docker/crates/live.lock   # shared with the nightly backup job (one writer at a time)
