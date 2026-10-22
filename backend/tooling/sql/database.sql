-- A SupportX database owned by the migrator; only supportx_app, supportx_relay (and the owner) may
-- connect.
SELECT format('CREATE DATABASE %I OWNER supportx_migrator', :'database')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'database') \gexec
REVOKE ALL ON DATABASE :"database" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE :"database" TO supportx_app;
GRANT CONNECT ON DATABASE :"database" TO supportx_relay;
