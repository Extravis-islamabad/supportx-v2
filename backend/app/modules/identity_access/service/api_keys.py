"""API keys (REQ-INT-019, 021; D-128): made, listed, revoked, and checked on every call.

Who makes keys: holders of `api_keys.manage` make them for service identities (an integration
keeps working when the person who set it up leaves) or for themselves, and see every key. Others
make keys for themselves only when the tenant allows it (`people_may_create_keys`, off by
default; REQ-SEC-037) and see their own. Anyone may revoke their own key.

On every call (`authenticate`): the key's tenant first (from the key), then under RLS the key
row; the secret's HMAC, revocation and expiry; the caller's address against the allowlist (a
refusal is audited); the owner still active. Nothing is cached, so a revoked key is refused on
its very next call (AC2). The owner's permissions are read live by the policy layer (REQ-INT-021
AC2).
"""

import hashlib
import hmac
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database
from app.core.errors import (
    FieldError,
    NotFound,
    PermissionDenied,
    ServiceUnavailable,
    Unauthenticated,
    ValidationFailed,
)
from app.core.tenancy import TenantContext
from app.modules.audit import RequestFacts, record, record_alone
from app.modules.identity_access.domain import api_keys as rules
from app.modules.identity_access.domain.network import NetworkApp, address_of
from app.modules.identity_access.domain.policy import Subject
from app.modules.identity_access.domain.support_grants import SUPPORT_USER_TYPE
from app.modules.identity_access.events import ApiKeyChanged
from app.modules.identity_access.infra.models import ApiKey, User
from app.modules.identity_access.service.identity_settings import (
    IdentitySettingsView,
    get_identity_settings,
)
from app.modules.identity_access.service.network_rules import admitted, get_network_rules
from app.shared.events import record_event
from app.shared.ids import new_id

VENDOR_SUPPORT_NO_KEYS = "api_key_vendor_support"
MANAGE = "api_keys.manage"
SERVICE = "service"
OWNERS_MAX = 500  # one per connector instance: far more than any tenant runs


# The context of the key derived from SUPPORTX_SESSION_SECRET: every hash made before the API-key
# key became its own production setting (audit row 26) is under it.
_LEGACY_CONTEXT = b"supportx-api-keys-v1"


def _derived_from_session_secret(settings: Settings) -> bytes | None:
    if settings.session_secret is None:
        return None
    secret = settings.session_secret.get_secret_value().encode()
    return hmac.new(secret, _LEGACY_CONTEXT, hashlib.sha256).digest()


def server_key(settings: Settings) -> bytes | None:
    """The key new secrets are hashed under: SUPPORTX_API_KEY_SECRET.

    Production refuses to start without it (audit row 26), so the session secret never guards API
    keys there. Dev and test without it derive one from SUPPORTX_SESSION_SECRET (the legacy
    secret, never the session key ring, D-162), so a dev stack needs no extra setting.
    """
    if settings.api_key_secret is not None:
        return settings.api_key_secret.get_secret_value().encode()
    return _derived_from_session_secret(settings)


def legacy_server_key(settings: Settings) -> bytes | None:
    """The key hashes made before SUPPORTX_API_KEY_SECRET was set are under, or None.

    Only while SUPPORTX_SESSION_SECRET is still set: such a key is re-hashed under the new key on
    its first good call (`authenticate`), so existing integrations keep working through the
    upgrade and the session secret stops mattering to them after it.
    """
    if settings.api_key_secret is None:
        return None  # the derived key is already the current one
    return _derived_from_session_secret(settings)


def _require_server_key(settings: Settings) -> bytes:
    key = server_key(settings)
    if key is None:
        raise ServiceUnavailable(code="api_keys_unavailable")
    return key


async def key_rules(session: AsyncSession) -> IdentitySettingsView:
    """The tenant's identity settings (people's own keys, keys without expiry; both off)."""
    return await get_identity_settings(session)


def _problem(
    *, field: str, code: str, params: dict[str, str | int | float | bool | None] | None = None
) -> ValidationFailed:
    return ValidationFailed(
        errors=[
            FieldError(
                field=f"body.{field}",
                code=code,
                message_key=f"errors.field.{code}",
                params=params or {},
            )
        ]
    )


