"""Sites, support groups, departments and desks in detail (WP-021; ADR-032).

REQ-ADM-031, REQ-ADM-037, REQ-ADM-039, REQ-ESM-002.

Every write is in the caller's transaction with its event (CLAUDE.md rule b) and If-Match on
changes (rule g). A unit in use is never removed: it can be made inactive (kept on the people
and records that use it, not offered for new ones). Who uses a unit is asked through the usage
registry (usage.py), since other modules own those rows.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY
from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.modules.licensing import LimitKey, reserve_capacity
from app.modules.organization.domain.structure import ancestor_loop, detail_problems, text
from app.modules.organization.events import (
    DepartmentChanged,
    DeskChanged,
    SiteChanged,
    SupportGroupChanged,
)
from app.modules.organization.infra.models import (
    Department,
    Desk,
    GroupMember,
    GroupSite,
    Site,
    SiteMember,
    SupportGroup,
)
from app.modules.organization.service import units
from app.modules.organization.service.usage import UnitType, usage
from app.shared.db.repository import Repository
from app.shared.events import record_event

DEFAULT_DESK = "it"
DEFAULT_SITE_NAME = "Main site"
LIMITS = {
    "name": 200,
    "description": 2000,
    "region": 100,
    "time_zone": 64,
    "address": 1000,
    "phone": 50,
    "email": 320,
    "sender_name": 200,
    "code": 50,
}

# Every field problem code this module returns (errors.field.<code> labels, checked in CI by
# tests/test_error_labels.py, which reads FIELD_PROBLEMS sets).
FIELD_PROBLEMS = frozenset(
    {
        "required",
        "value_too_long",
        "email_not_valid",
        "phone_not_valid",
        "unknown_time_zone",
        "invalid_choice",
        "invalid_code",
        "name_taken",
        "code_taken",
        "parent_loop",
        "user_not_found",
        "site_not_found",
        "department_not_found",
        "desk_not_found",
        "site_inactive",
        "default_cannot_be_inactive",
    }
)


class DeskRepository(Repository[Desk]):
    """Desks of the session's tenant."""

    model = Desk


class SiteRepository(Repository[Site]):
    """Sites of the session's tenant."""

    model = Site


class GroupRepository(Repository[SupportGroup]):
    """Support groups of the session's tenant."""

    model = SupportGroup


class DepartmentRepository(Repository[Department]):
    """Departments of the session's tenant."""

    model = Department


def _problems(problems: Sequence[tuple[str, str]]) -> ValidationFailed:
    errors: list[FieldError] = []
    for name, code in problems:
        if code == "value_too_long":
            # The limit in the message (D-091; QA WP-021 BUG-02).
            errors.append(
                FieldError(
                    field=f"body.{name}",
                    code=code,
                    message_key="errors.field.value_too_long_max",
                    params={"max_length": LIMITS.get(name, 200)},
                )
            )
        else:
            errors.append(
                FieldError(field=f"body.{name}", code=code, message_key=f"errors.field.{code}")
            )
    return ValidationFailed(errors=errors)


