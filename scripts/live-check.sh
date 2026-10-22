#!/usr/bin/env bash
# The Check (CLAUDE.md "Check"), in the deployed image: export every playlist, then compare the files with Navidrome.
#
#   scripts/live-check.sh            # exit 0 and "ok: every playlist file matches Navidrome…" is green
#   scripts/live-check.sh --print    # print the command, run nothing
#
# Export first: the worker exports only every 300 s (never while stopped), so a bare `check` reports "stale".
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "$#:${1:-}" in
    0:) print=() ;;
    1:--print) print=(--print) ;;
    *) echo "usage: scripts/live-check.sh [--print]" >&2; exit 2 ;;
esac
exec "$here/live-run.sh" "${print[@]}" sh -c 'python3 -m scripts.export_playlists export && python3 -m scripts.export_playlists check'