def policy_of(allowed: IdentitySettingsView) -> rules.KeyPolicy:
    """The tenant's key policy (REQ-SEC-037)."""
    return rules.KeyPolicy(
        max_lifetime=timedelta(days=allowed.key_max_lifetime_days),
        allow_non_expiring=allowed.allow_non_expiring_keys,
        require_ip_range=allowed.keys_require_ip_range,
        unused_after=timedelta(days=allowed.key_unused_days),
    )


@dataclass(frozen=True)
class MadeKey:
    """A new key: the row, and the whole key text, shown this once."""

    row: ApiKey
    text: str


async def service_owners(session: AsyncSession, subject: Subject) -> list[User]:
    """The active service identities a key manager may make keys for (PEO-14).

    Their own list, because service identities are never in the people list, search or
    pickers (WP-040 s2); only `api_keys.manage` sees them here.
    """
    if not subject.holds(MANAGE):
        raise PermissionDenied(params={"permission": MANAGE, "reason": "no_permission"})
    rows = await session.scalars(
        select(User)
        .where(User.deleted_at.is_(None), User.user_type == SERVICE, User.status == "active")
        .order_by(User.display_name, User.id)
        .limit(OWNERS_MAX)
    )
    return list(rows)


async def _check_owner(
    session: AsyncSession,
    subject: Subject,
    owner: uuid.UUID,
    *,
    manager: bool,
    people_may: bool,
) -> None:
    """Who may hold the new key: the person themself, or a service identity a manager names."""
    if owner == subject.user_id:
        if not (manager or people_may):
            raise PermissionDenied(code="api_keys_people_off")
        me = await session.get(User, owner)
        # A vendor support account never holds a key (WP-057 S4c-1, lane B (5)): its access is
        # its grant's, ended with it; a key would outlive both.
        if me is not None and me.user_type == SUPPORT_USER_TYPE:
            raise PermissionDenied(code=VENDOR_SUPPORT_NO_KEYS)
        return
    if not manager:
        raise PermissionDenied(params={"permission": MANAGE, "reason": "no_permission"})
    person = await session.get(User, owner)
    # Keys for others: service identities only, never another person (they act as their owner).
    if person is None or person.deleted_at is not None or person.user_type != SERVICE:
        raise _problem(field="owner_id", code="api_key_owner_not_service")


async def create_key(  # noqa: PLR0913 - the key's parts, explicit
    session: AsyncSession,
    subject: Subject,
    settings: Settings,
    facts: RequestFacts,
    *,
    owner_id: uuid.UUID | None,
    name: str,
    scopes: Sequence[str],
    known_scopes: frozenset[str],
    expires_at: datetime | None,
    never_expires: bool,
    ip_allowlist: Sequence[str],
    now: datetime,
) -> MadeKey:
    """Make a key; the text is returned once and never stored (REQ-INT-019 AC1)."""
    server = _require_server_key(settings)
    owner = owner_id or subject.user_id
    manager = subject.holds(MANAGE)
    allowed = await key_rules(session)
    await _check_owner(
        session, subject, owner, manager=manager, people_may=allowed.people_may_create_keys
    )
    title = name.strip()
    if not title or len(title) > rules.NAME_MAX:
        raise _problem(field="name", code="api_key_name_invalid")
    chosen = sorted(set(scopes))
    if not chosen or any(s not in known_scopes for s in chosen):
        raise _problem(field="scopes", code="api_key_scope_unknown")
    policy = policy_of(allowed)
    # No expiry chosen: the default, cut to the policy so the key is never refused (lane B).
    expiry = (
        None if never_expires else (expires_at or now + rules.default_lifetime(policy.max_lifetime))
    )
    wrong = rules.expiry_problem(
        expiry,
        now,
        allow_non_expiring=allowed.allow_non_expiring_keys,
        max_lifetime=policy.max_lifetime,
    )
    if wrong is not None:
        # The limit is shown with the refusal (REQ-SEC-037 AC1).
        raise _problem(
            field="expires_at", code=wrong, params={"max_days": allowed.key_max_lifetime_days}
        )
    networks = rules.parse_allowlist(ip_allowlist)
    if networks is None or len(networks) > rules.ALLOWLIST_MAX:
        raise _problem(field="ip_allowlist", code="api_key_allowlist_invalid")
    missing = rules.ip_range_problem(networks, required=policy.require_ip_range)
    if missing is not None:
        raise _problem(field="ip_allowlist", code=missing)
    key_id = new_id()
    made = rules.make_key(subject.tenant_id, key_id)
    parsed = rules.parse_key(made.text)
    assert parsed is not None  # noqa: S101 - just made in the key's own format
    row = ApiKey(
        id=key_id,
        tenant_id=subject.tenant_id,
        owner_id=owner,
        name=title,
        scopes=chosen,
        secret_hash=rules.secret_hash(server, key_id, parsed.secret),
        last_four=made.last_four,
        expires_at=expiry,
        ip_allowlist=networks,
    )
    session.add(row)
    await session.flush()
    await record(
        session,
        action_code="api_key.created",
        facts=facts,
        object_type="api_key",
        object_id=key_id,
        details={"name": title, "owner_id": str(owner), "scopes": chosen},
    )
    await _changed(session, row, "created")
    return MadeKey(row=row, text=made.text)


