"""Automation over HTTP (WP-029; ADR-035). No logic here.

Business rules and routing rules per record type (`?record_type=incident`), routing settings,
auto-assignment per support group, technician availability, and a record's automation log.
Changes send If-Match, creates take an Idempotency-Key, every change is audited.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission, require_signed_in
from app.core.database import TenantSession
from app.core.errors import PermissionDenied, ProblemDetail
from app.modules.audit import AuditNote, audited
from app.modules.automation.domain.assignment import AssignMethod, Availability
from app.modules.automation.domain.rules import ActionMode, FieldKind, RuleEvent, RuleState
from app.modules.automation.domain.triggers import Relative, TriggerEvent
from app.modules.automation.infra.models import (
    AssignmentSettings,
    AutomationTrigger,
    BusinessRule,
    RoutingRule,
    RoutingSettings,
    TransitionSetting,
)
from app.modules.automation.service import (
    assignment,
    business_rules,
    routing,
    transitions,
    triggers,
)
from app.modules.identity_access import Subject
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.api.idempotency import Created, Idempotency
from app.shared.api.ratelimit import rate_limit

RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemDetail, "description": "Not signed in."},
    403: {"model": ProblemDetail, "description": "Missing permission."},
    404: {"model": ProblemDetail, "description": "No such rule, group or record."},
    409: {"model": ProblemDetail, "description": "Stale If-Match, or the order is out of date."},
    422: {"model": ProblemDetail, "description": "Problems by field (checked when saved)."},
}
RATE = [Depends(rate_limit("automation"))]
View = Annotated[Subject, Depends(require_permission("automation.view"))]
Manage = Annotated[Subject, Depends(require_permission("automation.manage"))]
RecordType = Annotated[str, Query(min_length=1, max_length=30, description="e.g. incident")]

router = APIRouter(
    prefix="/automation", tags=["automation"], dependencies=RATE, responses=RESPONSES
)


# --- fields a rule can use ---------------------------------------------------------------------


class RuleFieldOut(BaseModel):
    """One field rules may test (and maybe set): the editor builds itself from these."""

    name: str = Field(description="e.g. priority, group_id, custom.floor, requester.vip")
    kind: FieldKind
    values: list[str] | None = Field(description="Allowed codes (code fields); null: any.")
    settable: bool
    derived: bool = Field(description="A fact about a related record (the requester's VIP).")


@router.get("/fields", summary="Fields rules may use for a record type")
async def list_fields(
    session: TenantSession, subject: View, record_type: RecordType
) -> list[RuleFieldOut]:
    """Standard and custom fields, with their operators' kind and allowed codes."""
    del subject
    fields = await business_rules.rule_fields(session, record_type)
    return [
        RuleFieldOut(
            name=name,
            kind=spec.kind,
            values=sorted(spec.values) if spec.values is not None else None,
            settable=spec.settable,
            derived=spec.derived,
        )
        for name, spec in sorted(fields.items())
    ]


# --- business rules ----------------------------------------------------------------------------


class RuleActionIO(BaseModel):
    """`set` a field (fill empty or overwrite), or `refuse` the save with a message."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["set", "refuse"]
    field: str | None = Field(default=None, max_length=80)
    value: Any = None
    mode: ActionMode = ActionMode.FILL_EMPTY
    message: dict[str, str] | None = Field(
        default=None, description="Refusal message per language (en required)."
    )


class RuleOut(BaseModel):
    """A business rule; `state` draft rules never run (REQ-RUL-029)."""

    id: uuid.UUID
    record_type: str
    name: str
    description: str | None
    events: list[RuleEvent]
    site_id: uuid.UUID | None
    conditions: dict[str, Any] | None = Field(description="Filter grammar plus change operators.")
    actions: list[RuleActionIO]
    stop_after: bool = Field(description="When it matches, later rules do not run.")
    position: int
    state: RuleState
    owner_id: uuid.UUID | None
    updated_at: datetime
    version: int


class RuleIn(BaseModel):
    """A new business rule (saved as a draft unless `state` says otherwise)."""

    model_config = ConfigDict(extra="forbid")

    record_type: str = Field(max_length=30)
    name: str = Field(max_length=400)
    description: str | None = Field(default=None, max_length=4000)
    events: list[RuleEvent] = Field(min_length=1)
    site_id: uuid.UUID | None = None
    conditions: dict[str, Any] | None = None
    actions: list[RuleActionIO] = Field(max_length=40)
    stop_after: bool = False
    state: RuleState = RuleState.DRAFT


class RulePatch(BaseModel):
    """What to change (only what is sent)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=400)
    description: str | None = Field(default=None, max_length=4000)
    events: list[RuleEvent] | None = None
    site_id: uuid.UUID | None = None
    conditions: dict[str, Any] | None = None
    actions: list[RuleActionIO] | None = Field(default=None, max_length=40)
    stop_after: bool | None = None
    state: RuleState | None = None


