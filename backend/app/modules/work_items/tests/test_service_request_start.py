"""How a service request starts from its item (WP-030 s1; no I/O)."""

import uuid

from app.modules.work_items.domain.service_requests import ItemDecides, after_approval, start

GROUP, TECH = uuid.uuid4(), uuid.uuid4()


def _item(**over: object) -> ItemDecides:
    values: dict[str, object] = {
        "needs_approval": False,
        "default_priority": None,
        "group_id": GROUP,
        "technician_id": None,
        "technician_after_approval": False,
    }
    values.update(over)
    return ItemDecides(**values)  # type: ignore[arg-type]  # test builder over a frozen dataclass


def test_an_item_needing_approval_waits_and_its_group_is_set_at_once() -> None:
    begun = start(_item(needs_approval=True, technician_id=TECH), tenant_default_priority="p3")
    assert (begun.status, begun.group_id, begun.technician_id) == ("awaiting_approval", GROUP, TECH)


def test_technician_after_approval_waits_for_it() -> None:
    item = _item(needs_approval=True, technician_id=TECH, technician_after_approval=True)
    begun = start(item, tenant_default_priority="p3")
    assert (begun.status, begun.technician_id) == ("awaiting_approval", None)
    assert after_approval(item, current_technician=None) == TECH  # REQ-SR-008 AC2
    other = uuid.uuid4()
    assert after_approval(item, current_technician=other) == other  # someone took it meanwhile


def test_no_approval_starts_new_or_assigned() -> None:
    assert start(_item(), tenant_default_priority="p3").status == "new"
    assert start(_item(technician_id=TECH), tenant_default_priority="p3").status == "assigned"


def test_the_priority_is_never_blank() -> None:
    from_item = start(_item(default_priority="p2"), tenant_default_priority="p3")
    assert (from_item.priority, from_item.priority_from_item) == ("p2", True)  # REQ-SR-005 AC1
    default = start(_item(), tenant_default_priority="p3")
    assert (default.priority, default.priority_from_item) == ("p3", False)  # AC2
