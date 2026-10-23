"""Realtime channel names (architecture.md §8.1; WP-011).

Every channel starts with the tenant, so a channel can never be shared across tenants:

    t:{tenant}:{kind}:{key}     e.g. t:<tenant>:users:<user id>, t:<tenant>:queue:users
    t:{tenant}:{kind}           key-less kinds, e.g. t:<tenant>:broadcast

`kind` is lowercase snake case; `key` is limited to letters, digits, `_`, `-` and `.`, so the
separator `:` can never appear inside it. List channels (`queue`) name the list first and, for
site/group audiences, the unit after a dot: `users`, `users.site.<id>`, `users.group.<id>`.
"""

import re
import uuid
from dataclasses import dataclass

PREFIX = "t"
_KIND = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_KEY = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")

# Kinds the platform defines (architecture.md §8.1 plus the two below). Modules add record kinds
# (e.g. `wi` for work items, `users` for user records) through ChannelSpec.
PERSONAL = "user"  # t:{tenant}:user:{user_id}: personal notifications, "your access changed"
QUEUE = "queue"  # t:{tenant}:queue:{list}[.site|group.{unit}]: list views
BROADCAST = "broadcast"  # t:{tenant}:broadcast: tenant-wide notices (plan changes)


class ChannelNameError(ValueError):
    """Not a valid SupportX channel name."""


@dataclass(frozen=True)
class Channel:
    """A parsed channel name."""

    tenant_id: uuid.UUID
    kind: str
    key: str | None = None

    def __post_init__(self) -> None:
        """Validate kind and key, so an invalid name can never be built."""
        if not _KIND.fullmatch(self.kind):
            msg = f"invalid channel kind {self.kind!r}"
            raise ChannelNameError(msg)
        if self.key is not None and not _KEY.fullmatch(self.key):
            msg = f"invalid channel key {self.key!r}"
            raise ChannelNameError(msg)

    @property
    def name(self) -> str:
        """The wire name, `t:{tenant}:{kind}[:{key}]`."""
        base = f"{PREFIX}:{self.tenant_id}:{self.kind}"
        return base if self.key is None else f"{base}:{self.key}"

    @property
    def list_name(self) -> str | None:
        """For a `queue` channel: the list (`users` in `users.site.<id>`)."""
        if self.kind != QUEUE or self.key is None:
            return None
        return self.key.split(".", 1)[0]

    @classmethod
    def parse(cls, name: str) -> "Channel":
        """Parse a wire name; ChannelNameError when it is not one of ours."""
        parts = name.split(":")
        if len(parts) not in {3, 4} or parts[0] != PREFIX:
            msg = f"not a SupportX channel: {name!r}"
            raise ChannelNameError(msg)
        try:
            tenant = uuid.UUID(parts[1])
        except ValueError as exc:
            msg = f"invalid tenant in channel {name!r}"
            raise ChannelNameError(msg) from exc
        if str(tenant) != parts[1]:  # only the canonical form, so one channel has one name
            msg = f"non-canonical tenant in channel {name!r}"
            raise ChannelNameError(msg)
        return cls(tenant, parts[2], parts[3] if len(parts) == 4 else None)  # noqa: PLR2004 - kind + key


def personal(tenant_id: uuid.UUID, user_id: uuid.UUID) -> Channel:
    """The user's own channel."""
    return Channel(tenant_id, PERSONAL, str(user_id))


def broadcast(tenant_id: uuid.UUID) -> Channel:
    """The tenant-wide channel every signed-in user of the tenant may join."""
    return Channel(tenant_id, BROADCAST)


def queue(
    tenant_id: uuid.UUID,
    list_name: str,
    *,
    site: uuid.UUID | None = None,
    group: uuid.UUID | None = None,
) -> Channel:
    """A list channel: everyone (`all` scope), or one site's / group's audience."""
    if site is not None:
        return Channel(tenant_id, QUEUE, f"{list_name}.site.{site}")
    if group is not None:
        return Channel(tenant_id, QUEUE, f"{list_name}.group.{group}")
    return Channel(tenant_id, QUEUE, list_name)


def record(tenant_id: uuid.UUID, kind: str, record_id: uuid.UUID) -> Channel:
    """A record channel, e.g. `t:{tenant}:wi:{id}`."""
    return Channel(tenant_id, kind, str(record_id))
