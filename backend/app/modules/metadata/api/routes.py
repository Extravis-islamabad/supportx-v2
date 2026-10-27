"""Custom fields over HTTP (WP-026): `/api/v1/custom-fields`. No logic here.

Reading needs the entity's view permission (forms show the fields); every write needs
`settings.manage`, sends If-Match (except create) and is audited (WP-018).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import require_permission, require_signed_in
from app.core.database import TenantSession
from app.core.errors import PermissionDenied, ProblemDetail
from app.modules.audit import AuditNote, audited
from app.modules.identity_access import Subject
from app.modules.metadata.domain.fields import (
    VIEW_PERMISSION,
    ChoiceDisplay,
    CustomFieldEntity,
    FieldType,
    IndexFailure,
    IndexState,
)
from app.modules.metadata.infra.models import CustomField
from app.modules.metadata.service import custom_fields as service
from app.shared.api.concurrency import ExpectedVersion, set_etag
from app.shared.history import source_of

router = APIRouter(
    prefix="/custom-fields",
    tags=["custom-fields"],
    responses={
        401: {"model": ProblemDetail, "description": "Not signed in."},
        403: {"model": ProblemDetail, "description": "Missing permission or licence feature."},
    },
)
CONFLICT: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ProblemDetail,
        "description": "version_conflict, or custom_field_in_use (retire it instead).",
    }
}
Admin = Annotated[Subject, Depends(require_permission("settings.manage"))]
SignedIn = Annotated[Subject, Depends(require_signed_in())]
IncludeRemoved = Annotated[
    bool, Query(description="Also fields removed while in use (to show old values).")
]
Confirm = Annotated[
    bool, Query(description="Remove even though records hold values (they keep them).")
]


class CustomFieldChoiceIO(BaseModel):
    """One choice. Send `code` for an existing one; a new one gets a code from its name."""

    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, max_length=40)
    labels: dict[str, str] = Field(description='{"en": ..., "ar": ..., "ur": ...}; en required.')
    retired: bool = False


class CustomFieldValidationIO(BaseModel):
    """Rules beyond the type. Numbers are decimal text (exact)."""

    model_config = ConfigDict(extra="forbid")

    required: bool = False
    min: str | None = Field(default=None, max_length=30)
    max: str | None = Field(default=None, max_length=30)
    min_length: int | None = Field(default=None, ge=0, le=10_000)
    max_length: int | None = Field(default=None, ge=1, le=10_000)
    pattern: str | None = Field(default=None, max_length=200)


class CustomFieldOut(BaseModel):
    """A custom field. `key` is for the API only: screens show `labels`."""

    id: uuid.UUID
    entity: CustomFieldEntity
    key: str = Field(description="Stable; the name values use in `custom`. Never shown as text.")
    field_type: FieldType
    labels: dict[str, str]
    help: dict[str, str] | None
    choices: list[CustomFieldChoiceIO]
    display: ChoiceDisplay
    default: Any = None
    validation: CustomFieldValidationIO
    currency: str | None
    sort_order: int
    retired: bool
    removed: bool = Field(description="Removed while in use: only for old values and history.")
    in_use: bool = Field(description="A record holds a value: it can be retired, not deleted.")
    index_state: IndexState
    index_error: IndexFailure | None = Field(description="Why the index failed (state failed).")
    changed_by: str | None = Field(
        default=None, description='Who saved it last (an open editor says "changed by").'
    )
    changed_at: datetime | None = None
    version: int

    @classmethod
    def of(cls, row: CustomField, changed_by: str | None = None) -> "CustomFieldOut":
        """From a row, with the name of who saved it last."""
        rules = row.validation or {}
        return cls(
            id=row.id,
            entity=CustomFieldEntity(row.entity),
            key=row.key,
            field_type=FieldType(row.field_type),
            labels=row.labels,
            help=row.help,
            choices=[CustomFieldChoiceIO.model_validate(c) for c in row.choices],
            display=ChoiceDisplay(row.display),
            default=row.default_value,
            validation=CustomFieldValidationIO(
                required=bool(rules.get("required", False)),
                min=rules.get("min"),
                max=rules.get("max"),
                min_length=rules.get("min_length"),
                max_length=rules.get("max_length"),
                pattern=rules.get("pattern"),
            ),
            currency=row.currency,
            sort_order=row.sort_order,
            retired=row.retired_at is not None,
            removed=row.deleted_at is not None,
            in_use=row.first_used_at is not None,
            index_state=IndexState(row.index_state),
            index_error=None if row.index_error is None else IndexFailure(row.index_error),
            changed_by=changed_by,
            changed_at=row.updated_at,
            version=row.version,
        )


class CustomFieldIn(BaseModel):
    """A new field."""

    model_config = ConfigDict(extra="forbid")

    entity: CustomFieldEntity
    field_type: FieldType
    labels: dict[str, str] = Field(description="Name per language; en required.")
    help: dict[str, str] | None = None
    choices: list[CustomFieldChoiceIO] = Field(default_factory=list, max_length=100)
    display: ChoiceDisplay = ChoiceDisplay.LIST
    default: Any = None
    validation: CustomFieldValidationIO = Field(default_factory=CustomFieldValidationIO)
    currency: str | None = Field(default=None, max_length=3, description="ISO 4217, currency type.")


class CustomFieldPatch(BaseModel):
    """What to change (only what is sent). The type and key cannot change."""

    model_config = ConfigDict(extra="forbid")

    labels: dict[str, str] | None = None
    help: dict[str, str] | None = None
    choices: list[CustomFieldChoiceIO] | None = Field(default=None, max_length=100)
    display: ChoiceDisplay | None = None
    default: Any = None
    validation: CustomFieldValidationIO | None = None
    currency: str | None = Field(default=None, max_length=3)
    retired: bool | None = None


class CustomFieldOrderIn(BaseModel):
    """Every field of the entity, in the new order."""

    model_config = ConfigDict(extra="forbid")

    entity: CustomFieldEntity
    ids: list[uuid.UUID] = Field(max_length=100)


def _may_read(subject: Subject, entity: CustomFieldEntity) -> None:
    permission = VIEW_PERMISSION[entity]
    if not subject.holds(permission) and not subject.holds("settings.manage"):
        raise PermissionDenied(params={"permission": permission, "reason": "no_permission"})


@router.get("", summary="Custom fields of an entity")
async def list_fields(
    session: TenantSession,
    subject: SignedIn,
    entity: Annotated[CustomFieldEntity, Query()],
    include_removed: IncludeRemoved = False,  # noqa: FBT002 - a query parameter
) -> list[CustomFieldOut]:
    """Every field in display order; retired ones are marked, not hidden (old values)."""
    _may_read(subject, entity)
    rows = await service.list_fields(session, entity, removed=include_removed)
    names = await service.editors(session, rows)
    return [CustomFieldOut.of(r, names.get(r.id)) for r in rows]


@router.post("", summary="Add a custom field", status_code=status.HTTP_201_CREATED)
async def create_field(
    body: CustomFieldIn,
    session: TenantSession,
    subject: Admin,
    request: Request,
    note: Annotated[
        AuditNote, audited("metadata.custom_field_created", object_type="custom_field")
    ],
) -> CustomFieldOut:
    """A new field at the end of the entity's list. Its key comes from the English name."""
    del subject
    row = await service.create_field(
        session, body.entity, body.model_dump(mode="json"), source=source_of(request)
    )
    note.object_id = str(row.id)
    note.details = {"entity": row.entity, "key": row.key, "field_type": row.field_type}
    return CustomFieldOut.of(row)


