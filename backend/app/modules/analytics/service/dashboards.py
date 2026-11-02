"""Dashboards (WP-036; REQ-DSH-002, 003, 005, 019, 021, 026, 028, 029).

Who sees what:
- built-in dashboards: everyone holding `reports.view` (read-only, copyable);
- a user-made dashboard: its owner, and everyone holding `reports.view` once it is shared;
- each viewer's widgets show the data they may see (they run through the report engine).
Creating needs `dashboards.create`, sharing `dashboards.share`, setting a role's home
`dashboards.manage_defaults`. The owner edits and deletes; `dashboards.manage_defaults` also
edits shared ones. Every write is versioned (If-Match), recorded in field history and emitted
through the outbox in the same transaction.

Home (REQ-DSH-002): the person's own choice (while they can still see it), else their role's
default (an admin's choice, else the built-in role home), else "my work".
"""

import json
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, NotFound, PermissionDenied, ValidationFailed
from app.modules.analytics.domain.builtin import BUILTIN as BUILTIN_REPORTS
from app.modules.analytics.domain.builtin import BUILTIN_PREFIX as REPORT_BUILTIN_PREFIX
from app.modules.analytics.domain.dashboard import (
    BUILTIN_PREFIX,
    MY_GROUPS,
    DashboardBody,
    builtin_ref,
    with_viewer,
)
from app.modules.analytics.domain.definition import ReportDefinition
from app.modules.analytics.domain.widgets import BUILTIN_DASHBOARDS, FALLBACK_HOME, ROLE_HOMES
from app.modules.analytics.events import DashboardDeleted, DashboardHomeChanged, DashboardSaved
from app.modules.analytics.infra.models import Dashboard, DashboardPreference, DashboardRoleDefault
from app.modules.analytics.service.library import VIEW, get_report
from app.modules.identity_access import Subject, role_names
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes

CREATE = "dashboards.create"
SHARE = "dashboards.share"
MANAGE_DEFAULTS = "dashboards.manage_defaults"
RECORD_TYPE = "dashboard"
MAX_FAVOURITES = 200

# Checks a widget's definition against its entity as the saver sees it (422 on any problem).
Validator = Callable[[ReportDefinition], Awaitable[None]]


class DashboardRepository(Repository[Dashboard]):
    """User-made dashboards of the session's tenant."""

    model = Dashboard


@dataclass(frozen=True)
class DashboardView:
    """A dashboard as one viewer sees it: built-in (code) or user-made (row)."""

    ref: str
    builtin: str | None
    record: Dashboard | None
    body: DashboardBody
    can_edit: bool

    @property
    def shared(self) -> bool:
        """Built-in dashboards are everyone's; a user-made one once shared."""
        return self.record is None or self.record.shared


def _require(subject: Subject, permission: str) -> None:
    if not subject.holds(permission):
        raise PermissionDenied(params={"permission": permission})


def _visible(subject: Subject) -> Any:  # noqa: ANN401 - SQLAlchemy condition
    return or_(Dashboard.shared.is_(True), Dashboard.owner_id == subject.user_id)


def _can_edit(subject: Subject, record: Dashboard) -> bool:
    if record.owner_id == subject.user_id and subject.holds(CREATE):
        return True
    return record.shared and subject.holds(MANAGE_DEFAULTS)


def _row_view(subject: Subject, record: Dashboard) -> DashboardView:
    return DashboardView(
        ref=str(record.id),
        builtin=None,
        record=record,
        body=DashboardBody.model_validate(record.body),
        can_edit=_can_edit(subject, record),
    )


def _builtin_view(code: str) -> DashboardView:
    return DashboardView(
        ref=builtin_ref(code),
        builtin=code,
        record=None,
        body=BUILTIN_DASHBOARDS[code],
        can_edit=False,
    )


async def list_dashboards(session: AsyncSession, subject: Subject) -> list[DashboardView]:
    """Built-in dashboards, then shared ones and the subject's own (REQ-DSH-005)."""
    _require(subject, VIEW)
    rows = (
        await session.scalars(
            select(Dashboard)
            .where(Dashboard.deleted_at.is_(None), _visible(subject))
            .order_by(Dashboard.name, Dashboard.id)
        )
    ).all()
    return [_builtin_view(code) for code in BUILTIN_DASHBOARDS] + [
        _row_view(subject, r) for r in rows
    ]


