"""Fine-grained access to assets and CIs over HTTP (ADR-053; service/resource_access.py).

- `/resource-access/criteria`: what a rule may name, per resource (`roles.view`).
- `/resource-access/rules`: reading needs `roles.view`; adding, changing and removing need
  `roles.manage` too and a recent sign-in. Creates take an Idempotency-Key, changes and removals
  If-Match. Adding or changing needs the `fine_grained_access` feature; viewing and removing
  never do. Every change is audited as `role.resource_access_changed`, criteria before and after.
- `/people/{user_id}/access-rules`: how one person sees assets and CIs, from the same compile as
  their access (lane C 7): `roles.manage` or the person themself; an access-information read;
  criteria only. No logic here.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.authorization import require_permission, require_signed_in
from app.core.database import TenantSession
from app.core.errors import NotFound, PermissionDenied, ProblemDetail
from app.core.recent_auth import RecentAuth
from app.modules.audit import AuditNote, ReadCategory, audit_read, audited
from app.modules.identity_access.api.access import Policy
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.domain.resource_access import Resource
from app.modules.identity_access.infra.models import RoleResourceAccess, User
from app.modules.identity_access.service import resource_access as service
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit

router = APIRouter(
    tags=["roles"],
    dependencies=[Depends(rate_limit("roles"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "Missing permission or feature."},
        404: {
            "model": ProblemDetail,
            "description": "role_not_found, resource_access_rule_not_found, user_not_found",
        },
    },
)

View = Annotated[Subject, Depends(require_permission(service.VIEW))]
Manage = Annotated[Subject, Depends(require_permission(service.MANAGE))]
SignedIn = Annotated[Subject, Depends(require_signed_in())]
READ_ACCESS = audit_read(ReadCategory.ACCESS_INFORMATION)
WRITE: dict[int | str, dict[str, Any]] = {
    409: {"model": ProblemDetail, "description": "version_conflict"},
    422: {
        "model": ProblemDetail,
        "description": "criteria_required, criterion_unknown, criterion_invalid, invalid_choice, "
        "resource_access_limit_reached",
    },
    428: {"model": ProblemDetail, "description": "If-Match missing."},
}
Criteria = Annotated[
    dict[str, Any],
    Field(
        description="What passes: {criterion: [IDs]} or a ceiling code; every criterion named "
        "must hold. See /resource-access/criteria."
    ),
]


class ResourceCriterionOut(BaseModel):
    """A criterion a rule may name."""

    key: str
    kind: str = Field(description="`ids` (a list of IDs) or `ceiling` (one code of `values`).")
    values: list[str] = Field(default_factory=list, description="A ceiling's codes, lowest first.")


class ResourceCriteriaOut(BaseModel):
    """What a resource's rules may name."""

    resource: Resource
    criteria: list[ResourceCriterionOut]


class ResourceRuleOut(BaseModel):
    """One role's rule narrowing assets or CIs."""

    id: uuid.UUID
    role_id: uuid.UUID
    resource: Resource
    criteria: dict[str, Any]
    updated_at: datetime
    updated_by: uuid.UUID | None
    version: int = Field(description="Send it back as If-Match to change or remove the rule.")

    @classmethod
    def of(cls, row: RoleResourceAccess) -> "ResourceRuleOut":
        """From the stored rule."""
        return cls(
            id=row.id,
            role_id=row.role_id,
            resource=Resource(row.resource),
            criteria=dict(row.criteria),
            updated_at=row.updated_at,
            updated_by=row.updated_by,
            version=row.version,
        )


class ResourceRuleIn(BaseModel):
    """A new rule."""

    model_config = ConfigDict(extra="forbid")

    role_id: uuid.UUID
    resource: Resource
    criteria: Criteria


class ResourceRulePatch(BaseModel):
    """Other criteria for a rule."""

    model_config = ConfigDict(extra="forbid")

    criteria: Criteria


class NarrowedOut(BaseModel):
    """One resource for one person: their roles' rules, criteria only."""

    rules: list[dict[str, Any]] = Field(
        description="Every narrowed role's rules: each role shows its own scope where they hold."
    )
    whole_scope_roles: int = Field(
        description="Roles that see the resource with no rule: their own scope applies in full."
    )


class PersonResourceAccessOut(BaseModel):
    """How one person sees assets and CIs (the same compile as their access)."""

    user_id: uuid.UUID
    tenant_admin: bool = Field(description="Tenant admins are never narrowed.")
    narrowed: dict[str, NarrowedOut] = Field(
        description="Per resource some role of theirs narrows. A resource not named shows what "
        "the person's scope shows."
    )


Audited = Annotated[AuditNote, audited("role.resource_access_changed", object_type="role")]


