"""An audience: the people of some departments, sites and groups (WP-053, D-172 (3)). Pure.

A business service's subscribers are one (cmdb, 0185); the catalogue's audience rules
(REQ-CAT-015) can be another. Each person counts once however many refs reach them. Regions are
not refs yet (REQ-CAT-015 names them; organization has none).
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class AudienceKind(StrEnum):
    """What an audience ref names (`audience_kind.<code>`)."""

    DEPARTMENT = "department"
    SITE = "site"
    GROUP = "group"


@dataclass(frozen=True)
class Audience:
    """Departments, sites and groups whose people are reached."""

    department_ids: frozenset[uuid.UUID] = frozenset()
    site_ids: frozenset[uuid.UUID] = frozenset()
    group_ids: frozenset[uuid.UUID] = frozenset()

    @property
    def empty(self) -> bool:
        """No ref at all: nobody."""
        return not (self.department_ids or self.site_ids or self.group_ids)

    @classmethod
    def of(cls, refs: Iterable[tuple[AudienceKind | str, uuid.UUID]]) -> "Audience":
        """From (kind, id) pairs, e.g. stored rows."""
        by: dict[AudienceKind, set[uuid.UUID]] = {kind: set() for kind in AudienceKind}
        for kind, ref_id in refs:
            by[AudienceKind(kind)].add(ref_id)
        return cls(
            department_ids=frozenset(by[AudienceKind.DEPARTMENT]),
            site_ids=frozenset(by[AudienceKind.SITE]),
            group_ids=frozenset(by[AudienceKind.GROUP]),
        )

    def union(self, other: "Audience") -> "Audience":
        """Both audiences' refs (people still count once)."""
        return Audience(
            department_ids=self.department_ids | other.department_ids,
            site_ids=self.site_ids | other.site_ids,
            group_ids=self.group_ids | other.group_ids,
        )
