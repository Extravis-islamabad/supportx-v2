"""Reading an approval reply (WP-047a S4; REQ-SR-038): clear decisions only, never a guess."""

import pytest

from app.modules.work_items.domain.approval_replies import ReplyIntent, read_reply
from app.modules.work_items.domain.approvals import COMMENT_MAX, Decision

APPROVE, REJECT = Decision.APPROVE, Decision.REJECT


@pytest.mark.parametrize(
    ("text", "decision"),
    [
        ("Approved, thanks", APPROVE),  # AC1
        ("approve", APPROVE),
        ("YES.", APPROVE),
        ("Approved! Thank you very much", APPROVE),
        ("Reject", REJECT),
        ("Rejected.", REJECT),
        ("Thanks, approved", APPROVE),
        ("Declined - thanks", REJECT),
        ("موافق، شكراً", APPROVE),  # Arabic, with tanween and the Arabic comma
        ("نعم", APPROVE),
        ("مرفوض", REJECT),
        ("منظور، شکریہ", APPROVE),  # Urdu
        ("جی ہاں", APPROVE),  # Urdu's polite "yes"
        ("مسترد", REJECT),
    ],
)
def test_a_clear_first_line_is_a_decision(text: str, decision: Decision) -> None:
    assert read_reply(text).decision is decision


@pytest.mark.parametrize(
    "text",
    [
        "approve only if cheaper",  # AC3: a qualified decision is never applied
        "not approved",
        "No problem, approved",
        "I approve",
        "approve but check the budget",
        "approved?? reject",
        "Can we talk first?",
        "",
        "   \n\n",
        "!!!",
        "Thanks",  # courtesy alone decides nothing
        "موافق بشرط",  # Arabic: "approve on condition"
        "منظور لیکن",  # Urdu: "approved but"
    ],
)
def test_anything_else_is_unclear(text: str) -> None:
    assert read_reply(text) == ReplyIntent(None)


def test_the_lines_after_the_decision_are_its_comment() -> None:
    found = read_reply("Approved\n\nPlease order the 16 GB model.\nThanks")
    assert found.decision is APPROVE
    assert found.comment == "Please order the 16 GB model.\nThanks"


def test_quoted_mail_and_signatures_are_not_the_reply() -> None:
    quoted = "Reject\nWrong cost centre.\n\nOn Mon, 24 Nov 2026 Desk wrote:\n> Approve or reject"
    assert read_reply(quoted) == ReplyIntent(REJECT, "Wrong cost centre.")
    signed = "approved\n-- \nAisha Approver\nFinance"
    assert read_reply(signed) == ReplyIntent(APPROVE, None)
    # A decision word only in the quoted part is not a reply.
    assert read_reply("\n> approved\n").decision is None


def test_a_comment_longer_than_a_decision_allows_is_unclear() -> None:
    assert read_reply("approve\n" + "x" * (COMMENT_MAX + 1)).decision is None