class OrderIn(BaseModel):
    """Every rule of the type, in the new order."""

    model_config = ConfigDict(extra="forbid")

    record_type: str = Field(max_length=30)
    ids: list[uuid.UUID] = Field(max_length=200)


def _rule_out(rule: BusinessRule) -> RuleOut:
    return RuleOut.model_validate(rule, from_attributes=True)


def _dump(body: BaseModel) -> dict[str, Any]:
    data = body.model_dump(mode="json", include=body.model_fields_set)
    if "actions" in data:
        data["actions"] = [
            {k: v for k, v in action.items() if v is not None or k == "value"}
            for action in data["actions"]
        ]
    for name in ("site_id",):
        if data.get(name) is not None:
            data[name] = uuid.UUID(str(data[name]))
    return data


@router.get("/rules", summary="Business rules of a record type, in order")
async def list_rules(
    session: TenantSession, subject: View, record_type: RecordType
) -> list[RuleOut]:
    """Drafts and disabled rules included (marked)."""
    del subject
    return [_rule_out(r) for r in await business_rules.list_rules(session, record_type)]


@router.post(
    "/rules",
    summary="Add a business rule",
    status_code=status.HTTP_201_CREATED,
    response_model=RuleOut,
    responses={201: {"model": RuleOut, "description": "Created (or replayed)."}},
)
async def create_rule(
    body: RuleIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("automation.rule_created", object_type="business_rule")],
) -> Response:
    """Checked against the record type when saved; last in the order."""
    del subject
    note.skip = True

    async def operation() -> Created:
        rule = await business_rules.create_rule(
            session, _dump(body) | {"record_type": body.record_type}
        )
        note.skip = False
        note.object_id = str(rule.id)
        return Created(_rule_out(rule), {"ETag": f'"{rule.version}"'})

    return await idempotency.run(body, operation)


@router.patch(
    "/rules/{rule_id}",
    summary="Change a business rule",
    dependencies=[
        audited("automation.rule_changed", object_type="business_rule", object_param="rule_id")
    ],
)
async def update_rule(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    rule_id: uuid.UUID,
    body: RulePatch,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
) -> RuleOut:
    """Checked again as a whole; switching a draft on is a change like any other."""
    del subject
    rule = await business_rules.update_rule(session, rule_id, _dump(body), expected_version=version)
    set_etag(response, rule.version)
    return _rule_out(rule)


@router.delete(
    "/rules/{rule_id}",
    summary="Remove a business rule",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        audited("automation.rule_deleted", object_type="business_rule", object_param="rule_id")
    ],
)
async def delete_rule(
    rule_id: uuid.UUID, version: ExpectedVersion, session: TenantSession, subject: Manage
) -> Response:
    """Records' history keeps naming it."""
    del subject
    await business_rules.delete_rule(session, rule_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/rules-order",
    summary="Order the business rules of a record type",
    dependencies=[audited("automation.rules_reordered", object_type="business_rule")],
)
async def order_rules(body: OrderIn, session: TenantSession, subject: Manage) -> list[RuleOut]:
    """409 `order_out_of_date` if the list does not name every rule exactly once."""
    del subject
    rules = await business_rules.reorder_rules(session, body.record_type, body.ids)
    return [_rule_out(r) for r in rules]


# --- routing ------------------------------------------------------------------------------------


class RoutingOut(BaseModel):
    """A routing rule: conditions → a group (REQ-ASG-001)."""

    id: uuid.UUID
    record_type: str
    name: str
    conditions: dict[str, Any] | None
    site_id: uuid.UUID | None
    group_id: uuid.UUID
    overwrite: bool = Field(description="Also replaces a group a person chose.")
    position: int
    state: RuleState
    version: int


class RoutingIn(BaseModel):
    """A new routing rule."""

    model_config = ConfigDict(extra="forbid")

    record_type: str = Field(max_length=30)
    name: str = Field(max_length=400)
    conditions: dict[str, Any] | None = None
    site_id: uuid.UUID | None = None
    group_id: uuid.UUID
    overwrite: bool = False
    state: RuleState = RuleState.DRAFT


