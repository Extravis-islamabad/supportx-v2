"""Asking for clarification on a request approval (WP-047a S3a; REQ-SR-037). Pure, no I/O.

An approver may ask a question instead of deciding. It goes to the requester (a public message
in the request's conversation, which the portal shows) or to the request's technician (an
internal note). The stage stays pending and its reminders pause; the addressee's next reply
answers it and the approver is told. A decision, or the stage closing, ends it too.
"""

from enum import StrEnum

QUESTION_MAX = 2000
# The field problems a question can have (each needs an `errors.field.*` label).
FIELD_PROBLEMS = frozenset(
    {
        "required",
        "question_too_long",
        "no_technician",
        "is_you",
    }
)


class Addressee(StrEnum):
    """Whom the question is for."""

    REQUESTER = "requester"
    TECHNICIAN = "technician"


class ClarificationEnd(StrEnum):
    """How an open question ended."""

    ANSWERED = "answered"  # the addressee replied
    DECIDED = "decided"  # the approver decided without waiting
    CLOSED = "closed"  # the approval itself closed (another decided, withdrawn, restarted)


class ClarificationState(StrEnum):
    """A clarification as shown on its approval: still open, or how it ended."""

    OPEN = "open"
    ANSWERED = "answered"
    DECIDED = "decided"
    CLOSED = "closed"


def state_of(ended_how: str | None) -> ClarificationState:
    """The shown state of a clarification row."""
    return ClarificationState.OPEN if ended_how is None else ClarificationState(ended_how)


def question_problems(question: str) -> list[tuple[str, str]]:
    """Field problems of a question."""
    text = question.strip()
    if not text:
        return [("question", "required")]
    if len(text) > QUESTION_MAX:
        return [("question", "question_too_long")]
    return []