async def get_dashboard(session: AsyncSession, subject: Subject, ref: str) -> DashboardView:
    """One dashboard by reference; 404 when unknown or someone else's private one."""
    _require(subject, VIEW)
    if ref.startswith(BUILTIN_PREFIX):
        code = ref.removeprefix(BUILTIN_PREFIX)
        if code not in BUILTIN_DASHBOARDS:
            raise NotFound(code="dashboard_not_found")
        return _builtin_view(code)
    try:
        dashboard_id = uuid.UUID(ref)
    except ValueError:
        raise NotFound(code="dashboard_not_found") from None
    record = await session.scalar(
        select(Dashboard).where(
            Dashboard.id == dashboard_id, Dashboard.deleted_at.is_(None), _visible(subject)
        )
    )
    if record is None:
        raise NotFound(code="dashboard_not_found")
    return _row_view(subject, record)


def for_viewer(definition: ReportDefinition, subject: Subject) -> ReportDefinition:
    """`definition` with `@me` and `@my_groups` as `subject` (D-114: always on the server)."""
    raw = definition.model_dump(mode="json", by_alias=True)
    return ReportDefinition.model_validate(with_viewer(raw, subject.user_id, subject.group_ids))


async def _check_body(
    session: AsyncSession, subject: Subject, body: DashboardBody, validate: Validator
) -> None:
    """Every widget's report must work for the saver (`@me` as the saver, REQ-DSH-009)."""
    for index, widget in enumerate(body.widgets):
        path = f"body.body.widgets.{index}"
        if widget.report is not None:
            await validate(for_viewer(widget.report, subject))
            continue
        if widget.records is not None:
            # The list's own filter fields and scope: checked as a report over the same filter.
            if MY_GROUPS in json.dumps(widget.records.filter_json()):
                raise ValidationFailed(
                    errors=[
                        FieldError(
                            field=f"{path}.records.filter",
                            code="my_groups_in_records",
                            message_key="errors.field.my_groups_in_records",
                        )
                    ]
                )
            records = ReportDefinition.model_validate(
                {"entity": widget.records.entity, "filter": widget.records.filter_json()}
            )
            await validate(for_viewer(records, subject))
            continue
        ref = widget.report_ref or ""
        if ref.startswith(REPORT_BUILTIN_PREFIX):
            if ref.removeprefix(REPORT_BUILTIN_PREFIX) in BUILTIN_REPORTS:
                continue
        else:
            try:
                await get_report(session, subject, uuid.UUID(ref))
                continue
            except (ValueError, NotFound):
                pass
        raise ValidationFailed(
            errors=[
                FieldError(
                    field=f"{path}.report_ref",
                    code="report_not_found",
                    message_key="errors.field.report_not_found",
                )
            ]
        )


def _snapshot(record: Dashboard) -> dict[str, Any]:
    return {
        "name": record.name,
        "names": record.names,
        "description": record.description,
        "shared": record.shared,
        "body": record.body,
    }


async def create_dashboard(  # noqa: PLR0913 - the new dashboard's parts, explicit
    session: AsyncSession,
    subject: Subject,
    *,
    name: str,
    names: Mapping[str, str],
    description: str | None,
    shared: bool,
    body: DashboardBody,
    copied_from: str | None,
    validate: Validator,
    source: Source,
) -> DashboardView:
    """A new private dashboard, or a shared one for `dashboards.share` (REQ-DSH-019, 026)."""
    _require(subject, CREATE)
    if shared:
        _require(subject, SHARE)
    if copied_from is not None:
        await get_dashboard(session, subject, copied_from)  # 404 for a dashboard not visible
    await _check_body(session, subject, body, validate)
    record = Dashboard(
        name=name.strip(),
        names={k: v.strip() for k, v in names.items() if v.strip()},
        description=(description or "").strip() or None,
        owner_id=subject.user_id,
        shared=shared,
        body=body.model_dump(mode="json", by_alias=True),
        copied_from=copied_from,
    )
    await DashboardRepository(session).add(record)
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=record.version,
        kind="created",
        changes=[Change(k, None, v) for k, v in _snapshot(record).items()],
        source=source,
    )
    await record_event(
        session,
        DashboardSaved(
            dashboard_id=record.id,
            owner_id=record.owner_id,
            shared=record.shared,
            was_shared=False,
            created=True,
            changed_fields=[],
        ),
        aggregate_id=record.id,
        aggregate_version=record.version,
    )
    return _row_view(subject, record)


