#!/bin/sh
# Restore the pilot dataset into a database migrated to main's Alembic head,
# using only privileges a managed PostgreSQL service actually grants.
#
#   infra/production-smoke/restore-dataset.sh --dump waterloo-main-data.dump \
#       --container pathable-envelope-db-1 --user pathable_app --db pathable_managed
#
# Why this script exists rather than one pg_restore line: the obvious
# invocation is `pg_restore --data-only --disable-triggers`, and it needs
# superuser. `--disable-triggers` turns off *system* triggers, which is how
# foreign keys are enforced, and PostgreSQL reserves that for superusers.
# DigitalOcean, Fly, Render, Neon and Supabase all hand you a role that is not
# one — on DigitalOcean the account is `doadmin`, which owns your databases and
# is explicitly not a superuser. So a bootstrap that depends on
# `--disable-triggers` is a bootstrap that works on a laptop and fails on the
# first real database it meets.
#
# The fix costs nothing. `--disable-triggers` exists because pg_dump cannot
# promise a working order for every schema — circular foreign keys have no such
# order. This schema is a tree, and measured against the real archive pg_dump
# already emits a usable order for it, so the flag was never doing anything
# except demanding a privilege. Rather than depend on that happening to stay
# true, the order is stated here and handed to `pg_restore --use-list`, the
# documented way to control it.
#
#     pilot_regions        no foreign keys
#     dataset_versions     -> pilot_regions
#     ingestion_runs       -> dataset_versions
#     graph_nodes          -> dataset_versions
#     graph_edges          -> dataset_versions, graph_nodes (from and to)
#
# The whole load runs in one transaction, so a failure leaves an empty database
# rather than half a network, and the verification at the end refuses to report
# success on a partial restore.
#
# Requires: the dump was produced by `pg_dump --data-only --no-owner
# --no-privileges --format=custom` over exactly these five tables.

set -eu

CONTAINER=""
DUMP=""
DB_USER=""
DB_NAME=""
SKIP_VERIFY=0

usage() {
    cat <<'USAGE'
usage: restore-dataset.sh --dump FILE --user ROLE --db NAME [--container NAME] [--skip-verify]

  --dump       Custom-format archive from pg_dump (see the header of this file).
  --user       Role to connect as. Must own the tables; must NOT be a superuser.
  --db         Database, already migrated to main's Alembic head.
  --container  Run psql/pg_restore inside this Docker container. Omit to use
               the tools on PATH against PGHOST/PGPORT/PGPASSWORD.
  --skip-verify  Load without the post-restore checks. For debugging only.
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --dump) DUMP="$2"; shift 2 ;;
        --container) CONTAINER="$2"; shift 2 ;;
        --user) DB_USER="$2"; shift 2 ;;
        --db) DB_NAME="$2"; shift 2 ;;
        --skip-verify) SKIP_VERIFY=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

[ -n "$DUMP" ] && [ -n "$DB_USER" ] && [ -n "$DB_NAME" ] || { usage >&2; exit 2; }
[ -f "$DUMP" ] || { echo "no such dump: $DUMP" >&2; exit 2; }

# Dependency order. Changing this is changing the contract with the schema's
# foreign keys, so it is one list in one place.
TABLE_ORDER="pilot_regions dataset_versions ingestion_runs graph_nodes graph_edges"

