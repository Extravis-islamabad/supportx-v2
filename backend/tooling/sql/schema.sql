-- Inside the SupportX database: extensions (created by the superuser, used by the roles) and schema
-- privileges. Only the migrator creates objects; table privileges for supportx_app are granted per
-- table by each migration (migrations/helpers.py grant_app), never by default privileges.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
ALTER SCHEMA public OWNER TO supportx_migrator;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO supportx_app;