async def _editable(session: AsyncSession, subject: Subject, ref: str) -> Dashboard:
    found = await get_dashboard(session, subject, ref)
    if found.record is None or not found.can_edit:
        raise PermissionDenied(code="dashboard_not_editable")
    return found.record


async def update_dashboard(  # noqa: PLR0913 - the change, explicit
    session: AsyncSession,
    subject: Subject,
    ref: str,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    validate: Validator,
    source: Source,
) -> DashboardView:
    """Rename, describe, share or un-share, or change widgets and layout (fields given only)."""
    record = await _editable(session, subject, ref)
    before = _snapshot(record)
    columns: dict[str, Any] = {}
    if "name" in values:
        columns["name"] = values["name"].strip()
    if "names" in values:
        columns["names"] = {k: v.strip() for k, v in values["names"].items() if v.strip()}
    if "description" in values:
        columns["description"] = (values["description"] or "").strip() or None
    if "shared" in values and values["shared"] != record.shared:
        _require(subject, SHARE)
        columns["shared"] = values["shared"]
    if "body" in values:
        body: DashboardBody = values["body"]
        await _check_body(session, subject, body, validate)
        columns["body"] = body.model_dump(mode="json", by_alias=True)
    columns = {k: v for k, v in columns.items() if getattr(record, k) != v}
    if not columns:
        if record.version != expected_version:
            raise Conflict(
                code="version_conflict",
                params={"expected_version": expected_version, "current_version": record.version},
            )
        return _row_view(subject, record)
    was_shared = record.shared
    updated = await DashboardRepository(session).update(
        record.id, expected_version=expected_version, changes=columns
    )
    after = _snapshot(updated)
    changes = [Change(k, before[k], v) for k, v in after.items() if before[k] != v]
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=updated.id,
        version=updated.version,
        kind="updated",
        changes=changes,
        source=source,
    )
    await record_event(
        session,
        DashboardSaved(
            dashboard_id=updated.id,
            owner_id=updated.owner_id,
            shared=updated.shared,
            was_shared=was_shared,
            created=False,
            changed_fields=[c.field for c in changes],
        ),
        aggregate_id=updated.id,
        aggregate_version=updated.version,
    )
    return _row_view(subject, updated)


async def delete_dashboard(
    session: AsyncSession,
    subject: Subject,
    ref: str,
    *,
    expected_version: int,
    source: Source,
) -> None:
    """Delete a dashboard (soft); homes and favourites pointing at it fall back by themselves."""
    record = await _editable(session, subject, ref)
    deleted = await DashboardRepository(session).soft_delete(
        record.id, expected_version=expected_version
    )
    await session.execute(
        delete(DashboardRoleDefault).where(DashboardRoleDefault.dashboard_ref == str(record.id))
    )
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=record.id,
        version=deleted.version,
        kind="deleted",
        changes=[],
        source=source,
    )
    await record_event(
        session,
        DashboardDeleted(dashboard_id=record.id, owner_id=record.owner_id, shared=record.shared),
        aggregate_id=record.id,
        aggregate_version=deleted.version,
    )


# --- home and favourites (one row per person) --------------------------------------------------


async def _preference(session: AsyncSession, subject: Subject) -> DashboardPreference | None:
    return await session.scalar(
        select(DashboardPreference).where(DashboardPreference.user_id == subject.user_id)
    )


async def _role_home(session: AsyncSession, subject: Subject) -> str | None:
    """The home an admin set for one of the subject's roles (first by role key), if any."""
    rows = (
        await session.scalars(
            select(DashboardRoleDefault)
            .where(DashboardRoleDefault.role_key.in_(sorted(subject.role_keys)))
            .order_by(DashboardRoleDefault.role_key)
        )
    ).all()
    return rows[0].dashboard_ref if rows else None