@router.put("/order", summary="Reorder custom fields")
async def put_order(
    body: CustomFieldOrderIn,
    session: TenantSession,
    subject: Admin,
    request: Request,
    note: Annotated[
        AuditNote, audited("metadata.custom_field_changed", object_type="custom_field")
    ],
) -> list[CustomFieldOut]:
    """Forms, records and filters follow the new order at once."""
    del subject
    note.details = {"entity": body.entity, "change": "reordered"}
    rows = await service.reorder(session, body.entity, body.ids, source=source_of(request))
    return [CustomFieldOut.of(r) for r in rows]


@router.patch("/{field_id}", summary="Change a custom field", responses=CONFLICT)
async def patch_field(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    field_id: uuid.UUID,
    body: CustomFieldPatch,
    session: TenantSession,
    subject: Admin,
    version: ExpectedVersion,
    response: Response,
    request: Request,
    note: Annotated[
        AuditNote,
        audited(
            "metadata.custom_field_changed", object_type="custom_field", object_param="field_id"
        ),
    ],
) -> CustomFieldOut:
    """Names, help, choices, default, validation; retire or bring back."""
    del subject
    note.details = {"changed_fields": sorted(body.model_fields_set)}
    row = await service.update_field(
        session,
        field_id,
        expected_version=version,
        values=body.model_dump(exclude_unset=True, mode="json"),
        source=source_of(request),
    )
    set_etag(response, row.version)
    return CustomFieldOut.of(row)


@router.delete(
    "/{field_id}",
    summary="Remove a custom field",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CONFLICT,
    dependencies=[
        audited(
            "metadata.custom_field_deleted", object_type="custom_field", object_param="field_id"
        )
    ],
)
async def delete_field(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    field_id: uuid.UUID,
    session: TenantSession,
    subject: Admin,
    version: ExpectedVersion,
    request: Request,
    confirm: Confirm = False,  # noqa: FBT002 - a query parameter
) -> Response:
    """A field records hold values in needs `confirm=true`, else 409 `custom_field_in_use`."""
    del subject
    await service.delete_field(
        session, field_id, expected_version=version, confirmed=confirm, source=source_of(request)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{field_id}/index", summary="Ask for an index on a custom field", responses=CONFLICT)
async def request_index(  # noqa: PLR0913, PLR0917 - FastAPI dependencies
    field_id: uuid.UUID,
    session: TenantSession,
    subject: Admin,
    version: ExpectedVersion,
    response: Response,
    request: Request,
    note: Annotated[
        AuditNote,
        audited(
            "metadata.custom_field_changed", object_type="custom_field", object_param="field_id"
        ),
    ],
) -> CustomFieldOut:
    """The index worker builds it (D-088); `index_state` says how far it got, live."""
    del subject
    note.details = {"change": "index_requested"}
    row = await service.request_index(
        session, field_id, expected_version=version, source=source_of(request)
    )
    set_etag(response, row.version)
    return CustomFieldOut.of(row)
