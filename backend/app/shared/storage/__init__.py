"""Object storage through the S3 API only (D-016, D-054, D-075; WP-018, reused by WP-022).

One small port so modules never depend on a vendor: `put`, `get`, `delete`, `exists` and a
health check. On-prem the installation's SeaweedFS answers (Helm chart), on SaaS the cloud
provider's S3, in development MinIO. Keys are always prefixed with the tenant:
`<area>/<tenant>/<...>`, and callers check permissions before touching storage.

Failures are never silent: an unreachable store raises `StorageUnavailable` (503
`storage_unavailable`) and a missing configuration raises `StorageNotConfigured` (503
`storage_not_configured`); callers turn those into visible errors or failed jobs.
"""

from app.shared.storage.s3 import (
    ObjectStorage,
    S3Storage,
    StorageNotConfigured,
    StorageUnavailable,
    storage_from,
)

__all__ = [
    "ObjectStorage",
    "S3Storage",
    "StorageNotConfigured",
    "StorageUnavailable",
    "storage_from",
]
