#!/usr/bin/env bash
# Consistent copies of crates.db and navidrome.db, for the nightly restic backup to pick up and as a run's restore point.
#
# Both databases run in SQLite WAL mode: recent writes (approvals, the wanted queue, playlists) sit in <db>-wal and the
# main file can be a few KB. Copying the files at different moments gives a database that may not open or may miss
# writes. `.backup` takes a consistent snapshot while the services keep running. Run it just before restic, as the owner
# of the files (mh550), e.g. as the first line of /usr/local/sbin/restic-backup:
#
#     sudo -u mh550 /home/mh550/projects/dj-crate-streaming/scripts/snapshot-crates-db.sh
#
#   snapshot-crates-db.sh                   crates.db.snap and navidrome.db.snap (the nightly backup's call)
#   snapshot-crates-db.sh --suffix pre-x    crates.db.pre-x.snap and navidrome.db.pre-x.snap, a restore point that
#                                           the nightly call does not overwrite
#
# CRATES_DB and NAVIDROME_DB name the databases (defaults: the live ones under /srv/docker). A missing navidrome.db is
# skipped with a note on stderr. The suffix is letters, digits, '.', '_' and '-'. Each snapshot is one self-contained file (journal_mode=delete) written beside its database as
# <snapshot>.new; both are renamed into place only once both pass SQLite's integrity check, so a failed copy replaces
# no snapshot. A source that is locked (a checkpoint, another writer) is waited for up to 10 s. It prints one line per database; exit 1 if a copy fails, 2 on bad arguments.
set -euo pipefail
usage() { echo "usage: snapshot-crates-db.sh [--suffix <name>]" >&2; exit 2; }
fail() { echo "snapshot-crates-db: $1" >&2; exit 1; }
suffix=""
case $# in
    0) ;;
    2) [ "$1" = --suffix ] || usage
       suffix="$2"
       case "$suffix" in ""|*[!A-Za-z0-9._-]*) usage ;; esac ;;
    *) usage ;;
esac
end="${suffix:+.$suffix}.snap"
crates="${CRATES_DB:-/srv/docker/crates/crates.db}"
navidrome="${NAVIDROME_DB:-/srv/docker/navidrome/navidrome.db}"

dbs=("$crates")
if [ -e "$navidrome" ]; then
    dbs+=("$navidrome")
else
    echo "snapshot-crates-db: no navidrome.db at $navidrome, skipped" >&2
fi

tmps=()
trap 'rm -f "${tmps[@]}"' EXIT
for db in "${dbs[@]}"; do
    [ -f "$db" ] || fail "$db: no such file"           # sqlite3 would create an empty database
    tmp="$db$end.new"
    tmps+=("$tmp")
    rm -f "$tmp"
    err="$(sqlite3 -cmd '.timeout 10000' "$db" ".backup '$tmp'" 2>&1)" || fail "$db: .backup failed: $err"
    err="$(sqlite3 "$tmp" 'pragma journal_mode=delete' 2>&1)" || fail "$db: the copy does not open: $err"
    check="$(sqlite3 "$tmp" 'pragma integrity_check' 2>&1)" || true
    [ "$check" = ok ] || fail "$db: integrity_check said: ${check//$'\n'/; }"
done
for db in "${dbs[@]}"; do
    mv -f "$db$end.new" "$db$end"
    echo "snapshot-crates-db: $db$end $(stat -c %s "$db$end") bytes, integrity ok"
done
