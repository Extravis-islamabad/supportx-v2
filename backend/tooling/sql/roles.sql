-- SupportX roles (CLAUDE.md rule a, architecture.md §7.2).
--   supportx_migrator  owns the database and schema; runs migrations.
--   supportx_app       runtime role: not superuser, owns nothing, NOBYPASSRLS, NOINHERIT.
-- Missing roles are created; existing roles keep their passwords, only their safety attributes are
-- re-asserted on every run.
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', 'supportx_migrator', :'migrator_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supportx_migrator') \gexec
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', 'supportx_app', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supportx_app') \gexec
ALTER ROLE supportx_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE supportx_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
