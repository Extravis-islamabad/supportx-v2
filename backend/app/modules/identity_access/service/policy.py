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
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Literal, Protocol

import valkey.exceptions
from fastapi import Request
from sqlalchemy import ColumnElement, Select, and_, exists, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import Scope
from app.core.database import REQUEST_SESSION_STATE, Database
from app.core.errors import PermissionDenied
from app.core.logging import get_logger
from app.core.scopes import scope_of
from app.core.tenancy import NO_SIGN_IN, AccessSource, AccessSourceKind, TenantContext
from app.modules.identity_access.domain import api_keys, support_access
from app.modules.identity_access.domain import field_access as field_rules
from app.modules.identity_access.domain import resource_access as resource_rules
from app.modules.identity_access.domain import support_grants as support_rules
from app.modules.identity_access.domain.group_mappings import SourceKind
from app.modules.identity_access.domain.identity import UserType
from app.modules.identity_access.domain.permissions import (
    DEPARTMENT_VIEWER,
    REQUESTER,
    SCOPE_RANK,
    SYSTEM_ROLES,
    TECHNICIAN,
    TENANT_ADMIN,
    Catalogue,
)
from app.modules.identity_access.domain.policy import (
    AccessRule,
    Decision,
    Grant,
    RecordFacts,
    Subject,
    compile_subject,
    decide,
    meets,
)
from app.modules.identity_access.domain.support_grants import SUPPORT_USER_TYPE
from app.modules.identity_access.infra.models import (
    AccessSource as AccessSourceRow,
)
from app.modules.identity_access.infra.models import (
    GroupRole,
    IdpGroupMapping,
    Role,
    RoleFieldAccess,
    RolePermission,
    SsoProvider,
    SupportGrant,
    User,
    UserRole,
)
from app.modules.identity_access.service.access_settings import tenant_technician_scope
from app.modules.identity_access.service.masking import shown_name
from app.modules.identity_access.service.person_search import person_match
from app.modules.identity_access.service.resource_access import resource_access_of
from app.modules.identity_access.service.resource_access import (
    rules_predicate as resource_rules_predicate,
)
from app.modules.organization import active_groups, heads_department, users_in_groups
from app.shared.api.filters import ResourceFields, compile_filter
from app.shared.clock import system_clock

log = get_logger(__name__)


SUBJECT_STATE = "authz_subject"


# --- access managed from outside SupportX, by sign-in (WP-057 S5c-1b; D-188) ------------------


@dataclass(frozen=True)
class Admitted:
    """The managed roles and group memberships a sign-in admits (hand-made access always counts)."""

    roles: frozenset[uuid.UUID]
    groups: frozenset[uuid.UUID]


NOTHING_MANAGED = Admitted(frozenset(), frozenset())


def _own_roles(user_id: uuid.UUID, admitted: Admitted | None) -> Select[uuid.UUID]:
    """The person's own role IDs: hand-made ones, and the managed ones the sign-in admits."""
    own = select(UserRole.role_id).where(UserRole.user_id == user_id)
    if admitted is None:
        return own
    return own.where(or_(UserRole.managed.is_(False), UserRole.role_id.in_(admitted.roles)))


def source_tag(source: AccessSource) -> str:
    """The compile's cache tag: one per source that compiles differently.

    Password and no sign-in compile the same (directory-managed access only), so they share one.
    An SSO session's tag is its alias: unique within the tenant, which the key names too.
    """
    match source.kind:
        case AccessSourceKind.SSO:
            return f"sso:{source.alias}"
        case AccessSourceKind.BREAK_GLASS:
            return "bg"
        case AccessSourceKind.ANY:
            return "any"
        case _:
            return "pw"