class RoutingPatch(BaseModel):
    """What to change."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=400)
    conditions: dict[str, Any] | None = None
    site_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    overwrite: bool | None = None
    state: RuleState | None = None


class RoutingSettingsOut(BaseModel):
    """The fallback group (none until an admin picks one, D-097) and the category switch."""

    record_type: str
    fallback_group_id: uuid.UUID | None
    use_category_group: bool
    version: int


class RoutingSettingsIn(BaseModel):
    """Change the routing settings."""

    model_config = ConfigDict(extra="forbid")

    fallback_group_id: uuid.UUID | None = None
    use_category_group: bool | None = None


def _routing_out(rule: RoutingRule) -> RoutingOut:
    return RoutingOut.model_validate(rule, from_attributes=True)


def _routing_values(body: BaseModel) -> dict[str, Any]:
    return body.model_dump(include=body.model_fields_set)


@router.get("/routing", summary="Routing rules of a record type, in order")
async def list_routing(
    session: TenantSession, subject: View, record_type: RecordType
) -> list[RoutingOut]:
    """Drafts and disabled ones included."""
    del subject
    return [_routing_out(r) for r in await routing.list_routing(session, record_type)]


@router.post(
    "/routing",
    summary="Add a routing rule",
    status_code=status.HTTP_201_CREATED,
    response_model=RoutingOut,
    responses={201: {"model": RoutingOut, "description": "Created (or replayed)."}},
)
async def create_routing(
    body: RoutingIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("automation.routing_created", object_type="routing_rule")],
) -> Response:
    """Last in the order."""
    del subject
    note.skip = True

    async def operation() -> Created:
        rule = await routing.create_routing(
            session, _routing_values(body) | {"record_type": body.record_type}
        )
        note.skip = False
        note.object_id = str(rule.id)
        return Created(_routing_out(rule), {"ETag": f'"{rule.version}"'})

    return await idempotency.run(body, operation)


@router.patch(
    "/routing/{rule_id}",
    summary="Change a routing rule",
    dependencies=[
        audited("automation.routing_changed", object_type="routing_rule", object_param="rule_id")
    ],
)
async def update_routing(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    rule_id: uuid.UUID,
    body: RoutingPatch,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
) -> RoutingOut:
    """Checked again as a whole."""
    del subject
    rule = await routing.update_routing(
        session, rule_id, _routing_values(body), expected_version=version
    )
    set_etag(response, rule.version)
    return _routing_out(rule)


@router.delete(
    "/routing/{rule_id}",
    summary="Remove a routing rule",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        audited("automation.routing_deleted", object_type="routing_rule", object_param="rule_id")
    ],
)
async def delete_routing(
    rule_id: uuid.UUID, version: ExpectedVersion, session: TenantSession, subject: Manage
) -> Response:
    """Records' history keeps naming it."""
    del subject
    await routing.delete_routing(session, rule_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/routing-order",
    summary="Order the routing rules of a record type",
    dependencies=[audited("automation.routing_reordered", object_type="routing_rule")],
)
async def order_routing(body: OrderIn, session: TenantSession, subject: Manage) -> list[RoutingOut]:
    """409 `order_out_of_date` if the list does not name every rule exactly once."""
    del subject
    rules = await routing.reorder_routing(session, body.record_type, body.ids)
    return [_routing_out(r) for r in rules]


def _settings_out(settings: RoutingSettings) -> RoutingSettingsOut:
    return RoutingSettingsOut.model_validate(settings, from_attributes=True)


@router.get("/routing-settings", summary="Routing settings of a record type")
async def get_routing_settings(
    response: Response, session: TenantSession, subject: View, record_type: RecordType
) -> RoutingSettingsOut:
    """Created with the defaults on first read."""
    del subject
    settings = await routing.routing_settings(session, record_type)
    set_etag(response, settings.version)
    return _settings_out(settings)


@router.put(
    "/routing-settings",
    summary="Change the routing settings of a record type",
    dependencies=[audited("automation.routing_settings_changed", object_type="routing_settings")],
)
async def put_routing_settings(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    body: RoutingSettingsIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
    record_type: RecordType,
) -> RoutingSettingsOut:
    """The fallback group must be an active group."""
    del subject
    settings = await routing.save_routing_settings(
        session, record_type, _routing_values(body), expected_version=version
    )
    set_etag(response, settings.version)
    return _settings_out(settings)


# --- auto-assignment and availability ----------------------------------------------------------


