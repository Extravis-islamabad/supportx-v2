"""Field access per role over HTTP (ADR-047; REQ-WI-016, REQ-ADM-026; service/field_access.py).

`/field-access`: reading needs `roles.view`; setting, changing and removing a rule need
`roles.manage` too. Creates take an Idempotency-Key, changes and removals If-Match. Adding or
changing a rule needs the `field_access` feature; viewing and removing never do. Every change is
audited as `role.field_access_changed` with the mode before and after. No logic here.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.audit import AuditNote, audited
from app.modules.identity_access.domain.field_access import FieldMode
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.infra.models import RoleFieldAccess
from app.modules.identity_access.service import field_access as service
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit

router = APIRouter(
    prefix="/field-access",
    tags=["roles"],
    dependencies=[Depends(rate_limit("roles"))],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "Missing permission or feature."},
        404: {"model": ProblemDetail, "description": "role_not_found, field_access_rule_not_found"},
    },
)

View = Annotated[Subject, Depends(require_permission(service.VIEW))]
Manage = Annotated[Subject, Depends(require_permission(service.MANAGE))]
WRITE: dict[int | str, dict[str, Any]] = {
    409: {"model": ProblemDetail, "description": "version_conflict, field_access_rule_exists"},
    422: {
        "model": ProblemDetail,
        "description": "field_not_ruleable, invalid_choice, field_access_limit_reached",
    },
    428: {"model": ProblemDetail, "description": "If-Match missing."},
}
RuleMode = Annotated[
    FieldMode,
    Field(description="read_only, masked or hidden (no rule: the field is clear for the role)."),
]


class RuleableFieldOut(BaseModel):
    """A field an admin may restrict."""

    key: str = Field(description='"root_cause", "custom.salary_band" ...')
    label_key: str | None = Field(description="Built-in fields: the label to show.")
    labels: dict[str, str] = Field(description="Custom fields: the admin's own names by language.")
    custom: bool
    personal_data: bool
    sensitive: bool


class CatalogueOut(BaseModel):
    """One record type's rule-able fields. Core fields (subject, status ...) are never offered."""

    record_type: str
    fields: list[RuleableFieldOut]


class FieldRuleOut(BaseModel):
    """One role's rule for one field."""

    id: uuid.UUID
    role_id: uuid.UUID
    record_type: str
    field: str
    mode: FieldMode
    updated_at: datetime
    updated_by: uuid.UUID | None
    version: int = Field(description="Send it back as If-Match to change or remove the rule.")

    @classmethod
    def of(cls, row: RoleFieldAccess) -> "FieldRuleOut":
        """From the stored rule."""
        return cls(
            id=row.id,
            role_id=row.role_id,
            record_type=row.record_type,
            field=row.field,
            mode=FieldMode(row.mode),
            updated_at=row.updated_at,
            updated_by=row.updated_by,
            version=row.version,
        )


class FieldRuleIn(BaseModel):
    """A new rule."""

    model_config = ConfigDict(extra="forbid")

    role_id: uuid.UUID
    record_type: str = Field(min_length=1, max_length=40)
    field: str = Field(min_length=1, max_length=80)
    mode: RuleMode


class FieldRulePatch(BaseModel):
    """Another mode for a rule."""

    model_config = ConfigDict(extra="forbid")

    mode: RuleMode


class FieldAccessPersonOut(BaseModel):
    """Someone in the effective view."""

    id: uuid.UUID
    name: str


class EffectiveOut(BaseModel):
    """Who sees one field how (ADR-047 §2: the clearest mode of a person's roles wins)."""

    record_type: str
    field: str
    counts: dict[FieldMode, int] = Field(description="People in each mode (all of them).")
    people: dict[FieldMode, list[FieldAccessPersonOut]] = Field(
        description=f"The first {service.PEOPLE_SHOWN} people in each mode, by name."
    )


Audited = Annotated[
    AuditNote, audited("role.field_access_changed", object_type="role")  # object: the rule's role
]


