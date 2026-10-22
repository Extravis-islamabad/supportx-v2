# deploy

Everything needed to run SupportX outside a developer's editor (architecture.md §14):

- `compose/`: Docker Compose stack for local development only: PostgreSQL 16 + pgvector,
  PgBouncer, NATS JetStream, Temporal, Centrifugo, Keycloak, Valkey, OpenSearch, MinIO, Mailpit,
  ClickHouse, ClamAV. Driven by `make dev-*`; see `docs/dev-setup.md`. **WP-002.**
- `helm/`: one Helm chart for every profile, with `values-*.yaml` per profile (dev, single-node,
  standard HA, enterprise HA, air-gapped), plus the k3d local cluster config (D-003). **WP-014.**

Rule: dev tooling never deletes volumes or data it did not create (CLAUDE.md rule h).