log() { printf '%s restore-dataset: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1"; }

# Every database command goes through these two, so container and host modes
# differ in exactly one place.
if [ -n "$CONTAINER" ]; then
    REMOTE_DUMP="/tmp/pathable-restore-$$.dump"
    REMOTE_LIST="/tmp/pathable-restore-$$.list"
    in_db() { docker exec -i "$CONTAINER" "$@"; }
    cleanup() { docker exec "$CONTAINER" rm -f "$REMOTE_DUMP" "$REMOTE_LIST" >/dev/null 2>&1 || true; }
    trap cleanup EXIT INT TERM
    # Streamed rather than `docker cp`d: on Git Bash the destination path in a
    # `docker cp` argument is rewritten into a Windows path before Docker sees it.
    docker exec -i "$CONTAINER" sh -c "cat > $REMOTE_DUMP" < "$DUMP"
    ARCHIVE="$REMOTE_DUMP"
    LIST="$REMOTE_LIST"
else
    in_db() { "$@"; }
    ARCHIVE="$DUMP"
    LIST="$(mktemp)"
    cleanup() { rm -f "$LIST"; }
    trap cleanup EXIT INT TERM
fi

psql_q() { in_db psql -U "$DB_USER" -d "$DB_NAME" -At -c "$1"; }

# ---------------------------------------------------------------------------
# 1. Refuse an archive that is not what this script is documented to take
# ---------------------------------------------------------------------------
log "inspecting the archive"
TOC="$(in_db pg_restore --list "$ARCHIVE")"

UNEXPECTED="$(printf '%s\n' "$TOC" \
    | grep -E '^[0-9]+; [0-9]+ [0-9]+ TABLE DATA ' \
    | sed -E 's/.*TABLE DATA [^ ]+ ([^ ]+) .*/\1/' \
    | while read -r table; do
        case " $TABLE_ORDER " in
            *" $table "*) ;;
            *) echo "$table" ;;
        esac
    done)"
if [ -n "$UNEXPECTED" ]; then
    log "refusing: the archive carries tables this bootstrap does not support:"
    printf '  %s\n' $UNEXPECTED >&2
    log "the supported set is: $TABLE_ORDER"
    exit 1
fi

SCHEMA_ENTRIES="$(printf '%s\n' "$TOC" | grep -vE '^;' | grep -vE ' TABLE DATA ' \
    | grep -E ' (TABLE|INDEX|CONSTRAINT|FK CONSTRAINT|SEQUENCE|TRIGGER|EXTENSION|SCHEMA) ' || true)"
if [ -n "$SCHEMA_ENTRIES" ]; then
    log "refusing: the archive contains schema objects; the schema must come from"
    log "Alembic, not from a dump. Re-export with --data-only."
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. Preconditions: the target must be migrated, empty and owned by this role
# ---------------------------------------------------------------------------
log "checking the target database"
WHOAMI="$(psql_q "select current_user")"
IS_SUPER="$(psql_q "select rolsuper from pg_roles where rolname = current_user")"
log "connected as ${WHOAMI} (superuser: ${IS_SUPER})"
if [ "$IS_SUPER" = "t" ]; then
    log "note: this role IS a superuser. The restore below does not need that;"
    log "run it as an ordinary owner role to prove the managed-hosting path."
fi

REVISION="$(psql_q "select version_num from alembic_version" || true)"
if [ -z "$REVISION" ]; then
    log "refusing: no alembic_version row. Migrate the database first:"
    log "  alembic upgrade head"
    exit 1
fi
log "alembic revision ${REVISION}"

EXISTING="$(psql_q "select coalesce(sum(n), 0) from (
    select count(*) n from graph_edges
    union all select count(*) from graph_nodes
    union all select count(*) from dataset_versions
    union all select count(*) from pilot_regions) t")"
if [ "$EXISTING" != "0" ]; then
    log "refusing: the target already holds ${EXISTING} rows across the map-fact tables."
    log "This bootstrap loads into an empty database so a partial or doubled"
    log "network can never be mistaken for a restored one."
    exit 1
fi

# ---------------------------------------------------------------------------
# 3. Restore, in dependency order, in one transaction
# ---------------------------------------------------------------------------
log "building the table-of-contents order: $TABLE_ORDER"
: > "${LIST}.local"
for table in $TABLE_ORDER; do
    printf '%s\n' "$TOC" \
        | grep -E "^[0-9]+; [0-9]+ [0-9]+ TABLE DATA [^ ]+ ${table} " >> "${LIST}.local" || {
            log "refusing: the archive has no data for ${table}"
            exit 1
        }
done
if [ -n "$CONTAINER" ]; then
    docker exec -i "$CONTAINER" sh -c "cat > $LIST" < "${LIST}.local"
    rm -f "${LIST}.local"
