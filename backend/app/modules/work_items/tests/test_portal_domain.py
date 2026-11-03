"""The requester's side of an incident: status, fields and reach (WP-028, no I/O)."""

import uuid

import pytest

from app.modules.work_items.domain.lifecycle import DEFAULT_STATUSES, StatusCategory
from app.modules.work_items.domain.portal import (
    ALWAYS,
    STAFF_ONLY,
    TEMPLATE_CONTROLLED,
    PortalStatus,
    Reach,
    RecordFacts,
    Viewer,
    portal_status,
    reaches,
    requester_fields,
    requester_fillable,
    unfillable,
)
from app.modules.work_items.domain.templates import FieldRule, TemplateField, default_rules


def test_every_default_status_has_a_plain_requester_status() -> None:
    shown = {s.code: portal_status(s.code, s.category) for s in DEFAULT_STATUSES}
    assert shown == {
        "new": PortalStatus.RECEIVED,
        "assigned": PortalStatus.IN_PROGRESS,
        "in_progress": PortalStatus.IN_PROGRESS,
        "awaiting_requester": PortalStatus.WAITING_FOR_YOU,
        # a technician-only status never reaches the requester (REQ-INC-147 AC2)
        "awaiting_third_party": PortalStatus.IN_PROGRESS,
        "resolved": PortalStatus.RESOLVED,
        "closed": PortalStatus.CLOSED,
        "canceled": PortalStatus.CANCELED,
        "merged": PortalStatus.CLOSED,
    }


@pytest.mark.parametrize("category", list(StatusCategory))
def test_a_custom_status_follows_its_category(category: StatusCategory) -> None:
    assert portal_status("vendor_lab_check", category) in set(PortalStatus)


def test_staff_only_fields_never_reach_requesters_whatever_the_template() -> None:
    rules = {name: FieldRule(requester_can_see=True) for name in STAFF_ONLY}
    rules |= default_rules()
    assert not requester_fields(rules) & STAFF_ONLY
    assert not (ALWAYS | TEMPLATE_CONTROLLED) & STAFF_ONLY


def test_template_hides_a_field_from_requesters() -> None:
    rules = default_rules()
    assert "category_id" in requester_fields(rules)
    rules["category_id"] = FieldRule(requester_can_see=False)
    assert "category_id" not in requester_fields(rules)
    rules["impact"] = FieldRule(shown=False)
    assert "impact" not in requester_fields(rules)
    assert requester_fields(rules) >= ALWAYS


def test_fillable_follows_the_template_and_never_staff_fields() -> None:
    rules = default_rules()
    assert requester_fillable(rules) == {"subject", "description"}
    rules[TemplateField.GROUP_ID.value] = FieldRule(requester_can_fill=True)
    rules[TemplateField.URGENCY.value] = FieldRule(requester_can_fill=True)
    assert requester_fillable(rules) == {"subject", "description", "urgency"}
    assert unfillable(["subject", "group_id", "technician_id"], rules) == [
        "group_id",
        "technician_id",
    ]


ME, BOSS, OTHER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
DEPT, SITE = uuid.uuid4(), uuid.uuid4()


def _record(requester: uuid.UUID | None, **kw: uuid.UUID | None) -> RecordFacts:
    return RecordFacts(
        requester_id=requester,
        on_behalf_of_id=kw.get("for_"),
        department_id=kw.get("dept"),
        site_id=kw.get("site"),
    )


def test_own_reach_is_requester_or_the_person_it_is_for_only() -> None:
    me = Viewer(ME)
    assert reaches(me, _record(ME)) is Reach.OWN
    assert reaches(me, _record(OTHER, for_=ME)) is Reach.OWN
    # same department and site but someone else's: not seen with own reach (REQ-PRT-007 AC1)
    assert reaches(me, _record(OTHER, dept=DEPT, site=SITE)) is None


def test_wider_reach_needs_its_permission_and_its_fact() -> None:
    record = _record(OTHER, dept=DEPT, site=SITE)
    assert reaches(Viewer(ME, frozenset({Reach.OWN, Reach.DEPARTMENT})), record) is None
    dept = Viewer(ME, frozenset({Reach.OWN, Reach.DEPARTMENT}), department_ids=frozenset({DEPT}))
    assert reaches(dept, record) is Reach.DEPARTMENT
    site = Viewer(ME, frozenset({Reach.OWN, Reach.SITE}), site_ids=frozenset({SITE}))
    assert reaches(site, record) is Reach.SITE
    assert reaches(Viewer(ME, frozenset({Reach.ALL})), record) is Reach.ALL


def test_direct_reports_are_their_own_reach() -> None:
    boss = Viewer(BOSS, frozenset({Reach.OWN, Reach.REPORTS}), report_ids=frozenset({ME}))
    assert reaches(boss, _record(ME)) is Reach.REPORTS
    assert reaches(boss, _record(OTHER, for_=ME)) is Reach.REPORTS
    assert reaches(boss, _record(OTHER)) is None
    # the narrowest reach wins: their own record is own, not reports
    assert reaches(boss, _record(BOSS, for_=ME)) is Reach.OWN
