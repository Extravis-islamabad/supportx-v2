"""Which trigger actions a record type offers (WP-047a S4; lane C's #627 review). No I/O.

The editor lists the answer and saving refuses anything else, so one rule decides both: the
server's, never a list in the browser.
"""

from typing import Any

from app.modules.automation.domain.triggers import TriggerActionKind
from app.modules.automation.service.registry import RecordType, offered_actions


async def _none(*_: Any) -> Any:  # noqa: ANN401 - a stand-in port
    return None


def test_an_approvable_type_offers_the_ask_and_one_without_approvals_does_not() -> None:
    approvable = RecordType(
        code="service_request",
        fields=_none,
        check_values=_none,
        apply=_none,
        add_note=_none,
        run_command=_none,
        approval_roles=(),
        ask_approval=_none,
    )
    assert offered_actions(approvable) == [
        TriggerActionKind.SET,
        TriggerActionKind.NOTE,
        TriggerActionKind.START_WORKFLOW,
        TriggerActionKind.START_APPROVAL,
    ]
    plain = RecordType(
        code="incident", fields=_none, check_values=_none, apply=_none, add_note=_none
    )
    assert offered_actions(plain) == [TriggerActionKind.SET, TriggerActionKind.NOTE]
    # A CI: fields only (WP-053 S5d), no notes, no approvals.
    ci = RecordType(code="cmdb_ci", fields=_none, check_values=_none, apply=_none)
    assert offered_actions(ci) == [TriggerActionKind.SET]
