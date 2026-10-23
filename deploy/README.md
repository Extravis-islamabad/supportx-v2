# deploy

Everything needed to run SupportX outside a developer's editor (architecture.md §14):

- `compose/`: Docker Compose stack for local development only: PostgreSQL 16 + pgvector,
  PgBouncer, NATS JetStream, Temporal, Centrifugo, Keycloak, Valkey, OpenSearch, MinIO, Mailpit,
  ClickHouse, ClamAV. Driven by `make dev-*`; see `docs/dev-setup.md`. **WP-002.**
- `helm/supportx/`: one Helm chart for every profile (`values-dev.yaml`, `values-single-node.yaml`;
  HA, SaaS and air-gapped follow in WP-014b/c/d). **WP-014**, ADR-025.
- `images/`: Dockerfiles of the two INTERNAL/DEV images (backend, web) and the web server config.
- `k3d/`: the local cluster (k3s v1.36.5, D-038), its prerequisites and the e2e runner.
- `scripts/`: `secrets.sh` (random Secrets, never overwrites), `chart-lint.sh`.

How to run, what runs where, secrets and CI: `docs/deployment.md`.

Rule: dev tooling never deletes volumes or data it did not create (CLAUDE.md rule h).