def _clean(
    values: Mapping[str, Any], fields: Sequence[str]
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Trimmed text fields that were sent, with their length and format problems."""
    cleaned: dict[str, Any] = {}
    problems: list[tuple[str, str]] = []
    for name in fields:
        if name not in values:
            continue
        value = text(values[name])
        if value is not None and len(value) > LIMITS.get(name, 200):
            problems.append((name, "value_too_long"))
        cleaned[name] = value
    problems += detail_problems(cleaned)
    if "name" in values and cleaned.get("name") is None:
        problems.append(("name", "required"))
    return cleaned, problems


def _now() -> datetime:
    return datetime.now(UTC)


# --- desks ----------------------------------------------------------------------------------------


async def default_desk(session: AsyncSession) -> Desk:
    """The tenant's IT desk, created on first need (tenants made after migration 0023)."""
    found = await session.scalar(
        select(Desk).where(Desk.is_default.is_(True), Desk.deleted_at.is_(None))
    )
    if found is not None:
        return found
    context = session.info[SESSION_TENANT_KEY]
    await session.execute(
        insert(Desk)
        .values(
            id=uuid.uuid4(),
            tenant_id=context.tenant_id,
            code=DEFAULT_DESK,
            labels={"en": "IT"},
            is_default=True,
        )
        .on_conflict_do_nothing()
    )
    created = await session.scalar(
        select(Desk).where(Desk.is_default.is_(True), Desk.deleted_at.is_(None))
    )
    if created is None:  # pragma: no cover - the insert above or a parallel one made it
        msg = "no default desk"
        raise RuntimeError(msg)
    return created


async def default_desk_id(session: AsyncSession) -> uuid.UUID:
    """The ID of the IT desk (what every record gets until ESM is on)."""
    return (await default_desk(session)).id


async def list_desks(session: AsyncSession) -> list[Desk]:
    """Every desk, the default first."""
    await default_desk(session)
    return list(
        await session.scalars(
            select(Desk)
            .where(Desk.deleted_at.is_(None))
            .order_by(Desk.is_default.desc(), Desk.created_at, Desk.id)
        )
    )


async def desk_exists(session: AsyncSession, desk_id: uuid.UUID) -> bool:
    """A live, active desk of the tenant."""
    found = await session.scalar(
        select(Desk.id).where(
            Desk.id == desk_id, Desk.deleted_at.is_(None), Desk.disabled_at.is_(None)
        )
    )
    return found is not None


async def count_desks(session: AsyncSession) -> int:
    """Desks in use against the licence limit `desks` (the IT desk counts)."""
    return int(
        await session.scalar(
            select(func.count()).select_from(Desk).where(Desk.deleted_at.is_(None))
        )
        or 0
    )


async def create_licensed_desk(session: AsyncSession, values: Mapping[str, Any]) -> Desk:
    """A new desk within the licence limit `desks` (403 `desk_limit_reached` when full)."""
    await default_desk(session)
    await reserve_capacity(session, LimitKey.DESKS, code="desk_limit_reached")
    return await save_desk(session, None, values)


async def save_desk(
    session: AsyncSession,
    desk_id: uuid.UUID | None,
    values: Mapping[str, Any],
    *,
    expected_version: int | None = None,
) -> Desk:
    """Add or change a desk. The caller checks the ESM feature and the `desks` limit."""
    labels = values.get("labels")
    if labels is not None and (
        not isinstance(labels, dict) or not str(labels.get("en", "")).strip()
    ):
        raise _problems([("labels", "english_label_required")])
    if desk_id is None:
        code = str(values.get("code") or "").strip()
        if not code or not code.isidentifier() or not code.islower():
            raise _problems([("code", "invalid_code")])
        try:
            row = await DeskRepository(session).add(Desk(code=code, labels=labels or {}))
        except IntegrityError as exc:
            raise _problems([("code", "code_taken")]) from exc
        changed = ["code", "labels"]
    else:
        current = await _get(session, Desk, desk_id, "desk_not_found")
        changes: dict[str, Any] = {}
        if labels is not None:
            changes["labels"] = labels
        if "disabled" in values:
            if values["disabled"] and current.is_default:
                raise _problems([("disabled", "default_cannot_be_inactive")])
            changes["disabled_at"] = _now() if values["disabled"] else None
        row = await DeskRepository(session).update(
            desk_id, expected_version=expected_version or 0, changes=changes
        )
        changed = sorted(changes)
    await record_event(
        session,
        DeskChanged(desk_id=row.id, changed_fields=changed),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )
    return row


# --- sites ----------------------------------------------------------------------------------------

SITE_FIELDS = (
    "name",
    "description",
    "region",
    "time_zone",
    "default_language",
    "address",
    "phone",
    "email",
)


async def default_site(session: AsyncSession) -> Site:
    """The tenant's default site, created on first need ("Main site", REQ-ADM-037)."""
    found = await session.scalar(
        select(Site).where(Site.is_default.is_(True), Site.deleted_at.is_(None))
    )
    if found is not None:
        return found
    oldest = await session.scalar(
        select(Site).where(Site.deleted_at.is_(None)).order_by(Site.created_at, Site.id).limit(1)
    )
    if oldest is not None:
        oldest.is_default = True
        await session.flush()
        return oldest
    return await SiteRepository(session).add(Site(name=DEFAULT_SITE_NAME, is_default=True))


async def list_sites(session: AsyncSession) -> list[Site]:
    """Every site, by name (inactive ones included, marked)."""
    await default_site(session)
    return list(
        await session.scalars(select(Site).where(Site.deleted_at.is_(None)).order_by(Site.name))
    )


async def save_site(
    session: AsyncSession,
    site_id: uuid.UUID | None,
    values: Mapping[str, Any],
    *,
    expected_version: int | None = None,
) -> Site:
    """Add or change a site; `disabled` makes it inactive (never the default site)."""
    cleaned, problems = _clean(values, SITE_FIELDS)
    changes = dict(cleaned)
    if site_id is not None and "disabled" in values:
        current = await _get(session, Site, site_id, "site_not_found")
        if values["disabled"] and current.is_default:
            problems.append(("disabled", "default_cannot_be_inactive"))
        changes["disabled_at"] = _now() if values["disabled"] else None
    if problems:
        raise _problems(problems)
    repository = SiteRepository(session)
    try:
        if site_id is None:
            row = await repository.add(Site(**changes))
        else:
            row = await repository.update(
                site_id, expected_version=expected_version or 0, changes=changes
            )
    except IntegrityError as exc:
        raise _problems([("name", "name_taken")]) from exc
    await record_event(
        session,
        SiteChanged(site_id=row.id, changed_fields=sorted(changes)),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )
    return row


async def site_members(session: AsyncSession) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Member IDs by site."""
    members: dict[uuid.UUID, list[uuid.UUID]] = {}
    for site_id, user_id in (
        await session.execute(select(SiteMember.site_id, SiteMember.user_id))
    ).all():
        members.setdefault(site_id, []).append(user_id)
    return {k: sorted(v) for k, v in members.items()}


async def find_site(session: AsyncSession, value: str) -> uuid.UUID | None:
    """An active site by its name, case-insensitive and trimmed (sign-in mapping, WP-039 D6)."""
    name = value.strip().lower()
    if not name:
        return None
    return await session.scalar(
        select(Site.id).where(
            func.lower(Site.name) == name,
            Site.deleted_at.is_(None),
            Site.disabled_at.is_(None),
        )
    )


# --- support groups -------------------------------------------------------------------------------

GROUP_FIELDS = ("name", "description", "email", "sender_name")


@dataclass(frozen=True)
class GroupDetail:
    """A support group with the sites it serves and its members."""

    group: SupportGroup
    site_ids: list[uuid.UUID] = field(default_factory=list)
    member_ids: list[uuid.UUID] = field(default_factory=list)


async def list_groups(
    session: AsyncSession, *, site_id: uuid.UUID | None = None
) -> list[GroupDetail]:
    """Every group by name, with sites and members; `site_id`: only groups serving that site."""
    query = select(SupportGroup).where(SupportGroup.deleted_at.is_(None))
    if site_id is not None:
        query = query.where(
            SupportGroup.id.in_(select(GroupSite.group_id).where(GroupSite.site_id == site_id))
        )
    groups = list(await session.scalars(query.order_by(SupportGroup.name)))
    sites: dict[uuid.UUID, list[uuid.UUID]] = {}
    for group_id, served in (
        await session.execute(select(GroupSite.group_id, GroupSite.site_id))
    ).all():
        sites.setdefault(group_id, []).append(served)
    members: dict[uuid.UUID, list[uuid.UUID]] = {}
    for group_id, user_id in (
        await session.execute(select(GroupMember.group_id, GroupMember.user_id))
    ).all():
        members.setdefault(group_id, []).append(user_id)
    return [
        GroupDetail(g, sorted(sites.get(g.id, [])), sorted(members.get(g.id, []))) for g in groups
    ]


async def group_detail(session: AsyncSession, group_id: uuid.UUID) -> GroupDetail:
    """One group with its sites and members."""
    group = await _get(session, SupportGroup, group_id, "group_not_found")
    sites = await session.scalars(select(GroupSite.site_id).where(GroupSite.group_id == group_id))
    members = await session.scalars(
        select(GroupMember.user_id).where(GroupMember.group_id == group_id)
    )
    return GroupDetail(group, sorted(sites), sorted(members))


async def save_group(  # noqa: C901 - one rule per setting, flat
    session: AsyncSession,
    group_id: uuid.UUID | None,
    values: Mapping[str, Any],
    *,
    expected_version: int | None = None,
) -> GroupDetail:
    """Add or change a group: details, lead, sites served, desk; `disabled` makes it inactive."""
    cleaned, problems = _clean(values, GROUP_FIELDS)
    changes = dict(cleaned)
    if "lead_id" in values:
        changes["lead_id"] = values["lead_id"]
    if "desk_id" in values and values["desk_id"] is not None:
        if not await desk_exists(session, values["desk_id"]):
            problems.append(("desk_id", "desk_not_found"))
        changes["desk_id"] = values["desk_id"]
    if "disabled" in values:
        changes["disabled_at"] = _now() if values["disabled"] else None
    site_ids: list[uuid.UUID] | None = None
    if "site_ids" in values:
        site_ids = list(dict.fromkeys(values["site_ids"] or []))
        known = set(
            await session.scalars(
                select(Site.id).where(Site.id.in_(site_ids), Site.deleted_at.is_(None))
            )
        )
        if set(site_ids) - known:
            problems.append(("site_ids", "site_not_found"))
    if problems:
        raise _problems(problems)
    repository = GroupRepository(session)
    try:
        if group_id is None:
            changes.setdefault("desk_id", await default_desk_id(session))
            row = await repository.add(SupportGroup(**changes))
        else:
            row = await repository.update(
                group_id, expected_version=expected_version or 0, changes=changes
            )
    except IntegrityError as exc:
        # The name, or a lead that is no person of this tenant (composite foreign key).
        if "lead" in str(exc.orig):
            raise _problems([("lead_id", "user_not_found")]) from exc
        raise _problems([("name", "name_taken")]) from exc
    changed = sorted(changes)
    if site_ids is not None:
        await _replace_sites(session, row.id, site_ids)
        changed.append("site_ids")
    await record_event(
        session,
        SupportGroupChanged(group_id=row.id, changed_fields=sorted(set(changed))),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )
    return await group_detail(session, row.id)


async def _replace_sites(
    session: AsyncSession, group_id: uuid.UUID, site_ids: list[uuid.UUID]
) -> None:
    context = session.info[SESSION_TENANT_KEY]
    await session.execute(delete(GroupSite).where(GroupSite.group_id == group_id))
    if site_ids:
        await session.execute(
            insert(GroupSite).values(
                [
                    {
                        "tenant_id": context.tenant_id,
                        "group_id": group_id,
                        "site_id": site_id,
                        "created_by": context.user_id,
                    }
                    for site_id in site_ids
                ]
            )
        )


# --- departments ----------------------------------------------------------------------------------

DEPARTMENT_FIELDS = ("name", "code", "description")


async def list_departments(
    session: AsyncSession, *, site_id: uuid.UUID | None = None
) -> list[Department]:
    """Every department by name; `site_id`: only that site's (REQ-ADM-039 AC1)."""
    query = select(Department).where(Department.deleted_at.is_(None))
    if site_id is not None:
        query = query.where(Department.site_id == site_id)
    return list(await session.scalars(query.order_by(Department.name)))


async def save_department(  # noqa: C901, PLR0912 - one rule per setting, flat
    session: AsyncSession,
    department_id: uuid.UUID | None,
    values: Mapping[str, Any],
    *,
    expected_version: int | None = None,
) -> Department:
    """Add or change a department; a parent that would make it its own ancestor is refused."""
    cleaned, problems = _clean(values, DEPARTMENT_FIELDS)
    changes = dict(cleaned)
    for name in ("site_id", "head_id"):
        if name in values:
            changes[name] = values[name]
    if "site_id" in values and values["site_id"] is not None:
        site = await session.scalar(
            select(Site).where(Site.id == values["site_id"], Site.deleted_at.is_(None))
        )
        if site is None:
            problems.append(("site_id", "site_not_found"))
    if "parent_id" in values:
        parent_id = values["parent_id"]
        changes["parent_id"] = parent_id
        if parent_id is not None:
            parents = dict(
                (
                    await session.execute(
                        select(Department.id, Department.parent_id).where(
                            Department.deleted_at.is_(None)
                        )
                    )
                ).all()
            )
            if parent_id not in parents:
                problems.append(("parent_id", "department_not_found"))
            elif department_id is not None and ancestor_loop(department_id, parent_id, parents):
                problems.append(("parent_id", "parent_loop"))
    if "disabled" in values:
        changes["disabled_at"] = _now() if values["disabled"] else None
    if problems:
        raise _problems(problems)
    repository = DepartmentRepository(session)
    try:
        if department_id is None:
            row = await repository.add(Department(**changes))
        else:
            row = await repository.update(
                department_id, expected_version=expected_version or 0, changes=changes
            )
    except IntegrityError as exc:
        cause = str(exc.orig)
        if "head" in cause:
            raise _problems([("head_id", "user_not_found")]) from exc
        if "code" in cause:
            raise _problems([("code", "code_taken")]) from exc
        raise _problems([("name", "name_taken")]) from exc
    await record_event(
        session,
        DepartmentChanged(department_id=row.id, changed_fields=sorted(changes)),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )
    return row


async def find_department(session: AsyncSession, value: str) -> uuid.UUID | None:
    """An active department by code, else by name; case-insensitive and trimmed (WP-039 D6)."""
    wanted = value.strip().lower()
    if not wanted:
        return None
    live = (Department.deleted_at.is_(None), Department.disabled_at.is_(None))
    by_code = await session.scalar(
        select(Department.id).where(func.lower(Department.code) == wanted, *live)
    )
    if by_code is not None:
        return by_code
    return await session.scalar(
        select(Department.id).where(func.lower(Department.name) == wanted, *live)
    )


async def department_site(session: AsyncSession, department_id: uuid.UUID) -> uuid.UUID | None:
    """The site a department is at (records may take it), or None."""
    return await session.scalar(select(Department.site_id).where(Department.id == department_id))


async def existing_departments(
    session: AsyncSession, ids: Sequence[uuid.UUID]
) -> frozenset[uuid.UUID]:
    """Which of `ids` are live departments of the tenant (for other modules)."""
    if not ids:
        return frozenset()
    found = await session.scalars(
        select(Department.id).where(Department.id.in_(list(ids)), Department.deleted_at.is_(None))
    )
    return frozenset(found)


async def active_unit_ids(
    session: AsyncSession, kind: UnitType, ids: Sequence[uuid.UUID]
) -> frozenset[uuid.UUID]:
    """Which of `ids` are live, active sites / groups / departments (offered for new uses)."""
    if not ids:
        return frozenset()
    model = _MODELS[kind][0]
    found = await session.scalars(
        select(model.id).where(
            model.id.in_(list(ids)), model.deleted_at.is_(None), model.disabled_at.is_(None)
        )
    )
    return frozenset(found)


async def leave_groups(
    session: AsyncSession, user_id: uuid.UUID, group_ids: Sequence[uuid.UUID]
) -> None:
    """Take a person out of these support groups (reactivation keeps only confirmed ones)."""
    for group_id in group_ids:
        await units.remove_member(session, "group", group_id, user_id)


# --- removing -------------------------------------------------------------------------------------

_MODELS: dict[UnitType, tuple[Any, str]] = {
    "site": (Site, "site_not_found"),
    "group": (SupportGroup, "group_not_found"),
    "department": (Department, "department_not_found"),
}


async def remove_unit(
    session: AsyncSession, kind: UnitType, unit_id: uuid.UUID, *, expected_version: int
) -> None:
    """Remove a site, group or department nothing uses (409 `<kind>_in_use` with the counts).

    The default site cannot go. Members, people pointing at it, records, departments and
    groups serving a site keep it in use: make it inactive instead.
    """
    model, missing = _MODELS[kind]
    row = await _get(session, model, unit_id, missing)
    if kind == "site" and row.is_default:
        raise Conflict(code="default_site_required")
    used = await usage(session, kind, unit_id)
    used.update(await _own_usage(session, kind, unit_id))
    if used:
        raise Conflict(code=f"{kind}_in_use", params=used)
    repositories: dict[UnitType, type[Repository[Any]]] = {
        "site": SiteRepository,
        "group": GroupRepository,
        "department": DepartmentRepository,
    }
    removed = await repositories[kind](session).soft_delete(
        unit_id, expected_version=expected_version
    )
    event: SiteChanged | SupportGroupChanged | DepartmentChanged
    if kind == "site":
        event = SiteChanged(site_id=unit_id, changed_fields=["deleted"])
    elif kind == "group":
        await session.execute(delete(GroupSite).where(GroupSite.group_id == unit_id))
        event = SupportGroupChanged(group_id=unit_id, changed_fields=["deleted"])
    else:
        event = DepartmentChanged(department_id=unit_id, changed_fields=["deleted"])
    await record_event(session, event, aggregate_id=unit_id, aggregate_version=removed.version)


async def _own_usage(session: AsyncSession, kind: UnitType, unit_id: uuid.UUID) -> dict[str, int]:
    """Uses inside this module: members, departments, groups serving a site.

    Members count: removing a unit never silently narrows someone's access.
    """
    found: dict[str, int] = {}
    if kind in {"site", "group"}:
        member = SiteMember if kind == "site" else GroupMember
        column = SiteMember.site_id if kind == "site" else GroupMember.group_id
        members = await session.scalar(
            select(func.count()).select_from(member).where(column == unit_id)
        )
        if members:
            found["members"] = int(members)
    if kind == "site":
        departments = await session.scalar(
            select(func.count())
            .select_from(Department)
            .where(Department.site_id == unit_id, Department.deleted_at.is_(None))
        )
        groups = await session.scalar(
            select(func.count()).select_from(GroupSite).where(GroupSite.site_id == unit_id)
        )
        if departments:
            found["departments"] = int(departments)
        if groups:
            found["groups"] = int(groups)
    if kind == "department":
        children = await session.scalar(
            select(func.count())
            .select_from(Department)
            .where(Department.parent_id == unit_id, Department.deleted_at.is_(None))
        )
        if children:
            found["departments"] = int(children)
    return found


async def _get(session: AsyncSession, model: Any, unit_id: uuid.UUID, missing: str) -> Any:  # noqa: ANN401 - one of the unit models
    row = await session.scalar(select(model).where(model.id == unit_id, model.deleted_at.is_(None)))
    if row is None:
        raise NotFound(code=missing)
    return row
