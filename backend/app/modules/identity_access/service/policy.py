"""The authorization policy service: one place that decides (architecture.md §11.2; WP-016).

    subject_for / subject   compile (and cache) a user's effective permissions
    authorize               one decision: permission, optionally on one record (+ SoD rules)
    scope_filter            SQL predicate so a list only ever returns what the user may see
    visible                 field-level hiding / masking when serialising a record

Used by the API now; search, the realtime fan-out (WP-011) and AI agents call the same functions,
so a rule is written once. PostgreSQL RLS stays the final tenant boundary underneath.

Caching: the compiled subject lives in Valkey under the tenant's generation. Any role,
assignment, membership or entitlement change bumps the generation: right after the change commits
in the API process that made it (after_commit hook) and again when the change's event reaches
the `identity_access__invalidate_authz` consumer (every other process).
"""

import json
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Literal, Protocol

import valkey.exceptions
from fastapi import Request
from sqlalchemy import ColumnElement, and_, exists, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import REQUEST_SESSION_STATE, Database
from app.core.errors import PermissionDenied
from app.core.logging import get_logger
from app.core.tenancy import TenantContext
from app.modules.identity_access.domain.permissions import (
    REQUESTER,
    SYSTEM_ROLES,
    TECHNICIAN,
    TENANT_ADMIN,
    Catalogue,
)
from app.modules.identity_access.domain.policy import (
    Decision,
    Grant,
    RecordFacts,
    Subject,
    compile_subject,
    decide,
)
from app.modules.identity_access.infra.models import Role, RolePermission, User, UserRole
from app.shared.api.filters import ResourceFields, compile_filter

log = get_logger(__name__)

SUBJECT_STATE = "authz_subject"
MemberLookup = Callable[
    [AsyncSession, uuid.UUID], Awaitable[tuple[frozenset[uuid.UUID], frozenset[uuid.UUID]]]
]
EntitledFeatures = Callable[[uuid.UUID, AsyncSession | None], Awaitable[frozenset[str]]]


# --- resource types: how scopes, rules and field visibility apply to one kind of record ---------

ScopePredicate = Callable[[frozenset[uuid.UUID]], ColumnElement[bool]]


@dataclass(frozen=True)
class FieldRule:
    """A field only subjects holding `permission` see in full; others get it hidden or masked."""

    permission: str
    mode: Literal["hide", "mask"] = "hide"


@dataclass(frozen=True)
class SodRule:
    """Segregation of duties: `permission` is refused on a record when `violated` holds."""

    code: str
    violated: Callable[[Subject, RecordFacts], bool]


@dataclass(frozen=True)
class ResourceType:
    """What the policy needs to know about one kind of record.

    `owner_columns` define `own` (requester, assignee, the user themselves); `site_scope` and
    `group_scope` build the `site`/`group` predicates from the subject's memberships; `fields`
    is the filter-DSL allowlist that attribute conditions are compiled against.
    """

    name: str
    fields: ResourceFields
    owner_columns: Sequence[Any] = ()
    site_scope: ScopePredicate | None = None
    group_scope: ScopePredicate | None = None
    field_rules: Mapping[str, FieldRule] = field(default_factory=lambda: MappingProxyType({}))
    sod_rules: Mapping[str, Sequence[SodRule]] = field(default_factory=lambda: MappingProxyType({}))


def requested_it_yourself(subject: Subject, record: RecordFacts) -> bool:
    """SoD example (§11.2): the requester of a record may not approve it."""
    return record.attributes.get("requester_id") in {subject.user_id, str(subject.user_id)}


# --- decisions -----------------------------------------------------------------------------------


def authorize(
    subject: Subject,
    permission: str,
    resource_type: ResourceType | None = None,
    record: RecordFacts | None = None,
) -> Decision:
    """One decision, allow or deny, with a machine reason.

    Reasons: not_entitled, no_permission, out_of_scope, condition_not_met, or the code of a
    segregation-of-duties rule.
    """
    if record is None:
        return subject.check(permission)
    decision = decide(subject, permission, record)
    if not decision or resource_type is None:
        return decision
    for rule in resource_type.sod_rules.get(permission, ()):
        if rule.violated(subject, record):
            return Decision(allowed=False, reason=rule.code)
    return decision


def require(decision: Decision, permission: str) -> None:
    """Raise 403 `permission_denied` (params: permission, reason) for a refused decision."""
    if not decision:
        raise PermissionDenied(params={"permission": permission, "reason": decision.reason})


