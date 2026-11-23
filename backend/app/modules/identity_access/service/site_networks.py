"""A tenant's address ranges mapped to sites, for the sign-in place (WP-057 S2b-1; D-170).

One list, saved whole under the tenant's identity settings version (as the IP allow-lists are),
so If-Match covers it: version 0 = never saved. Every range is validated (host bits clear, at
most MAX_SITE_NETWORKS, no range twice) and every site must be an active site of this tenant
(organization's public interface; the composite key keeps it in the tenant either way). The
route audits each change with the ranges and site IDs before and after: ranges, never anyone's
address. Read at sign-in (`tenant_site_networks`) to name the place.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY, Database
from app.core.errors import Conflict, FieldError, ValidationFailed
from app.core.tenancy import TenantContext
from app.modules.identity_access.domain.place import MAX_SITE_NETWORKS, SiteNetwork, parse_network
from app.modules.identity_access.infra.models import IdentitySettings
from app.modules.identity_access.infra.models import SiteNetwork as SiteNetworkRow
from app.modules.identity_access.service.network_rules import save_settings_version
from app.modules.organization import active_unit_ids
from app.shared.history import stale_version
from app.shared.ids import new_id

FIELD = "site_networks"


@dataclass(frozen=True)
class SiteMap:
    """The ranges as saved (most specific first, then by text) and the settings version."""

    entries: tuple[tuple[str, uuid.UUID], ...] = ()
    version: int = 0

    def networks(self) -> tuple[SiteNetwork, ...]:
        """The parsed ranges (saved ones are valid by construction)."""
        return tuple(SiteNetwork(parse_network(net), site) for net, site in self.entries)


def _ordered(pairs: Sequence[tuple[str, uuid.UUID]]) -> tuple[tuple[str, uuid.UUID], ...]:
    def key(pair: tuple[str, uuid.UUID]) -> tuple[int, int, str]:
        net = parse_network(pair[0])
        return (net.version, -net.prefixlen, str(net))

    return tuple(sorted(pairs, key=key))


async def get_site_map(session: AsyncSession) -> SiteMap:
    """The tenant's ranges (empty when never saved)."""
    settings = await session.scalar(select(IdentitySettings))
    rows = await session.execute(select(SiteNetworkRow.network, SiteNetworkRow.site_id))
    entries = _ordered([(str(net), site) for net, site in rows.all()])
    return SiteMap(entries, settings.version if settings is not None else 0)


async def tenant_site_networks(database: Database, tenant_id: uuid.UUID) -> tuple[SiteNetwork, ...]:
    """The ranges of `tenant_id`, read at sign-in to name its place."""
    async with database.tenant_session(TenantContext(tenant_id)) as session:
        return (await get_site_map(session)).networks()


def _error(index: int, code: str, params: dict[str, str | int | float | bool | None]) -> FieldError:
    return FieldError(
        field=f"entries.{index}", code=code, message_key=f"errors.field.{code}", params=params
    )


async def _validated(
    session: AsyncSession, entries: Sequence[tuple[str, uuid.UUID]]
) -> tuple[tuple[str, uuid.UUID], ...]:
    if len(entries) > MAX_SITE_NETWORKS:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="entries",
                    code="site_network_too_many",
                    message_key="errors.field.site_network_too_many",
                    params={"max": MAX_SITE_NETWORKS},
                )
            ]
        )
    errors: list[FieldError] = []
    seen: set[str] = set()
    parsed: list[tuple[str, uuid.UUID]] = []
    for index, (text, site_id) in enumerate(entries):
        try:
            network = str(parse_network(text))
        except ValueError:
            errors.append(_error(index, "site_network_invalid", {"entry": text[:64]}))
            continue
        if network in seen:
            errors.append(_error(index, "duplicate_value", {"entry": network}))
            continue
        seen.add(network)
        parsed.append((network, site_id))
    sites = {site for _net, site in parsed}
    active = set(await active_unit_ids(session, "site", list(sites))) if sites else set()
    errors += [
        _error(index, "site_not_found", {})
        for index, (_net, site) in enumerate(parsed)
        if site not in active
    ]
    if errors:
        raise ValidationFailed(errors=errors)
    return _ordered(parsed)


async def save_site_map(
    session: AsyncSession,
    entries: Sequence[tuple[str, uuid.UUID]],
    *,
    expected_version: int,
) -> tuple[SiteMap, dict[str, object]]:
    """Replace the list if the settings are at `expected_version`; the audit details too."""
    after = await _validated(session, entries)
    row = await session.scalar(select(IdentitySettings))
    current = await get_site_map(session)
    if current.version != expected_version:
        if row is not None:
            raise await stale_version(session, row, expected_version=expected_version)
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": current.version},
        )
    if after == current.entries:
        return current, {}
    version = await save_settings_version(
        session, expected_version=expected_version, changed=[FIELD]
    )
    tenant = session.info[SESSION_TENANT_KEY]
    await session.execute(delete(SiteNetworkRow))
    session.add_all(
        SiteNetworkRow(
            tenant_id=tenant.tenant_id,
            id=new_id(),
            network=net,
            site_id=site,
            created_by=tenant.user_id,
            updated_by=tenant.user_id,
        )
        for net, site in after
    )
    await session.flush()
    details: dict[str, object] = {
        "changed_fields": [FIELD],
        "before": [{"network": n, "site_id": str(s)} for n, s in current.entries],
        "after": [{"network": n, "site_id": str(s)} for n, s in after],
        "version": version,
    }
    return SiteMap(after, version), details