async def admitted_managed(
    session: AsyncSession, user_id: uuid.UUID, source: AccessSource
) -> Admitted | None:
    """What of the person's managed access `source` admits; None: all of it (ANY only).

    - break-glass: none (hand-made access only);
    - password, or no sign-in: what a directory mapping gives (the coordinator's ruling on (b));
    - single sign-on: that too, and what a mapping of this tenant's provider `alias` gives. An
      alias that is not this tenant's provider (a tenant switch) admits no SSO access.
    A managed row counts when any one of its sources is admitted.
    """
    if source.kind is AccessSourceKind.ANY:
        return None
    if source.kind is AccessSourceKind.BREAK_GLASS:
        return NOTHING_MANAGED
    admits: list[ColumnElement[bool]] = [IdpGroupMapping.source_kind == SourceKind.DIRECTORY.value]
    if source.kind is AccessSourceKind.SSO and source.alias:
        provider = await session.scalar(
            select(SsoProvider.id).where(
                SsoProvider.alias == source.alias, SsoProvider.deleted_at.is_(None)
            )
        )
        if provider is not None:
            admits.append(
                and_(
                    IdpGroupMapping.source_kind == SourceKind.SSO.value,
                    IdpGroupMapping.source_id == provider,
                )
            )
    rows = (
        await session.execute(
            select(AccessSourceRow.target_kind, AccessSourceRow.target_id)
            .join(IdpGroupMapping, IdpGroupMapping.id == AccessSourceRow.mapping_id)
            .where(
                AccessSourceRow.user_id == user_id,
                IdpGroupMapping.deleted_at.is_(None),
                or_(*admits),
            )
        )
    ).all()
    return Admitted(
        roles=frozenset(r.target_id for r in rows if r.target_kind == "role"),
        groups=frozenset(r.target_id for r in rows if r.target_kind == "group"),
    )


