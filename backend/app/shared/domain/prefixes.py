"""Display-ID prefixes: the one rule every numbered record uses (incidents, articles; D-120)."""

import re

PREFIX_PATTERN = r"^[A-Z]{2,6}$"
_PREFIX = re.compile(PREFIX_PATTERN)


def prefix_problems(prefix: str) -> list[str]:
    """Codes for an invalid display prefix (2-6 capital letters)."""
    return [] if _PREFIX.fullmatch(prefix) else ["invalid_prefix"]