def _note(note: AuditNote, change: service.RuleChange) -> None:
    """The audit entry: which rule, and its criteria before and after."""
    note.object_id = str(change.rule.role_id)
    note.details = {
        "rule_id": str(change.rule.id),
        "change": change.action,
        "resource": change.rule.resource,
        "old_criteria": change.old_criteria,
        "new_criteria": change.new_criteria,
    }


@router.get("/resource-access/criteria", summary="What fine-grained access rules may name")
async def list_criteria(subject: View) -> list[ResourceCriteriaOut]:
    """Per resource, the criteria its rules may name (`roles.view`)."""
    del subject
    found: list[ResourceCriteriaOut] = []
    for resource in Resource:
        registered = service.criteria_of(resource.value)
        if registered is None:
            continue
        found.append(
            ResourceCriteriaOut(
                resource=resource,
                criteria=[
                    ResourceCriterionOut(
                        key=key, kind=kind, values=list(registered.ceilings.get(key, ()))
                    )
                    for key, kind in registered.fields.items()
                ],
            )
        )
    return found


@router.get(
    "/resource-access/rules", summary="Fine-grained access rules", dependencies=[READ_ACCESS]
)
async def list_rules(
    session: TenantSession,
    subject: View,
    role_id: Annotated[uuid.UUID | None, Query()] = None,
    resource: Annotated[Resource | None, Query()] = None,
) -> list[ResourceRuleOut]:
    """The live rules; narrowed to a role or a resource when given."""
    rows = await service.list_rules(
        session, subject, role_id=role_id, resource=None if resource is None else resource.value
    )
    return [ResourceRuleOut.of(r) for r in rows]


@router.post(
    "/resource-access/rules",
    summary="Narrow which assets or CIs a role shows",
    dependencies=[RecentAuth],  # as sensitive as role changes (REQ-SEC-027)
    status_code=status.HTTP_201_CREATED,
    response_model=ResourceRuleOut,
    responses={**WRITE, 201: {"model": ResourceRuleOut, "description": "Created (or replayed)."}},
)
async def add_rule(
    body: ResourceRuleIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    note: Audited,
) -> Response:
    """A new rule (Idempotency-Key); needs the `fine_grained_access` feature."""
    note.skip = True  # a replay changes nothing

    async def run() -> Created:
        change = await service.add_rule(
            session,
            subject,
            role_id=body.role_id,
            resource=body.resource.value,
            criteria=body.criteria,
        )
        note.skip = False
        _note(note, change)
        return Created(
            body=ResourceRuleOut.of(change.rule), headers={"ETag": f'"{change.rule.version}"'}
        )

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.patch(
    "/resource-access/rules/{rule_id}",
    summary="Change a fine-grained access rule",
    dependencies=[RecentAuth],
    responses=WRITE,
)
async def change_rule(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    rule_id: uuid.UUID,
    body: ResourceRulePatch,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    response: Response,
    note: Audited,
) -> ResourceRuleOut:
    """Other criteria (If-Match); needs the `fine_grained_access` feature."""
    change = await service.change_rule(
        session, subject, rule_id, criteria=body.criteria, expected_version=version
    )
    _note(note, change)
    note.skip = change.old_criteria == change.new_criteria
    set_etag(response, change.rule.version)
    return ResourceRuleOut.of(change.rule)


@router.delete(
    "/resource-access/rules/{rule_id}",
    summary="Remove a fine-grained access rule",
    dependencies=[RecentAuth],
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE,
)
async def remove_rule(
    rule_id: uuid.UUID,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    note: Audited,
) -> None:
    """Removed (If-Match), whatever the licence says (ADR-053 §5)."""
    change = await service.remove_rule(session, subject, rule_id, expected_version=version)
    _note(note, change)


@router.get(
    "/people/{user_id}/access-rules",
    summary="How one person sees assets and CIs",
    dependencies=[READ_ACCESS],
)
async def person_access(
    user_id: uuid.UUID, session: TenantSession, subject: SignedIn, policy: Policy
) -> PersonResourceAccessOut:
    """The person's own compiled narrowing: `roles.manage`, or the person themself."""
    if user_id != subject.user_id and not subject.holds(service.MANAGE):
        raise PermissionDenied(params={"permission": service.MANAGE, "reason": "no_permission"})
    found_user = await session.scalar(
        select(User.id).where(User.id == user_id, User.deleted_at.is_(None))
    )
    if found_user is None:
        raise NotFound(code="user_not_found", params={"id": str(user_id)})
    target = await policy.compile(session, subject.tenant_id, user_id)
    found = service.effective_of(target)
    return PersonResourceAccessOut(
        user_id=found.user_id,
        tenant_admin=found.tenant_admin,
        narrowed={
            resource: NarrowedOut(
                rules=[
                    {k: list(v) if isinstance(v, tuple) else v for k, v in c.items()}
                    for c in one.rules
                ],
                whole_scope_roles=one.whole_scope_roles,
            )
            for resource, one in found.narrowed.items()
        },
    )
