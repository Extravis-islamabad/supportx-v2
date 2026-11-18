"""GET /identity/security-overview (WP-057 S4d): the security screens' numbers, with flags.

`identity.manage` and the identity rate limit, as the other identity reads (lane B's condition
4). Counts and codes only; each tile links to the screen with the detail, which applies its own
rights (condition 1). Flags are recommendations, never enforced.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.domain.security_overview import SecurityArea, SecuritySeverity
from app.modules.identity_access.service import security_overview as service
from app.shared.api.ratelimit import rate_limit
from app.shared.clock import system_clock

Manage = Annotated[Subject, Depends(require_permission("identity.manage"))]

router = APIRouter(
    prefix="/identity",
    tags=["identity"],
    dependencies=[Depends(rate_limit("identity"))],
)


class FlagOut(BaseModel):
    """A weaker-than-recommended choice; labels: `security_flag.<code>`."""

    code: str
    area: SecurityArea
    severity: SecuritySeverity
    count: int | None = Field(description="How many things it is about, when it is about things.")


class MfaOut(BaseModel):
    """Roles somebody holds; the same counts as GET /identity/mfa."""

    roles: int
    roles_required: int
    holders: int
    enrolled: int


class KeysOut(BaseModel):
    """Active keys and those flagged; the same flags as GET /api-keys."""

    active: int
    out_of_policy: int
    unused: int


class RecommendationsOut(BaseModel):
    """What each flag compares to: recommendations, never enforced (lane B: a pinned model)."""

    password_min_length: int
    password_breached_check: bool
    console_idle_seconds: int
    console_absolute_seconds: int
    key_max_lifetime_days: int
    allow_non_expiring_keys: bool
    sso_expiry_warn_days: int
    sso_expiry_urgent_days: int


class SecurityOverviewOut(BaseModel):
    """One tile per area, the flags (most severe first) and the recommendations they compare to."""

    sso_required: str = Field(description="off, technicians or everyone.")
    sso_setups: int
    sso_expiry_days_left: int | None = Field(
        description="Days until the soonest certificate or secret runs out; null: none set. "
        "A SAML certificate is as of the set-up's last connection check."
    )
    mfa: MfaOut
    password_min_length: int
    password_breached_check: bool
    console_idle_seconds: int
    console_absolute_seconds: int
    network_rules: dict[str, int] = Field(
        description="Ranges listed per app (console, portal, api); 0: open to every address."
    )
    keys: KeysOut | None = Field(description="Null without api_keys.manage (see tiles_hidden).")
    service_accounts: int | None = Field(description="Null without api_keys.manage.")
    service_accounts_without_owner: int | None
    seal_states: dict[str, int] = Field(description="Sensitive custom fields by seal state.")
    key_since: datetime | None = Field(description="When the current data key was made.")
    failed_sign_ins: int | None = Field(
        description="Failed sign-ins in the last 7 days; null without identity.view_sign_ins."
    )
    locked_sign_ins: int | None = Field(description="Locked-out sign-ins in the last 7 days.")
    data_region: str | None = Field(
        description="The installation's data region as its operator states it; null: not shown."
    )
    flags: list[FlagOut]
    recommendations: RecommendationsOut
    tiles_hidden: list[SecurityArea] = Field(
        description="Tiles left out: you lack their screen's right; no flag comes from them."
    )


@router.get("/security-overview", summary="The security overview")
async def security_overview(
    request: Request, response: Response, session: TenantSession, subject: Manage
) -> SecurityOverviewOut:
    """Each area's numbers from its own screen's service, and the weak choices to look at."""
    found = await service.overview(session, subject, request.app.state.settings, system_clock.now())
    response.headers["Cache-Control"] = "no-store"
    return SecurityOverviewOut(
        sso_required=found.sso_required,
        sso_setups=found.sso_setups,
        sso_expiry_days_left=found.sso_expiry_days_left,
        mfa=MfaOut(**found.mfa.__dict__),
        password_min_length=found.password_min_length,
        password_breached_check=found.password_breached_check,
        console_idle_seconds=found.console_idle_seconds,
        console_absolute_seconds=found.console_absolute_seconds,
        network_rules=dict(found.network_rules),
        keys=None if found.keys is None else KeysOut(**found.keys.__dict__),
        service_accounts=found.service_accounts,
        service_accounts_without_owner=found.service_accounts_without_owner,
        seal_states=dict(found.seal_states),
        key_since=found.key_since,
        failed_sign_ins=found.failed_sign_ins,
        locked_sign_ins=found.locked_sign_ins,
        data_region=found.data_region,
        flags=[
            FlagOut(code=f.code, area=f.area, severity=f.severity, count=f.count)
            for f in found.flags
        ],
        recommendations=RecommendationsOut.model_validate(dict(found.recommendations)),
        tiles_hidden=found.tiles_hidden,
    )
