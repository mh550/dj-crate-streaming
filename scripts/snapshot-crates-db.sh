#!/usr/bin/env bash
# A consistent copy of crates.db, for the nightly restic backup to pick up.
#
# crates.db runs in SQLite WAL mode: recent writes (approvals, the wanted queue) sit in crates.db-wal and the main file can
# be a few KB. Copying the three files at different moments gives a database that may not open or may miss writes.
# `.backup` takes a consistent snapshot while the services keep running. Run it just before restic, as the owner of the
# file (mh550), e.g. as the first line of /usr/local/sbin/restic-backup:
#
#     sudo -u mh550 /home/mh550/projects/dj-crate-streaming/scripts/snapshot-crates-db.sh
#
# It prints one line and exits non-zero if the copy fails or does not pass SQLite's integrity check.
set -euo pipefail
db="${CRATES_DB:-/srv/docker/crates/crates.db}"
snap="$db.snap"
tmp="$snap.new"
rm -f "$tmp"
sqlite3 "$db" ".backup '$tmp'"
check="$(sqlite3 "$tmp" 'pragma integrity_check')"
if [ "$check" != "ok" ]; then
    echo "snapshot-crates-db: integrity_check said: $check" >&2
    rm -f "$tmp"
    exit 1
fi
mv -f "$tmp" "$snap"
echo "snapshot-crates-db: $snap $(stat -c %s "$snap") bytes, integrity ok"
