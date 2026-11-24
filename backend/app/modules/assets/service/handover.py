"""Hand an asset over to a person from a fulfilment task (WP-047a S5; REQ-SR-056).

Lane B's terms for the port (the assets owner; lane A built it under that review):

1. As the task's owner, through `writable`: site scope, fine-grained access and D-157's
   through-a-ticket path apply as for any edit. The D-157 path may change the location only, so
   it never hands over. Refusals reuse its codes; vendor support holds no hand-over right; no
   new bypass, never a system user.
2. The person must be live in this tenant: active, and not a vendor support or service account
   (`handover_person_not_active`, 422).
3. Never a retired or disposed asset (`asset_handover_end_of_life`, 409); never one held by
   someone else (`asset_assigned_elsewhere`, 409), so a reassignment is never silent.
4. The row is locked (`writable` locks it) and its version bumped.
5. In the caller's transaction (the task's completion): field history `owner_user_id` with
   source `workflow` and the request's ref as the reason; the asset's change event through the
   outbox; an audit entry `asset.handed_over` naming the task's owner. The link to the request
   is the caller's (work_items' asset links).
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, ValidationFailed
from app.modules.assets.domain.catalogue import AssetStateCategory
from app.modules.assets.infra.models import AssetState
from app.modules.assets.service import ticket_access
from app.modules.assets.service.assets import _saved, writable
from app.modules.audit import WORKER as AUDIT_WORKER
from app.modules.audit import AuditActorType
from app.modules.audit import record as record_audit
from app.modules.identity_access import Subject, person_placement
from app.shared.history import Change

HANDED_OVER = "asset.handed_over"
OWNER_FIELD = "owner_user_id"
END_OF_LIFE = frozenset({AssetStateCategory.RETIRED.value, AssetStateCategory.DISPOSED.value})
NOT_A_PERSON = frozenset({"vendor_support", "service"})  # never a hand-over's target


@dataclass(frozen=True)
class AssetHandover:
    """What a hand-over did: the asset, its version now, and whether anything changed."""

    asset_id: uuid.UUID
    version: int
    changed: bool


async def handover_asset(
    session: AsyncSession,
    subject: Subject,
    asset_id: uuid.UUID,
    to_user_id: uuid.UUID,
    *,
    source_ref: Mapping[str, Any],
) -> AssetHandover:
    """Assign the asset to `to_user_id` as `subject` may (the terms above); what it did."""
    row, limited = await writable(session, subject, asset_id)
    if limited:  # D-157's through-a-ticket path changes the location only: never a hand-over
        raise ticket_access.refuse_field(OWNER_FIELD)
    state = await session.get(AssetState, row.state_id)
    if state is not None and state.category in END_OF_LIFE:
        raise Conflict(code="asset_handover_end_of_life", params={"state": state.category})
    held_elsewhere = (row.owner_user_id not in (None, to_user_id)) or any(
        getattr(row, column, None) is not None
        for column in ("owner_department_id", "owner_asset_id")
    )
    if held_elsewhere:
        raise Conflict(code="asset_assigned_elsewhere")
    placement = await person_placement(session, to_user_id)
    if not placement.active or placement.user_type in NOT_A_PERSON:
        raise ValidationFailed(
            errors=[
                FieldError(
                    field="body.to_user_id",
                    code="handover_person_not_active",
                    message_key="errors.field.handover_person_not_active",
                )
            ]
        )
    if row.owner_user_id == to_user_id:
        return AssetHandover(row.id, row.version, changed=False)
    change = Change("owner_user_id", None, str(to_user_id))
    row.owner_user_id = to_user_id
    reference = str(source_ref.get("display_id") or source_ref.get("work_item_id") or "")
    await _saved(
        session, subject, row, [change], action="updated", source="workflow", reason=reference
    )
    await record_audit(
        session,
        action_code=HANDED_OVER,
        facts=AUDIT_WORKER,
        actor=(AuditActorType.PERSON, subject.user_id),
        object_type="asset",
        object_id=str(row.id),
        details={
            "to_user_id": str(to_user_id),
            **{k: str(v) for k, v in source_ref.items() if k in {"work_item_id", "task_id"}},
        },
    )
    return AssetHandover(row.id, row.version, changed=True)


__all__ = ["HANDED_OVER", "AssetHandover", "handover_asset"]
