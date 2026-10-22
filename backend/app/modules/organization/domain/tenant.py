"""Tenant domain rules: pure Python, no I/O."""

import re
import uuid
from dataclasses import dataclass
from enum import StrEnum

# Lowercase letters, digits and inner hyphens; 2-63 chars (fits a DNS label for vanity hosts).
SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$"
_SLUG = re.compile(SLUG_PATTERN)


class TenantStatus(StrEnum):
    """Lifecycle of a tenant. Stored as stable lowercase codes; the UI shows labels."""

    ACTIVE = "active"
    SUSPENDED = "suspended"


def is_valid_slug(slug: str) -> bool:
    """Whether `slug` is a valid tenant slug."""
    return bool(_SLUG.fullmatch(slug))


@dataclass(frozen=True)
class TenantView:
    """What other modules may know about a tenant (public, read-only)."""

    id: uuid.UUID
    name: str
    slug: str
    status: TenantStatus
