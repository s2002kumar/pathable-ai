#!/bin/sh
# First start of an empty data volume only (docker-entrypoint-initdb.d).
#
# Creates the role the API connects as — not a superuser, owner of its own
# database and nothing else — and installs the two extensions the migrations
# need. CREATE EXTENSION postgis is superuser-only, which is why it happens here
# and not in Alembic; migration 0001's CREATE EXTENSION IF NOT EXISTS is then a
# no-op. This is the same split a managed PostgreSQL service makes
# (docs/deployment/PRODUCTION_SMOKE.md, "Approximating a managed database").

set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -v app_user="$PATHABLE_DB_USER" \
    -v app_password="$PATHABLE_DB_PASSWORD" \
    -v app_db="$PATHABLE_DB_NAME" <<'SQL'
CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION NOINHERIT;
CREATE DATABASE :"app_db" OWNER :"app_user" TEMPLATE template0 ENCODING 'UTF8' LOCALE 'C';
\connect :"app_db"
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SQL
