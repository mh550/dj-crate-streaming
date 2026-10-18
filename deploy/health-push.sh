#!/usr/bin/env bash
# Pushes disk health to Gatus' external endpoint `disk` (D40: Gatus also alerts when the pushes stop).
#
#   healthy:  /srv (SRV_PATH) under 85 % used, and /mnt/backup (BACKUP_PATH) mounted and under 90 % used
#   otherwise: success=false with the reason in ?error=
#
# Run every 10 min by deploy/systemd/dj-health-push.timer (a user unit). GATUS_BACKUP_URL and GATUS_BACKUP_TOKEN come
# from the environment (the unit reads ~/.config/dj-health-push.env). Either unset: warn and exit 0, no request.
# GATUS_DISK_KEY overrides the endpoint key (default `_disk`: endpoint `disk`, no group).
set -uo pipefail

srv="${SRV_PATH:-/srv}"
backup="${BACKUP_PATH:-/mnt/backup}"
srv_max="${SRV_MAX_PCT:-85}"
backup_max="${BACKUP_MAX_PCT:-90}"

if [ -z "${GATUS_BACKUP_URL:-}" ] || [ -z "${GATUS_BACKUP_TOKEN:-}" ]; then
    echo "WARNING: GATUS_BACKUP_URL or GATUS_BACKUP_TOKEN is not set; nothing pushed" >&2
    exit 0
fi

used_pct() { df --output=pcent "$1" 2>/dev/null | tail -n 1 | tr -dc '0-9'; }

problems=()
pct=$(used_pct "$srv")
if [ -z "$pct" ]; then problems+=("$srv: df failed")
elif [ "$pct" -ge "$srv_max" ]; then problems+=("$srv is ${pct}% used (limit ${srv_max}%)"); fi

if ! mountpoint -q "$backup"; then
    problems+=("$backup is not mounted")
else
    pct=$(used_pct "$backup")
    if [ -z "$pct" ]; then problems+=("$backup: df failed")
    elif [ "$pct" -ge "$backup_max" ]; then problems+=("$backup is ${pct}% used (limit ${backup_max}%)"); fi
fi

url="${GATUS_BACKUP_URL%/}/api/v1/endpoints/${GATUS_DISK_KEY:-_disk}/external"
if [ "${#problems[@]}" -eq 0 ]; then
    query="success=true"
else
    reason=$(IFS=';'; echo "${problems[*]}")
    echo "disk problem: $reason" >&2
    query="success=false&error=$(printf %s "$reason" | tr -c 'A-Za-z0-9._~-' '_')"   # anything else becomes _
fi

# The token goes in on stdin, so `ps` never shows it.
printf 'Authorization: Bearer %s\n' "$GATUS_BACKUP_TOKEN" \
    | curl -fsS -m 10 -o /dev/null -X POST -H @- "$url?$query" \
    || { echo "WARNING: push to Gatus failed" >&2; exit 1; }
