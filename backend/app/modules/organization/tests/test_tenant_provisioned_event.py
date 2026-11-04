"""The `organization.tenant.provisioned` contract (WP-031, D-138; no I/O).

Modules seed a new tenant's starting content from it, and a retried provisioning must stay safe
(lane B, 2026-11-04): so it carries the tenant's ID and nothing else, and it is registered.
"""

import uuid

from app.modules.organization.events import EVENTS, TenantProvisioned


def test_the_event_carries_only_the_tenant() -> None:
    assert TenantProvisioned.event_type == "organization.tenant.provisioned"
    assert TenantProvisioned.aggregate_type == "tenant"
    assert TenantProvisioned.schema_version == 1
    assert set(TenantProvisioned.model_fields) == {"tenant_id"}
    tenant = uuid.uuid4()
    assert TenantProvisioned(tenant_id=tenant).model_dump(mode="json") == {"tenant_id": str(tenant)}


def test_the_event_is_published_by_the_module() -> None:
    assert TenantProvisioned in EVENTS