def _builtin_role_home(subject: Subject) -> str:
    for key in ("tenant_admin", *sorted(subject.role_keys)):
        if key in subject.role_keys and key in ROLE_HOMES:
            return builtin_ref(ROLE_HOMES[key])
    return builtin_ref(FALLBACK_HOME)


@dataclass(frozen=True)
class Home:
    """Which dashboard the home page shows, and why (own choice or the role's)."""

    ref: str
    chosen: bool


async def home(session: AsyncSession, subject: Subject) -> Home:
    """The subject's home dashboard (REQ-DSH-002): their choice, the role's, else built-in."""
    _require(subject, VIEW)
    preference = await _preference(session, subject)
    for ref, chosen in (
        (preference.home_ref if preference else None, True),
        (await _role_home(session, subject), False),
    ):
        if ref is None:
            continue
        try:
            await get_dashboard(session, subject, ref)
        except NotFound:
            continue  # deleted or no longer shared: fall back
        return Home(ref, chosen=chosen)
    return Home(_builtin_role_home(subject), chosen=False)


async def set_home(session: AsyncSession, subject: Subject, ref: str | None) -> Home:
    """Choose a home dashboard the subject can see, or None to go back to the role's."""
    if ref is not None:
        await get_dashboard(session, subject, ref)
    await session.execute(
        insert(DashboardPreference)
        .values(tenant_id=subject.tenant_id, user_id=subject.user_id, home_ref=ref)
        .on_conflict_do_update(
            index_elements=["tenant_id", "user_id"],
            set_={"home_ref": ref, "updated_at": func.now()},
        )
    )
    return await home(session, subject)


async def favourites(session: AsyncSession, subject: Subject) -> list[str]:
    """The subject's starred dashboards, newest first."""
    preference = await _preference(session, subject)
    return list(preference.favourites) if preference else []


async def set_favourite(
    session: AsyncSession, subject: Subject, ref: str, *, starred: bool
) -> list[str]:
    """Star or unstar a dashboard the subject can see (REQ-DSH-005 AC1)."""
    await get_dashboard(session, subject, ref)
    current = [r for r in await favourites(session, subject) if r != ref]
    wanted = [ref, *current] if starred else current
    if len(wanted) > MAX_FAVOURITES:
        raise ValidationFailed(code="too_many_favourites", params={"max": MAX_FAVOURITES})
    await session.execute(
        insert(DashboardPreference)
        .values(tenant_id=subject.tenant_id, user_id=subject.user_id, favourites=wanted)
        .on_conflict_do_update(
            index_elements=["tenant_id", "user_id"],
            set_={"favourites": wanted, "updated_at": func.now()},
        )
    )
    return wanted


# --- role homes (admins) ------------------------------------------------------------------------


async def role_homes(session: AsyncSession, subject: Subject) -> dict[str, str]:
    """The homes admins set, by role key."""
    _require(subject, MANAGE_DEFAULTS)
    rows = (await session.scalars(select(DashboardRoleDefault))).all()
    return {r.role_key: r.dashboard_ref for r in rows}


async def set_role_home(
    session: AsyncSession, subject: Subject, role_key: str, ref: str | None
) -> None:
    """Set (or clear, None) a role's home: a built-in or shared dashboard (REQ-DSH-002)."""
    _require(subject, MANAGE_DEFAULTS)
    if not await role_names(session, [role_key]):
        raise NotFound(code="role_not_found")
    if ref is None:
        await session.execute(
            delete(DashboardRoleDefault).where(DashboardRoleDefault.role_key == role_key)
        )
    else:
        found = await get_dashboard(session, subject, ref)
        if not found.shared:
            raise ValidationFailed(
                errors=[
                    FieldError(
                        field="body.dashboard_ref",
                        code="dashboard_not_shared",
                        message_key="errors.field.dashboard_not_shared",
                    )
                ]
            )
        await session.execute(
            insert(DashboardRoleDefault)
            .values(tenant_id=subject.tenant_id, role_key=role_key, dashboard_ref=ref)
            .on_conflict_do_update(
                index_elements=["tenant_id", "role_key"],
                set_={"dashboard_ref": ref, "updated_at": func.now()},
            )
        )
    await record_event(
        session,
        DashboardHomeChanged(role_key=role_key),
        aggregate_id=role_key,
    )
