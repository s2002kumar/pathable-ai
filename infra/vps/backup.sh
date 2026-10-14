#!/bin/sh
# Logical backup of the whole PathAble database on this host.
#
#   backup.sh [label]      label: scheduled (the timer), pre-deploy, manual (default)
#
# A full `pg_dump --format=custom` of the `pathable` database: schema, the map
# facts, the place index and the dataset-lifecycle evidence, with ownership. It
# is what restore.sh takes. The file name carries the UTC time, the label and
# the revision that was serving, and a .sha256 file sits beside it.
#
# Retention: files older than PATHABLE_BACKUP_KEEP_DAYS (14) are deleted, but
# the newest three are always kept, whatever their age, so a host that stopped
# backing up never deletes its last good copy.
#
# These backups live on the same disk as the database. They protect against a
# bad deploy, a bad migration and operator error — not against losing the host.
# Copy one off the host to cover that (docs/deployment/VPS.md, "Off-host copy").

set -eu

DEST="${PATHABLE_BACKUP_DIR:-/var/backups/pathable}"
KEEP_DAYS="${PATHABLE_BACKUP_KEEP_DAYS:-14}"
CONTAINER="${PATHABLE_DB_CONTAINER:-pathable-db-1}"
RELEASE="${PATHABLE_ROOT:-/srv/pathable}/release.env"
LABEL="${1:-manual}"

log() { printf '%s backup: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1"; }

case "$LABEL" in
    *[!a-z0-9-]*|"") log "label must be lowercase letters, digits and hyphens"; exit 2 ;;
esac

revision="$(sed -n 's/^PATHABLE_REVISION=//p' "$RELEASE" 2>/dev/null | cut -c1-12)"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
name="pathable-${stamp}-${LABEL}-${revision:-unknown}.dump"
mkdir -p "$DEST"
umask 077

started="$(date +%s)"
# Written under a temporary name and renamed only after pg_dump succeeds, so a
# half-written file is never mistaken for a backup.
docker exec "$CONTAINER" pg_dump -U postgres -d pathable --format=custom --compress=6 \
    > "$DEST/$name.partial"
mv "$DEST/$name.partial" "$DEST/$name"
( cd "$DEST" && sha256sum "$name" > "$name.sha256" )

# A dump that pg_restore cannot list is not a backup.
entries="$(docker exec -i "$CONTAINER" pg_restore --list < "$DEST/$name" | grep -c 'TABLE DATA')"
size="$(du -h "$DEST/$name" | cut -f1)"
log "wrote $DEST/$name ($size, $entries tables with data, $(( $(date +%s) - started ))s)"

# Retention: never below three files.
total="$(find "$DEST" -maxdepth 1 -name 'pathable-*.dump' | wc -l)"
find "$DEST" -maxdepth 1 -name 'pathable-*.dump' -mtime +"$KEEP_DAYS" -printf '%T@ %p\n' \
    | sort -n | while read -r _ old; do
        [ "$total" -le 3 ] && break
        rm -f "$old" "$old.sha256"
        log "expired $(basename "$old")"
        total=$((total - 1))
    done
