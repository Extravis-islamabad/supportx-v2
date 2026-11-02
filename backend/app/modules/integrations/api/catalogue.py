"""Connector catalogue HTTP API under /api/v1/integrations/catalogue (WP-040). No logic here.

Reading needs `integrations.view`. Each entry says whether the caller may set it up and, when not,
why (a code the console turns into a sentence, REQ-INT-013 AC1). No secret ever appears: instances
carry names, codes and times only (REQ-INT-003 AC1).
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.identity_access import Subject
from app.modules.integrations.service import catalogue as service
from app.shared.api.ratelimit import rate_limit
from app.shared.connectors.ports import ConnectorCategory, ConnectorInstance, ConnectorStatus

catalogue_router = APIRouter(
    prefix="/integrations/catalogue",
    tags=["integrations"],
    dependencies=[Depends(rate_limit("integrations"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "Missing permission (integrations.view)."},
    },
)
View = Annotated[Subject, Depends(require_permission(service.VIEW))]


class ConnectorInstanceOut(BaseModel):
    """One configured connector and its health."""

    id: uuid.UUID
    name: str = Field(description="What the admin called it, such as a mailbox address.")
    status: ConnectorStatus
    reason: str | None = Field(description="Why it fails or is degraded (a label code).")
    last_success_at: datetime | None
    next_run_at: datetime | None
    credential_expires_at: datetime | None

    @classmethod
    def of(cls, instance: ConnectorInstance) -> "ConnectorInstanceOut":
        """From the registry's instance."""
        return cls(
            id=instance.id,
            name=instance.name,
            status=instance.status,
            reason=instance.reason,
            last_success_at=instance.last_success_at,
            next_run_at=instance.next_run_at,
            credential_expires_at=instance.credential_expires_at,
        )


class ConnectorKindOut(BaseModel):
    """One kind of connector in the catalogue, as the caller sees it."""

    code: str = Field(description="The kind's code; the console shows its label.")
    category: ConnectorCategory
    page: str = Field(description="The console page where it is set up.")
    keywords: list[str] = Field(description="Label codes the catalogue search also matches.")
    reason_labels: str = Field(description="Label prefix of its instances' failure reasons.")
    multiple: bool = Field(description="Whether more than one can be added.")
    available: bool = Field(description="Whether the tenant's edition includes it.")
    can_manage: bool
    manage_reason: str | None = Field(
        description="Why it cannot be set up: not_in_edition or no_permission."
    )
    instances: list[ConnectorInstanceOut]

    @classmethod
    def of(cls, entry: service.CatalogueEntry) -> "ConnectorKindOut":
        """From the service's entry."""
        return cls(
            code=entry.kind.code,
            category=entry.kind.category,
            page=entry.kind.page,
            keywords=list(entry.kind.keywords),
            reason_labels=entry.kind.reason_labels,
            multiple=entry.kind.multiple,
            available=entry.available,
            can_manage=entry.can_manage,
            manage_reason=entry.manage_reason,
            instances=[ConnectorInstanceOut.of(i) for i in entry.instances],
        )


@catalogue_router.get("", summary="Connector catalogue")
async def connector_catalogue(session: TenantSession, subject: View) -> list[ConnectorKindOut]:
    """Every kind of connector with its instances and their live status (REQ-INT-001)."""
    return [ConnectorKindOut.of(e) for e in await service.catalogue(session, subject)]
