"""Admin settings and templates over HTTP (WP-020c). No logic here.

`/settings/...` edits values of the type's configuration (D-056): status labels and colours,
reason prompts per transition, scale labels and colours, the matrix, pick lists (reasons,
levels, closure codes) and the next display number. Each needs If-Match with the catalogue
`version` and returns the new catalogue. `/templates` lists, creates, changes and copies
templates (each with its own version). Every write is audited (WP-018); every change reaches
open screens live through `work_items.settings_changed`.

Registered before `/{record_id}` so these paths are never read as record IDs.
"""

import uuid
from typing import Annotated, Any, Protocol, Self

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import require_permission
from app.core.database import TenantSession
from app.core.errors import ProblemDetail
from app.modules.audit import AuditNote, audited
from app.modules.identity_access import PolicyService, Subject, get_policy
from app.modules.work_items.domain.approvals import LevelRule
from app.modules.work_items.domain.classification import Impact, Priority, Scale, Urgency
from app.modules.work_items.domain.lifecycle import ReasonMode, WorkItemAction
from app.modules.work_items.domain.templates import (
    CUSTOM_PREFIX,
    TEMPLATE_DESCRIPTION_MAX,
    TEMPLATE_GROUP_MAX,
    FieldRule,
    PickList,
    TemplateField,
    is_custom,
    rules_from_json,
)
from app.modules.work_items.domain.types import STANDARD_LIFECYCLE, WorkItemType
from app.modules.work_items.infra.models import WorkItemTemplate
from app.modules.work_items.service import configuration
from app.modules.work_items.service import templates as template_service
from app.modules.work_items.service.catalogue import Catalogue
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.history import source_of

CONFLICT: dict[int | str, dict[str, Any]] = {
    409: {"model": ProblemDetail, "description": "version_conflict: reload and try again."}
}


class StatusPatch(BaseModel):
    """A status's labels and colour (its category and code are fixed, D-056)."""

    model_config = ConfigDict(extra="forbid")

    labels: dict[str, str] | None = Field(default=None, description="{en, ar, ur}; null: shipped.")
    colour: str | None = Field(default=None, max_length=7, description="#rrggbb")
    resume_on_requester_reply: bool | None = Field(
        default=None,
        description="Paused statuses: a requester reply moves the record to in progress (051).",
    )


class TransitionPatch(BaseModel):
    """Whether running the transition asks for a reason (REQ-INC-047 AC3)."""

    model_config = ConfigDict(extra="forbid")

    reason_mode: ReasonMode


class ScaleValuePatch(BaseModel):
    """Labels and colour of an impact, urgency or priority value."""

    model_config = ConfigDict(extra="forbid")

    labels: dict[str, str] | None = None
    colour: str | None = Field(default=None, max_length=7)


class MatrixCellIn(BaseModel):
    """One cell."""

    impact: Impact
    urgency: Urgency
    priority: Priority


class MatrixIn(BaseModel):
    """Every cell of the matrix (4 x 4); one missing refuses the whole save."""

    model_config = ConfigDict(extra="forbid")

    cells: list[MatrixCellIn] = Field(max_length=16)


class ListValueIn(BaseModel):
    """A new value of a pick list."""

    model_config = ConfigDict(extra="forbid")

    labels: dict[str, str]
    colour: str | None = Field(default=None, max_length=7)


class ListValuePatch(BaseModel):
    """Rename / translate, colour, retire or bring back."""

    model_config = ConfigDict(extra="forbid")

    labels: dict[str, str] | None = None
    colour: str | None = Field(default=None, max_length=7)
    disabled: bool | None = None
    attributes: dict[str, Any] | None = Field(
        default=None,
        description="The value's own settings, replacing all of them (release types:"
        " default_template_id, default_risk).",
    )


class StageAccessRuleIO(BaseModel):
    """Who may: any of these groups, permissions or role holders (all empty: anyone)."""

    model_config = ConfigDict(extra="forbid")

    group_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    permissions: list[str] = Field(default_factory=list, max_length=50)
    roles: list[str] = Field(
        default_factory=list, max_length=20, description="Role codes: their holders on the record."
    )


