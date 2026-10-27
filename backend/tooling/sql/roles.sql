-- SupportX roles (CLAUDE.md rule a, architecture.md §7.2).
--   supportx_migrator  owns the database and schema; runs migrations.
--   supportx_app       runtime role: not superuser, owns nothing, NOBYPASSRLS, NOINHERIT.
--   supportx_relay     outbox relay (WP-007): same safety attributes; per-table grants and RLS
--                      policies (migration 0003) let it read and mark outbox rows of every tenant
--                      and touch nothing else. Deliberately NOT BYPASSRLS: see
--                      docs/architecture/events.md, "Database roles".
--   supportx_report    reporting (WP-035, ADR-033): NOLOGIN, SELECT only on the tables each
--                      migration grants it (grant_report), NOBYPASSRLS. supportx_app switches to it
--                      with SET LOCAL ROLE inside report transactions, so report queries can
--                      never write, whatever the compiler emits.
-- Missing roles are created; existing roles keep their passwords, only their safety attributes are
-- re-asserted on every run.
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', 'supportx_migrator', :'migrator_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supportx_migrator') \gexec
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', 'supportx_app', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supportx_app') \gexec
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', 'supportx_relay', :'relay_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supportx_relay') \gexec
SELECT format('CREATE ROLE %I NOLOGIN', 'supportx_report')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supportx_report') \gexec
ALTER ROLE supportx_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE supportx_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
ALTER ROLE supportx_relay LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
ALTER ROLE supportx_report NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
GRANT supportx_report TO supportx_app;
