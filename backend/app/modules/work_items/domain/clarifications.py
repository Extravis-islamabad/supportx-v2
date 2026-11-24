"""Asking for clarification on a request approval (WP-047a S3a; REQ-SR-037). Pure, no I/O.

An approver may ask a question instead of deciding. It goes to the requester (a public message
in the request's conversation, which the portal shows) or to the request's technician (an
internal note). The stage stays pending and its reminders pause; the addressee's next reply
answers it and the approver is told. A decision, or the stage closing, ends it too.
"""

from enum import StrEnum

QUESTION_MAX = 2000


class Addressee(StrEnum):
    """Whom the question is for."""

    REQUESTER = "requester"
    TECHNICIAN = "technician"


class ClarificationEnd(StrEnum):
    """How an open question ended."""

    ANSWERED = "answered"  # the addressee replied
    DECIDED = "decided"  # the approver decided without waiting
    CLOSED = "closed"  # the approval itself closed (another decided, withdrawn, restarted)


def question_problems(question: str) -> list[tuple[str, str]]:
    """Field problems of a question."""
    text = question.strip()
    if not text:
        return [("question", "required")]
    if len(text) > QUESTION_MAX:
        return [("question", "too_long")]
    return []