def scope_filter(
    subject: Subject,
    permission: str,
    resource_type: ResourceType,
    *,
    now: datetime | None = None,
) -> ColumnElement[bool]:
    """WHERE predicate: rows of `resource_type` the subject may see for `permission`.

    OR over the subject's grants; each grant is (scope predicate) AND (attribute condition,
    compiled by the filter DSL compiler). No grant → FALSE: the list is empty, never unfiltered.
    Combine it with the request's own filter: `.where(scope_filter(...)).where(query.where)`.
    """
    parts: list[ColumnElement[bool]] = []
    for grant in subject.grants.get(permission, ()):
        reach = _scope_predicate(subject, grant, resource_type)
        if reach is None:
            continue
        if grant.condition is not None:
            reach = reach & compile_filter(
                dict(grant.condition),
                resource_type.fields,
                now=now or datetime.now(UTC),
                path="condition",
            )
        parts.append(reach)
    return or_(*parts) if parts else false()


def _scope_predicate(
    subject: Subject, grant: Grant, resource_type: ResourceType
) -> ColumnElement[bool] | None:
    if grant.scope == "all":
        return true()
    if grant.scope == "own":
        if not resource_type.owner_columns:
            return None
        return or_(*(column == subject.user_id for column in resource_type.owner_columns))
    builder = resource_type.site_scope if grant.scope == "site" else resource_type.group_scope
    ids = subject.site_ids if grant.scope == "site" else subject.group_ids
    if builder is None or not ids:
        return None
    return builder(ids)


async def authorize_stored(  # noqa: PLR0913, PLR0917 - the record is identified by model and id
    session: AsyncSession,
    subject: Subject,
    permission: str,
    resource_type: ResourceType,
    id_column: Any,  # noqa: ANN401 - SQLAlchemy column attribute
    record_id: uuid.UUID,
) -> Decision:
    """Decision for a stored record, evaluated by the database.

    Uses the same scope filter as lists, so a record is visible on its own exactly when it would
    appear in a list.
    """
    first = subject.check(permission)
    if not first:
        return first
    found = await session.scalar(
        select(id_column).where(
            id_column == record_id, scope_filter(subject, permission, resource_type)
        )
    )
    return first if found is not None else Decision(allowed=False, reason="out_of_scope")


MASK = "••••"


def visible(
    subject: Subject, resource_type: ResourceType, data: Mapping[str, Any]
) -> dict[str, Any]:
    """`data` with restricted fields hidden (None) or masked unless their permission is held."""
    result = dict(data)
    for name, rule in resource_type.field_rules.items():
        if name in result and not subject.holds(rule.permission) and result[name] is not None:
            result[name] = None if rule.mode == "hide" else MASK
    return result


# --- compiling subjects ---------------------------------------------------------------------------


