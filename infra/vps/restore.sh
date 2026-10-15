#!/bin/sh
# Restore a backup.sh dump, and prove it is the database it claims to be.
#
#   restore.sh --into scratch    [--dump FILE]   non-destructive: a throwaway
#       PostGIS container, restored, verified, then removed. Production is not
#       touched. This is the routine proof that the backups restore.
#   restore.sh --into production --dump FILE --yes   disaster recovery: takes a
#       safety backup, stops the API, replaces the `pathable` database with the
#       dump, verifies it, and starts the API again.
#
# Without --dump, the newest file in the backup directory is used.
#
# Verification, in both modes:
#   * the Alembic revision, and that every map-fact and place-index table loaded
#   * the active OpenStreetMap dataset's node and segment counts against the
#     counts its own dataset_versions row records
#   * the place index's entry count against the counts its build row records
#   * the content checksum recomputed from the restored rows by the release's
#     own API image (`pathable datasets checksum`), which must match the one
#     recorded when the dataset was verified
#
# The dump's PostGIS and pg_trgm extensions are created by the superuser before
# the restore, exactly as db-init/20-pathable.sh does on a fresh volume, and the
# dump's own CREATE EXTENSION entries are skipped.

set -eu

ROOT="${PATHABLE_ROOT:-/srv/pathable}"
DEST="${PATHABLE_BACKUP_DIR:-/var/backups/pathable}"
SECRETS="$ROOT/secrets/pathable.env"
RELEASE="$ROOT/release.env"
PROD_DB="pathable-db-1"
PROD_API="pathable-api-1"
PROD_NETWORK="pathable_data"
SCRATCH_DB="pathable-restore-check-db"
SCRATCH_NETWORK="pathable-restore-check"
POSTGIS_IMAGE="postgis/postgis:17-3.5"
HERE="$(cd "$(dirname "$0")" && pwd)"

INTO=""; DUMP=""; YES=0
while [ $# -gt 0 ]; do
    case "$1" in
        --into) INTO="$2"; shift 2 ;;
        --dump) DUMP="$2"; shift 2 ;;
        --yes) YES=1; shift ;;
        *) sed -n '2,13p' "$0"; exit 2 ;;
    esac
done

log() { printf '%s restore: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1"; }
die() { log "$1"; exit 1; }
now() { date +%s.%N; }
elapsed() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.1f", b - a }'; }

case "$INTO" in scratch|production) ;; *) die "--into scratch|production is required" ;; esac
if [ -z "$DUMP" ]; then
    DUMP="$(find "$DEST" -maxdepth 1 -name 'pathable-*.dump' -printf '%T@ %p\n' | sort -n | tail -n 1 | cut -d' ' -f2-)"
fi
[ -n "$DUMP" ] && [ -f "$DUMP" ] || die "no dump to restore"
if [ -f "$DUMP.sha256" ]; then
    ( cd "$(dirname "$DUMP")" && sha256sum --quiet -c "$(basename "$DUMP").sha256" ) \
        || die "checksum mismatch: $DUMP is not the file backup.sh wrote"
fi
log "dump $(basename "$DUMP") ($(du -h "$DUMP" | cut -f1), sha256 $(sha256sum "$DUMP" | cut -c1-16)…)"

# shellcheck disable=SC1090
. "$SECRETS"
REVISION="$(sed -n 's/^PATHABLE_REVISION=//p' "$RELEASE")"
# The release's own image runs the checksum. PATHABLE_CLI_IMAGE overrides it for
# a release whose image cannot start the CLI: images built before the libexpat1
# fix in services/api/Dockerfile (see docs/deployment/VPS.md).
API_IMAGE="${PATHABLE_CLI_IMAGE:-pathable-api:$REVISION}"

# --- the restore itself, into database `pathable` of a running container ------
recreate_and_restore() {
    container="$1"
    docker exec -i "$container" psql -v ON_ERROR_STOP=1 -q -U postgres -d postgres <<SQL
DROP DATABASE IF EXISTS pathable WITH (FORCE);
CREATE DATABASE pathable OWNER pathable_app TEMPLATE template0 ENCODING 'UTF8' LOCALE 'C';
\connect pathable
CREATE EXTENSION postgis;
CREATE EXTENSION pg_trgm;
SQL
    docker exec -i "$container" sh -c 'cat > /tmp/pathable-restore.dump' < "$DUMP"
    docker exec "$container" sh -c \
        "pg_restore --list /tmp/pathable-restore.dump | grep -v ' EXTENSION ' > /tmp/pathable-restore.list"
    restore_started="$(now)"
    docker exec "$container" pg_restore -U postgres -d pathable \
        --exit-on-error --single-transaction \
        --use-list /tmp/pathable-restore.list /tmp/pathable-restore.dump
    docker exec "$container" rm -f /tmp/pathable-restore.dump /tmp/pathable-restore.list
    log "  pg_restore took $(elapsed "$restore_started" "$(now)")s"
    docker exec "$container" psql -q -U postgres -d pathable -c "vacuum analyze" >/dev/null
}

