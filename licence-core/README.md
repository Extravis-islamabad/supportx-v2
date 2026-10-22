# licence-core

Rust library for on-prem licensing (architecture.md §13, ADR-009): Ed25519 licence signature
verification, hardware fingerprint v1 (3-of-5 match), clock-rollback detection and enforcement,
exposed to Python through PyO3/maturin (approved in D-004). Domain code never calls it directly. It
sits behind the `licensing` module's entitlement interface (`has_feature`, `check_limit`, `remaining`).

Filled by **WP-013** (licence core prototype), after WP-009 (entitlement interface). Needs a Rust
toolchain installed. Production signing keys never live in this repo.
