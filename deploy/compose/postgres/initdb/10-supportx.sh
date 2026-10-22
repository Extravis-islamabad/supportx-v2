#!/usr/bin/env bash
# First-start bootstrap for the dev PostgreSQL. Runs once, only when the data volume is empty.
#
# The SupportX roles (supportx_migrator, supportx_app) and the supportx database are defined in
# backend/tooling/sql/*.sql, mounted at /supportx-sql. The same files are executed by
# backend/tooling/db_bootstrap.py for tests and CI, so the dev stack can never drift from them.
# Keycloak and Temporal get their own roles and databases here (dev stack only).
set -euo pipefail

: "${SUPPORTX_MIGRATOR_PASSWORD:?}" "${SUPPORTX_APP_PASSWORD:?}"
: "${KEYCLOAK_DB_PASSWORD:?}" "${TEMPORAL_DB_PASSWORD:?}"
SQL_DIR=/supportx-sql

psql_su() {
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" "$@"
}

# --- SupportX (single source: backend/tooling/sql) ----------------------------------------------
psql_su --dbname postgres \
  -v app_password="$SUPPORTX_APP_PASSWORD" \
  -v migrator_password="$SUPPORTX_MIGRATOR_PASSWORD" \
  -f "$SQL_DIR/roles.sql"
psql_su --dbname postgres -v database=supportx -f "$SQL_DIR/database.sql"
psql_su --dbname supportx -f "$SQL_DIR/schema.sql"

# --- Keycloak and Temporal (dev stack only) ------------------------------------------------------
psql_su --dbname postgres \
  -v keycloak_pw="$KEYCLOAK_DB_PASSWORD" \
  -v temporal_pw="$TEMPORAL_DB_PASSWORD" <<'SQL'
CREATE ROLE keycloak LOGIN PASSWORD :'keycloak_pw'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE temporal LOGIN PASSWORD :'temporal_pw'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

CREATE DATABASE keycloak OWNER keycloak;
-- Temporal's auto-setup also needs a visibility store next to the main one.
CREATE DATABASE temporal OWNER temporal;
CREATE DATABASE temporal_visibility OWNER temporal;

REVOKE ALL ON DATABASE keycloak, temporal, temporal_visibility FROM PUBLIC;
SQL

psql_su --dbname temporal -c 'ALTER SCHEMA public OWNER TO temporal;'
psql_su --dbname temporal_visibility -c 'ALTER SCHEMA public OWNER TO temporal;'
psql_su --dbname keycloak -c 'ALTER SCHEMA public OWNER TO keycloak;'
