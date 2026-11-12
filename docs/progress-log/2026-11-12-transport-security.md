### 2026-11-12 — Audit row 5 (lane B): transport security in the chart

- **Scope:** the engineering-practices audit's row 5 (transport defaults), four commits on
  `fix/security-audit-b2`.
- **Built:** HTTPS by default at the gateway with plain HTTP only redirecting (301), from your
  own Secret or a cert-manager Certificate (`routing.tls`); a chart-local internal CA through
  cert-manager (`internalTls`, or your own issuer); Valkey and Sentinel TLS only in the HA profile
  with the app, Centrifugo and the helm test verifying; NATS client and route TLS in the HA
  profile; PostgreSQL verify-full from the API, workers and migrate Job against CloudNativePG's CA,
  with the pooler named in the cluster's server certificate (HA first). One verified client
  context in `app/core/tls.py`; settings refuse a CA with a plaintext URL.
- **Open:** single-node PostgreSQL verification (`values-single-node.yaml` keeps it off until the
  Cluster workflow's HA job has proven it); Keycloak's and Temporal's own database connections;
  the audit document's row 5 status, once the Cluster run is green.
- **Tests:** test_core_tls, test_database_tls, test_valkey_client (TLS cases),
  tests/ha/test_valkey_failover under TLS (Docker, the scripts as shipped), chart-lint transport
  checks for every profile; by hand on Docker: Centrifugo's engine through TLS sentinels, a TLS
  NATS cluster of three with an R3 stream, asyncpg verify-full against a TLS PostgreSQL.