# --- verification -----------------------------------------------------------
FAILED=0
check() {
    if [ "$2" = "$3" ]; then log "  ok    $1: $2"; else log "  FAIL  $1: got $2, expected $3"; FAILED=1; fi
}
verify() {
    container="$1"; network="$2"; host="$3"
    q() { docker exec "$container" psql -U postgres -d pathable -At -c "$1"; }
    log "verifying"
    log "  alembic revision $(q 'select version_num from alembic_version')"
    active="$(q "select id from dataset_versions where status='active' and source_type='osm'")"
    [ -n "$active" ] || { log "  FAIL  no active OpenStreetMap dataset"; FAILED=1; return; }
    log "  active dataset $active"
    check "nodes" "$(q "select count(*) from graph_nodes where dataset_version_id='$active'")" \
        "$(q "select node_count from dataset_versions where id='$active'")"
    check "segments" "$(q "select count(*) from graph_edges where dataset_version_id='$active'")" \
        "$(q "select edge_count from dataset_versions where id='$active'")"
    check "place index entries" "$(q "select count(*) from gazetteer_entries")" \
        "$(q "select coalesce(sum(place_count + address_count + street_count), 0) from gazetteer_builds")"
    check "sealed-dataset triggers" \
        "$(q "select count(*) from pg_trigger where tgname in ('graph_nodes_immutable_once_sealed','graph_edges_immutable_once_sealed','dataset_versions_lifecycle')")" "3"
    check "role pathable_app is not a superuser" \
        "$(q "select rolsuper from pg_roles where rolname='pathable_app'")" "f"
    log "  database size $(q "select pg_size_pretty(pg_database_size('pathable'))")"

    # The checksum is recomputed by the release's own code, in its own container,
    # connected as the application role — the path the API itself reads through.
    log "  recomputing the content checksum with $API_IMAGE"
    checksum_started="$(now)"
    if docker run --rm --network "$network" --memory 1g \
        -e DATABASE_URL="postgresql+psycopg://pathable_app:${PATHABLE_DB_PASSWORD}@${host}:5432/pathable" \
        "$API_IMAGE" pathable datasets checksum "$active"; then
        log "  ok    content checksum matches ($(elapsed "$checksum_started" "$(now)")s)"
    else
        log "  FAIL  content checksum does not match, or none is recorded"
        FAILED=1
    fi
}

if [ "$INTO" = "scratch" ]; then
    cleanup() {
        docker rm -f "$SCRATCH_DB" >/dev/null 2>&1 || true
        docker network rm "$SCRATCH_NETWORK" >/dev/null 2>&1 || true
    }
    trap cleanup EXIT INT TERM
    cleanup
    docker network create --internal "$SCRATCH_NETWORK" >/dev/null
    scratch_password="$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    total_started="$(now)"
    docker run -d --name "$SCRATCH_DB" --network "$SCRATCH_NETWORK" --network-alias scratch \
        --memory 768m --shm-size 256m \
        -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD="$scratch_password" -e POSTGRES_DB=postgres \
        -e POSTGRES_INITDB_ARGS="--encoding=UTF8 --locale=C" \
        "$POSTGIS_IMAGE" >/dev/null
    # TCP, not the socket: the image's first-boot server listens on the socket only.
    until docker exec "$SCRATCH_DB" psql -h 127.0.0.1 -U postgres -d postgres -Atc 'select 1' >/dev/null 2>&1; do
        sleep 1
    done
    docker exec -i "$SCRATCH_DB" psql -v ON_ERROR_STOP=1 -q -U postgres -d postgres \
        -v pw="$PATHABLE_DB_PASSWORD" <<'SQL'
CREATE ROLE pathable_app LOGIN PASSWORD :'pw'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION NOINHERIT;
SQL
    log "restoring into a throwaway container ($SCRATCH_DB); production is not touched"
    recreate_and_restore "$SCRATCH_DB"
    verify "$SCRATCH_DB" "$SCRATCH_NETWORK" scratch
    log "scratch restore and verification took $(elapsed "$total_started" "$(now)")s in all"
else
    [ "$YES" = "1" ] || die "--into production replaces the live database; add --yes"
    log "safety backup of the database being replaced"
    "$HERE/backup.sh" pre-restore
    total_started="$(now)"
    docker stop "$PROD_API" >/dev/null
    log "API stopped; restoring into $PROD_DB"
    recreate_and_restore "$PROD_DB"
    verify "$PROD_DB" "$PROD_NETWORK" db
    if [ "$FAILED" != "0" ]; then
        die "VERIFICATION FAILED — the API was left stopped. The safety backup is the newest pre-restore file."
    fi
    docker start "$PROD_API" >/dev/null
    until docker exec "$PROD_API" python -c 'import urllib.request,sys; sys.exit(0 if urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health/ready", timeout=5).status==200 else 1)' >/dev/null 2>&1; do
        sleep 1
    done
    log "API ready again; outage $(elapsed "$total_started" "$(now)")s from stop to ready"
fi

[ "$FAILED" = "0" ] || die "VERIFICATION FAILED"
log "restore verified"