def _note(note: AuditNote, change: service.RuleChange) -> None:
    """The audit entry: which rule, and its mode before and after."""
    note.object_id = str(change.rule.role_id)
    note.details = {
        "rule_id": str(change.rule.id),
        "change": change.action,
        "record_type": change.rule.record_type,
        "field": change.rule.field,
        "old_mode": change.old_mode,
        "new_mode": change.new_mode,
    }


@router.get("/catalogue", summary="Fields that may be restricted, per record type")
async def list_catalogue(session: TenantSession, subject: View) -> list[CatalogueOut]:
    """Every record type with rule-able fields (`roles.view`)."""
    del subject
    return [
        CatalogueOut(
            record_type=record_type,
            fields=[
                RuleableFieldOut(
                    key=f.key,
                    label_key=f.label_key,
                    labels=f.labels,
                    custom=f.custom,
                    personal_data=f.personal_data,
                    sensitive=f.sensitive,
                )
                for f in await service.catalogue(session, record_type)
            ],
        )
        for record_type in service.record_types()
    ]


@router.get("/rules", summary="Field access rules")
async def list_rules(
    session: TenantSession,
    subject: View,
    role_id: Annotated[uuid.UUID | None, Query()] = None,
    record_type: Annotated[str | None, Query(max_length=40)] = None,
) -> list[FieldRuleOut]:
    """The live rules, by role, type and field; narrowed to a role or a type when given."""
    rows = await service.list_rules(session, subject, role_id=role_id, record_type=record_type)
    return [FieldRuleOut.of(r) for r in rows]


@router.post(
    "/rules",
    summary="Restrict a field for a role",
    status_code=status.HTTP_201_CREATED,
    response_model=FieldRuleOut,
    responses={**WRITE, 201: {"model": FieldRuleOut, "description": "Created (or replayed)."}},
)
async def add_rule(
    body: FieldRuleIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    note: Audited,
) -> Response:
    """A new rule (Idempotency-Key); needs the `field_access` feature."""
    note.skip = True  # a replay changes nothing

    async def run() -> Created:
        change = await service.set_rule(
            session,
            subject,
            role_id=body.role_id,
            record_type=body.record_type,
            field_key=body.field,
            mode=body.mode,
        )
        note.skip = False
        _note(note, change)
        return Created(
            body=FieldRuleOut.of(change.rule), headers={"ETag": f'"{change.rule.version}"'}
        )

    return await idempotency.run(body, run, status_code=status.HTTP_201_CREATED)


@router.patch("/rules/{rule_id}", summary="Change a field access rule", responses=WRITE)
async def change_rule(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    rule_id: uuid.UUID,
    body: FieldRulePatch,
    session: TenantSession,
    subject: Manage,
    version: ExpectedVersion,
    response: Response,
    note: Audited,
) -> FieldRuleOut:
    """Another mode (If-Match); needs the `field_access` feature."""
    change = await service.change_rule(
        session, subject, rule_id, mode=body.mode, expected_version=version
    )
    _note(note, change)
    note.skip = change.old_mode == change.new_mode
    set_etag(response, change.rule.version)
    return FieldRuleOut.of(change.rule)


@router.delete(
    "/rules/{rule_id}",
    summary="Remove a field access rule",
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
    """Removed (If-Match), whatever the licence says (ADR-047 §13)."""
    change = await service.remove_rule(session, subject, rule_id, expected_version=version)
    _note(note, change)


@router.get("/effective", summary="Who sees a field how")
async def effective_access(
    session: TenantSession,
    subject: View,
    record_type: Annotated[str, Query(min_length=1, max_length=40)],
    field: Annotated[str, Query(min_length=1, max_length=80)],
) -> EffectiveOut:
    """Per mode, how many people and the first of them by name (`roles.view`)."""
    found = await service.effective_access(
        session, subject, record_type=record_type, field_key=field
    )
    return EffectiveOut(
        record_type=found.record_type,
        field=found.field,
        counts={FieldMode(m): n for m, n in found.counts.items()},
        people={
            FieldMode(m): [FieldAccessPersonOut(id=p.id, name=p.name) for p in people]
            for m, people in found.people.items()
        },
    )
