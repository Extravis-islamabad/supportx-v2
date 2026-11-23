"""A refused workflow step names the run-as identity's missing right only when that is what it
is (lane B's #416 review): a rule's own code and a licence refusal keep their codes."""

from app.core.errors import Conflict, EntitlementRequired, NotFound, PermissionDenied
from app.modules.work_items.domain.types import TYPES, WorkItemTypeCode
from app.modules.work_items.service.workflow_commands import _refusal

INCIDENT = TYPES[WorkItemTypeCode.INCIDENT]


def test_a_record_it_may_not_see_or_change_is_the_identity_s_missing_right() -> None:
    assert _refusal(INCIDENT, NotFound(code="work_item_not_found")) == (
        "workflow_identity_not_permitted"
    )
    assert _refusal(INCIDENT, PermissionDenied()) == "workflow_identity_not_permitted"


def test_other_refusals_keep_their_own_codes() -> None:
    assert _refusal(INCIDENT, EntitlementRequired()) == "entitlement_required"
    assert _refusal(INCIDENT, PermissionDenied(code="sod_conflict")) == "sod_conflict"
    assert _refusal(INCIDENT, Conflict(code="move_not_allowed")) == "move_not_allowed"