class AssignmentSettingsOut(BaseModel):
    """A group's auto-assignment (off by default, D-097). Version 0: never set up."""

    group_id: uuid.UUID
    enabled: bool
    method: AssignMethod
    record_types: list[str] = Field(description="Empty: every record type.")
    on_create: bool
    on_move: bool = Field(description="Also when a record is moved to the group.")
    unassigned_only: bool
    count_paused: bool = Field(description="Paused records count as load.")
    load_cap: int | None = Field(description="Most open records per technician; none: no cap.")
    version: int


class AssignmentSettingsIn(BaseModel):
    """Switch auto-assignment on or off and set it up."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    method: AssignMethod | None = None
    record_types: list[str] | None = Field(default=None, max_length=10)
    on_create: bool | None = None
    on_move: bool | None = None
    unassigned_only: bool | None = None
    count_paused: bool | None = None
    load_cap: int | None = None


def _assignment_out(group_id: uuid.UUID, row: AssignmentSettings | None) -> AssignmentSettingsOut:
    if row is None:
        return AssignmentSettingsOut(
            group_id=group_id,
            enabled=False,
            method=AssignMethod.ROUND_ROBIN,
            record_types=[],
            on_create=True,
            on_move=True,
            unassigned_only=True,
            count_paused=False,
            load_cap=None,
            version=0,
        )
    return AssignmentSettingsOut.model_validate(row, from_attributes=True)


@router.get("/groups/{group_id}/assignment", summary="A group's auto-assignment")
async def get_assignment(
    group_id: uuid.UUID, response: Response, session: TenantSession, subject: View
) -> AssignmentSettingsOut:
    """The defaults (off, round robin) until set up."""
    del subject
    out = _assignment_out(group_id, await assignment.group_settings(session, group_id))
    set_etag(response, out.version)
    return out


@router.put(
    "/groups/{group_id}/assignment",
    summary="Set up a group's auto-assignment",
    dependencies=[
        audited(
            "automation.assignment_changed", object_type="support_group", object_param="group_id"
        )
    ],
)
async def put_assignment(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    group_id: uuid.UUID,
    body: AssignmentSettingsIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
) -> AssignmentSettingsOut:
    """If-Match "0" for the first set-up."""
    del subject
    values = {
        k: (v.value if hasattr(v, "value") else v)
        for k, v in body.model_dump(include=body.model_fields_set).items()
    }
    row = await assignment.save_group_settings(session, group_id, values, expected_version=version)
    set_etag(response, row.version)
    return _assignment_out(group_id, row)


class AvailabilityOut(BaseModel):
    """A technician's own state (REQ-ASG-006): Away is never auto-assigned."""

    user_id: uuid.UUID
    state: Availability


class AvailabilityIn(BaseModel):
    """Set Available or Away."""

    model_config = ConfigDict(extra="forbid")

    state: Availability


SignedIn = Annotated[Subject, Depends(require_signed_in())]


@router.get("/availability", summary="Availability of technicians")
async def get_availability(
    session: TenantSession,
    subject: SignedIn,
    user_ids: Annotated[list[uuid.UUID], Query(max_length=200)],
) -> list[AvailabilityOut]:
    """Anyone signed in may see who is available (the assign picker shows it)."""
    del subject
    found = await assignment.availability(session, user_ids)
    return [AvailabilityOut(user_id=u, state=s) for u, s in found.items()]


@router.put(
    "/availability/{user_id}",
    summary="Set a technician Available or Away",
    dependencies=[
        audited("automation.availability_changed", object_type="user", object_param="user_id")
    ],
)
async def put_availability(
    user_id: uuid.UUID, body: AvailabilityIn, session: TenantSession, subject: SignedIn
) -> AvailabilityOut:
    """Yourself always; someone else only with `users.manage`."""
    if user_id != subject.user_id and not subject.holds("users.manage"):
        raise PermissionDenied(params={"permission": "users.manage"})
    state = await assignment.set_availability(session, user_id, body.state)
    return AvailabilityOut(user_id=user_id, state=state)


# --- the run log --------------------------------------------------------------------------------


class RunOut(BaseModel):
    """One automation step on one record (names, codes and loads, never record values)."""

    id: uuid.UUID
    kind: str
    automation_id: uuid.UUID | None
    automation_name: str | None
    outcome: str
    detail: dict[str, Any]
    occurred_at: datetime


