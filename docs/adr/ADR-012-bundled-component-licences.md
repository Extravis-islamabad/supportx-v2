# ADR-012: Bundled component licences (MinIO, Grafana, Redis)

- **Status:** Open
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
  - **On-prem bundle — open:** evaluate SeaweedFS (Apache-2.0) and other S3-compatible stores
    (licence, air-gap install, HA, operational fit) before the first on-prem release. MinIO stays a
    candidate only if legal approves AGPL redistribution.
- **Grafana — open:** legal review before the first on-prem release; alternatives exist if needed.

## Consequences

- Any other non-permissive component found later is added to this ADR.
- Code and config reference Valkey, never Redis-only features.

## Notes

Open in architecture.md §19 for the on-prem object store and Grafana; decision required before the
first on-prem release. Redis part resolved 2026-10-22 (D-011). Object-storage direction set
2026-10-22 (D-016).

MinIO image situation (found in WP-002, 2026-10-22): MinIO Inc. no longer publishes community
container images. `minio/minio` and `minio/mc` pulls from Docker Hub are denied and the Quay tags
are gone. `pgsty/minio` is a maintained community build of the same AGPL source (on UBI 9 micro).
It is acceptable for local development, but it is a third-party build with no vendor support, so
it is not a basis for a bundled production component.
