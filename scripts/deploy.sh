#!/usr/bin/env bash
# Build and (re)start the crates + worker containers from a COMMIT, never from loose edits.
#
#   scripts/deploy.sh            # crates + worker
#   scripts/deploy.sh crates     # just one
#
# Refuses a dirty tree (an image must equal a commit), tags the image dj-crates:<short sha> and labels it with the
# full sha, so `docker image ls dj-crates` and `docker inspect` say what is running. Rollback: check out the older
# commit and run this again (or `GIT_SHA=<old> docker compose ... up -d --no-build` if its image is still here).
# Compose and .env come from /srv/docker (project name `dj`, so the existing containers are replaced in place).
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
if [ -n "$(git status --porcelain)" ]; then
    echo "deploy: the working tree has uncommitted changes; commit first so the image matches a commit" >&2
    git status --short >&2
    exit 1
fi
export GIT_SHA="$(git rev-parse --short=10 HEAD)"
export CRATES_SRC="$root"
services=("$@")
[ $# -eq 0 ] && services=(crates worker)
echo "deploy: building ${services[*]} from $GIT_SHA ($(git rev-parse --abbrev-ref HEAD)) in $root"
docker compose --project-directory /srv/docker -f "$root/deploy/compose.yml" up -d --build "${services[@]}"
docker compose --project-directory /srv/docker -f "$root/deploy/compose.yml" ps "${services[@]}"