class StageAccessIn(BaseModel):
    """A stage's access (REQ-REL-019): who may edit it, and who may move a record out of it."""

    model_config = ConfigDict(extra="forbid")

    edit: StageAccessRuleIO | None = None
    move_out: StageAccessRuleIO | None = None


class StageApproverIO(BaseModel):
    """One approver of a level: a person, a group (each member) or a record role (its holders)."""

    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    role: str | None = Field(default=None, max_length=40)


class ApprovalLevelIO(BaseModel):
    """One level: its approvers and how they decide it."""

    model_config = ConfigDict(extra="forbid")

    rule: LevelRule = LevelRule.ANY
    approvers: list[StageApproverIO] = Field(max_length=50)


class StageApprovalsIO(BaseModel):
    """A stage's approvals (REQ-REL-031): the status that raises them and the outcomes."""

    model_config = ConfigDict(extra="forbid")

    raised_by: str = Field(max_length=40)
    approved: str = Field(max_length=40)
    rejected: str = Field(max_length=40)
    self_approval: bool = Field(
        default=False, description="False: the requester may not approve (segregation)."
    )
    levels: list[ApprovalLevelIO] = Field(min_length=1, max_length=5)


class StageApprovalsIn(BaseModel):
    """Set the stage's approvals, or clear them (null)."""

    model_config = ConfigDict(extra="forbid")

    approvals: StageApprovalsIO | None


class StageSettingsOut(BaseModel):
    """One stage of a staged type, with its access and approvals."""

    code: str
    sort_order: int
    access: StageAccessIn | None
    approvals: StageApprovalsIO | None = None


class EligibilityIO(BaseModel):
    """Who may hold a role: any of these permissions, groups or people (all empty: anyone)."""

    model_config = ConfigDict(extra="forbid")

    permissions: list[str] = Field(default_factory=list, max_length=20)
    group_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)


class RoleDefOut(BaseModel):
    """One named role of the type (REQ-REL-023, -024)."""

    code: str
    labels: dict[str, str] | None = Field(description="Null: labelled by the UI from the code.")
    description: dict[str, str] | None
    single: bool
    eligibility: EligibilityIO | None
    system: bool
    disabled: bool


class RoleDefIn(BaseModel):
    """An admin's own role."""

    model_config = ConfigDict(extra="forbid")

    labels: dict[str, str]
    description: dict[str, str] | None = None
    single: bool = True
    eligibility: EligibilityIO | None = None


class RoleDefPatch(BaseModel):
    """What to change (only what is sent)."""

    model_config = ConfigDict(extra="forbid")

    labels: dict[str, str] | None = None
    description: dict[str, str] | None = None
    eligibility: EligibilityIO | None = None
    disabled: bool | None = None


class ListOrderIn(BaseModel):
    """Every code of the list, in the new order."""

    model_config = ConfigDict(extra="forbid")

    codes: list[str] = Field(max_length=100)


class NumberingIn(BaseModel):
    """The number the next record gets (never one already used)."""

    model_config = ConfigDict(extra="forbid")

    next_number: int = Field(ge=1, le=10**15)


class FieldRuleIO(BaseModel):
    """How a template treats one field."""

    model_config = ConfigDict(extra="forbid")

    shown: bool = True
    required: bool = False
    requester_can_see: bool = Field(default=True, description="For the portal (WP-028).")
    requester_can_fill: bool = Field(default=False, description="For the portal (WP-028).")

    @classmethod
    def of(cls, rule: FieldRule) -> "FieldRuleIO":
        """From the domain rule."""
        return cls(
            shown=rule.shown,
            required=rule.required,
            requester_can_see=rule.requester_can_see,
            requester_can_fill=rule.requester_can_fill,
        )


class StageFieldRuleIO(BaseModel):
    """One field's rule in one stage (unset flags keep their defaults)."""

    model_config = ConfigDict(extra="forbid")

    shown: bool = True
    required: bool = False
    read_only: bool = False