class MemberLookup(Protocol):
    """A person's (site IDs, group IDs); `admitted_managed` filters managed group memberships."""

    def __call__(  # noqa: D102 - the protocol's call
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        /,
        *,
        admitted_managed: frozenset[uuid.UUID] | None = None,
    ) -> Awaitable[tuple[frozenset[uuid.UUID], frozenset[uuid.UUID]]]: ...


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

    `group_scope_extra` widens the `group` scope with records a group member must also reach,
    built from the whole subject. Work items use it for the unassigned queue of the member's
    sites (D-052): a technician at group scope sees their groups' records and the new,
    unassigned records of their sites, so nobody's new ticket is invisible to everyone.

    `shared_scope` adds records shared with the subject one by one, for the permissions whose
    action is in `shared_actions` only, and only when the subject holds the permission at some
    scope. Work items use it for followers who kept access after a hand-over (D-068): they may
    view and add private notes, never edit, assign or change the status (REQ-INC-151 AC2).
    Grant conditions do not narrow a shared record: sharing is an explicit, per-record grant.
    """

    name: str
    fields: ResourceFields
    owner_columns: Sequence[Any] = ()
    site_scope: ScopePredicate | None = None
    group_scope: ScopePredicate | None = None
    group_scope_extra: Callable[[Subject], ColumnElement[bool] | None] | None = None
    # More records that are the subject's own (WP-058a: records where they hold a named role,
    # in person or through a group). OR'ed into the `own` scope only; None: no extra records.
    owner_extra: Callable[[Subject], ColumnElement[bool] | None] | None = None
    shared_scope: Callable[[Subject], ColumnElement[bool]] | None = None
    shared_actions: frozenset[str] = frozenset()
    field_rules: Mapping[str, FieldRule] = field(default_factory=lambda: MappingProxyType({}))
    sod_rules: Mapping[str, Sequence[SodRule]] = field(default_factory=lambda: MappingProxyType({}))
    # Fine-grained access (ADR-053): the resource whose rules narrow this type (asset, ci);
    # None: never narrowed. Applied inside `scope_filter`, so every path using it is narrowed.
    narrowed_as: str | None = None


def requested_it_yourself(subject: Subject, record: RecordFacts) -> bool:
    """SoD example (§11.2): the requester of a record may not approve it."""
    return record.attributes.get("requester_id") in {subject.user_id, str(subject.user_id)}


# --- decisions -----------------------------------------------------------------------------------


def authorize(
    subject: Subject,
    permission: str,
    resource_type: ResourceType | None = None,
    record: RecordFacts | None = None,
    *,
    rule: AccessRule | None = None,
) -> Decision:
    """One decision, allow or deny, with a machine reason.

    Reasons: not_entitled, no_permission, out_of_scope, condition_not_met, the code of a
    segregation-of-duties rule, or stage_access (`rule`, applied after everything else).
    """
    if record is None:
        decision = subject.check(permission)
        return meets(subject, rule) if decision else decision
    decision = decide(subject, permission, record)
    if not decision or resource_type is None:
        return meets(subject, rule) if decision else decision
    for sod in resource_type.sod_rules.get(permission, ()):
        if sod.violated(subject, record):
            return Decision(allowed=False, reason=sod.code)
    return meets(subject, rule)


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

    Fine-grained access (ADR-053 §2): when the person is narrowed for the type's resource, each
    of their roles shows its own scope narrowed by its own rules, and the person sees the union
    of those; one role's rules never combine with another role's scope.
    """
    at = now or datetime.now(UTC)
    reaches = (
        resource_rules.narrowing(subject.resource_access, resource_type.narrowed_as)
        if resource_type.narrowed_as is not None
        else None
    )
    for hook in _SCOPE_HOOKS:
        hook(resource_type.name, permission)
    held = _grant_parts(subject, subject.grants.get(permission, ()), resource_type, at)
    if reaches is None or not held:
        # Not narrowed, or the subject itself lacks the permission: an API key's scopes trim
        # only `subject.grants` (`for_key`), never the roles' reaches below (lane C, #560).
        parts = held
    else:
        parts = []
        # Narrow-only (ADR-053 §2): never wider than the subject's own grants, whatever trimmed
        # them, so each role's narrowed reach is also held to those.
        own_reach = or_(*held)
        for reach in reaches:
            own = [Grant(scope, condition) for scope, condition in reach.grants.get(permission, ())]
            role_parts = _grant_parts(subject, own, resource_type, at)
            if not role_parts:
                continue
            role_reach = and_(or_(*role_parts), own_reach)
            if reach.rules is not None:
                assert resource_type.narrowed_as is not None  # noqa: S101 - reaches imply it
                role_reach = and_(
                    role_reach, resource_rules_predicate(resource_type.narrowed_as, reach.rules)
                )
            parts.append(role_reach)
    if (
        resource_type.shared_scope is not None
        and permission.rsplit(".", 1)[-1] in resource_type.shared_actions
        and subject.grants.get(permission)
    ):
        parts.append(resource_type.shared_scope(subject))
    return or_(*parts) if parts else false()


def _grant_parts(
    subject: Subject, grants: Sequence[Grant], resource_type: ResourceType, now: datetime
) -> list[ColumnElement[bool]]:
    """Each grant's scope predicate AND its attribute condition (grants with no reach skipped)."""
    parts: list[ColumnElement[bool]] = []
    for grant in grants:
        reach = _scope_predicate(subject, grant, resource_type)
        if reach is None:
            continue
        if grant.condition is not None:
            reach = reach & compile_filter(
                dict(grant.condition), resource_type.fields, now=now, path="condition"
            )
        parts.append(reach)
    return parts


# Test-only observers of `scope_filter` (the route-walk guard, ADR-053 / lane C 6): each gets the
# resource type's name and the permission. Empty in the running app.
ScopeHook = Callable[[str, str], None]
_SCOPE_HOOKS: list[ScopeHook] = []


def add_scope_hook(hook: ScopeHook) -> None:
    """Observe `scope_filter` calls (tests)."""
    _SCOPE_HOOKS.append(hook)


def remove_scope_hook(hook: ScopeHook) -> None:
    """Stop observing (tests)."""
    if hook in _SCOPE_HOOKS:
        _SCOPE_HOOKS.remove(hook)