@router.get("/runs", summary="Automation log of one record")
async def list_runs(
    session: TenantSession,
    subject: View,
    record_id: Annotated[uuid.UUID, Query()],
) -> list[RunOut]:
    """The latest 200 steps, newest first (kept 30 days)."""
    del subject
    rows = await business_rules.record_runs(session, record_id)
    return [RunOut.model_validate(r, from_attributes=True) for r in rows]


# --- triggers (WP-029 part 2) ------------------------------------------------------------------


class TriggerActionIO(BaseModel):
    """`set` a field (fill empty or overwrite) or add a private `note` (REQ-RUL-010)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["set", "note"]
    field: str | None = Field(default=None, max_length=80)
    value: Any = None
    mode: ActionMode = ActionMode.FILL_EMPTY
    text: str | None = Field(default=None, max_length=10000, description="The note (note only).")


class TriggerOut(BaseModel):
    """A trigger: runs after a change is committed, from its event (REQ-RUL-009)."""

    id: uuid.UUID
    record_type: str
    name: str
    description: str | None
    events: list[TriggerEvent]
    site_id: uuid.UUID | None
    conditions: dict[str, Any] | None
    actions: list[TriggerActionIO]
    fire_on_own_change: bool = Field(
        description="Also runs on the change its own action made (loop guard still applies)."
    )
    position: int
    state: RuleState
    owner_id: uuid.UUID | None
    updated_at: datetime
    version: int


class TriggerIn(BaseModel):
    """A new trigger (a draft unless `state` says otherwise)."""

    model_config = ConfigDict(extra="forbid")

    record_type: str = Field(max_length=30)
    name: str = Field(max_length=400)
    description: str | None = Field(default=None, max_length=4000)
    events: list[TriggerEvent] = Field(min_length=1)
    site_id: uuid.UUID | None = None
    conditions: dict[str, Any] | None = None
    actions: list[TriggerActionIO] = Field(max_length=40)
    fire_on_own_change: bool = False
    state: RuleState = RuleState.DRAFT


class TriggerPatch(BaseModel):
    """What to change (only what is sent)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=400)
    description: str | None = Field(default=None, max_length=4000)
    events: list[TriggerEvent] | None = None
    site_id: uuid.UUID | None = None
    conditions: dict[str, Any] | None = None
    actions: list[TriggerActionIO] | None = Field(default=None, max_length=40)
    fire_on_own_change: bool | None = None
    state: RuleState | None = None


def _trigger_out(trigger: AutomationTrigger) -> TriggerOut:
    return TriggerOut.model_validate(trigger, from_attributes=True)


@router.get("/triggers", summary="Triggers of a record type, in order")
async def list_triggers(
    session: TenantSession, subject: View, record_type: RecordType
) -> list[TriggerOut]:
    """Drafts and disabled triggers included (marked)."""
    del subject
    return [_trigger_out(t) for t in await triggers.list_triggers(session, record_type)]


@router.post(
    "/triggers",
    summary="Add a trigger",
    status_code=status.HTTP_201_CREATED,
    response_model=TriggerOut,
    responses={201: {"model": TriggerOut, "description": "Created (or replayed)."}},
)
async def create_trigger(
    body: TriggerIn,
    session: TenantSession,
    subject: Manage,
    idempotency: Idempotency,
    note: Annotated[AuditNote, audited("automation.trigger_created", object_type="trigger")],
) -> Response:
    """Checked against the record type when saved; last in the order."""
    del subject
    note.skip = True

    async def operation() -> Created:
        trigger = await triggers.create_trigger(
            session, _dump(body) | {"record_type": body.record_type}
        )
        note.skip = False
        note.object_id = str(trigger.id)
        return Created(_trigger_out(trigger), {"ETag": f'"{trigger.version}"'})

    return await idempotency.run(body, operation)


@router.patch(
    "/triggers/{trigger_id}",
    summary="Change a trigger",
    dependencies=[
        audited("automation.trigger_changed", object_type="trigger", object_param="trigger_id")
    ],
)
async def update_trigger(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    trigger_id: uuid.UUID,
    body: TriggerPatch,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
) -> TriggerOut:
    """Checked again as a whole."""
    del subject
    trigger = await triggers.update_trigger(
        session, trigger_id, _dump(body), expected_version=version
    )
    set_etag(response, trigger.version)
    return _trigger_out(trigger)


