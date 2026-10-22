#!/usr/bin/env bash
# First-start bootstrap for the dev PostgreSQL. Runs once, only when the data volume is empty.
#
# Role model (CLAUDE.md rule a, architecture.md §7.2):
#   supportx_migrator  owns the supportx database and schema; Alembic runs as this role.
#   supportx_app       runtime role for API and workers. Not superuser, not owner of anything,
#                      NOBYPASSRLS, so row-level security policies always apply to it.
#   keycloak, temporal own their own databases and cannot reach supportx.
set -euo pipefail

: "${SUPPORTX_MIGRATOR_PASSWORD:?}" "${SUPPORTX_APP_PASSWORD:?}"
: "${KEYCLOAK_DB_PASSWORD:?}" "${TEMPORAL_DB_PASSWORD:?}"

psql_su() {
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" "$@"
}

psql_su --dbname postgres \
  -v migrator_pw="$SUPPORTX_MIGRATOR_PASSWORD" \
  -v app_pw="$SUPPORTX_APP_PASSWORD" \
  -v keycloak_pw="$KEYCLOAK_DB_PASSWORD" \
  -v temporal_pw="$TEMPORAL_DB_PASSWORD" <<'SQL'
CREATE ROLE supportx_migrator LOGIN PASSWORD :'migrator_pw'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE supportx_app LOGIN PASSWORD :'app_pw'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
CREATE ROLE keycloak LOGIN PASSWORD :'keycloak_pw'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE temporal LOGIN PASSWORD :'temporal_pw'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

CREATE DATABASE supportx OWNER supportx_migrator;
CREATE DATABASE keycloak OWNER keycloak;
-- Temporal's auto-setup also needs a visibility store next to the main one.
CREATE DATABASE temporal OWNER temporal;
CREATE DATABASE temporal_visibility OWNER temporal;

-- No role reaches a database it was not granted.
REVOKE ALL ON DATABASE supportx, keycloak, temporal, temporal_visibility FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE supportx TO supportx_app;
SQL

psql_su --dbname supportx <<'SQL'
-- Extensions are created by the superuser; the app roles only use them.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

-- Only the migrator may create objects; the app may only use what the migrator grants.
ALTER SCHEMA public OWNER TO supportx_migrator;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO supportx_app;

-- Tables the migrator creates later are usable (DML only) by the app, never owned by it.
ALTER DEFAULT PRIVILEGES FOR ROLE supportx_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO supportx_app;
ALTER DEFAULT PRIVILEGES FOR ROLE supportx_migrator IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO supportx_app;
SQL

psql_su --dbname temporal -c 'ALTER SCHEMA public OWNER TO temporal;'
psql_su --dbname temporal_visibility -c 'ALTER SCHEMA public OWNER TO temporal;'
psql_su --dbname keycloak -c 'ALTER SCHEMA public OWNER TO keycloak;'