async def policy_impact(
    session: AsyncSession, subject: Subject, policy: rules.KeyPolicy, now: datetime
) -> dict[str, int]:
    """How many active keys a proposed policy would flag, by reason (shown before saving).

    The coordinator (2026-11-16): keys made before a stricter policy are flagged and listed,
    never revoked; the admin sees how many first.
    """
    if not subject.holds(MANAGE):
        raise PermissionDenied(params={"permission": MANAGE, "reason": "no_permission"})
    rows = await session.scalars(
        select(ApiKey).where(
            ApiKey.deleted_at.is_(None),
            ApiKey.revoked_at.is_(None),
            (ApiKey.expires_at.is_(None)) | (ApiKey.expires_at > now),
        )
    )
    counts = {"lifetime_over_policy": 0, "no_ip_range": 0, "keys": 0}
    for row in rows:
        gaps = rules.out_of_policy(
            created_at=row.created_at,
            expires_at=row.expires_at,
            ip_allowlist=row.ip_allowlist,
            policy=policy,
        )
        for gap in gaps:
            counts[gap] += 1
        counts["keys"] += bool(gaps)
    return counts


async def list_keys(session: AsyncSession, subject: Subject) -> list[ApiKey]:
    """Every key for managers; your own keys for everyone else. Newest first."""
    statement = select(ApiKey).where(ApiKey.deleted_at.is_(None))
    if not subject.holds(MANAGE):
        statement = statement.where(ApiKey.owner_id == subject.user_id)
    return list(await session.scalars(statement.order_by(ApiKey.created_at.desc(), ApiKey.id)))


async def revoke_key(
    session: AsyncSession, subject: Subject, facts: RequestFacts, key_id: uuid.UUID, now: datetime
) -> ApiKey:
    """Revoke at once; revoking again changes nothing. Managers any key, people their own."""
    row = await session.get(ApiKey, key_id)
    if row is None or row.deleted_at is not None:
        raise NotFound(code="api_key_not_found")
    if row.owner_id != subject.user_id and not subject.holds(MANAGE):
        raise NotFound(code="api_key_not_found")  # someone else's key: not even that it exists
    if row.revoked_at is None:
        row.revoked_at = now
        row.revoked_by = subject.user_id
        row.version += 1
        await session.flush()
        await record(
            session,
            action_code="api_key.revoked",
            facts=facts,
            object_type="api_key",
            object_id=key_id,
            details={"name": row.name},
        )
        await _changed(session, row, "revoked")
    return row


async def _changed(
    session: AsyncSession, row: ApiKey, change: Literal["created", "revoked"]
) -> None:
    """The outbox event, in the same transaction as the key (architecture.md §6.5)."""
    await record_event(
        session,
        ApiKeyChanged(change=change, owner_id=row.owner_id),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )


