"""The tenant's portal settings with no other home (WP-032 D8, D-143; REQ-PRT-031, -003).

One row, made on the first change; reading never writes (the defaults until then). Changing
needs the service desk configuration right; the change is audited by the route, recorded in
field history here and published so open portals take it at once (AC2).
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import PermissionDenied
from app.modules.identity_access import Subject
from app.modules.work_items.events import WorkItemPortalSettingsChanged
from app.modules.work_items.infra.models import PORTAL_SEARCH_SOURCES, WorkItemPortalSettings
from app.modules.work_items.service import work_items as items
from app.shared.events import record_event
from app.shared.history import Change, Source, record_changes, stale_version

MANAGE = ("config.service_desk", "settings.manage")
RECORD_TYPE = "work_item_portal_settings"
SWITCHES = ["profile_editing", "requester_reminders"]
EDITABLE = ["search_sources", *SWITCHES]


async def read(session: AsyncSession) -> WorkItemPortalSettings:
    """The tenant's settings; the defaults (version 1, not stored) before the first change."""
    row: WorkItemPortalSettings | None = await session.scalar(select(WorkItemPortalSettings))
    if row is not None:
        return row
    return WorkItemPortalSettings(
        tenant_id=session.info[SESSION_TENANT_KEY].tenant_id,
        search_sources=list(PORTAL_SEARCH_SOURCES),
        profile_editing=True,
        requester_reminders=True,
        version=1,
    )


def _sources(value: object) -> tuple[list[str] | None, list[tuple[str, str]]]:
    """Known sources, each once, at least one (the order is the admin's)."""
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        return None, [("search_sources", "invalid_choice")]
    if not value:
        return None, [("search_sources", "required")]
    if len(set(value)) != len(value) or any(v not in PORTAL_SEARCH_SOURCES for v in value):
        return None, [("search_sources", "invalid_choice")]
    return list(value), []


async def update(
    session: AsyncSession,
    subject: Subject,
    *,
    expected_version: int,
    values: Mapping[str, Any],
    source: Source,
) -> WorkItemPortalSettings:
    """Change what is sent (If-Match); unchanged input keeps the version."""
    if not any(subject.holds(p) for p in MANAGE):
        raise PermissionDenied(params={"permission": MANAGE[0], "reason": "no_permission"})
    clean: dict[str, Any] = {}
    problems: list[tuple[str, str]] = []
    if "search_sources" in values:
        sources, codes = _sources(values["search_sources"])
        problems += codes
        if sources is not None:
            clean["search_sources"] = sources
    for name in SWITCHES:
        if name in values:
            clean[name] = bool(values[name])
    if problems:
        raise items.field_errors(problems)
    await session.execute(
        insert(WorkItemPortalSettings)
        .values(tenant_id=session.info[SESSION_TENANT_KEY].tenant_id)
        .on_conflict_do_nothing(index_elements=["tenant_id"])
    )
    row = await session.scalar(select(WorkItemPortalSettings).with_for_update())
    assert row is not None  # noqa: S101 - inserted just above (RLS: this tenant's row only)
    if row.version != expected_version:
        # §5g: the 409 says who changed what since (from this row's field history).
        raise await stale_version(
            session,
            row,
            expected_version=expected_version,
            record_type=RECORD_TYPE,
            record_id=row.tenant_id,
        )
    changed = [k for k in EDITABLE if k in clean and getattr(row, k) != clean[k]]
    if not changed:
        return row
    before = {k: getattr(row, k) for k in changed}
    for name in changed:
        setattr(row, name, clean[name])
    row.version += 1
    await session.flush()
    await record_changes(
        session,
        record_type=RECORD_TYPE,
        record_id=row.tenant_id,
        version=row.version,
        kind="updated",
        changes=[Change(k, before[k], clean[k]) for k in changed],
        source=source,
    )
    await record_event(
        session,
        WorkItemPortalSettingsChanged(changed_fields=changed),
        aggregate_id=row.tenant_id,
        aggregate_version=row.version,
    )
    return row


__all__ = ["read", "update"]
