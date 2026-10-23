# ADR-012: Bundled component licences (MinIO, Grafana, Redis, monitoring stack)

- **Status:** Accepted (2026-10-24, D-038; Open before)
- **Date:** 2026-10-22
- **Source:** architecture.md §5 licence box, §19
- **Owner:** Haider (Product Owner)

## Context

On-prem installs redistribute third-party components. MinIO and Grafana are AGPL; Redis 7.4+ moved to non-OSI licences. Source-available and AGPL licences need legal approval.

## Decision

- **Redis — resolved (D-011, via D-004):** Valkey (BSD-3-Clause, Redis-compatible) replaces Redis everywhere.
- **Object storage — S3 API only (D-016):** application code talks to object storage through the S3
  API only and uses no MinIO-specific features (admin API, MinIO-only extensions), so the store is
  swappable per profile.
  - **Local development:** MinIO from the `pgsty/minio` and `pgsty/mc` community images (see Notes).
    Dev only; never bundled.
  - **SaaS:** the cloud provider's S3 service.
  - **On-prem bundle — SeaweedFS (Apache-2.0)** (D-038). Packaged with WP-014b (single node) and
    WP-014c (air-gapped bundle); the evaluation there covers HA and backup. MinIO is not bundled.
- **Monitoring stack — permissive only on-prem (D-038).** Grafana, Loki and Tempo are all AGPL, so
  the on-prem observability bundle is VictoriaMetrics + VictoriaLogs (Apache-2.0), Jaeger
  (Apache-2.0) and Perses (Apache-2.0, dashboards). Grafana (with Loki/Tempo) may be used only
  inside Extravis-run SaaS, never shipped to customers.

## Consequences

- Any other non-permissive component found later is added to this ADR.
- Code and config reference Valkey, never Redis-only features.

## Notes

Open in architecture.md §19 for the on-prem object store and Grafana until 2026-10-24, when the
WP-014 plan decisions closed both (D-038). Redis part resolved 2026-10-22 (D-011). Object-storage
direction set 2026-10-22 (D-016). Deployment components approved as D-037 are all permissive.

MinIO image situation (found in WP-002, 2026-10-22): MinIO Inc. no longer publishes community
container images. `minio/minio` and `minio/mc` pulls from Docker Hub are denied and the Quay tags
are gone. `pgsty/minio` is a maintained community build of the same AGPL source (on UBI 9 micro).
It is acceptable for local development, but it is a third-party build with no vendor support, so
it is not a basis for a bundled production component.
