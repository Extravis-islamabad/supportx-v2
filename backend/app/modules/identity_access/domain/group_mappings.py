"""Roles and support groups from identity provider and directory groups (WP-057 S5c, REQ-SEC-014).

Pure rules, with no I/O. The service (service/group_mappings.py) reads and writes. Lane B blocks
it; the conditions are in ~/Extravis/plans/wp-057-s5c-plan.md.

- **A mapping** maps one external group ID (exact, immutable: Entra's object ID, never a display
  name) from one source onto one role **or** one support group.
- **A person's mapped access** is a set of (target, mapping) pairs. `plan` compares the wanted
  set with what is held: sources to add, sources to drop, targets to create, and targets to
  remove once their last source has gone. A hand-made target is never removed; the service
  never puts one in `remove`.
- **Privileged access never comes from a mapping** unless the tenant turns that on: tenant admin,
  or any role holding a right that can mint access or hide its trail (lane B's Q3).
"""

from collections.abc import Iterable
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

# S5c-1a ships SSO-source mappings switched off (the coordinator, 2026-11-24): nothing applies
# them until S5c-1b's sign-in wiring lands, so the API refuses them and the screen doesn't offer
# them. S5c-1b deletes this constant. It's a release switch for unfinished work, never licensing.
SSO_GROUP_MAPPINGS_READY = False

TENANT_ADMIN_ROLE = "tenant_admin"
# Rights that can mint access or hide its trail (lane B's Q3, in real keys, 2026-11-24).
NEVER_VIA_IDP: frozenset[str] = frozenset(
    {
        "identity.manage",  # SSO set-ups, sign-in policy, break-glass, vendor support grants
        "audit.manage",
        "audit.manage_holds",  # lifting a hold can let a trail go
        "api_keys.manage",  # API keys and service accounts, their roles included
        "roles.manage",  # creates roles with any rights, links roles to groups
        "users.manage",  # assigns roles to people
    }
)

MAX_GROUPS = 500  # more in one list counts as an overage: no change (lane B's G2)
MAX_GROUP_ID = 256


class SourceKind(StrEnum):
    """Where a mapping's groups come from."""

    DIRECTORY = "directory"
    SSO = "sso"


TargetKind = Literal["role", "group"]


@dataclass(frozen=True, order=True)
class Target:
    """A role or a support group a mapping gives."""

    kind: TargetKind
    id: str


@dataclass(frozen=True, order=True)
class Held:
    """One target held through one mapping."""

    target: Target
    mapping_id: str


@dataclass(frozen=True)
class Plan:
    """What `follow` changes for one person and one source."""

    add_sources: tuple[Held, ...]
    drop_sources: tuple[Held, ...]
    # Targets the person gains (made managed when they don't hold them yet).
    gain: tuple[Target, ...]
    # Targets whose every source has gone: removed if they are managed (never if hand-made).
    lose: tuple[Target, ...]

    @property
    def empty(self) -> bool:
        """Nothing to change."""
        return not (self.add_sources or self.drop_sources)


def plan(
    wanted: AbstractSet[Held], held: AbstractSet[Held], *, other_sources: AbstractSet[Target]
) -> Plan:
    """Changes for one person and one source.

    `wanted` is what this source's enabled mappings give for the person's groups now; `held` is
    what this source holds for them today; `other_sources` are targets another source (another
    connector, or an SSO set-up) also holds for them, which therefore stay.
    """
    add = tuple(sorted(wanted - held))
    drop = tuple(sorted(held - wanted))
    before = {h.target for h in held}
    after = {h.target for h in wanted}
    gain = tuple(sorted(after - before))
    lose = tuple(sorted((before - after) - set(other_sources)))
    return Plan(add_sources=add, drop_sources=drop, gain=gain, lose=lose)


def privileged(role_key: str, permissions: Iterable[str]) -> bool:
    """Whether a role is tenant admin, or holds a right no mapping may give without the opt-in."""
    return role_key == TENANT_ADMIN_ROLE or not NEVER_VIA_IDP.isdisjoint(permissions)


def overage(values: Iterable[str]) -> bool:
    """A list too long, or holding a value too long, to trust as complete (lane B's G2)."""
    items = list(values)
    return len(items) > MAX_GROUPS or any(len(v) > MAX_GROUP_ID or not v for v in items)