def _scope_predicate(
    subject: Subject, grant: Grant, resource_type: ResourceType
) -> ColumnElement[bool] | None:
    if grant.scope == "all":
        return true()
    if grant.scope == "own":
        owned = [column == subject.user_id for column in resource_type.owner_columns]
        extra = resource_type.owner_extra(subject) if resource_type.owner_extra else None
        if extra is not None:
            owned.append(extra)
        return or_(*owned) if owned else None
    builder = resource_type.site_scope if grant.scope == "site" else resource_type.group_scope
    ids = subject.site_ids if grant.scope == "site" else subject.group_ids
    parts = [builder(ids)] if builder is not None and ids else []
    if grant.scope == "group" and resource_type.group_scope_extra is not None:
        extra = resource_type.group_scope_extra(subject)
        if extra is not None:
            parts.append(extra)
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else or_(*parts)


def unrestricted(subject: Subject, permission: str) -> bool:
    """Whether the subject holds `permission` over every record, so `scope_filter` is TRUE.

    That is a grant of scope "all" with no attribute condition.
    For a caller that just saved a record and must confirm it is within reach (assets,
    `_within_scope`): with this true the confirming query can only say yes. Never a stand-in for
    an existence check of a record someone named: `authorize_stored` still does that.

    Never true for a person narrowed by fine-grained access (ADR-053): their rules narrow even
    a scope of "all", so a saved record could fall outside them (a create at a site the rule
    leaves out).
    """
    if subject.resource_access:
        return False
    return any(
        grant.scope == "all" and grant.condition is None
        for grant in subject.grants.get(permission, ())
    )


async def authorize_stored(  # noqa: PLR0913, PLR0917 - the record is identified by model and id
    session: AsyncSession,
    subject: Subject,
    permission: str,
    resource_type: ResourceType,
    id_column: Any,  # noqa: ANN401 - SQLAlchemy column attribute
    record_id: uuid.UUID,
    *,
    rule: AccessRule | None = None,
) -> Decision:
    """Decision for a stored record, evaluated by the database.

    Uses the same scope filter as lists, so a record is visible on its own exactly when it would
    appear in a list. `rule` (stage access) narrows an allowed decision only, after the scope.
    """
    first = subject.check(permission)
    if not first:
        return first
    found = await session.scalar(
        select(id_column).where(
            id_column == record_id, scope_filter(subject, permission, resource_type)
        )
    )
    if found is None:
        return Decision(allowed=False, reason="out_of_scope")
    return meets(subject, rule)


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

    async def get(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, *, tag: str
    ) -> tuple[Subject | None, int]:
        """The cached subject if current, plus the generation to store under."""
        ...

    async def put(self, subject: Subject, generation: int, *, tag: str) -> None:
        """Store a compiled subject (`tag`: its access source, see `source_tag`)."""
        ...

    async def invalidate(self, tenant_id: uuid.UUID) -> None:
        """Make every cached subject of the tenant stale."""
        ...


class NoSubjectCache:
    """No caching (no Valkey)."""

    async def get(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, *, tag: str
    ) -> tuple[Subject | None, int]:
        """Always a miss."""
        del tenant_id, user_id, tag
        return None, 0

    async def put(self, subject: Subject, generation: int, *, tag: str) -> None:
        """Nothing to store."""
        del subject, generation, tag

    async def invalidate(self, tenant_id: uuid.UUID) -> None:
        """Nothing to drop."""
        del tenant_id


_VALKEY_ERRORS = (valkey.exceptions.ValkeyError, OSError)


