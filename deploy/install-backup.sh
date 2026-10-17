#!/usr/bin/env bash
# Install the nightly backup from a commit on main. Michael runs it (agents never do):
#
#     cd ~/projects/dj-crate-streaming && git pull && sudo deploy/install-backup.sh
#
#   scripts/snapshot-crates-db.sh  → /usr/local/lib/dj-crates/snapshot-crates-db.sh   (0755, root)
#   deploy/restic-backup           → /usr/local/sbin/restic-backup                     (0755, root)
#
# Refuses a dirty tree and a commit that is not on origin/main (an older one is fine: that is the rollback). The files
# come from the commit itself, not the working tree, so what is installed is exactly what the diff shows. Shows a diff
# of each file against what is installed, asks, installs, and prints the installed commit.
# The checks cover the files it installs, not this script: sudo runs the working-tree copy, so before running it make
# sure it is main's (`git diff origin/main -- deploy/install-backup.sh` prints nothing).
# RESTIC_BACKUP_TARGET and SNAPSHOT_TARGET override the targets (tests).
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# git runs as the checkout's owner, never as root: the repo's config (core.fsmonitor, filters) can name commands, and
# a root git could leave root-owned files in .git. --no-optional-locks: a status never rewrites the index.
owner="$(stat -c %U "$root")"
if [ "$(id -u)" = 0 ] && [ "$owner" != root ]; then
    git() { sudo -u "$owner" -- git --no-optional-locks -C "$root" "$@"; }
else
    git() { command git --no-optional-locks -C "$root" "$@"; }
fi

if [ -n "$(git status --porcelain)" ]; then
    echo "install-backup: the working tree has uncommitted changes; install from a clean checkout of main" >&2
    git status --short >&2
    exit 1
fi
commit="$(git rev-parse --short=10 HEAD)"
if ! git merge-base --is-ancestor HEAD origin/main 2>/dev/null; then
    echo "install-backup: HEAD ($commit, $(git rev-parse --abbrev-ref HEAD)) is not a commit on origin/main" >&2
    exit 1
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
pairs=("scripts/snapshot-crates-db.sh" "${SNAPSHOT_TARGET:-/usr/local/lib/dj-crates/snapshot-crates-db.sh}"
       "deploy/restic-backup" "${RESTIC_BACKUP_TARGET:-/usr/local/sbin/restic-backup}")
changed=0
for ((i = 0; i < ${#pairs[@]}; i += 2)); do
    path="${pairs[i]}" dst="${pairs[i+1]}"
    src="$tmp/$(basename "$path")"
    git show "HEAD:$path" >"$src"
    # Unchanged means the same bytes, 0755 and owned by whoever installs (root): a writable copy is not unchanged.
    if [ -f "$dst" ] && cmp -s "$src" "$dst" && [ "$(stat -c '%a %u' "$dst")" = "755 $(id -u)" ]; then
        echo "$dst: unchanged"
    else
        changed=1
        [ -f "$dst" ] && old="$dst" || old=/dev/null
        diff -u --label "$dst (installed)" --label "$path ($commit)" "$old" "$src" || true
    fi
done
if [ "$changed" = 0 ]; then
    echo "install-backup: already installed ($commit)"
    exit 0
fi

printf "install these? [y/N] "
read -r answer || true
case "${answer:-}" in [yY]*) ;; *) echo "install-backup: nothing installed"; exit 1 ;; esac
# The snapshot script first: a restic-backup that names a missing one would warn every night.
for ((i = 0; i < ${#pairs[@]}; i += 2)); do
    install -D -m 0755 "$tmp/$(basename "${pairs[i]}")" "${pairs[i+1]}"
done
echo "install-backup: installed $commit ($(git log -1 --format=%s HEAD))"
