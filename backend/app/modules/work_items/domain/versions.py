"""Life cycle versions (ADR-049): one versioning model for action-based and staged types.

A life cycle (a type's transition set: "standard", or one a template names) has numbered
versions. A draft is edited; a published one never changes (an edit makes the next draft);
a retired one stays readable for the records still on it. Every record runs on the version it
was made on until an administrator migrates it (REQ-INC-049 AC3).
"""

from enum import StrEnum

FIRST_VERSION = 1


class VersionState(StrEnum):
    """Where a life cycle version stands."""

    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


# Records may run on these (a retired version keeps working for the records still on it).
RUNNABLE_STATES = frozenset({VersionState.PUBLISHED, VersionState.RETIRED})

__all__ = ["FIRST_VERSION", "RUNNABLE_STATES", "VersionState"]
