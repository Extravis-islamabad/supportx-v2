"""Names for report values on the server (exports, report emails; WP-035, ADR-033/034).

Report results carry codes and ids. The screens name them from lists they already load; files
and emails are written by the server, so the module that owns a kind of value registers how to
name it:

    register_names("group", resolver)           ids of support groups   (organization)
    register_names("incident.status", resolver) admin-defined codes     (work_items)
    register_names("incident.custom", resolver) custom choices; `field` is "custom.<key>"

A resolver gets the ids or codes of one grouping and the reader's language and returns the
names it knows; anything it does not know is shown as "Unknown value", never as the raw value.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

# (session, values, language, field) -> {value: name}
NameResolver = Callable[[AsyncSession, Sequence[str], str, str], Awaitable[Mapping[str, str]]]

_RESOLVERS: dict[str, NameResolver] = {}


def register_names(kind: str, resolver: NameResolver) -> None:
    """Name values of `kind` (a reference kind, or "<entity>.<field>" for admin codes)."""
    _RESOLVERS[kind] = resolver


def unregister_names(kind: str) -> None:
    """Undo `register_names` (module shutdown, tests)."""
    _RESOLVERS.pop(kind, None)


def names_resolver(kind: str) -> NameResolver | None:
    """The resolver for `kind`, if a module registered one."""
    return _RESOLVERS.get(kind)