@router.delete(
    "/triggers/{trigger_id}",
    summary="Remove a trigger",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        audited("automation.trigger_deleted", object_type="trigger", object_param="trigger_id")
    ],
)
async def delete_trigger(
    trigger_id: uuid.UUID, version: ExpectedVersion, session: TenantSession, subject: Manage
) -> Response:
    """Records' history and the log keep naming it."""
    del subject
    await triggers.delete_trigger(session, trigger_id, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/triggers-order",
    summary="Order the triggers of a record type",
    dependencies=[audited("automation.triggers_reordered", object_type="trigger")],
)
async def order_triggers(
    body: OrderIn, session: TenantSession, subject: Manage
) -> list[TriggerOut]:
    """409 `order_out_of_date` if the list does not name every trigger exactly once."""
    del subject
    return [
        _trigger_out(t)
        for t in await triggers.reorder_triggers(session, body.record_type, body.ids)
    ]


class LoopStopOut(BaseModel):
    """A loop the guard stopped (REQ-RUL-028), for the admins' banner and log."""

    id: uuid.UUID
    record_type: str
    record_id: uuid.UUID
    cap: str = Field(description="chain_depth or per_minute")
    triggers: list[str]
    occurred_at: datetime


@router.get("/loop-stops", summary="Loops the guard stopped in the last 24 hours")
async def list_loop_stops(session: TenantSession, subject: View) -> list[LoopStopOut]:
    """Newest first, at most 50: the admins' banner until notifications arrive (WP-023)."""
    del subject
    return [
        LoopStopOut(
            id=row.id,
            record_type=row.record_type,
            record_id=row.record_id,
            cap=row.outcome,
            triggers=list((row.detail or {}).get("triggers", [])),
            occurred_at=row.occurred_at,
        )
        for row in await triggers.recent_loop_stops(session)
    ]


# --- transition settings (WP-029 part 2) --------------------------------------------------------


class TransitionSettingsOut(BaseModel):
    """Who may run a life-cycle action, when it is offered, its confirmation and "after"."""

    record_type: str
    action: str
    roles: list[str]
    group_ids: list[uuid.UUID]
    relatives: list[Relative]
    conditions: dict[str, Any] | None
    confirmation: dict[str, str] | None
    after_actions: list[TriggerActionIO]
    version: int = Field(description="0: no settings yet (permission only).")


class TransitionSettingsIn(BaseModel):
    """The whole settings of one action (empty lists: anyone with the permission)."""

    model_config = ConfigDict(extra="forbid")

    roles: list[str] = Field(default_factory=list, max_length=100)
    group_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    relatives: list[Relative] = Field(default_factory=list, max_length=10)
    conditions: dict[str, Any] | None = None
    confirmation: dict[str, str] | None = None
    after_actions: list[TriggerActionIO] = Field(default_factory=list, max_length=40)


def _transition_out(row: TransitionSetting) -> TransitionSettingsOut:
    return TransitionSettingsOut.model_validate(row, from_attributes=True)


@router.get("/transitions", summary="Transition settings of a record type")
async def list_transitions(
    session: TenantSession, subject: View, record_type: RecordType
) -> list[TransitionSettingsOut]:
    """Only actions that have settings; the others run on their permission alone."""
    del subject
    return [_transition_out(r) for r in await transitions.list_settings(session, record_type)]


@router.put(
    "/transitions/{action}",
    summary="Save one action's transition settings",
    dependencies=[
        audited("automation.transition_saved", object_type="transition", object_param="action")
    ],
)
async def save_transition(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    action: Annotated[str, Path(max_length=40)],
    body: TransitionSettingsIn,
    version: ExpectedVersion,
    response: Response,
    session: TenantSession,
    subject: Manage,
    record_type: RecordType,
) -> TransitionSettingsOut:
    """If-Match "0" the first time. 404 `transition_not_found` for an unknown action."""
    del subject
    data = body.model_dump(mode="json")
    data["after_actions"] = [
        {k: v for k, v in a.items() if v is not None or k == "value"} for a in data["after_actions"]
    ]
    row = await transitions.save_setting(
        session, record_type, action, data, expected_version=version
    )
    set_etag(response, row.version)
    return _transition_out(row)


@router.delete(
    "/transitions/{action}",
    summary="Back to permission only for one action",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        audited("automation.transition_reset", object_type="transition", object_param="action")
    ],
)
async def reset_transition(
    action: str,
    version: ExpectedVersion,
    session: TenantSession,
    subject: Manage,
    record_type: RecordType,
) -> Response:
    """Removes the settings; the action is again offered to everyone permitted."""
    del subject
    await transitions.reset_setting(session, record_type, action, expected_version=version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
