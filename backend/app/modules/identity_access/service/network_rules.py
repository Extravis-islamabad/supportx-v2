"""A tenant's IP allow-lists (REQ-SEC-034; WP-057 S1a; domain/network.py).

One list per app (console, portal, API), kept on the tenant's `identity_settings` row (0151), so
they share its version: If-Match with the version read, version 0 = never saved. Saving needs
`identity.manage`; the route audits every change (`identity.network_rules_changed`, the lists
before and after: ranges, never a person's address). A save that would shut out the admin
making it is refused (AC2); the check uses the address the BFF and the rate limiter see
(uvicorn's, through the trusted proxies only).

Enforcement (service/auth.py): before a person is looked up or created at sign-in and at a
tenant switch, again when a session refreshes, at the realtime token and when an API key calls.
"""

import ipaddress
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SESSION_TENANT_KEY, Database
from app.core.errors import Conflict, FieldError, ValidationFailed
from app.core.tenancy import TenantContext
from app.modules.identity_access.domain.network import (
    IP_ALLOW_MAX,
    Address,
    ListProblem,
    Network,
    NetworkApp,
    allows,
    locks_out,
    parse_list,
)
from app.modules.identity_access.events import IdentitySettingsChanged
from app.modules.identity_access.infra.models import IdentitySettings
from app.shared.events import record_event
from app.shared.history import stale_version

COLUMNS: dict[NetworkApp, str] = {
    NetworkApp.CONSOLE: "console_ip_allow",
    NetworkApp.PORTAL: "portal_ip_allow",
    NetworkApp.API: "api_ip_allow",
}


@dataclass(frozen=True)
class NetworkRules:
    """The lists as saved (ranges as text, in the order given) and the row's version."""

    lists: dict[NetworkApp, tuple[str, ...]] = field(
        default_factory=lambda: dict.fromkeys(NetworkApp, ())
    )
    version: int = 0

    def networks(self, app: NetworkApp) -> tuple[Network, ...]:
        """The parsed list of `app` (saved lists are valid by construction)."""
        return tuple(ipaddress.ip_network(entry) for entry in self.lists.get(app, ()))


def _rules(row: IdentitySettings | None) -> NetworkRules:
    if row is None:
        return NetworkRules()
    return NetworkRules(
        {app: tuple(str(n) for n in getattr(row, column)) for app, column in COLUMNS.items()},
        row.version,
    )


async def get_network_rules(session: AsyncSession) -> NetworkRules:
    """The tenant's lists (empty when never saved)."""
    return _rules(await session.scalar(select(IdentitySettings)))


async def tenant_network_rules(database: Database, tenant_id: uuid.UUID) -> NetworkRules:
    """The lists of `tenant_id`, read before anyone is signed in to it (the sign-in hook)."""
    async with database.tenant_session(TenantContext(tenant_id)) as session:
        return await get_network_rules(session)


def admitted(rules: NetworkRules, app: NetworkApp, address: Address | None) -> bool:
    """Whether `address` may use `app` under `rules`."""
    return allows(rules.networks(app), address)


def _field_error(
    app: NetworkApp, code: str, params: dict[str, str | int | float | bool | None]
) -> FieldError:
    return FieldError(
        field=COLUMNS[app],
        code=code,
        message_key=f"errors.field.{code}",
        params=params,
    )


def _validated(lists: dict[NetworkApp, list[str]]) -> dict[NetworkApp, tuple[Network, ...]]:
    errors: list[FieldError] = []
    parsed: dict[NetworkApp, tuple[Network, ...]] = {}
    for app in NetworkApp:
        result = parse_list(lists.get(app, []))
        if result.problem is ListProblem.TOO_MANY:
            errors.append(_field_error(app, result.problem.value, {"max": IP_ALLOW_MAX}))
        elif result.problem is not None:
            errors.append(_field_error(app, result.problem.value, {"entry": result.bad_entry}))
        parsed[app] = result.networks
    if errors:
        raise ValidationFailed(errors=errors)
    return parsed


async def save_network_rules(
    session: AsyncSession,
    lists: dict[NetworkApp, list[str]],
    *,
    expected_version: int,
    admin_address: Address | None,
    via_api_key: bool,
) -> tuple[NetworkRules, dict[str, object]]:
    """Save the lists if the stored version is `expected_version`; the audit details too.

    Refused, with the list that would do it, when the admin saving them could no longer reach
    the console (or the API, saving with a key) from where they are (AC2).
    """
    parsed = _validated(lists)
    shut = locks_out(parsed, admin_address, via_api_key=via_api_key)
    if shut is not None:
        raise ValidationFailed(
            errors=[
                _field_error(
                    shut,
                    ListProblem.LOCKS_YOU_OUT.value,
                    {"address": str(admin_address) if admin_address else ""},
                )
            ]
        )
    row = await session.scalar(select(IdentitySettings))
    current = _rules(row)
    if current.version != expected_version:
        if row is not None:
            raise await stale_version(session, row, expected_version=expected_version)
        raise Conflict(
            code="version_conflict",
            params={"expected_version": expected_version, "current_version": current.version},
        )
    after = {app: tuple(str(n) for n in parsed[app]) for app in NetworkApp}
    changed = [COLUMNS[app] for app in NetworkApp if after[app] != current.lists.get(app, ())]
    if not changed:
        return current, {}
    columns = {COLUMNS[app]: [str(n) for n in parsed[app]] for app in NetworkApp}
    version = await save_settings_version(
        session, expected_version=expected_version, changed=changed, columns=columns
    )
    details: dict[str, object] = {
        "changed_fields": changed,
        "before": {COLUMNS[app]: list(current.lists.get(app, ())) for app in NetworkApp},
        "after": {COLUMNS[app]: list(after[app]) for app in NetworkApp},
        "version": version,
    }
    return NetworkRules(after, version), details


async def save_settings_version(
    session: AsyncSession,
    *,
    expected_version: int,
    changed: list[str],
    columns: Mapping[str, object] | None = None,
) -> int:
    """Write `columns` to the tenant's identity settings and move their version, or 409.

    Shared by the settings saved under this row's version (the allow-lists, the site map): the
    upsert only applies at `expected_version` (version 0 = never saved), and the change is in the
    outbox in the same transaction (rule b).
    """
    context = session.info[SESSION_TENANT_KEY]
    values = dict(columns or {})
    statement = (
        insert(IdentitySettings)
        .values(
            tenant_id=context.tenant_id,
            created_by=context.user_id,
            updated_by=context.user_id,
            version=1,
            **values,
        )
        .on_conflict_do_update(
            index_elements=[IdentitySettings.tenant_id],
            set_={
                **values,
                "updated_at": datetime.now(UTC),
                "updated_by": context.user_id,
                "version": IdentitySettings.version + 1,
            },
            where=IdentitySettings.version == expected_version,
        )
        .returning(IdentitySettings.version)
    )
    version = await session.scalar(statement)
    if version is None:  # changed by someone else between the read and the write
        raise Conflict(code="version_conflict", params={"expected_version": expected_version})
    await record_event(
        session,
        IdentitySettingsChanged(changed_fields=changed),
        aggregate_id=context.tenant_id,
        aggregate_version=version,
    )
    return int(version)
