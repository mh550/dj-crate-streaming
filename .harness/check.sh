#!/usr/bin/env bash
# The suite, sandboxed: every path the code reads from the environment points into scratch, live credentials are
# unset, so no test can reach /srv/music, /srv/_trash, Navidrome, slskd or AcoustID even if it forgets a fixture.
set -uo pipefail
cd "$(dirname "$0")/.."
# Without HARNESS_SCRATCH the sandbox is our own temp dir, removed on exit.
if [[ -n ${HARNESS_SCRATCH:-} ]]; then S=$HARNESS_SCRATCH/sandbox; else T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; S=$T/sandbox; fi
mkdir -p "$S"/{music,incoming,trash,navidrome}
export MUSIC_ROOT=$S/music DOWNLOADS_ROOT=$S/incoming TRASH_ROOT=$S/trash \
  NAVIDROME_DB=$S/navidrome/navidrome.db CRATES_DB=$S/crates.db CRATES_LOG=$S/crates.log
unset ACOUSTID_KEY SLSKD_URL SLSKD_API_KEY SUBSONIC_URL SUBSONIC_USER SUBSONIC_PASS
"${PYTEST:-$HOME/.local/bin/pytest}" -q -x -p no:cacheprovider "$@"
