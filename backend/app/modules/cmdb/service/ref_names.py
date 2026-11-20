"""Names of a CI's references, through the reader's current rights (CMDB polish, after #550).

A CI points at a site, an owner (a person), an owner group, a managed-by group, an asset, and
people through person-type custom fields. The record, "as of" and compare name them here instead
of showing "Set". Each kind is named only through its owner module's public interface (rule e),
with one call per kind per response:

- sites (organization.site_names) and groups (organization's registered "group" names) only for a
  reader who may view sites or groups; otherwise `restricted`;
- people by display name (identity_access.user_names), as every history line names its actor;
- an asset only if the reader may see it (assets.asset_refs); a hidden one is `restricted`.

A label is never an ID (rule d). A reference to something since removed is `gone`.
"""

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules import assets, metadata
from app.modules.cmdb.domain import field_access as field_rules
from app.modules.identity_access import Subject, user_names
from app.modules.organization import site_names
from app.shared.reporting import names_resolver

log = get_logger(__name__)

SITE_FIELDS = ("site_id",)
GROUP_FIELDS = ("owner_group_id", "managed_by_group_id")
PERSON_FIELDS = ("owner_user_id",)
ASSET_FIELDS = ("asset_id",)
REFERENCE_FIELDS = (*SITE_FIELDS, *GROUP_FIELDS, *PERSON_FIELDS, *ASSET_FIELDS)

SITES_VIEW = "sites.view"
GROUPS_VIEW = "groups.view"
DEPARTMENTS_VIEW = "departments.view"
# Organization registers its group names with the shared names port (app/shared/reporting).
GROUP_KIND = "group"
DEPARTMENT_KIND = "department"


@dataclass(frozen=True)
class RefName:
    """How one reference reads: its label, or why it has none."""

    label: str | None = None
    restricted: bool = False  # the reader may not see it now
    gone: bool = False  # it no longer exists


@dataclass
class Refs:
    """The IDs one response refers to, by kind (as strings)."""

    sites: set[str] = field(default_factory=set)
    groups: set[str] = field(default_factory=set)
    departments: set[str] = field(default_factory=set)
    people: set[str] = field(default_factory=set)
    assets: set[str] = field(default_factory=set)


def _id(value: object) -> str | None:
    if value is None or value == "":
        return None
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        return None


async def person_keys(session: AsyncSession) -> frozenset[str]:
    """The CI custom fields whose values name a person (`custom.<key>`)."""
    found = await metadata.definitions(session, metadata.CustomFieldEntity.CI)
    return frozenset(
        f"{field_rules.CUSTOM}{key}"
        for key, definition in found.items()
        if definition.type == metadata.FieldType.PERSON
    )


def collect(fields: Mapping[str, Any], people_fields: Iterable[str], refs: Refs) -> None:
    """Add the references in `fields` (built-ins by name, custom values as `custom.<key>`)."""
    for name, bucket in (
        *((n, refs.sites) for n in SITE_FIELDS),
        *((n, refs.groups) for n in GROUP_FIELDS),
        *((n, refs.people) for n in PERSON_FIELDS),
        *((n, refs.assets) for n in ASSET_FIELDS),
    ):
        if (found := _id(fields.get(name))) is not None:
            bucket.add(found)
    for name in people_fields:
        if (found := _id(fields.get(name))) is not None:
            refs.people.add(found)


async def _sites(session: AsyncSession, subject: Subject, ids: set[str]) -> dict[str, RefName]:
    if not ids:
        return {}
    if not subject.holds(SITES_VIEW):
        return dict.fromkeys(ids, RefName(restricted=True))
    named = await site_names(session, [uuid.UUID(i) for i in sorted(ids)])
    return {
        i: RefName(label=named[uuid.UUID(i)]) if uuid.UUID(i) in named else RefName(gone=True)
        for i in ids
    }


async def _named_units(
    session: AsyncSession, subject: Subject, ids: set[str], *, kind: str, right: str
) -> dict[str, RefName]:
    """Groups or departments by the names organization registered (their admins' own words)."""
    if not ids:
        return {}
    resolver = names_resolver(kind)
    if not subject.holds(right) or resolver is None:
        return dict.fromkeys(ids, RefName(restricted=True))
    # A resolver that fails leaves every unit restricted, never its ID as text (lane C).
    try:
        named = await resolver(session, sorted(ids), "en", kind)
    except Exception:  # noqa: BLE001 - any failure of another module's port fails closed
        log.warning("cmdb_unit_names_failed", kind=kind)
        return dict.fromkeys(ids, RefName(restricted=True))
    return {i: RefName(label=named[i]) if i in named else RefName(gone=True) for i in ids}


async def _groups(session: AsyncSession, subject: Subject, ids: set[str]) -> dict[str, RefName]:
    return await _named_units(session, subject, ids, kind=GROUP_KIND, right=GROUPS_VIEW)


async def _departments(
    session: AsyncSession, subject: Subject, ids: set[str]
) -> dict[str, RefName]:
    return await _named_units(session, subject, ids, kind=DEPARTMENT_KIND, right=DEPARTMENTS_VIEW)


async def _people(session: AsyncSession, ids: set[str]) -> dict[str, RefName]:
    if not ids:
        return {}
    named = await user_names(session, sorted(ids))
    return {i: RefName(label=named[i]) if i in named else RefName(gone=True) for i in ids}


def _asset_label(ref: assets.AssetRef) -> str | None:
    parts = [p for p in (ref.tag, ref.name) if p]
    return " · ".join(parts) if parts else None


async def _assets(session: AsyncSession, subject: Subject, ids: set[str]) -> dict[str, RefName]:
    if not ids:
        return {}
    found = await assets.asset_refs(session, subject, [uuid.UUID(i) for i in sorted(ids)])
    out: dict[str, RefName] = {}
    for i in ids:
        ref = found.get(uuid.UUID(i))
        # A deleted asset can't be judged by the reader's rights any more, so it reads as
        # restricted: "gone" would confirm it existed to someone who might never have seen it
        # (lane C).
        if ref is None or ref.gone or ref.hidden:
            out[i] = RefName(restricted=True)
        else:
            label = _asset_label(ref)
            out[i] = RefName(label=label) if label else RefName(gone=True)
    return out


async def resolve(session: AsyncSession, subject: Subject, refs: Refs) -> dict[str, RefName]:
    """Every reference in `refs` named for this reader, one call per kind."""
    return {
        **await _sites(session, subject, refs.sites),
        **await _groups(session, subject, refs.groups),
        **await _departments(session, subject, refs.departments),
        **await _people(session, refs.people),
        **await _assets(session, subject, refs.assets),
    }


async def names_for(
    session: AsyncSession, subject: Subject, fields: Iterable[Mapping[str, Any]]
) -> dict[str, RefName]:
    """Collect and name the references of one or more field sets in one go."""
    refs = Refs()
    people = await person_keys(session)
    for one in fields:
        collect(one, people, refs)
    return await resolve(session, subject, refs)
