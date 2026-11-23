"""Field purposes: one per kind of sealed value, owned by one module (ADR-050 item 4).

A purpose is `field.<module>.<what>` (e.g. `field.automation.webhook_header`): it names the HKDF
key the value is sealed under (ADR-048) and is bound into the blob, so a value of one purpose
never opens as another. Modules declare theirs once, as module constants, with `purpose`; the
same name declared twice (by two modules or one) is refused at import, so no two uses can ever
share a key by accident (lane B's condition).
"""

import re

_PART = re.compile(r"^[a-z][a-z0-9_]{0,24}$")
_DECLARED: dict[str, str] = {}


class PurposeError(ValueError):
    """A malformed purpose, or one already declared."""


def purpose(module: str, what: str) -> str:
    """Declare `field.<module>.<what>`; PurposeError when malformed or declared before."""
    if not _PART.fullmatch(module) or not _PART.fullmatch(what):
        msg = f"field purpose parts must be lower-case names: {module!r}, {what!r}"
        raise PurposeError(msg)
    name = f"field.{module}.{what}"
    if name in _DECLARED:
        msg = f"field purpose {name!r} is declared twice"
        raise PurposeError(msg)
    _DECLARED[name] = module
    return name


def declared() -> dict[str, str]:
    """Every declared purpose and its module (the guard test reads it)."""
    return dict(_DECLARED)


def is_declared(name: str) -> bool:
    """Whether `name` was declared with `purpose` (seal and open accept nothing else)."""
    return name in _DECLARED