class ValkeySubjectCache:
    """`<prefix>authz:<tenant>:<user>:<source>` = {gen, subject}; `<prefix>authz:gen:<tenant>`.

    One compile per access source (WP-057 S5c-1b, D-188): a password and an SSO session of the
    same person never share one. The generation stays per tenant, so every invalidation still
    reaches all of them.
    """

    def __init__(self, client: Any, *, prefix: str, ttl_seconds: int) -> None:  # noqa: ANN401 - untyped valkey client
        self.client = client
        self.prefix = prefix
        self.ttl_seconds = ttl_seconds

    def _key(self, tenant_id: uuid.UUID, user_id: uuid.UUID, tag: str) -> str:
        return f"{self.prefix}authz:{tenant_id}:{user_id}:{tag}"

    def generation_key(self, tenant_id: uuid.UUID) -> str:
        """Key of the tenant's generation counter."""
        return f"{self.prefix}authz:gen:{tenant_id}"

    async def get(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, *, tag: str
    ) -> tuple[Subject | None, int]:
        """The cached subject if its generation is current; Valkey errors count as a miss."""
        try:
            raw, gen = await self.client.mget(
                self._key(tenant_id, user_id, tag), self.generation_key(tenant_id)
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
        try:
            return Subject.from_dict(entry["subject"]), generation
        except (KeyError, TypeError, ValueError):
            # A form this code can't read (an older release's): compiled again, never guessed.
            return None, generation

    async def put(self, subject: Subject, generation: int, *, tag: str) -> None:
        """Store under the generation it was compiled for."""
        if generation < 0:
            return
        entry = json.dumps({"gen": generation, "subject": subject.to_dict()})
        try:
            await self.client.set(
                self._key(subject.tenant_id, subject.user_id, tag), entry, ex=self.ttl_seconds
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


async def field_access_of(
    session: AsyncSession, role_ids: Sequence[uuid.UUID]
) -> field_rules.Compiled:
    """The restricted fields of someone holding exactly these roles (ADR-047 §2, §3).

    Clearest wins: a field is restricted only when every one of the roles has a live rule for
    it. Applied whatever the licence says, so a lapse never shows what a rule hides (§13).
    """
    if not role_ids:
        return field_rules.EMPTY
    rows = await session.execute(
        select(RoleFieldAccess.record_type, RoleFieldAccess.field, RoleFieldAccess.mode).where(
            RoleFieldAccess.role_id.in_(role_ids), RoleFieldAccess.deleted_at.is_(None)
        )
    )
    return field_rules.compile_access(
        len(set(role_ids)), [(r.record_type, r.field, r.mode) for r in rows]
    )


class PolicyService:
    """Compiles, caches and evaluates subjects; also the app's core Authorizer."""

    def __init__(  # noqa: PLR0913 - collaborators injected for testability
        self,
        database: Database | None,
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
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        session: AsyncSession | None = None,
        *,
        source: AccessSource = NO_SIGN_IN,
    ) -> Subject:
        """The user's compiled subject (cache, else compiled; through `session` if given).

        `source` (WP-057 S5c-1b, D-188): how the person signed in, which decides the access
        managed from outside SupportX that counts. Without one, the strict side (no sign-in).
        """
        tag = source_tag(source)
        cached, generation = await self.cache.get(tenant_id, user_id, tag=tag)
        if cached is not None:
            return cached
        if session is not None:
            subject = await self.compile(session, tenant_id, user_id, source=source)
        elif self.database is None:
            msg = "a PolicyService without a database compiles only through a given session"
            raise RuntimeError(msg)
        else:
            async with self.database.tenant_session(TenantContext(tenant_id, user_id)) as own:
                subject = await self.compile(own, tenant_id, user_id, source=source)
        await self.cache.put(subject, generation, tag=tag)
        return subject

    async def compile(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        source: AccessSource = NO_SIGN_IN,
    ) -> Subject:
        """Build the subject from the database (no cache), with the access `source` admits."""
        user = (
            await session.execute(
                select(User.status, User.user_type, User.roles_mapped_at).where(User.id == user_id)
            )
        ).one_or_none()
        if user is None or user.status != "active":
            return _nobody(tenant_id, user_id)
        if user.user_type == SUPPORT_USER_TYPE:
            # A vendor support account's permissions are its grant's only (D-173, lane B): never
            # a role, never a group's, never a default.
            return await self._support_subject(session, tenant_id, user_id)
        # The managed access this sign-in admits (D-188); None: all of it ("could act" only).
        admitted = await admitted_managed(session, user_id, source)
        site_ids, group_ids = await self.memberships(
            session, user_id, admitted_managed=None if admitted is None else admitted.groups
        )
        # Roles of one's own and those of the active groups one belongs to (WP-042): a disabled
        # or deleted group grants nothing, at once.
        carrying = await active_groups(session, group_ids)
        own_roles = _own_roles(user_id, admitted)
        roles = (
            await session.execute(
                select(Role.id, Role.key, Role.is_system)
                .where(
                    Role.deleted_at.is_(None),
                    or_(
                        Role.id.in_(own_roles),
                        Role.id.in_(
                            select(GroupRole.role_id).where(GroupRole.group_id.in_(carrying))
                        ),
                    ),
                )
                .distinct()
            )
        ).all()
        role_keys = {r.key for r in roles}
        role_ids = [r.id for r in roles]
        # Each role by ID with its key, for fine-grained access (ADR-053): which roles count.
        held: dict[uuid.UUID, str] = {r.id: r.key for r in roles}
        if not roles and user.roles_mapped_at is None:
            # A service identity has only the roles given to it (none: it may do nothing).
            default = UNMAPPED_DEFAULT.get(user.user_type)
            role_keys = {default} if default is not None else set()
            defaults = (
                await session.execute(
                    select(Role.id, Role.key).where(
                        Role.key.in_(role_keys), Role.deleted_at.is_(None)
                    )
                )
            ).all()
            role_ids = [r.id for r in defaults]
            held = {r.id: r.key for r in defaults}
        grants: list[tuple[str, Grant]] = []
        technician_scope = await tenant_technician_scope(session)
        # Each role's own grants (ADR-053 §2: a role's rules narrow that role's scope only).
        role_grants: dict[uuid.UUID, list[tuple[str, Scope, Any]]] = {role: [] for role in held}
        for key in role_keys & set(SYSTEM_ROLES):
            system = self.catalogue.system_grants(key, technician_scope=technician_scope)
            grants += [(permission, Grant(scope)) for permission, scope in system]
            for role, role_key in held.items():
                if role_key == key:
                    role_grants[role] += [(permission, scope, None) for permission, scope in system]
        # A department's head views its requests in the portal by default (D-152), computed
        # here, so a new head has it at once and a replaced one loses it (the department's save
        # makes compiled permissions stale).
        if DEPARTMENT_VIEWER not in role_keys and await heads_department(session, user_id):
            grants += [
                (permission, Grant(scope))
                for permission, scope in self.catalogue.system_grants(DEPARTMENT_VIEWER)
            ]
        custom = [r.id for r in roles if not r.is_system]
        if custom:
            rows = await session.execute(
                select(
                    RolePermission.permission, RolePermission.scope, RolePermission.condition
                ).where(RolePermission.role_id.in_(custom))
            )
            grants += [(row.permission, Grant(row.scope, row.condition)) for row in rows]
            per_role = await session.execute(
                select(
                    RolePermission.role_id,
                    RolePermission.permission,
                    RolePermission.scope,
                    RolePermission.condition,
                ).where(RolePermission.role_id.in_(custom))
            )
            for row in per_role:
                role_grants.setdefault(row.role_id, []).append(
                    (row.permission, row.scope, row.condition)
                )
        features = await self.entitled_features(tenant_id, session)
        return compile_subject(
            tenant_id=tenant_id,
            user_id=user_id,
            role_keys=role_keys,
            grants=grants,
            catalogue=self.catalogue,
            entitled_features=features,
            site_ids=site_ids,
            group_ids=group_ids,
            is_tenant_admin=TENANT_ADMIN in role_keys,
            fields=await field_access_of(session, role_ids),
            resources=await resource_access_of(
                session, self._entitled_role_grants(role_grants, features)
            ),
            person=user.user_type != UserType.SERVICE.value,
        )

    def _entitled_role_grants(
        self,
        role_grants: Mapping[uuid.UUID, list[tuple[str, Scope, Any]]],
        features: frozenset[str],
    ) -> dict[uuid.UUID, resource_rules.RoleGrants]:
        """Each role's grants as the merged subject keeps them: known, allowed scopes, licensed."""
        result: dict[uuid.UUID, resource_rules.RoleGrants] = {}
        for role, grants in role_grants.items():
            kept: dict[str, list[tuple[Scope, Mapping[str, Any] | None]]] = {}
            for permission, scope, condition in grants:
                spec = self.catalogue.get(permission)
                if spec is None or scope not in spec.scopes:
                    continue
                if spec.feature is not None and spec.feature not in features:
                    continue
                kept.setdefault(permission, []).append((scope, condition))
            result[role] = MappingProxyType({p: tuple(g) for p, g in kept.items()})
        return result

    async def _support_subject(
        self, session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> Subject:
        """A support account: its open grant's level, from the allow-list only (WP-057 S4c-2).

        No grant open and in time: nothing. Otherwise each permission the level allows, at the
        broadest scope it has (the account belongs to no site or group: lane B (8)), through
        the licence as for everyone. Never a tenant admin, and never a `never` key, whatever
        went wrong upstream (checked here, lane B (1)).
        """
        grant = (
            await session.execute(
                select(
                    SupportGrant.id,
                    SupportGrant.access,
                    SupportGrant.unmask_personal,
                    SupportGrant.mask_names,
                    SupportGrant.state,
                    SupportGrant.starts_at,
                    SupportGrant.ends_at,
                )
                .where(SupportGrant.support_user_id == user_id)
                .order_by(SupportGrant.created_at.desc())
                .limit(1)
            )
        ).one_or_none()
        now = system_clock.now()
        if (
            grant is None
            or not support_rules.is_open(grant.state)
            or not (grant.starts_at <= now < grant.ends_at)
        ):
            return _nobody(tenant_id, user_id)
        grants = [
            (key, Grant(_broadest(spec.scopes)))
            for key in support_access.permissions_for(grant.access)
            if (spec := self.catalogue.get(key)) is not None
        ]
        subject = compile_subject(
            tenant_id=tenant_id,
            user_id=user_id,
            role_keys=frozenset(),
            grants=grants,
            catalogue=self.catalogue,
            entitled_features=await self.entitled_features(tenant_id, session),
            is_tenant_admin=False,
            fields=await _support_fields(session, unmask_personal=grant.unmask_personal),
        )
        given = [
            k
            for k in subject.grants
            if not support_access.allowed(grant.access, support_access.SUPPORT_ACCESS.get(k))
        ]
        if given or subject.is_tenant_admin:
            msg = f"a support subject holds what its level never allows: {given}"
            raise AssertionError(msg)
        # D-180: e-mail and phone are always withheld from support; names only on the grant's
        # tick (0188). unmask_personal now governs the other personal fields alone (above).
        return replace(
            subject, support_grant_id=grant.id, mask_contacts=True, mask_names=grant.mask_names
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
        # People holding a granting role through a group (WP-042); each is confirmed below with
        # their compiled subject, which drops disabled groups.
        carrying = frozenset(
            await session.scalars(
                select(GroupRole.group_id).where(GroupRole.role_id.in_(granting_roles))
            )
        )
        unmapped_types = [t for t, key in UNMAPPED_DEFAULT.items() if key in granting_system]
        query = select(User.id, User.display_name).where(
            User.status == "active",
            # Connectors' service identities are never offered or told anything (REQ-INT-012).
            User.user_type != UserType.SERVICE.value,
            or_(
                User.id.in_(select(UserRole.user_id).where(UserRole.role_id.in_(granting_roles))),
                User.id.in_(users_in_groups(carrying)),
                and_(
                    User.roles_mapped_at.is_(None),
                    User.user_type.in_(unmapped_types),
                    ~exists(live_role),
                ),
            ),
        )
        order: list[Any] = [User.display_name, User.id]
        if search:
            # Names only for support, refused when names are masked (D-180, person_search).
            found = await person_match(session, search)
            if found is None:
                return []  # typed, but nothing searchable (only punctuation): nobody matches
            # Name or email words, word forms in Arabic and Urdu, and typos (WP-027).
            query = query.where(found.predicate)
            order.insert(0, found.rank.desc())
        rows = (await session.execute(query.order_by(*order).limit(limit))).all()
        # The UI labels an empty name (D-173, D-180); an address used as a name is withheld too.
        return [
            (row.id, shown_name(session, row.display_name))
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
        memo: tuple[AccessSource, Subject] | None = getattr(request.state, SUBJECT_STATE, None)
        if (
            memo is not None
            and memo[1].tenant_id == context.tenant_id
            and memo[0] == context.access_source
        ):
            return memo[1]
        subject = (
            _nobody(context.tenant_id, uuid.UUID(int=0))
            if context.user_id is None
            else await self.subject(
                context.tenant_id,
                context.user_id,
                # Reuse the request's connection when it already holds one (see database.py).
                getattr(request.state, REQUEST_SESSION_STATE, None),
                source=context.access_source,
            )
        )
        if context.api_scopes is not None:
            # An API key: its owner's live grants, narrowed to what the key's scopes cover. Every
            # check (routes and services) then sees both rules at once (REQ-INT-021, D-128).
            subject = for_key(subject, context.api_scopes)
        # A request is always a person's write as field rules see it (ADR-047 §8), a service
        # identity's API key included: only in-process jobs under their own identity are system
        # writes (lane B's #503 review).
        subject = replace(subject, person=True)
        setattr(request.state, SUBJECT_STATE, (context.access_source, subject))
        return subject

    def require(self, subject: Subject, permissions: Sequence[str]) -> None:
        """403 `permission_denied` unless one of `permissions` is held."""
        if any(subject.holds(p) for p in permissions):
            return
        beyond: frozenset[str] = subject.extra.get(OUT_OF_SCOPE, frozenset())
        lacking = next((p for p in permissions if p in beyond), None)
        if lacking is not None:
            # The owner may, the key may not: name a scope the key lacks (REQ-INT-021 AC1).
            raise PermissionDenied(code="api_scope_missing", params={"scope": scope_of(lacking)})
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


OUT_OF_SCOPE = "api_out_of_scope"


def for_key(subject: Subject, scopes: frozenset[str]) -> Subject:
    """The subject an API key acts as: the owner's grants its scopes cover, nothing more."""
    kept = {k: g for k, g in subject.grants.items() if api_keys.covered(k, scopes)}
    beyond = frozenset(k for k in subject.grants if k not in kept)
    return replace(
        subject,
        grants=MappingProxyType(kept),
        extra=MappingProxyType({**subject.extra, OUT_OF_SCOPE: beyond}),
    )


async def _support_fields(session: AsyncSession, *, unmask_personal: bool) -> field_rules.Compiled:
    """Every record type's sensitive fields hidden, personal ones masked (WP-057 S4c-2)."""
    # Imported here: the field-access service builds on this module's defaults.
    from app.modules.identity_access.service import field_access  # noqa: PLC0415

    marks = {
        record_type: [
            (f.key, f.personal_data, f.sensitive)
            for f in await field_access.catalogue(session, record_type)
        ]
        for record_type in field_access.record_types()
    }
    return support_access.field_access(marks, unmask_personal=unmask_personal)


def _broadest(scopes: Sequence[Scope]) -> Scope:
    """The widest scope a permission allows (`all` wherever it has one)."""
    return max(scopes, key=SCOPE_RANK.__getitem__)


def _nobody(tenant_id: uuid.UUID, user_id: uuid.UUID) -> Subject:
    return Subject(
        tenant_id=tenant_id,
        user_id=user_id,
        role_keys=frozenset(),
        is_tenant_admin=False,
        grants=MappingProxyType({}),
    )
