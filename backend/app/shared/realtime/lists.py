"""Live lists: which list channels a user follows and may join (WP-011).

A list (users, roles, later requests…) is published on one channel per audience, so a message
only ever reaches people who may see the records it names (architecture.md §8.2):

    t:{tenant}:queue:{list}                 holders of the permission at `all`, no rule
    t:{tenant}:queue:{list}.site.{site}     holders at `site` scope who belong to that site
    t:{tenant}:queue:{list}.group.{group}   holders at `group` scope who belong to that group
    t:{tenant}:user:{user}                  `own` scope: the user's own records
    t:{tenant}:queue:{list}.signal          holders whose grants carry an attribute rule:
                                            "this list changed", never which records

The fan-out publishes each change to every audience the record belongs to; the list screen
refetches through the API, where the rule and scopes are applied again.
"""

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.shared.realtime.channels import QUEUE, Channel, personal, queue
from app.shared.realtime.specs import ChannelAccess, ChannelRequest, ChannelSpec, Publication

SIGNAL = "signal"


class _Grant(Protocol):
    @property
    def scope(self) -> str: ...
    @property
    def condition(self) -> Any: ...  # noqa: ANN401 - filter DSL tree or None


class ScopedSubject(Protocol):
    """What this module needs from a compiled subject (identity_access.Subject fits)."""

    @property
    def tenant_id(self) -> uuid.UUID: ...  # noqa: D102
    @property
    def user_id(self) -> uuid.UUID: ...  # noqa: D102
    @property
    def site_ids(self) -> frozenset[uuid.UUID]: ...  # noqa: D102
    @property
    def group_ids(self) -> frozenset[uuid.UUID]: ...  # noqa: D102
    @property
    def grants(self) -> Mapping[str, Sequence[_Grant]]: ...  # noqa: D102


@dataclass(frozen=True)
class LiveList:
    """One list that screens can follow, guarded by `permission`."""

    name: str
    permission: str

    def channels_for(self, subject: ScopedSubject, tenant_id: uuid.UUID) -> list[Channel]:
        """The channels `subject` joins to follow this list (empty: no access)."""
        grants = list(subject.grants.get(self.permission, ()))
        plain = [g for g in grants if g.condition is None]
        if any(g.scope == "all" for g in plain):
            return [queue(tenant_id, self.name)]
        found: list[Channel] = []
        for grant in plain:
            if grant.scope == "site":
                found += [queue(tenant_id, self.name, site=s) for s in sorted(subject.site_ids)]
            elif grant.scope == "group":
                found += [queue(tenant_id, self.name, group=g) for g in sorted(subject.group_ids)]
            elif grant.scope == "own":
                found.append(personal(tenant_id, subject.user_id))
        if len(plain) < len(grants):
            found.append(Channel(tenant_id, QUEUE, f"{self.name}.{SIGNAL}"))
        unique: dict[str, Channel] = {c.name: c for c in found}
        return list(unique.values())

    async def authorize(self, request: ChannelRequest) -> ChannelAccess | None:
        """Yes exactly when the channel is one this subject would be told to follow."""
        wanted = request.channel.name
        if any(c.name == wanted for c in self.channels_for(request.subject, request.tenant_id)):
            return ChannelAccess()
        return None

    def spec(self) -> ChannelSpec:
        """The ChannelSpec a module declares for this list."""
        return ChannelSpec(
            kind=QUEUE,
            list_name=self.name,
            authorize=self.authorize,
            channels_for=self.channels_for,
        )

    def publications(  # noqa: PLR0913 - one record's audiences, all explicit
        self,
        tenant_id: uuid.UUID,
        event_type: str,
        record_id: uuid.UUID,
        *,
        sites: Iterable[uuid.UUID] = (),
        groups: Iterable[uuid.UUID] = (),
        owners: Iterable[uuid.UUID] = (),
        actor_id: str | None = None,
    ) -> list[Publication]:
        """One coalescable message per audience the record belongs to."""
        ids = (str(record_id),)
        channels = [queue(tenant_id, self.name)]
        channels += [queue(tenant_id, self.name, site=s) for s in sites]
        channels += [queue(tenant_id, self.name, group=g) for g in groups]
        channels += [personal(tenant_id, o) for o in owners]
        found = [
            Publication(c, event_type, ids=ids, actor_id=actor_id, coalesce=True) for c in channels
        ]
        # The rule-bound audience learns that the list changed, never which record.
        signal = Channel(tenant_id, QUEUE, f"{self.name}.{SIGNAL}")
        found.append(Publication(signal, event_type, coalesce=True))
        return found