class TemplateOut(BaseModel):
    """A template as admins and the create form see it."""

    id: uuid.UUID
    code: str | None = Field(description="Seeded templates: labelled by the UI from this code.")
    labels: dict[str, str] | None
    description: str | None
    group_name: str | None
    is_default: bool
    for_requesters: bool
    disabled: bool
    copied_from_id: uuid.UUID | None = Field(description="Set on copies (REQ-INC-035 AC3).")
    fields: dict[TemplateField, FieldRuleIO]
    custom_fields: dict[str, FieldRuleIO] = Field(
        description="Custom field rules by key (WP-026); sent as `fields['custom.<key>']`."
    )
    defaults: dict[str, Any] = Field(description="Starting values by field.")
    lifecycle: str = Field(
        default=STANDARD_LIFECYCLE,
        description="The transition set new records from it follow (WP-044a; REQ-PRB-025).",
    )
    stage_path: str | None = Field(default=None, description="Staged types: the path it sets.")
    stage_rules: dict[str, dict[str, StageFieldRuleIO]] | None = Field(
        default=None, description="Staged types: rules per stage (only what differs)."
    )
    version: int

    @classmethod
    def of(cls, row: WorkItemTemplate) -> "TemplateOut":
        """From a row."""
        rules = rules_from_json(row.field_rules)
        return cls(
            id=row.id,
            code=row.code,
            labels=row.labels,
            description=row.description,
            group_name=row.group_name,
            is_default=row.is_default,
            for_requesters=row.for_requesters,
            disabled=row.disabled_at is not None,
            copied_from_id=row.copied_from_id,
            fields={
                TemplateField(name): FieldRuleIO.of(rule)
                for name, rule in rules.items()
                if not is_custom(name)
            },
            custom_fields={
                name.removeprefix(CUSTOM_PREFIX): FieldRuleIO.of(rule)
                for name, rule in rules.items()
                if is_custom(name)
            },
            defaults=dict(row.defaults),
            lifecycle=row.lifecycle or STANDARD_LIFECYCLE,
            stage_path=row.stage_path,
            stage_rules=row.stage_rules,
            version=row.version,
        )


class TemplateIn(BaseModel):
    """A new template."""

    model_config = ConfigDict(extra="forbid")

    labels: dict[str, str]
    description: str | None = Field(default=None, max_length=TEMPLATE_DESCRIPTION_MAX * 2)
    group_name: str | None = Field(default=None, max_length=TEMPLATE_GROUP_MAX * 2)
    for_requesters: bool = False
    fields: dict[str, FieldRuleIO] | None = None
    defaults: dict[str, Any] | None = None
    lifecycle: str | None = Field(
        default=None, max_length=40, description="One of the type's transition sets."
    )
    stage_path: str | None = Field(
        default=None, max_length=40, description="Staged types: the path its records take."
    )
    stage_rules: dict[str, dict[str, StageFieldRuleIO]] | None = Field(
        default=None,
        description="Staged types, per stage and field (standard, the type's own, custom.<key>):"
        " shown, required to leave the stage, read-only while in it. Replaces all of them.",
    )


class TemplatePatch(BaseModel):
    """What to change (only what is sent); `fields` may name only some fields."""

    model_config = ConfigDict(extra="forbid")

    labels: dict[str, str] | None = None
    description: str | None = Field(default=None, max_length=TEMPLATE_DESCRIPTION_MAX * 2)
    group_name: str | None = Field(default=None, max_length=TEMPLATE_GROUP_MAX * 2)
    for_requesters: bool | None = None
    fields: dict[str, FieldRuleIO] | None = None
    defaults: dict[str, Any] | None = Field(default=None, description="Replaces all of them.")
    is_default: bool | None = None
    disabled: bool | None = None
    lifecycle: str | None = Field(
        default=None, max_length=40, description="For new records; running ones keep theirs."
    )
    stage_path: str | None = Field(
        default=None, max_length=40, description="Staged types: the path its records take."
    )
    stage_rules: dict[str, dict[str, StageFieldRuleIO]] | None = Field(
        default=None,
        description="Staged types, per stage and field (standard, the type's own, custom.<key>):"
        " shown, required to leave the stage, read-only while in it. Replaces all of them.",
    )