else
    mv "${LIST}.local" "$LIST"
fi

log "restoring (single transaction, no superuser, no --disable-triggers)"
STARTED="$(date +%s)"
in_db pg_restore \
    --username "$DB_USER" \
    --dbname "$DB_NAME" \
    --data-only \
    --no-owner \
    --no-privileges \
    --single-transaction \
    --use-list "$LIST" \
    "$ARCHIVE"
ELAPSED="$(( $(date +%s) - STARTED ))"
log "restored in ${ELAPSED}s"

log "analyzing"
# Named rather than a bare ANALYZE: an ordinary role may not analyze the shared
# catalogs, and a screenful of permission warnings in a bootstrap teaches people
# to ignore its output.
psql_q "analyze $(echo "$TABLE_ORDER" | tr ' ' ',')" >/dev/null

# ---------------------------------------------------------------------------
# 4. Prove it landed. A bootstrap that cannot fail loudly is not a bootstrap.
# ---------------------------------------------------------------------------
if [ "$SKIP_VERIFY" = "1" ]; then
    log "skipping verification at the caller's request"
    exit 0
fi

log "verifying"
FAILED=0
check() {
    label="$1"; actual="$2"; expected="$3"
    if [ "$actual" = "$expected" ]; then
        log "  ok    ${label}: ${actual}"
    else
        log "  FAIL  ${label}: got ${actual}, expected ${expected}"
        FAILED=1
    fi
}

ACTIVE="$(psql_q "select id::text from dataset_versions where status='active' and source_type='osm'")"
if [ -z "$ACTIVE" ]; then
    log "  FAIL  no active OpenStreetMap dataset after restore"
    exit 1
fi
log "  active dataset ${ACTIVE}"

check "nodes"    "$(psql_q "select count(*) from graph_nodes where dataset_version_id='${ACTIVE}'")" \
                 "$(psql_q "select node_count from dataset_versions where id='${ACTIVE}'")"
check "segments" "$(psql_q "select count(*) from graph_edges where dataset_version_id='${ACTIVE}'")" \
                 "$(psql_q "select edge_count from dataset_versions where id='${ACTIVE}'")"
check "orphaned edges (from_node)" \
      "$(psql_q "select count(*) from graph_edges e left join graph_nodes n on n.id = e.from_node_id where n.id is null")" "0"
check "orphaned edges (to_node)" \
      "$(psql_q "select count(*) from graph_edges e left join graph_nodes n on n.id = e.to_node_id where n.id is null")" "0"
check "orphaned nodes" \
      "$(psql_q "select count(*) from graph_nodes n left join dataset_versions d on d.id = n.dataset_version_id where d.id is null")" "0"
check "invalid geometries" \
      "$(psql_q "select count(*) from graph_edges where not ST_IsValid(geometry)")" "0"
check "non-linestring geometries" \
      "$(psql_q "select count(*) from graph_edges where GeometryType(geometry) <> 'LINESTRING'")" "0"

check "incline_direction check constraint"       "$(psql_q "select count(*) from pg_constraint where conrelid='graph_edges'::regclass and contype='c' and conname='ck_graph_edges_edge_incline_direction'")" "1"
check "rows violating the incline_direction check"       "$(psql_q "select count(*) from graph_edges where incline_direction not in ('up','down','unknown')")" "0"

log "  foreign keys on graph_edges: $(psql_q "select count(*) from pg_constraint where conrelid='graph_edges'::regclass and contype='f'")"
log "  check constraints on graph_edges: $(psql_q "select count(*) from pg_constraint where conrelid='graph_edges'::regclass and contype='c'")"
log "  postgis: $(psql_q "select extversion from pg_extension where extname='postgis'")"
log "  database size: $(psql_q "select pg_size_pretty(pg_database_size(current_database()))")"

if [ "$FAILED" != "0" ]; then
    log "VERIFICATION FAILED — do not use this database"
    exit 1
fi
log "dataset ${ACTIVE} restored and verified"
