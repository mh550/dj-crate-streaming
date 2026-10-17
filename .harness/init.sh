#!/usr/bin/env bash
# Run by the harness before every session, in the run's worktree (HARNESS_PORT, HARNESS_SCRATCH are set).
# No services to start: tests use the fake Navidrome/slskd. Checks the tools, runs the sandboxed suite.
set -uo pipefail
cd "$(dirname "$0")/.."
SCRATCH=${HARNESS_SCRATCH:?}; mkdir -p "$SCRATCH"
python3 -c 'import sys; assert sys.version_info >= (3, 10), sys.version' || { echo "python3 >= 3.10 missing"; exit 1; }
[[ -x ~/.local/bin/pytest ]] || { echo "pytest missing: pipx install pytest"; exit 1; }
for t in ffmpeg flac fpcalc beet sqlite3; do command -v "$t" > /dev/null || echo "note: $t not found (its tests skip)"; done
# same key as the harness driver's green(): an unchanged code tree that was green is not re-run (the suite takes ~7 min)
key=$({ git ls-files -s -- . ':!.harness/runs'; git diff HEAD -- . ':!.harness/runs'; } | sha1sum | cut -c1-16)
start=$(date +%s)
if [[ -f $SCRATCH/green-$key ]]; then
  echo "check: green (cached: this code tree passed already)"
elif .harness/check.sh > "$SCRATCH/check.log" 2>&1; then
  touch "$SCRATCH/green-$key"
  echo "check: green — $(tail -1 "$SCRATCH/check.log") ($(( $(date +%s) - start )) s)"
else
  echo "check: RED — see $SCRATCH/check.log"; tail -25 "$SCRATCH/check.log"
fi
echo "branch: $(git branch --show-current) · last: $(git log --oneline -1)"
