"""GET /api/v1/entitlements: what the tenant's plan includes (WP-009).

For the UI to hide menus and show limit/grace notices. It is a convenience view only: every
enforcement happens on the server (route gate, `reserve`), never in the browser (§13.7).
No secrets: no signature, customer, licence ID, installation ID or fingerprint.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.authorization import require_signed_in
from app.core.database import TenantSession
from app.core.errors import ProblemDetail, ServiceUnavailable
from app.modules.licensing.domain.catalogue import Edition, Feature, LimitKey
from app.modules.licensing.domain.entitlement import EntitlementState, StateReason
from app.modules.licensing.service.entitlements import EntitlementService
from app.shared.api.ratelimit import rate_limit

router = APIRouter(
    prefix="/entitlements",
    tags=["entitlements"],
    dependencies=[Depends(rate_limit("entitlements"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        429: {"model": ProblemDetail, "description": "Rate limit exceeded."},
        503: {"model": ProblemDetail, "description": "Entitlements are not available."},
    },
)


class LimitOut(BaseModel):
    """A counted limit. `limit` null = unlimited; `used` null = not counted (yet) or not shown."""

    key: LimitKey
    limit: int | None
    used: int | None = Field(description="Live usage; shown to technicians and admins only.")
    remaining: int | None


class TermOut(BaseModel):
    """Validity of the plan or licence."""

    starts_at: datetime
    expires_at: datetime | None
    maintenance_until: datetime | None
    grace_days: int


class EntitlementsResponse(BaseModel):
    """The current tenant's entitlement. Codes render through labels (edition.*, feature.* ...)."""

    edition: Edition | None
    state: EntitlementState
    state_reason: StateReason | None
    writable: bool = Field(description="False in read-only mode: changes are refused.")
    grace_ends_at: datetime | None
    days_left: int | None = Field(description="Whole days of grace left, while in grace.")
    admin_warning: bool = Field(description="Show the licence warning banner to this user.")
    features: list[Feature]
    limits: list[LimitOut]
    term: TermOut | None


def get_service(request: Request) -> EntitlementService:
    """The running entitlement service (503 when the licensing module could not start one)."""
    service: EntitlementService | None = getattr(request.app.state, "entitlements", None)
    if service is None:
        raise ServiceUnavailable(code="entitlements_unavailable")
    return service


@router.get("", summary="Current entitlements")
async def read_entitlements(
    session: TenantSession,
    service: Annotated[EntitlementService, Depends(get_service)],
    subject: Annotated[Any, Depends(require_signed_in())],  # noqa: ANN401 - identity_access's Subject
) -> EntitlementsResponse:
    """Edition, features, limits with usage, state and term of the caller's tenant.

    Usage (seat counts) for subjects holding `users.view`; the admin warning for `licence.manage`.
    """
    summary = await service.summary(
        session, show_usage=subject.holds("users.view"), is_admin=subject.holds("licence.manage")
    )
    status = summary.status
    term = summary.term
    return EntitlementsResponse(
        edition=summary.edition,
        state=status.state,
        state_reason=status.reason,
        writable=status.allows_writes,
        grace_ends_at=status.grace_ends_at,
        days_left=summary.days_left,
        admin_warning=summary.admin_warning,
        features=summary.features,
        limits=[LimitOut(**vars(limit)) for limit in summary.limits],
        term=None
        if term is None
        else TermOut(
            starts_at=term.starts_at,
            expires_at=term.expires_at,
            maintenance_until=term.maintenance_until,
            grace_days=term.grace_days,
        ),
    )
