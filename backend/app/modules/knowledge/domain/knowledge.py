"""Knowledge rules (WP-033; parity file 08, D-108). Pure: no I/O.

An article lives in one topic and has versions per language (English and Arabic at MVP, Urdu
V1). A version's status is draft, in_review, published, superseded or rejected; "expired" and
"review due" are flags computed from dates, never statuses (REQ-KB-026). Who may see an article
(its audience) comes from its topic and may only narrow it (REQ-KB-044).
"""

import calendar
import uuid
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

MAX_TOPIC_DEPTH = 6  # REQ-KB-003 AC3
ID_PREFIX = "KB"  # D-108 (8): KB-1, KB-2 ...


class KbLanguage(StrEnum):
    """Languages an article can be written in (REQ-KB-049; Urdu articles are V1, D-108)."""

    EN = "en"
    AR = "ar"


class VersionStatus(StrEnum):
    """One version's place in its life (REQ-KB-026)."""

    DRAFT = "draft"
    IN_REVIEW = "in_review"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"  # an earlier published version, kept (REQ-KB-020)
    REJECTED = "rejected"


class RequesterAudience(StrEnum):
    """Who among requesters may read (REQ-KB-045)."""

    NONE = "none"
    ALL = "all"
    SELECTED = "selected"  # requester groups, sites or departments


@dataclass(frozen=True)
class ArticleType:
    """A built-in article type (file 08 Appendix A): its review interval in months."""

    code: str
    review_months: int
    needs_problems: bool = False  # workaround and known issue: only with problems (REQ-KB-008)


BUILTIN_TYPES: tuple[ArticleType, ...] = (
    ArticleType("how_to", 12),
    ArticleType("troubleshooting", 12),
    ArticleType("faq", 12),
    ArticleType("reference", 24),
    ArticleType("policy", 12),
    ArticleType("workaround", 3, needs_problems=True),
    ArticleType("known_issue", 1, needs_problems=True),
)


@dataclass(frozen=True)
class Audience:
    """Who may read: technicians (all, or chosen groups) and requesters (REQ-KB-044, 045)."""

    tech_all: bool = True
    tech_groups: frozenset[uuid.UUID] = frozenset()
    requesters: RequesterAudience = RequesterAudience.NONE
    req_groups: frozenset[uuid.UUID] = frozenset()
    req_sites: frozenset[uuid.UUID] = frozenset()
    req_departments: frozenset[uuid.UUID] = frozenset()

    def problems(self) -> list[str]:
        """Codes of what is wrong with the audience itself."""
        found: list[str] = []
        if not self.tech_all and not self.tech_groups:
            found.append("technician_audience_empty")
        if self.requesters == RequesterAudience.SELECTED and not (
            self.req_groups or self.req_sites or self.req_departments
        ):
            found.append("requester_audience_empty")
        return found

    def within(self, topic: "Audience") -> list[str]:
        """Codes where this (an article's own audience) is wider than its topic's (AC3)."""
        found: list[str] = []
        if not topic.tech_all and (self.tech_all or not self.tech_groups <= topic.tech_groups):
            found.append("wider_than_topic_technicians")
        widest = {
            RequesterAudience.NONE: 0,
            RequesterAudience.SELECTED: 1,
            RequesterAudience.ALL: 2,
        }
        if widest[self.requesters] > widest[topic.requesters] or (
            self.requesters == RequesterAudience.SELECTED
            and topic.requesters == RequesterAudience.SELECTED
            and not (
                self.req_groups <= topic.req_groups
                and self.req_sites <= topic.req_sites
                and self.req_departments <= topic.req_departments
            )
        ):
            found.append("wider_than_topic_requesters")
        return found


@dataclass(frozen=True)
class Reader:
    """Who is reading, as far as audiences go."""

    staff: bool
    group_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    site_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    department_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)


def may_read(audience: Audience, reader: Reader) -> bool:
    """Whether `reader` is in `audience` (published content; drafts have their own rule)."""
    if reader.staff:
        return audience.tech_all or bool(audience.tech_groups & reader.group_ids)
    if audience.requesters == RequesterAudience.ALL:
        return True
    if audience.requesters == RequesterAudience.SELECTED:
        return bool(
            audience.req_groups & reader.group_ids
            or audience.req_sites & reader.site_ids
            or audience.req_departments & reader.department_ids
        )
    return False


def add_months(day: date, months: int) -> date:
    """`day` plus `months`, on the last day of a shorter month (31 Jan + 1 → 28/29 Feb)."""
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def default_review(today: date, review_months: int) -> date:
    """A new article's review date from its type's interval (REQ-KB-034 AC1)."""
    return add_months(today, review_months)


def date_problems(review_on: date | None, expires_on: date | None, today: date) -> list[str]:
    """Review today or later is fine (AC2: today accepted); expiry after the review (AC3)."""
    found: list[str] = []
    if review_on is not None and review_on < today:
        found.append("review_date_past")
    if review_on is not None and expires_on is not None and expires_on <= review_on:
        found.append("expiry_before_review")
    return found


def depth_problem(parent_depth: int | None, subtree_height: int = 1) -> str | None:
    """A topic (with its subtree) placed under a parent must stay within six levels."""
    depth = (parent_depth or 0) + subtree_height
    return "topic_too_deep" if depth > MAX_TOPIC_DEPTH else None


# --- review and approval (session 2; REQ-KB-027, 028, 031, 034) ---------------------------------


class WorkflowStep(StrEnum):
    """What happened to an article or one of its versions, for events and notifications."""

    SUBMITTED = "submitted"  # a draft went to review
    APPROVED = "approved"  # published to its audience (REQ-KB-027)
    REJECTED = "rejected"  # sent back to its author with a reason
    WITHDRAWN = "withdrawn"  # taken off every reader path (REQ-KB-031)
    REVIEWED = "reviewed"  # "still correct": the review date moved, no new version (REQ-KB-034)
    DELETED = "deleted"  # to the trash (REQ-KB-079)
    RESTORED = "restored"  # back from the trash
    REVIEW_DUE = "review_due"  # its review date came (REQ-KB-034, 086): the owner hears it once


def submit_problem(status: VersionStatus) -> str | None:
    """Only a draft goes to review."""
    return None if status == VersionStatus.DRAFT else "kb_not_a_draft"


def decide_problem(status: VersionStatus) -> str | None:
    """Only a version in review is approved or sent back."""
    return None if status == VersionStatus.IN_REVIEW else "kb_not_in_review"


def self_approval_problem(
    *, allowed: bool, author_id: uuid.UUID | None, approver: uuid.UUID
) -> str | None:
    """Approving your own version follows the setting (REQ-KB-028; on by default)."""
    if allowed or author_id != approver:
        return None
    return "kb_self_approval_off"


def requester_may_read(
    audience: "Audience",
    reader: "Reader",
    *,
    requesters_enabled: bool,
    expired: bool,
    withdrawn: bool,
) -> bool:
    """A requester reads a published article only inside its audience, unexpired and live."""
    if reader.staff or not requesters_enabled or expired or withdrawn:
        return False
    return may_read(audience, reader)