class SubjectCache(Protocol):
    """Where compiled subjects are kept (Valkey), per tenant generation."""

    async def get(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> tuple[Subject | None, int]:
        """The cached subject if current, plus the generation to store under."""
        ...

    async def put(self, subject: Subject, generation: int) -> None:
        """Store a compiled subject."""
        ...

    async def invalidate(self, tenant_id: uuid.UUID) -> None:
        """Make every cached subject of the tenant stale."""
        ...


class NoSubjectCache:
    """No caching (no Valkey)."""

    async def get(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> tuple[Subject | None, int]:
        """Always a miss."""
        del tenant_id, user_id
        return None, 0

    async def put(self, subject: Subject, generation: int) -> None:
        """Nothing to store."""
        del subject, generation

    async def invalidate(self, tenant_id: uuid.UUID) -> None:
        """Nothing to drop."""
        del tenant_id


_VALKEY_ERRORS = (valkey.exceptions.ValkeyError, OSError)


class ValkeySubjectCache:
    """`<prefix>authz:<tenant>:<user>` = {gen, subject}; `<prefix>authz:gen:<tenant>` counter."""

    def __init__(self, client: Any, *, prefix: str, ttl_seconds: int) -> None:  # noqa: ANN401 - untyped valkey client
        self.client = client
        self.prefix = prefix
        self.ttl_seconds = ttl_seconds

    def _key(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> str:
        return f"{self.prefix}authz:{tenant_id}:{user_id}"

    def generation_key(self, tenant_id: uuid.UUID) -> str:
        """Key of the tenant's generation counter."""
        return f"{self.prefix}authz:gen:{tenant_id}"

    async def get(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> tuple[Subject | None, int]:
        """The cached subject if its generation is current; Valkey errors count as a miss."""
        try:
            raw, gen = await self.client.mget(
                self._key(tenant_id, user_id), self.generation_key(tenant_id)
            )
        except _VALKEY_ERRORS:
            log.warning("authz_cache_unavailable", operation="get")
            return None, -1
        generation = int(gen or 0)
        if raw is None:
            return None, generation
        entry = json.loads(raw)
        if entry.get("gen") != generation:
            return None, generation
        return Subject.from_dict(entry["subject"]), generation

    async def put(self, subject: Subject, generation: int) -> None:
        """Store under the generation it was compiled for."""
        if generation < 0:
            return
        entry = json.dumps({"gen": generation, "subject": subject.to_dict()})
        try:
            await self.client.set(
                self._key(subject.tenant_id, subject.user_id), entry, ex=self.ttl_seconds
            )
        except _VALKEY_ERRORS:
            log.warning("authz_cache_unavailable", operation="put")

    async def invalidate(self, tenant_id: uuid.UUID) -> None:
        """New generation: every cached subject of the tenant is stale from now on."""
        await self.client.incr(self.generation_key(tenant_id))


# Roles a user gets when their row has never been mapped (created before WP-016 or by tooling):
# from the identity's user type. Never tenant admin: that comes only from the Keycloak mapping at
# login (D-029) or an explicit assignment.
UNMAPPED_DEFAULT = MappingProxyType({"technician": TECHNICIAN, "requester": REQUESTER})


class PolicyService:
    """Compiles, caches and evaluates subjects; also the app's core Authorizer."""

    def __init__(  # noqa: PLR0913 - collaborators injected for testability
        self,
        database: Database,
        catalogue: Catalogue,
        *,
        cache: SubjectCache | None = None,
        memberships: MemberLookup,
        entitled_features: EntitledFeatures,
        resources: Mapping[str, ResourceType] | None = None,
    ) -> None:
        self.database = database
        # Resource types by permission module (`users`): attribute conditions of that module's
        # permissions are compiled against its filter fields.
        self.resources: Mapping[str, ResourceType] = MappingProxyType(dict(resources or {}))
        self.catalogue = catalogue
        self.cache: SubjectCache = cache or NoSubjectCache()
        self.memberships = memberships
        self.entitled_features = entitled_features

    async def subject(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, session: AsyncSession | None = None
    ) -> Subject:
        """The user's compiled subject (cache, else compiled; through `session` if given)."""
        cached, generation = await self.cache.get(tenant_id, user_id)
        if cached is not None:
            return cached
        if session is not None:
            subject = await self.compile(session, tenant_id, user_id)
        else:
            async with self.database.tenant_session(TenantContext(tenant_id, user_id)) as own:
                subject = await self.compile(own, tenant_id, user_id)
        await self.cache.put(subject, generation)
        return subject

    async def compile(
        self, session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> Subject:
        """Build the subject from the database (no cache)."""
        user = (
            await session.execute(
                select(User.status, User.user_type, User.roles_mapped_at).where(User.id == user_id)
            )
        ).one_or_none()
        if user is None or user.status != "active":
            return _nobody(tenant_id, user_id)
        roles = (
            await session.execute(
                select(Role.id, Role.key, Role.is_system)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user_id, Role.deleted_at.is_(None))
            )
        ).all()
        role_keys = {r.key for r in roles}
        if not roles and user.roles_mapped_at is None:
            role_keys = {UNMAPPED_DEFAULT[user.user_type]}
        grants: list[tuple[str, Grant]] = []
        for key in role_keys & set(SYSTEM_ROLES):
            grants += [
                (permission, Grant(scope))
                for permission, scope in self.catalogue.system_grants(key)
            ]
        custom = [r.id for r in roles if not r.is_system]
        if custom:
            rows = await session.execute(
                select(
                    RolePermission.permission, RolePermission.scope, RolePermission.condition
                ).where(RolePermission.role_id.in_(custom))
            )
            grants += [(row.permission, Grant(row.scope, row.condition)) for row in rows]
        site_ids, group_ids = await self.memberships(session, user_id)
        return compile_subject(
            tenant_id=tenant_id,
            user_id=user_id,
            role_keys=role_keys,
            grants=grants,
            catalogue=self.catalogue,
            entitled_features=await self.entitled_features(tenant_id, session),
            site_ids=site_ids,
            group_ids=group_ids,
            is_tenant_admin=TENANT_ADMIN in role_keys,
        )

    async def invalidate(self, tenant_id: uuid.UUID) -> None:
        """Make every cached subject of the tenant stale."""
        await self.cache.invalidate(tenant_id)

    async def holders(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        permission: str,
        *,
        search: str | None = None,
        limit: int = 20,
    ) -> list[tuple[uuid.UUID, str]]:
        """Active users of the tenant who hold `permission` (any scope): (id, display name).

        For pickers such as "owner" (only people who may own the record). SQL narrows to users
        with a granting role; each is then confirmed with their compiled subject, so licence
        entitlement and unmapped defaults apply exactly as on their own requests.
        """
        granting_system = [
            key
            for key in SYSTEM_ROLES
            if any(p == permission for p, _ in self.catalogue.system_grants(key))
        ]
        granting_roles = select(Role.id).where(
            Role.deleted_at.is_(None),
            or_(
                and_(Role.is_system.is_(True), Role.key.in_(granting_system)),
                and_(
                    Role.is_system.is_(False),
                    Role.id.in_(
                        select(RolePermission.role_id).where(
                            RolePermission.permission == permission
                        )
                    ),
                ),
            ),
        )
        live_role = (
            select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id == User.id, Role.deleted_at.is_(None))
        )
        unmapped_types = [t for t, key in UNMAPPED_DEFAULT.items() if key in granting_system]
        query = select(User.id, User.display_name).where(
            User.status == "active",
            or_(
                User.id.in_(select(UserRole.user_id).where(UserRole.role_id.in_(granting_roles))),
                and_(
                    User.roles_mapped_at.is_(None),
                    User.user_type.in_(unmapped_types),
                    ~exists(live_role),
                ),
            ),
        )
        if search:
            # LIKE wildcards typed by the user match themselves only.
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            query = query.where(
                or_(
                    User.display_name.ilike(pattern, escape="\\"),
                    User.email.ilike(pattern, escape="\\"),
                )
            )
        rows = (
            await session.execute(query.order_by(User.display_name, User.id).limit(limit))
        ).all()
        return [
            (row.id, row.display_name)
            for row in rows
            if (await self.subject(tenant_id, row.id, session)).holds(permission)
        ]

    async def user_holds(
        self, session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, permission: str
    ) -> bool:
        """Whether another user of the tenant holds `permission` (e.g. a proposed owner)."""
        return (await self.subject(tenant_id, user_id, session)).holds(permission)

    # --- core Authorizer protocol ----------------------------------------------------------------

    async def subject_for(self, request: Request, context: TenantContext) -> Subject:
        """Once per request (memoised on request.state)."""
        memo: Subject | None = getattr(request.state, SUBJECT_STATE, None)
        if memo is not None and memo.tenant_id == context.tenant_id:
            return memo
        subject = (
            _nobody(context.tenant_id, uuid.UUID(int=0))
            if context.user_id is None
            else await self.subject(
                context.tenant_id,
                context.user_id,
                # Reuse the request's connection when it already holds one (see database.py).
                getattr(request.state, REQUEST_SESSION_STATE, None),
            )
        )
        setattr(request.state, SUBJECT_STATE, subject)
        return subject

    def require(self, subject: Subject, permissions: Sequence[str]) -> None:
        """403 `permission_denied` unless one of `permissions` is held."""
        if any(subject.holds(p) for p in permissions):
            return
        reason = (
            "not_entitled"
            if all(p in subject.not_entitled for p in permissions)
            else "no_permission"
        )
        raise PermissionDenied(params={"permission": permissions[0], "reason": reason})

    async def allows(self, context: TenantContext, permission: str) -> bool:
        """For other modules (licensing's admin notices)."""
        if context.user_id is None:
            return False
        return (await self.subject(context.tenant_id, context.user_id)).holds(permission)


def _nobody(tenant_id: uuid.UUID, user_id: uuid.UUID) -> Subject:
    return Subject(
        tenant_id=tenant_id,
        user_id=user_id,
        role_keys=frozenset(),
        is_tenant_admin=False,
        grants=MappingProxyType({}),
    )
