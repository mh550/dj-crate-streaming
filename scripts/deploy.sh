#!/usr/bin/env bash
# Build and (re)start the crates + worker containers from a COMMIT, never from loose edits.
#
#   scripts/deploy.sh            # crates + worker
#   scripts/deploy.sh crates     # just one
#   scripts/deploy.sh gatus      # monitoring: installs this commit's deploy/gatus/config.yaml, then starts Gatus, waits for its API
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
if [[ " ${services[*]} " == *" gatus "* ]]; then
    # On its own: a failed build after the copy below would leave Gatus checking images that never shipped.
    if [ ${#services[@]} -ne 1 ]; then
        echo "deploy: deploy gatus on its own (scripts/deploy.sh gatus), not with ${services[*]}" >&2
        exit 1
    fi
    # Gatus reads a copy of this commit's checks, not the checkout: removing a worktree mustn't take monitoring down.
    # mh550 creates the directory (Docker would make it root's) and the copy is renamed into place, so Gatus reads a
    # whole file. The one it replaces stays as config.yaml.prev, the rollback. compose.yml mounts the same GATUS_DIR.
    export GATUS_DIR="${GATUS_DIR:-/srv/docker/gatus}"
    mkdir -p "$GATUS_DIR/config" 2>/dev/null || true      # a failure is reported just below, with the fix
    if [ ! -w "$GATUS_DIR/config" ]; then
        echo "deploy: $GATUS_DIR/config is not writable (made by Docker as root?); Michael: sudo chown -R $(id -u):$(id -g) $GATUS_DIR" >&2
        exit 1
    fi
    git show HEAD:deploy/gatus/config.yaml > "$GATUS_DIR/config/config.yaml.new"
    [ -f "$GATUS_DIR/config/config.yaml" ] && cp -p "$GATUS_DIR/config/config.yaml" "$GATUS_DIR/config/config.yaml.prev"
    mv -f "$GATUS_DIR/config/config.yaml.new" "$GATUS_DIR/config/config.yaml"
    echo "deploy: gatus config from $GIT_SHA in $GATUS_DIR/config"
fi
echo "deploy: building ${services[*]} from $GIT_SHA ($(git rev-parse --abbrev-ref HEAD)) in $root"
# Gatus is always recreated: after a config-only change `up -d` would keep the old process, whose API answers at
# once, and an invalid new file would only show at the next restart (as a crash loop). Recreated, it loads the file
# now, and the wait below fails on a bad one.
recreate=()
[[ " ${services[*]} " == *" gatus "* ]] && recreate=(--force-recreate)
docker compose --project-directory /srv/docker -f "$root/deploy/compose.yml" up -d --build ${recreate[@]+"${recreate[@]}"} "${services[@]}"
docker compose --project-directory /srv/docker -f "$root/deploy/compose.yml" ps "${services[@]}"
if [[ " ${services[*]} " == *" gatus "* ]]; then
    # `up -d` exits 0 even when Gatus exits at start (an unset GATUS_NTFY_TOPIC or GATUS_BACKUP_TOKEN), so wait for
    # its API before calling the deploy done.
    url="http://127.0.0.1:4590/api/v1/endpoints/statuses"
    for ((i = 1; i <= ${GATUS_WAIT:-30}; i++)); do
        if curl -fsS -o /dev/null --max-time 2 "$url"; then
            echo "deploy: gatus answers on $url"
            exit 0
        fi
        [ "$i" -lt "${GATUS_WAIT:-30}" ] && sleep 1
    done
    echo "deploy: gatus did not answer $url within ${GATUS_WAIT:-30} s; are GATUS_NTFY_TOPIC and GATUS_BACKUP_TOKEN" \
         "set in /srv/docker/.env? \`docker compose --project-directory /srv/docker -f $root/deploy/compose.yml logs gatus\`." >&2
    echo "deploy: rollback to the last config: mv $GATUS_DIR/config/config.yaml.prev $GATUS_DIR/config/config.yaml &&" \
         "docker compose --project-directory /srv/docker -f $root/deploy/compose.yml up -d --force-recreate gatus" >&2
    echo "deploy: or remove Gatus: docker compose --project-directory /srv/docker -f $root/deploy/compose.yml stop gatus &&" \
         "docker compose --project-directory /srv/docker -f $root/deploy/compose.yml rm -f gatus" >&2
    exit 1
fi
