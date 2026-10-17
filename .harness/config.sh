# .harness/config.sh — dj-crate-streaming settings for the agent harness (~/projects/agent-harness, `harness start`).
SPEC_FILES="docs/next-todos.md docs/specs/2026-10-17-amperfy-pivot.md docs/specs/2026-10-17-m9-remaining-ownership.md docs/hard-won-facts.md docs/architecture.md"
CHECK_CMD=".harness/check.sh"           # pytest, sandboxed (paths in scratch, live credentials unset)
INIT_CMD=".harness/init.sh"
SMOKE_CMD="python3 -c 'import crates, sourcing, subsonic, scripts' && echo imports ok"
BASE_PORT=7821

INIT_MODEL=fable
WORKER_MODEL=opus
VERIFY_MODEL=sonnet
SUPERVISOR_MODEL=opus

HOURS=8
MAX_SESSIONS=40
MAX_ATTEMPTS=2
MAX_REPAIRS=3
MAX_VERIFY_ROUNDS=2
SESSION_TIMEOUT=100m
MAX_TURNS=250
SESSION_BUDGET_USD=20

PR_POLICY=milestone
MAIN_BRANCH=main
AGENT_SETTINGS=.harness/agent-settings.json   # harness sessions only; interactive sessions (which deploy) keep their own
NOTIFY_CMD=""
