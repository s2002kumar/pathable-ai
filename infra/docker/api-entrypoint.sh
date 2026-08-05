#!/bin/sh
# PathAble API container entrypoint.
#
#   1. wait for the database, with a bounded retry budget
#   2. apply migrations
#   3. exec the server so it becomes PID 1 and receives SIGTERM directly
#
# Compose already gates startup on the database healthcheck. The wait below is
# still worth having: `service_healthy` means the server accepts connections, not
# that it finished the first-boot initdb pass, and other orchestrators offer no
# such gate at all.

set -eu

WAIT_ATTEMPTS="${DB_WAIT_ATTEMPTS:-30}"
WAIT_INTERVAL="${DB_WAIT_INTERVAL_SECONDS:-2}"

log() {
    printf '%s api-entrypoint: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1"
}

if [ -z "${DATABASE_URL:-}" ]; then
    log "DATABASE_URL is not set; starting without migrations. Readiness will report not_ready."
    exec "$@"
fi

log "waiting for the database (up to $((WAIT_ATTEMPTS * WAIT_INTERVAL))s)"

attempt=1
while [ "${attempt}" -le "${WAIT_ATTEMPTS}" ]; do
    # Uses the application's own validated settings, so the URL is parsed exactly
    # once in the system and the failure message never echoes the password.
    if python -c '
import sys

from sqlalchemy import create_engine, text

from pathable_api.core.config import Settings

settings = Settings()
engine = create_engine(settings.require_database_url(), connect_args={"connect_timeout": 3})
try:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
except Exception:
    sys.exit(1)
finally:
    engine.dispose()
' 2>/dev/null; then
        log "database reachable after ${attempt} attempt(s)"
        break
    fi

    if [ "${attempt}" -eq "${WAIT_ATTEMPTS}" ]; then
        log "database did not become reachable; giving up"
        exit 1
    fi

    attempt=$((attempt + 1))
    sleep "${WAIT_INTERVAL}"
done

log "applying migrations"
alembic upgrade head
log "migrations applied"

log "starting: $*"
exec "$@"
