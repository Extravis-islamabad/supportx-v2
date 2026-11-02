"""Knowledge domain rules, no I/O (WP-033, D-108)."""

import uuid
from datetime import date

from app.modules.knowledge.domain.knowledge import (
    BUILTIN_TYPES,
    MAX_TOPIC_DEPTH,
    Audience,
    Reader,
    RequesterAudience,
    VersionStatus,
    add_months,
    date_problems,
    decide_problem,
    default_review,
    depth_problem,
    may_read,
    requester_may_read,
    self_approval_problem,
    submit_problem,
)

GA, GB = uuid.uuid4(), uuid.uuid4()
SITE, DEPT = uuid.uuid4(), uuid.uuid4()


def test_add_months_lands_on_the_last_day_of_a_shorter_month() -> None:
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)
    assert add_months(date(2026, 5, 1), 24) == date(2028, 5, 1)


def test_req_kb_034_review_date_from_the_type() -> None:
    months = {t.code: t.review_months for t in BUILTIN_TYPES}
    assert months["reference"] == 24
    assert months["known_issue"] == 1
    assert default_review(date(2026, 10, 28), months["how_to"]) == date(2027, 10, 28)


def test_req_kb_034_ac2_ac3_dates() -> None:
    today = date(2026, 10, 28)
    assert date_problems(today, None, today) == []  # AC2: today is accepted
    assert date_problems(date(2026, 10, 27), None, today) == ["review_date_past"]
    assert date_problems(date(2027, 1, 1), date(2027, 1, 1), today) == ["expiry_before_review"]
    assert date_problems(date(2027, 1, 1), date(2027, 1, 2), today) == []
    assert date_problems(None, date(2020, 1, 1), today) == []


def test_req_kb_040_six_levels_including_a_moved_subtree() -> None:
    assert depth_problem(None) is None
    assert depth_problem(MAX_TOPIC_DEPTH - 1) is None
    assert depth_problem(MAX_TOPIC_DEPTH) == "topic_too_deep"
    assert depth_problem(3, subtree_height=3) is None
    assert depth_problem(3, subtree_height=4) == "topic_too_deep"


def test_audience_problems() -> None:
    assert Audience().problems() == []
    assert Audience(tech_all=False).problems() == ["technician_audience_empty"]
    selected = Audience(requesters=RequesterAudience.SELECTED)
    assert selected.problems() == ["requester_audience_empty"]
    assert (
        Audience(requesters=RequesterAudience.SELECTED, req_sites=frozenset({SITE})).problems()
        == []
    )


def test_req_kb_044_ac3_an_article_only_narrows_its_topic() -> None:
    topic = Audience(tech_all=False, tech_groups=frozenset({GA, GB}))
    assert Audience(tech_all=False, tech_groups=frozenset({GA})).within(topic) == []
    assert Audience().within(topic) == ["wider_than_topic_technicians"]
    assert Audience(tech_all=False, tech_groups=frozenset({uuid.uuid4()})).within(topic) == [
        "wider_than_topic_technicians"
    ]
    # Requesters: none < selected < all; selected must stay inside the topic's selection.
    some = Audience(requesters=RequesterAudience.SELECTED, req_sites=frozenset({SITE}))
    assert Audience(requesters=RequesterAudience.ALL).within(some) == [
        "wider_than_topic_requesters"
    ]
    assert some.within(Audience(requesters=RequesterAudience.ALL)) == []
    other = Audience(requesters=RequesterAudience.SELECTED, req_departments=frozenset({DEPT}))
    assert other.within(some) == ["wider_than_topic_requesters"]
    assert Audience(requesters=RequesterAudience.NONE).within(Audience()) == []


def test_d108_4_who_reads_published_content() -> None:
    staff_a = Reader(staff=True, group_ids=frozenset({GA}))
    assert may_read(Audience(), staff_a)
    assert may_read(Audience(tech_all=False, tech_groups=frozenset({GA})), staff_a)
    assert not may_read(Audience(tech_all=False, tech_groups=frozenset({GB})), staff_a)

    requester = Reader(staff=False, group_ids=frozenset({GB}), site_ids=frozenset({SITE}))
    assert not may_read(Audience(), requester)  # technicians only by default
    assert may_read(Audience(requesters=RequesterAudience.ALL), requester)
    by_site = Audience(requesters=RequesterAudience.SELECTED, req_sites=frozenset({SITE}))
    assert may_read(by_site, requester)
    by_dept = Audience(requesters=RequesterAudience.SELECTED, req_departments=frozenset({DEPT}))
    assert not may_read(by_dept, requester)


# --- session 2: the review flow (REQ-KB-027, 028, 031, 035) ---------------------------------------


def test_req_kb_027_only_drafts_go_to_review_and_only_reviews_are_decided() -> None:
    assert submit_problem(VersionStatus.DRAFT) is None
    for status in (VersionStatus.IN_REVIEW, VersionStatus.PUBLISHED, VersionStatus.SUPERSEDED):
        assert submit_problem(status) == "kb_not_a_draft"
    assert decide_problem(VersionStatus.IN_REVIEW) is None
    for status in (VersionStatus.DRAFT, VersionStatus.PUBLISHED, VersionStatus.REJECTED):
        assert decide_problem(status) == "kb_not_in_review"


def test_req_kb_028_self_approval_follows_the_setting() -> None:
    author, other = uuid.uuid4(), uuid.uuid4()
    assert self_approval_problem(allowed=True, author_id=author, approver=author) is None
    assert self_approval_problem(allowed=False, author_id=author, approver=other) is None
    assert (
        self_approval_problem(allowed=False, author_id=author, approver=author)
        == "kb_self_approval_off"
    )


def test_req_kb_031_035_requesters_never_read_withdrawn_or_expired() -> None:
    everyone = Audience(requesters=RequesterAudience.ALL)
    requester = Reader(staff=False)
    live = {"requesters_enabled": True, "expired": False, "withdrawn": False}
    assert requester_may_read(everyone, requester, **live)
    assert not requester_may_read(everyone, requester, **{**live, "expired": True})
    assert not requester_may_read(everyone, requester, **{**live, "withdrawn": True})
    assert not requester_may_read(everyone, requester, **{**live, "requesters_enabled": False})
    assert not requester_may_read(Audience(), requester, **live)
    assert not requester_may_read(everyone, Reader(staff=True), **live)
