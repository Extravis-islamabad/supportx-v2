"""A technician's narrower write on the assets of its own tickets (D-157, after D-153 item 2).

A technician holds `assets.view`, not `assets.manage`. It may still change an asset when both
hold:

- the asset is linked to a ticket assigned to it that is still being worked (open, paused, or
  resolved and not closed: work_items' rule, the coordinator 2026-11-10), and
- the asset is held by that ticket's requester or the person it was raised on behalf of, or by
  one of their departments.

Even then only the asset's state (a life cycle move), its location, its notes (open to anyone
who sees the asset, REQ-AST-050) and its fitted components change; anything else is refused with
`asset_field_not_allowed` (403, `params.field`). Who it is, the money, the holder and the rest
stay with `assets.manage`.

Work items answer "which requesters of my tickets link this asset" through a SQL builder they
register here (`register_ticket_requesters`), so assets never imports work_items or names its
tables (CLAUDE.md rule e). Without it (work_items not loaded) nothing is granted.
"""

import uuid
from collections.abc import Callable

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDenied
from app.modules.assets.infra.models import Asset
from app.modules.identity_access import Subject, person_placement

# (technician, asset) -> SELECT of (requester, on behalf of) of its tickets still worked that
# link the asset.
TicketRequesters = Callable[[uuid.UUID, uuid.UUID], Select[uuid.UUID, uuid.UUID | None]]
# What the narrower path may change through the asset's own save (PATCH). The state moves
# through the life cycle, components through the component's holder, notes through notes.
LIMITED_FIELDS = frozenset({"location"})
FIELD_CODE = "asset_field_not_allowed"

_ports: list[TicketRequesters] = []


def register_ticket_requesters(port: TicketRequesters) -> None:
    """Work items' builder (at their import); registering again replaces it."""
    _ports[:] = [port]


def unregister_ticket_requesters() -> None:
    """Forget the builder (tests)."""
    _ports.clear()


async def ticket_grants(session: AsyncSession, subject: Subject, row: Asset) -> bool:
    """Whether the D-157 narrower write applies to `row` for `subject`."""
    if not _ports:
        return False
    found = await session.execute(_ports[0](subject.user_id, row.id))
    # The requester and the person a ticket was raised on behalf of both count (lane A).
    requesters = {person for pair in found.tuples() for person in pair if person is not None}
    if not requesters:
        return False
    if row.owner_user_id is not None and row.owner_user_id in requesters:
        return True
    if row.department_id is None:
        return False
    for person in sorted(requesters):
        if (await person_placement(session, person)).department_id == row.department_id:
            return True
    return False


def refuse_field(field: str) -> PermissionDenied:
    """The labelled refusal of a field the narrower path may not change."""
    return PermissionDenied(code=FIELD_CODE, params={"field": field})
