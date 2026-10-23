"""What modules declare for realtime (WP-011; docs/architecture/realtime.md).

Two declarations, both in `ModuleSpec`:

* `channels=[ChannelSpec(...)]`: who may join which channel. The API calls `authorize` before it
  signs a subscription token, so a channel is only ever joined after the policy layer said yes.
  List channels also say which channels a user should join to follow a list (`channels_for`):
  one per scope the user holds (everyone / their sites / their groups / their own records).

* `realtime=[RealtimeRoute(...)]`: what reaches screens when an event happens. The fan-out
  worker calls `route` for each matching event; it returns the publications (channel + a
  minimal payload: type, IDs, changed field names, version, actor ID) and the users whose access
  changed (their connections are cut so they rejoin with fresh tokens).
"""

import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events import EventEnvelope
from app.shared.realtime.channels import QUEUE, Channel


class RealtimeRegistrationError(RuntimeError):
    """A realtime declaration breaks the rules. Always a programming error."""


@dataclass(frozen=True)
class ChannelRequest:
    """One subscription request, after the user's session and subject are known."""

    channel: Channel
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    # The module's compiled permissions (identity_access Subject); typed loosely because shared
    # code cannot import a module.
    subject: Any
    session: AsyncSession


@dataclass(frozen=True)
class ChannelAccess:
    """A yes, with the subscription's options."""

    # Presence plus join/leave messages for this subscription (record channels: "who else is
    # looking at this?"). Off for lists, where thousands of joins would flood every subscriber.
    presence: bool = False


Authorize = Callable[[ChannelRequest], Awaitable[ChannelAccess | None]]
ChannelsFor = Callable[[Any, uuid.UUID], Sequence[Channel]]


@dataclass(frozen=True)
class ChannelSpec:
    """Who may join one kind of channel.

    `kind` is the channel kind (`users`, `wi`, `user`, `broadcast`, `queue`). For `queue` the
    spec is per list (`list_name="users"`) and must say which list channels a subject follows.
    """

    kind: str
    authorize: Authorize
    list_name: str | None = None
    channels_for: ChannelsFor | None = None

    @property
    def key(self) -> tuple[str, str | None]:
        """Registry key."""
        return (self.kind, self.list_name)


@dataclass(frozen=True)
class Publication:
    """One message for one channel.

    `coalesce=True` (list channels): messages of the same type for the same channel inside the
    fan-out window are merged into one `{type, ids}` message. Record messages for the same record
    are merged too (changed fields united, highest version kept).
    """

    channel: Channel
    type: str
    ids: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()
    version: int | None = None
    actor_id: str | None = None
    coalesce: bool = False

    def data(self) -> dict[str, Any]:
        """The payload: IDs, field names, version and actor only (architecture.md §8.2)."""
        body: dict[str, Any] = {"type": self.type, "ids": list(self.ids)}
        if self.fields:
            body["fields"] = list(self.fields)
        if self.version is not None:
            body["version"] = self.version
        if self.actor_id is not None:
            body["by"] = self.actor_id
        return body


@dataclass(frozen=True)
class RealtimeEffects:
    """What one event changes on screens and in access."""

    publications: Sequence[Publication] = ()
    # Users of the event's tenant whose access changed: cut and rejoin with fresh tokens.
    revoke_users: Sequence[uuid.UUID] = ()


Route = Callable[[EventEnvelope, AsyncSession], Awaitable[RealtimeEffects]]


@dataclass(frozen=True)
class RealtimeRoute:
    """Fan-out for some event types. `route` runs in a read-only tenant session of the event."""

    event_types: tuple[str, ...]
    route: Route


@dataclass(frozen=True)
class RealtimeRegistry:
    """Every module's channel specs and routes, validated."""

    channels: Mapping[tuple[str, str | None], ChannelSpec] = field(default_factory=dict)
    routes: Sequence[RealtimeRoute] = ()

    def spec_for(self, channel: Channel) -> ChannelSpec | None:
        """The spec that decides about `channel`, if any module declared one."""
        key = (channel.kind, channel.list_name if channel.kind == QUEUE else None)
        return self.channels.get(key)

    def lists(self) -> list[str]:
        """Names of the lists that can be followed live."""
        return sorted(name for kind, name in self.channels if kind == QUEUE and name is not None)

    def event_types(self) -> list[str]:
        """Every event type some route handles."""
        return sorted({t for route in self.routes for t in route.event_types})

    def routes_for(self, event_type: str) -> list[RealtimeRoute]:
        """Routes that handle `event_type`."""
        return [route for route in self.routes if event_type in route.event_types]

    @classmethod
    def build(cls, modules: Iterable[Any]) -> "RealtimeRegistry":
        """From `ModuleSpec.channels` / `ModuleSpec.realtime` of every module."""
        channels: dict[tuple[str, str | None], ChannelSpec] = {}
        routes: list[RealtimeRoute] = []
        for module in modules:
            for spec in getattr(module, "channels", ()):
                if not isinstance(spec, ChannelSpec):
                    msg = f"{module.name}: channels must be ChannelSpec instances"
                    raise RealtimeRegistrationError(msg)
                if spec.kind == QUEUE and (spec.list_name is None or spec.channels_for is None):
                    msg = f"{module.name}: a queue ChannelSpec needs list_name and channels_for"
                    raise RealtimeRegistrationError(msg)
                if spec.key in channels:
                    msg = f"channel {spec.key} is declared twice"
                    raise RealtimeRegistrationError(msg)
                channels[spec.key] = spec
            for route in getattr(module, "realtime", ()):
                if not isinstance(route, RealtimeRoute) or not route.event_types:
                    msg = f"{module.name}: realtime must be RealtimeRoute instances with events"
                    raise RealtimeRegistrationError(msg)
                routes.append(route)
        return cls(channels=channels, routes=tuple(routes))
