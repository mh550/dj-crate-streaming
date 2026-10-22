#!/usr/bin/env bash
# Run a one-off worker command in the image the worker container was deployed from (R2, D45), not dj-crates:dev.
#
#   scripts/live-run.sh python3 -m scripts.duplicate_cleanup trash --dry-run
#   scripts/live-run.sh --print <command…>     # print the exact command, run nothing
#
# The revision comes from the dj-worker-1 container, running or stopped: its org.opencontainers.image.revision
# label, which the Dockerfile sets from the GIT_SHA build arg. scripts/deploy.sh passes the 10-char sha
# (`git rev-parse --short=10`), the same as the dj-crates:<sha> tag; a full sha is cut to 10. Refuses (exit 1, one
# line) when the container is missing, the label is empty or `dev`, or that image is not here. Otherwise runs
#   GIT_SHA=<rev> docker compose --project-directory /srv/docker run --rm --no-deps worker <command…>
# and exits with its status. --no-deps: a run with dependencies recreates Navidrome whenever compose.yml changed.
set -euo pipefail
refuse() { echo "live-run: refused: $*" >&2; exit 1; }
print=0
if [ "${1:-}" = "--print" ]; then print=1; shift; fi
if [ $# -eq 0 ]; then
    echo "usage: scripts/live-run.sh [--print] <command…>" >&2
    exit 2
fi
command -v docker >/dev/null || refuse "docker is not on PATH"
container=dj-worker-1
rev="$(docker inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$container" 2>/dev/null)" \
    || refuse "no container $container (docker inspect failed); deploy with scripts/deploy.sh first"
rev="${rev:0:10}"
[ -n "$rev" ] && [ "$rev" != "<no value>" ] || refuse "$container has no org.opencontainers.image.revision label; redeploy with scripts/deploy.sh"
[ "$rev" != "dev" ] || refuse "$container was built as 'dev', not from a commit; redeploy with scripts/deploy.sh"
docker image inspect "dj-crates:$rev" >/dev/null 2>&1 \
    || refuse "image dj-crates:$rev is not here (docker image ls dj-crates); redeploy that commit with scripts/deploy.sh"
cmd=(docker compose --project-directory /srv/docker run --rm --no-deps worker "$@")
if [ "$print" -eq 1 ]; then
    printf 'GIT_SHA=%s' "$rev"
    printf ' %q' "${cmd[@]}"
    printf '\n'
    exit 0
fi
echo "live-run: image dj-crates:$rev"
GIT_SHA="$rev" exec "${cmd[@]}"
