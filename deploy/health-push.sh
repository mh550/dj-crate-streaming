#!/usr/bin/env bash
# Pushes two results to Gatus' external endpoints (a failure carries the reason in ?error=):
#
#   disk:    /srv (SRV_PATH) under 85 % used, and /mnt/backup (BACKUP_PATH) mounted and under 90 % used
#            (D40: Gatus also alerts when these pushes stop)
#   backup:  the nightly restic-backup.service (BACKUP_UNIT) succeeded and ended under 26 h (BACKUP_MAX_AGE_H) ago,
#            from systemd (D42). Gatus' own 26 h heartbeat restarts with Gatus, so this is what makes a missed backup
#            alert on time (H2/H3 review I3). systemd clears a run's result when the next one starts, and at boot:
#            then nothing is pushed (deploy/restic-backup's own push and the heartbeat decide), unless the box has
#            been up longer than the limit without a run.
#
# Run every 10 min by deploy/systemd/dj-health-push.timer (a user unit). GATUS_BACKUP_URL and GATUS_BACKUP_TOKEN come
# from the environment (the unit reads ~/.config/dj-health-push.env). Either unset: warn and exit 0, no request.
# GATUS_DISK_KEY and GATUS_BACKUP_KEY override the endpoint keys (default `_disk`, `_backup`: no group).
# Exit 1 if a push failed.
set -uo pipefail

srv="${SRV_PATH:-/srv}"
backup="${BACKUP_PATH:-/mnt/backup}"
srv_max="${SRV_MAX_PCT:-85}"
backup_max="${BACKUP_MAX_PCT:-90}"
unit="${BACKUP_UNIT:-restic-backup.service}"
max_age_h="${BACKUP_MAX_AGE_H:-26}"

if [ -z "${GATUS_BACKUP_URL:-}" ] || [ -z "${GATUS_BACKUP_TOKEN:-}" ]; then
    echo "WARNING: GATUS_BACKUP_URL or GATUS_BACKUP_TOKEN is not set; nothing pushed" >&2
    exit 0
fi

# urlencode <text>: percent-encoded for a query string (the reasons are ASCII)
urlencode() {
    local s="$1" out="" c i
    for ((i = 0; i < ${#s}; i++)); do
        c="${s:i:1}"
        case "$c" in [A-Za-z0-9._~-]) out+="$c" ;; *) printf -v c '%%%02X' "'$c"; out+="$c" ;; esac
    done
    printf %s "$out"
}

# push <key> <label> [problem…]: success=true with no problems, else success=false with the reasons in error=
pushed_ok=1
push() {
    local key="$1" label="$2" query="success=true" reason
    shift 2
    if [ "$#" -gt 0 ]; then
        reason=$(IFS=';'; echo "$*")
        echo "$label problem: $reason" >&2
        query="success=false&error=$(urlencode "$reason")"
    fi
    # The token goes in on stdin, so `ps` never shows it.
    printf 'Authorization: Bearer %s\n' "$GATUS_BACKUP_TOKEN" \
        | curl -fsS -m 10 -o /dev/null -X POST -H @- "${GATUS_BACKUP_URL%/}/api/v1/endpoints/$key/external?$query" \
        || { echo "WARNING: push of $label to Gatus failed" >&2; pushed_ok=0; }
}

# --- disk (timeout: a dying USB disk can hang df, and the unit would never finish)
used_pct() { timeout -k 5 20 df --output=pcent "$1" 2>/dev/null | tail -n 1 | tr -dc '0-9'; }

problems=()
pct=$(used_pct "$srv")
if [ -z "$pct" ]; then problems+=("$srv: df failed")
elif [ "$pct" -ge "$srv_max" ]; then problems+=("$srv is ${pct}% used (limit ${srv_max}%)"); fi

if ! timeout -k 5 20 mountpoint -q "$backup"; then
    problems+=("$backup is not mounted")
else
    pct=$(used_pct "$backup")
    if [ -z "$pct" ]; then problems+=("$backup: df failed")
    elif [ "$pct" -ge "$backup_max" ]; then problems+=("$backup is ${pct}% used (limit ${backup_max}%)"); fi
fi
push "${GATUS_DISK_KEY:-_disk}" disk ${problems[@]+"${problems[@]}"}

# --- backup, from systemd: one `show`, parsed as key=value (systemd prints its own order); end time in epoch seconds
declare -A sd=()
if show=$(systemctl show "$unit" --timestamp=unix -p LoadState -p ActiveState -p Result -p ExecMainStatus -p ExecMainExitTimestamp); then
    while IFS='=' read -r k v; do [ -n "$k" ] && sd[$k]="$v"; done <<<"$show"
    ended="${sd[ExecMainExitTimestamp]:-}"
    ended="${ended#@}"
    if [ "${sd[LoadState]:-}" != loaded ]; then          # a typo in BACKUP_UNIT would otherwise read as "no run yet"
        push "${GATUS_BACKUP_KEY:-_backup}" backup "$unit is ${sd[LoadState]:-unknown}"
    elif [[ "${sd[ActiveState]:-}" == activ* ]]; then
        echo "backup: $unit is running; not reported" >&2
    elif ! [[ "$ended" =~ ^[0-9]+$ ]]; then
        up=$(cut -d. -f1 "${UPTIME_FILE:-/proc/uptime}" 2>/dev/null)
        up_h=$(( ${up:-0} / 3600 ))
        if [ "$up_h" -ge "$max_age_h" ]; then
            push "${GATUS_BACKUP_KEY:-_backup}" backup "no run of $unit since boot $up_h h ago (limit $max_age_h h)"
        else
            echo "backup: no run of $unit since boot $up_h h ago; not reported yet" >&2
        fi
    elif [ "${sd[Result]:-}" != success ] || [ "${sd[ExecMainStatus]:-}" != 0 ]; then
        push "${GATUS_BACKUP_KEY:-_backup}" backup "last backup exited ${sd[ExecMainStatus]:-?} (${sd[Result]:-?})"
    elif age_h=$(( ($(date +%s) - ended) / 3600 )); [ "$age_h" -ge "$max_age_h" ]; then
        push "${GATUS_BACKUP_KEY:-_backup}" backup "last backup ended $age_h h ago (limit $max_age_h h)"
    else
        push "${GATUS_BACKUP_KEY:-_backup}" backup
    fi
else
    push "${GATUS_BACKUP_KEY:-_backup}" backup "systemctl show $unit failed"
fi

[ "$pushed_ok" = 1 ]