async def _check_secret(
    session: AsyncSession,
    row: ApiKey,
    parsed: rules.ParsedKey,
    server: bytes,
    legacy: bytes | None,
) -> None:
    """The secret against the stored hash; a hash under the legacy key moves to the current one."""
    if rules.secret_matches(server, parsed.key_id, parsed.secret, row.secret_hash):
        return
    if legacy is None or not rules.secret_matches(
        legacy, parsed.key_id, parsed.secret, row.secret_hash
    ):
        raise Unauthenticated(code="api_key_invalid")
    # Made under the session-secret key: move it to the API-key key now (audit row 26). Guarded
    # by the old hash, so two replicas re-hashing at once write the same value once.
    await session.execute(
        update(ApiKey)
        .where(ApiKey.id == row.id, ApiKey.secret_hash == row.secret_hash)
        .values(secret_hash=rules.secret_hash(server, parsed.key_id, parsed.secret))
    )


async def authenticate(
    database: Database, settings: Settings, text: str, facts: RequestFacts, now: datetime
) -> TenantContext:
    """The context an API key's call runs in, or a refusal (D-128)."""
    parsed = rules.parse_key(text)
    if parsed is None:
        raise Unauthenticated(code="api_key_invalid")
    server = server_key(settings)
    if server is None:
        raise ServiceUnavailable(code="api_keys_unavailable")
    legacy = legacy_server_key(settings)
    tenant_only = TenantContext(parsed.tenant_id)
    async with database.tenant_session(tenant_only) as session:
        row = await session.get(ApiKey, parsed.key_id)
        if row is None or row.deleted_at is not None:
            raise Unauthenticated(code="api_key_invalid")
        await _check_secret(session, row, parsed, server, legacy)
        if row.revoked_at is not None:
            raise Unauthenticated(code="api_key_revoked")
        if row.expires_at is not None and row.expires_at <= now:
            raise Unauthenticated(code="api_key_expired")
        owner = await session.get(User, row.owner_id)
        if owner is None or owner.deleted_at is not None or owner.status != "active":
            raise Unauthenticated(code="api_key_owner_inactive")
        if owner.user_type == SUPPORT_USER_TYPE:  # never made; refused anyway (lane B (5))
            raise Unauthenticated(code=VENDOR_SUPPORT_NO_KEYS)
        # The key's own list, then the tenant's API list (REQ-SEC-034): both must admit it.
        key_allowed = rules.address_allowed(facts.ip, row.ip_allowlist)
        tenant_allowed = admitted(
            await get_network_rules(session), NetworkApp.API, address_of(facts.ip)
        )
        allowed = key_allowed and tenant_allowed
        if allowed and (
            row.last_used_at is None or now - row.last_used_at >= rules.LAST_USED_EVERY
        ):
            await session.execute(
                update(ApiKey)
                .where(ApiKey.id == row.id)
                .values(last_used_at=now, last_used_ip=facts.ip)
            )
        key_id, owner_id, scopes, name = row.id, row.owner_id, frozenset(row.scopes), row.name
        service_identity = owner.user_type == "service"
    if not allowed:
        # Refused and written down: which key, from where (REQ-INT-019 AC3).
        await record_alone(
            database,
            TenantContext(parsed.tenant_id, owner_id),
            action_code="api_key.refused",
            facts=facts,
            object_type="api_key",
            object_id=key_id,
            details={
                "name": name,
                "reason": "address_not_allowed" if not key_allowed else "tenant_ip_not_allowed",
            },
        )
        raise PermissionDenied(code="api_key_ip_refused" if not key_allowed else "ip_not_allowed")
    return TenantContext(
        parsed.tenant_id,
        owner_id,
        api_key_id=key_id,
        api_scopes=scopes,
        service_identity=service_identity,
    )


def bearer(authorization: str | None) -> str | None:
    """The key in `Authorization: Bearer sxk_…`, or None (another scheme, or no header)."""
    if authorization is None:
        return None
    scheme, _, value = authorization.partition(" ")
    value = value.strip()
    if scheme.lower() != "bearer" or not value.startswith(f"{rules.PREFIX}_"):
        return None
    return value