class TemplateCopyIn(BaseModel):
    """The copy's name."""

    model_config = ConfigDict(extra="forbid")

    labels: dict[str, str]


class CatalogueModel(Protocol):
    """The catalogue response model (defined with the record routes)."""

    @classmethod
    async def of(cls, session: AsyncSession, cat: Catalogue) -> Self:
        """From a loaded catalogue (and the tenant's requester channels)."""
        ...


def add_settings_routes(  # noqa: C901, PLR0915 - one route per operation
    router: APIRouter, wtype: WorkItemType, catalogue_model: type[CatalogueModel]
) -> None:
    """The admin routes of one type; they answer with `catalogue_model`."""
    audit = wtype.code.value  # audit codes: "incident.settings_changed" ...
    View = Annotated[Subject, Depends(require_permission(wtype.permission("view")))]  # noqa: N806 - type alias
    Admin = Annotated[  # noqa: N806 - type alias
        Subject, Depends(require_permission("config.service_desk", "settings.manage"))
    ]
    Settings = Annotated[  # noqa: N806 - type alias
        AuditNote, audited(f"{audit}.settings_changed", object_type=f"{audit}_settings")
    ]
    response_model: Any = catalogue_model

    async def done(session: AsyncSession, cat: Catalogue, response: Response) -> Any:  # noqa: ANN401 - the response model
        set_etag(response, cat.settings_version)
        return await catalogue_model.of(session, cat)

    @router.patch(
        "/settings/statuses/{code}",
        summary="Change a status's labels or colour",
        responses=CONFLICT,
        response_model=response_model,
    )
    async def patch_status(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        code: str,
        body: StatusPatch,
        session: TenantSession,
        subject: Admin,
        version: ExpectedVersion,
        response: Response,
        request: Request,
        note: Settings,
    ) -> Any:  # noqa: ANN401 - the catalogue model
        note.details = {"status": code, "changed_fields": sorted(body.model_fields_set)}
        cat = await configuration.update_status(
            session,
            wtype,
            code,
            expected_version=version,
            values=body.model_dump(include=body.model_fields_set),
            source=source_of(request),
            user_id=subject.user_id,
        )
        return await done(session, cat, response)

    @router.patch(
        "/settings/transitions/{from_status}/{action}",
        summary="Change a transition's reason prompt",
        responses=CONFLICT,
        response_model=response_model,
    )
    async def patch_transition(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        from_status: str,
        action: WorkItemAction,
        body: TransitionPatch,
        session: TenantSession,
        subject: Admin,
        version: ExpectedVersion,
        response: Response,
        request: Request,
        note: Settings,
    ) -> Any:  # noqa: ANN401 - the catalogue model
        note.details = {"transition": f"{from_status}.{action}", "reason_mode": body.reason_mode}
        cat = await configuration.update_transition(
            session,
            wtype,
            from_status,
            action,
            expected_version=version,
            reason_mode=body.reason_mode,
            source=source_of(request),
            user_id=subject.user_id,
        )
        return await done(session, cat, response)

    @router.patch(
        "/settings/scales/{scale}/{code}",
        summary="Change an impact, urgency or priority value's labels or colour",
        responses=CONFLICT,
        response_model=response_model,
    )
    async def patch_scale_value(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        scale: Scale,
        code: str,
        body: ScaleValuePatch,
        session: TenantSession,
        subject: Admin,
        version: ExpectedVersion,
        response: Response,
        request: Request,
        note: Settings,
    ) -> Any:  # noqa: ANN401 - the catalogue model
        note.details = {
            "scale": scale,
            "value": code,
            "changed_fields": sorted(body.model_fields_set),
        }
        cat = await configuration.update_scale_value(
            session,
            wtype,
            scale,
            code,
            expected_version=version,
            values=body.model_dump(include=body.model_fields_set),
            source=source_of(request),
            user_id=subject.user_id,
        )
        return await done(session, cat, response)

    if wtype.roles:  # REQ-REL-023, -024: the type's named roles

        def known(policy: PolicyService) -> Any:  # noqa: ANN401 - a key check
            return lambda key: policy.catalogue.get(key) is not None

        @router.get("/settings/roles", summary="Roles and who may hold them")
        async def get_role_defs(session: TenantSession, subject: Admin) -> list[RoleDefOut]:
            """Every role in order, retired ones included (marked)."""
            del subject
            return [
                RoleDefOut(
                    code=r.code,
                    labels=r.labels,
                    description=r.description,
                    single=r.single,
                    eligibility=EligibilityIO.model_validate(r.eligibility)
                    if r.eligibility
                    else None,
                    system=r.system,
                    disabled=r.disabled_at is not None,
                )
                for r in await configuration.role_def_rows(session, wtype)
            ]

        @router.post(
            "/settings/roles",
            summary="Add a role",
            status_code=status.HTTP_201_CREATED,
            responses=CONFLICT,
            response_model=response_model,
        )
        async def add_role_def(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
            body: RoleDefIn,
            session: TenantSession,
            subject: Admin,
            version: ExpectedVersion,
            response: Response,
            request: Request,
            note: Settings,
            policy: Annotated[PolicyService, Depends(get_policy)],
        ) -> Any:  # noqa: ANN401 - the catalogue model
            """A role of the admin's own: named, for one holder or several (REQ-CHG-035)."""
            cat, code = await configuration.add_role_def(
                session,
                wtype,
                expected_version=version,
                values=body.model_dump(mode="json", exclude_none=True),
                known_permission=known(policy),
                source=source_of(request),
                user_id=subject.user_id,
            )
            note.details = {"role": code, "change": "added"}
            response.headers["Location"] = f"{request.url.path}/{code}"
            return await done(session, cat, response)

        @router.patch(
            "/settings/roles/{code}",
            summary="Change a role",
            responses=CONFLICT,
            response_model=response_model,
        )
        async def patch_role_def(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
            code: str,
            body: RoleDefPatch,
            session: TenantSession,
            subject: Admin,
            version: ExpectedVersion,
            response: Response,
            request: Request,
            note: Settings,
            policy: Annotated[PolicyService, Depends(get_policy)],
        ) -> Any:  # noqa: ANN401 - the catalogue model
            """Rename, describe, set who may hold it, retire or bring it back (never deleted)."""
            note.details = {"role": code, "changed_fields": sorted(body.model_fields_set)}
            cat = await configuration.update_role_def(
                session,
                wtype,
                code,
                expected_version=version,
                values=body.model_dump(mode="json", include=body.model_fields_set),
                known_permission=known(policy),
                source=source_of(request),
                user_id=subject.user_id,
            )
            return await done(session, cat, response)

    if wtype.stages is not None:  # ADR-041: a staged type's stages and their access

        @router.get("/settings/stages", summary="Stages and who may work in them")
        async def get_stages(session: TenantSession, subject: Admin) -> list[StageSettingsOut]:
            """Every stage of the type in order, with its edit and move-out access."""
            del subject
            rows = await configuration.stage_rows(session, wtype)
            return [
                StageSettingsOut(
                    code=r.code,
                    sort_order=r.sort_order,
                    access=StageAccessIn.model_validate(r.access) if r.access else None,
                    approvals=StageApprovalsIO.model_validate(r.approvals) if r.approvals else None,
                )
                for r in rows
            ]

        @router.put(
            "/settings/stages/{stage}/access",
            summary="Set who may edit a stage and move a record out of it",
            responses=CONFLICT,
            response_model=response_model,
        )
        async def put_stage_access(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
            stage: str,
            body: StageAccessIn,
            session: TenantSession,
            subject: Admin,
            version: ExpectedVersion,
            response: Response,
            request: Request,
            note: Settings,
            policy: Annotated[PolicyService, Depends(get_policy)],
        ) -> Any:  # noqa: ANN401 - the catalogue model
            """Groups and permissions are checked, so a typo never locks a stage.

            Empty: anyone who may edit the record.
            """
            note.details = {"changed_fields": [f"stages.{stage}"]}
            cat = await configuration.update_stage_access(
                session,
                wtype,
                stage,
                expected_version=version,
                access=body.model_dump(mode="json", exclude_none=True),
                known_permission=lambda key: policy.catalogue.get(key) is not None,
                source=source_of(request),
                user_id=subject.user_id,
            )
            return await done(session, cat, response)

    if wtype.stages is not None:

        @router.put(
            "/settings/stages/{stage}/approvals",
            summary="Set a stage's approvals",
            responses=CONFLICT,
            response_model=response_model,
        )
        async def put_stage_approvals(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
            stage: str,
            body: StageApprovalsIn,
            session: TenantSession,
            subject: Admin,
            version: ExpectedVersion,
            response: Response,
            request: Request,
            note: Settings,
        ) -> Any:  # noqa: ANN401 - the catalogue model
            """Statuses, roles, people and groups are checked; null clears the approvals."""
            note.details = {"changed_fields": [f"stages.{stage}.approvals"]}
            raw = body.approvals.model_dump(mode="json") if body.approvals else None
            if raw is not None:  # one key per approver, as stored
                for level in raw["levels"]:
                    level["approvers"] = [
                        {k: v for k, v in a.items() if v is not None} for a in level["approvers"]
                    ]
            cat = await configuration.update_stage_approvals(
                session,
                wtype,
                stage,
                expected_version=version,
                approvals=raw,
                source=source_of(request),
                user_id=subject.user_id,
            )
            return await done(session, cat, response)

    @router.put(
        "/settings/matrix",
        summary="Replace the priority matrix",
        responses=CONFLICT,
        response_model=response_model,
    )
    async def put_matrix(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        body: MatrixIn,
        session: TenantSession,
        subject: Admin,
        version: ExpectedVersion,
        response: Response,
        request: Request,
        note: Settings,
    ) -> Any:  # noqa: ANN401 - the catalogue model
        note.details = {"changed_fields": ["matrix"]}
        cat = await configuration.replace_matrix(
            session,
            wtype,
            expected_version=version,
            cells=[c.model_dump(mode="json") for c in body.cells],
            source=source_of(request),
            user_id=subject.user_id,
        )
        return await done(session, cat, response)

    @router.post(
        "/settings/lists/{list_name}/values",
        summary="Add a value to a pick list",
        status_code=status.HTTP_201_CREATED,
        responses=CONFLICT,
        response_model=response_model,
    )
    async def add_list_value(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        list_name: PickList,
        body: ListValueIn,
        session: TenantSession,
        subject: Admin,
        version: ExpectedVersion,
        response: Response,
        request: Request,
        note: Settings,
    ) -> Any:  # noqa: ANN401 - the catalogue model
        cat, code = await configuration.add_list_value(
            session,
            wtype,
            list_name,
            expected_version=version,
            labels=body.labels,
            colour=body.colour,
            source=source_of(request),
            user_id=subject.user_id,
        )
        note.details = {"list": list_name, "value": code, "change": "added"}
        response.headers["Location"] = f"{request.url.path}/{code}"
        return await done(session, cat, response)

    @router.patch(
        "/settings/lists/{list_name}/values/{code}",
        summary="Rename, colour, retire or bring back a pick list value",
        responses=CONFLICT,
        response_model=response_model,
    )
    async def patch_list_value(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        list_name: PickList,
        code: str,
        body: ListValuePatch,
        session: TenantSession,
        subject: Admin,
        version: ExpectedVersion,
        response: Response,
        request: Request,
        note: Settings,
    ) -> Any:  # noqa: ANN401 - the catalogue model
        note.details = {
            "list": list_name,
            "value": code,
            "changed_fields": sorted(body.model_fields_set),
        }
        cat = await configuration.update_list_value(
            session,
            wtype,
            list_name,
            code,
            expected_version=version,
            values=body.model_dump(include=body.model_fields_set),
            source=source_of(request),
            user_id=subject.user_id,
        )
        return await done(session, cat, response)

    @router.put(
        "/settings/lists/{list_name}/order",
        summary="Reorder a pick list",
        responses=CONFLICT,
        response_model=response_model,
    )
    async def put_list_order(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        list_name: PickList,
        body: ListOrderIn,
        session: TenantSession,
        subject: Admin,
        version: ExpectedVersion,
        response: Response,
        request: Request,
        note: Settings,
    ) -> Any:  # noqa: ANN401 - the catalogue model
        note.details = {"list": list_name, "change": "reordered"}
        cat = await configuration.reorder_list(
            session,
            wtype,
            list_name,
            expected_version=version,
            codes=body.codes,
            source=source_of(request),
            user_id=subject.user_id,
        )
        return await done(session, cat, response)

    @router.put(
        "/settings/numbering",
        summary="Set the next display number",
        responses=CONFLICT,
        response_model=response_model,
    )
    async def put_numbering(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        body: NumberingIn,
        session: TenantSession,
        subject: Admin,
        version: ExpectedVersion,
        response: Response,
        request: Request,
        note: Settings,
    ) -> Any:  # noqa: ANN401 - the catalogue model
        note.details = {"changed_fields": ["next_number"], "next_number": body.next_number}
        cat = await configuration.change_next_number(
            session,
            wtype,
            expected_version=version,
            next_number=body.next_number,
            source=source_of(request),
            user_id=subject.user_id,
        )
        return await done(session, cat, response)

    # --- templates --------------------------------------------------------------------------------

    @router.get("/templates", summary="Templates")
    async def list_templates(session: TenantSession, subject: View) -> list[TemplateOut]:
        """Every template, the default first; disabled ones are marked, not hidden."""
        del subject
        return [TemplateOut.of(t) for t in await template_service.list_templates(session, wtype)]

    @router.post("/templates", summary="Add a template", status_code=status.HTTP_201_CREATED)
    async def create_template(
        body: TemplateIn,
        session: TenantSession,
        subject: Admin,
        request: Request,
        note: Annotated[
            AuditNote, audited(f"{audit}.template_created", object_type=f"{audit}_template")
        ],
    ) -> TemplateOut:
        """A new template (never the default until made so)."""
        del subject
        row = await template_service.create_template(
            session,
            wtype,
            # exclude_unset: a field rule changes only the flags sent (the rest keep theirs).
            body.model_dump(exclude_unset=True, exclude_none=True, mode="json"),
            source=source_of(request),
        )
        note.object_id = str(row.id)
        return TemplateOut.of(row)

    @router.post(
        "/templates/{template_id}/copy",
        summary="Copy a template",
        status_code=status.HTTP_201_CREATED,
    )
    async def copy_template(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        template_id: uuid.UUID,
        body: TemplateCopyIn,
        session: TenantSession,
        subject: Admin,
        request: Request,
        note: Annotated[
            AuditNote, audited(f"{audit}.template_created", object_type=f"{audit}_template")
        ],
    ) -> TemplateOut:
        """An independent copy, marked as a copy of the original (REQ-INC-035 AC3)."""
        del subject
        row = await template_service.copy_template(
            session, wtype, template_id, labels=body.labels, source=source_of(request)
        )
        note.object_id = str(row.id)
        note.details = {"copied_from_id": str(template_id)}
        return TemplateOut.of(row)

    @router.patch("/templates/{template_id}", summary="Change a template", responses=CONFLICT)
    async def patch_template(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
        template_id: uuid.UUID,
        body: TemplatePatch,
        session: TenantSession,
        subject: Admin,
        version: ExpectedVersion,
        response: Response,
        request: Request,
        note: Annotated[
            AuditNote,
            audited(
                f"{audit}.template_changed",
                object_type=f"{audit}_template",
                object_param="template_id",
            ),
        ],
    ) -> TemplateOut:
        """Name, rules, starting values, requester flags, default, enabled."""
        del subject
        note.details = {"changed_fields": sorted(body.model_fields_set)}
        row = await template_service.update_template(
            session,
            wtype,
            template_id,
            expected_version=version,
            values=body.model_dump(exclude_unset=True, mode="json"),
            source=source_of(request),
        )
        set_etag(response, row.version)
        return TemplateOut.of(row)
