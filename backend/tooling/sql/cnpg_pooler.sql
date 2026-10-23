-- Kubernetes only (WP-014): CloudNativePG's PgBouncer (Pooler) authenticates SupportX's roles by
-- looking their password hashes up through this function, as the operator's documentation
-- prescribes for databases other than its bootstrap database. Run as superuser by
-- tooling/deploy_migrate.py; the dev Compose stack and CI use their own PgBouncer and never run it.
-- The function only exposes hashes to the pooler's own role, never to supportx_app.
SELECT format('GRANT CONNECT ON DATABASE %I TO cnpg_pooler_pgbouncer', :'database') \gexec
CREATE OR REPLACE FUNCTION public.user_search(uname TEXT) RETURNS TABLE (usename name, passwd text) LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $$SELECT usename, passwd FROM pg_catalog.pg_shadow WHERE usename = $1$$;
REVOKE ALL ON FUNCTION public.user_search(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.user_search(text) TO cnpg_pooler_pgbouncer;
