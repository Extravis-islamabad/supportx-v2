"""Permission catalogue, scopes and system roles: pure Python (architecture.md §11.2; WP-016).

Permissions are `module.action` (`users.view`, `changes.approve`). Modules declare theirs in
their ModuleSpec (`permissions=`); the ITSM permissions of modules not built yet are reserved
here so roles can be designed now and later modules only move their entries into their own
ModuleSpec. Each permission names its licence feature: a tenant without the feature never holds
the permission, whatever its roles say.

Scopes, broadest first: `all` (every record), `site` (records of the user's sites), `group`
(records of the user's support groups), `own` (records the user owns: requester, assignee,
themselves). Only `all` covers the others: a user's own records can lie outside their sites and
groups, so `site`, `group` and `own` reach different, overlapping sets.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.core.authorization import ALL_SCOPES, PermissionSpec, Scope

PERMISSION_KEY = re.compile(r"^[a-z][a-z_]*\.[a-z][a-z_]*$")
SCOPE_RANK: Mapping[Scope, int] = MappingProxyType({"all": 3, "site": 2, "group": 2, "own": 1})

TENANT_ADMIN = "tenant_admin"
TECHNICIAN = "technician"
REQUESTER = "requester"
# Reads, searches, exports and verifies the audit log and reads access settings; changes nothing
# (separation of duties, WP-018, D-076). Its audit permissions come from the audit module.
AUDITOR = "auditor"
# Sign-in, MFA, sessions and the people they apply to; no record access (Appendix A, D-089 D7).
SECURITY_ADMIN = "security_admin"
# Writes, reviews and publishes knowledge (D-108, WP-033 session 2). Its knowledge permissions
# come from the knowledge module (PermissionSpec.defaults); identity only gives the role its key.
KNOWLEDGE_MANAGER = "knowledge_manager"
SYSTEM_ROLES = (TENANT_ADMIN, TECHNICIAN, REQUESTER, AUDITOR, SECURITY_ADMIN, KNOWLEDGE_MANAGER)

ALL = ALL_SCOPES
OWN_ONLY: tuple[Scope, ...] = ("own",)
NOT_OWN: tuple[Scope, ...] = ("all", "site", "group")

# identity_access's own permissions (registered through its ModuleSpec).
IDENTITY_PERMISSIONS: tuple[PermissionSpec, ...] = (
    PermissionSpec("users.view", scopes=ALL),
    PermissionSpec("users.manage"),
    PermissionSpec("roles.view"),
    PermissionSpec("roles.manage"),
    PermissionSpec("profile.edit", scopes=OWN_ONLY),
    # Sign-in and security settings: SSO, sessions, people creation (WP-039, D-089 D7).
    PermissionSpec("identity.manage"),
)

# Reserved for the ITSM modules of Stage 1+ (each moves its entries into its ModuleSpec).
RESERVED_PERMISSIONS: tuple[PermissionSpec, ...] = (
    PermissionSpec("requests.view", "incident", ALL),
    PermissionSpec("requests.create", "incident"),
    PermissionSpec("requests.edit", "incident", ALL),
    PermissionSpec("requests.assign", "incident", NOT_OWN),
    PermissionSpec("requests.close", "incident", ALL),
    PermissionSpec("problems.view", "problem", ALL),
    PermissionSpec("problems.manage", "problem", NOT_OWN),
    PermissionSpec("changes.view", "change", ALL),
    PermissionSpec("changes.create", "change"),
    PermissionSpec("changes.approve", "change", NOT_OWN),
    PermissionSpec("releases.view", "release", ALL),
    PermissionSpec("releases.manage", "release"),
    PermissionSpec("assets.view", "assets", ALL),
    PermissionSpec("assets.manage", "assets", NOT_OWN),
    PermissionSpec("cmdb.view", "cmdb", NOT_OWN),
    PermissionSpec("cmdb.manage", "cmdb"),
)

# Permissions that make the console's Admin area visible (any one of them).
ADMIN_PERMISSIONS = frozenset(
    {
        "users.manage",
        "roles.view",
        "roles.manage",
        "sites.manage",
        "groups.manage",
        "settings.manage",
        "licence.manage",
        "audit.view",
        "identity.manage",
    }
)

# The technician and requester system roles, as (permission, scope), for the permissions of this
# module and the reserved ones. Built modules add theirs with PermissionSpec.defaults. The tenant
# admin holds every catalogue permission at its broadest scope (computed, so modules are included).
SYSTEM_ROLE_GRANTS: Mapping[str, tuple[tuple[str, Scope], ...]] = MappingProxyType(
    {
        TECHNICIAN: (
            ("profile.edit", "own"),
            ("users.view", "all"),
            ("sites.view", "all"),
            ("groups.view", "all"),
            ("requests.view", "all"),
            ("requests.create", "all"),
            ("requests.edit", "all"),
            ("requests.assign", "all"),
            ("requests.close", "all"),
            ("problems.view", "all"),
            ("problems.manage", "group"),
            ("changes.view", "all"),
            ("changes.create", "all"),
            ("releases.view", "all"),
            ("assets.view", "all"),
            ("assets.manage", "group"),
            ("cmdb.view", "all"),
        ),
        REQUESTER: (
            ("profile.edit", "own"),
            ("requests.view", "own"),
            ("requests.create", "all"),
            ("requests.close", "own"),
        ),
        AUDITOR: (
            ("profile.edit", "own"),
            ("users.view", "all"),
            ("roles.view", "all"),
            ("sites.view", "all"),
            ("groups.view", "all"),
        ),
        SECURITY_ADMIN: (
            ("profile.edit", "own"),
            ("users.view", "all"),
            ("roles.view", "all"),
            ("identity.manage", "all"),
        ),
        KNOWLEDGE_MANAGER: (("profile.edit", "own"),),
    }
)


class CatalogueError(RuntimeError):
    """A module declares an invalid or duplicate permission (a programming error)."""


@dataclass(frozen=True)
class Catalogue:
    """Every permission of the running app, by key."""

    permissions: Mapping[str, PermissionSpec]

    @classmethod
    def build(cls, specs: Iterable[PermissionSpec], known_features: frozenset[str]) -> "Catalogue":
        """Validate and index; fails at startup for bad keys, scopes, features or duplicates."""
        found: dict[str, PermissionSpec] = {}
        for spec in specs:
            if not PERMISSION_KEY.fullmatch(spec.key):
                msg = f"permission {spec.key!r} must be 'module.action' in lowercase"
                raise CatalogueError(msg)
            if spec.key in found:
                msg = f"permission {spec.key!r} is declared twice"
                raise CatalogueError(msg)
            if not spec.scopes or not set(spec.scopes) <= set(ALL_SCOPES):
                msg = f"permission {spec.key!r} has invalid scopes {spec.scopes!r}"
                raise CatalogueError(msg)
            if spec.feature is not None and spec.feature not in known_features:
                msg = f"permission {spec.key!r} names unknown feature {spec.feature!r}"
                raise CatalogueError(msg)
            found[spec.key] = spec
        declared = [(r, spec.key, s) for spec in found.values() for r, s in spec.defaults]
        listed = [(r, key, s) for r, grants in SYSTEM_ROLE_GRANTS.items() for key, s in grants]
        for role, key, scope in listed + declared:
            if role not in SYSTEM_ROLE_GRANTS:
                msg = f"permission {key!r} gives a default to unknown system role {role!r}"
                raise CatalogueError(msg)
            if key not in found or scope not in found[key].scopes:
                msg = f"system role {role!r} grants {key!r} at {scope!r}, not in the catalogue"
                raise CatalogueError(msg)
        return cls(MappingProxyType(dict(sorted(found.items()))))

    def get(self, key: str) -> PermissionSpec | None:
        """A permission by key."""
        return self.permissions.get(key)

    def system_grants(
        self, role: str, *, technician_scope: Scope = "group"
    ) -> tuple[tuple[str, Scope], ...]:
        """(permission, scope) pairs of a system role; the admin gets everything, broadest.

        `technician_scope` is the tenant's answer to the first-run question (D-052, D-073):
        "all" widens the technician defaults that modules declare at `group` (records' view and
        work) to `all`, where the permission allows it.
        """
        if role == TENANT_ADMIN:
            return tuple((key, spec.scopes[0]) for key, spec in self.permissions.items())
        declared = tuple(
            (key, _widened(spec, role, scope, technician_scope))
            for key, spec in self.permissions.items()
            for granted_to, scope in spec.defaults
            if granted_to == role
        )
        return SYSTEM_ROLE_GRANTS.get(role, ()) + declared


def _widened(spec: PermissionSpec, role: str, scope: Scope, technician_scope: Scope) -> Scope:
    if role == TECHNICIAN and scope == "group" and technician_scope in spec.scopes:
        return technician_scope
    return scope


def covers(held: Scope, wanted: Scope) -> bool:
    """Whether holding `held` includes everything `wanted` reaches (only `all` covers others)."""
    return held in {wanted, "all"}


def broadest(scopes: Iterable[Scope]) -> Scope:
    """The widest-reaching of several scopes, for display (site wins a site/group tie)."""
    return max(scopes, key=lambda scope: (SCOPE_RANK[scope], scope == "site"))
