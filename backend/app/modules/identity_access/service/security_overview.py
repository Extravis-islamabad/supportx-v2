"""The security overview (WP-057 S4d): the security screens' numbers in one place, with flags.

Every number comes from the function its own screen uses, so the overview never disagrees with
the screen a tile links to (lane B's condition 2; a test per tile checks it):

- MFA: `mfa.list_policies` (GET /identity/mfa);
- sign-in: `get_sso_policy` and the SSO set-ups' `expiry_items` (the expiry notices' own list);
- passwords and sessions: `get_identity_settings` (GET /identity/settings);
- network: `get_network_rules` (GET /identity/network-rules);
- keys: `list_keys` and `key_state` (GET /api-keys);
- service accounts: `list_service_accounts` (GET /service-accounts);
- encryption: metadata's `seal_counts` and the data key's date;
- sign-in events: `sign_in_log.count_events` with the log's own filters (GET /identity/sign-ins).

IDs and counts only, never a name, address or e-mail (lane B's condition 1). Flags are
recommendations; nothing here changes a setting.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.audit import plaintext_siem_destinations
from app.modules.identity_access.domain import api_keys as key_rules
from app.modules.identity_access.domain import security_overview as rules
from app.modules.identity_access.domain.network import NetworkApp
from app.modules.identity_access.domain.permissions import TENANT_ADMIN
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.domain.sign_in import SignInOutcome
from app.modules.identity_access.infra.models import SsoProvider
from app.modules.identity_access.service import (
    api_keys,
    mfa,
    service_accounts,
    sign_in_log,
    support_grants,
)
from app.modules.identity_access.service.break_glass import get_sso_policy
from app.modules.identity_access.service.expiry_alerts import expiry_items
from app.modules.identity_access.service.identity_settings import get_identity_settings
from app.modules.identity_access.service.network_rules import get_network_rules
from app.shared.fields import key_ring_since

VIEW_SIGN_INS = "identity.view_sign_ins"  # the sign-in log's right (GET /identity/sign-ins)


@dataclass(frozen=True)
class MfaTile:
    """Roles held by someone, and how many of their holders have enrolled."""

    roles: int
    roles_required: int
    holders: int
    enrolled: int


@dataclass(frozen=True)
class KeysTile:
    """Active keys, and those the policy flags (the key list's own flags)."""

    active: int
    out_of_policy: int
    unused: int


@dataclass(frozen=True)
class Overview:
    """The overview: one tile per area, the flags, and the optional data region."""

    sso_required: str  # off, technicians or everyone
    sso_setups: int
    sso_expiry_days_left: int | None
    mfa: MfaTile
    password_min_length: int
    password_breached_check: bool
    console_idle_seconds: int
    console_absolute_seconds: int
    network_rules: Mapping[str, int]  # app → ranges listed (0: open)
    keys: KeysTile | None  # None: the viewer lacks api_keys.manage (the key list's right)
    service_accounts: int | None  # None: as keys
    service_accounts_without_owner: int | None
    seal_states: Mapping[str, int]  # sensitive fields by seal state
    key_since: datetime | None
    failed_sign_ins: int | None  # None: the viewer lacks identity.view_sign_ins
    locked_sign_ins: int | None
    data_region: str | None  # the instance's setting; None hides the tile
    flags: list[rules.Flag]
    recommendations: Mapping[str, int | bool]
    # Tiles left out because the viewer lacks their screen's right (lane B, #537): their numbers
    # are null and no flag from them is shown.
    tiles_hidden: list[rules.SecurityArea]


async def _sso(session: AsyncSession, now: datetime) -> tuple[int, int | None]:
    providers = list(
        await session.scalars(
            select(SsoProvider).where(
                SsoProvider.deleted_at.is_(None), SsoProvider.state != "draft"
            )
        )
    )
    soonest: datetime | None = None
    for provider in providers:
        for _, _, expires_at in await expiry_items(provider, None):
            soonest = expires_at if soonest is None else min(soonest, expires_at)
    days = None if soonest is None else (soonest - now) // timedelta(days=1)
    return len(providers), days


async def _keys(session: AsyncSession, subject: Subject, now: datetime) -> KeysTile:
    policy = api_keys.policy_of(await api_keys.key_rules(session))
    states = [
        key_rules.key_state(
            created_at=row.created_at,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
            last_used_at=row.last_used_at,
            ip_allowlist=row.ip_allowlist,
            policy=policy,
            now=now,
        )
        for row in await api_keys.list_keys(session, subject)
    ]
    active = [s for s in states if s.status == "active"]
    return KeysTile(
        len(active), sum(1 for s in active if s.gaps), sum(1 for s in active if s.unused)
    )


async def _sign_ins(session: AsyncSession, now: datetime) -> tuple[int, int]:
    since = now - timedelta(days=rules.FAILED_SIGN_INS_WINDOW_DAYS)

    async def count(outcome: SignInOutcome) -> int:
        found = sign_in_log.LogFilter(outcomes=(outcome,), since=since)
        return await sign_in_log.count_events(session, found)

    return await count(SignInOutcome.FAILED), await count(SignInOutcome.LOCKED)


# Metadata counts its sensitive fields by seal state and registers that here at load (it imports
# this module, never the reverse): identity_access never reads another module's tables.
SealCounter = Callable[[AsyncSession], Awaitable[dict[str, int]]]
_seal_counter: SealCounter | None = None


def register_seal_counter(counter: SealCounter) -> None:
    """Metadata's count of sensitive fields by seal state (WP-057 S4d)."""
    global _seal_counter  # noqa: PLW0603 - one registry per process, set once at import
    _seal_counter = counter


async def _seal_states(session: AsyncSession) -> dict[str, int]:
    """Empty when no module registered (the tile then shows no encrypted fields)."""
    return {} if _seal_counter is None else await _seal_counter(session)


async def overview(
    session: AsyncSession, subject: Subject, settings: Settings, now: datetime
) -> Overview:
    """Gather each tile from its screen's own service, then the flags (identity.manage)."""
    found = await get_identity_settings(session)
    sso_policy = await get_sso_policy(session)
    sso_setups, expiry_days = await _sso(session, now)
    policies = [p for p in await mfa.list_policies(session) if p.holders > 0]
    network = await get_network_rules(session)
    # Each tile only with its own screen's right (lane B, #537): tenant-wide key and service
    # account numbers need api_keys.manage, sign-in numbers identity.view_sign_ins.
    hidden: list[rules.SecurityArea] = []
    keys: KeysTile | None = None
    accounts: list[service_accounts.ServiceAccountView] | None = None
    if subject.holds(api_keys.MANAGE):
        keys = await _keys(session, subject, now)
        accounts = await service_accounts.list_service_accounts(session, subject)
    else:
        hidden += [rules.SecurityArea.KEYS, rules.SecurityArea.SERVICE_ACCOUNTS]
    seal_states = await _seal_states(session)
    failed: int | None = None
    locked: int | None = None
    if subject.holds(VIEW_SIGN_INS):
        failed, locked = await _sign_ins(session, now)
    else:
        hidden.append(rules.SecurityArea.SIGN_IN_EVENTS)
    without_owner = None if accounts is None else sum(1 for a in accounts if a.needs_new_owner)
    choices = rules.Choices(
        roles_without_mfa=sum(1 for p in policies if p.mode == "off"),
        admins_without_mfa=any(p.key == TENANT_ADMIN and p.mode == "off" for p in policies),
        sso_required=sso_policy.required == "everyone",
        password_min_length=found.password_min_length,
        password_breached_check=found.password_breached_check,
        password_expiry_days=found.password_expiry_days,
        console_idle_seconds=found.console_idle_seconds,
        console_absolute_seconds=found.console_absolute_seconds,
        console_network_rule=bool(network.lists.get(NetworkApp.CONSOLE)),
        api_network_rule=bool(network.lists.get(NetworkApp.API)),
        allow_non_expiring_keys=found.allow_non_expiring_keys,
        key_max_lifetime_days=found.key_max_lifetime_days,
        keys_out_of_policy=0 if keys is None else keys.out_of_policy,
        keys_unused=0 if keys is None else keys.unused,
        service_accounts_without_owner=without_owner or 0,
        sso_expiry_days_left=expiry_days,
        fields_not_sealed=seal_states.get("sealing", 0) + seal_states.get("opening", 0),
        failed_sign_ins=failed or 0,
        locked_sign_ins=locked or 0,
        support_removals_stuck=len(await support_grants.stuck_removals(session, now)),
        plaintext_siem_destinations=await plaintext_siem_destinations(session),
    )
    return Overview(
        sso_required=sso_policy.required,
        sso_setups=sso_setups,
        sso_expiry_days_left=expiry_days,
        mfa=MfaTile(
            roles=len(policies),
            roles_required=sum(1 for p in policies if p.mode == "required"),
            holders=sum(p.holders for p in policies),
            enrolled=sum(p.enrolled for p in policies),
        ),
        password_min_length=found.password_min_length,
        password_breached_check=found.password_breached_check,
        console_idle_seconds=found.console_idle_seconds,
        console_absolute_seconds=found.console_absolute_seconds,
        network_rules={app.value: len(network.lists.get(app, ())) for app in NetworkApp},
        keys=keys,
        service_accounts=None if accounts is None else len(accounts),
        service_accounts_without_owner=without_owner,
        seal_states=seal_states,
        key_since=await key_ring_since(session),
        failed_sign_ins=failed,
        locked_sign_ins=locked,
        data_region=(settings.data_region or "").strip() or None,
        flags=[f for f in rules.flags(choices) if f.area not in hidden],
        recommendations=rules.RECOMMENDATIONS,
        tiles_hidden=hidden,
    )
