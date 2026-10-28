"""What an incoming message becomes (WP-024): pure routing rules."""

import pytest

from app.modules.integrations.domain.mailboxes import (
    MAX_MESSAGE_BYTES,
    PER_SENDER_LIMIT,
    ConnectionSecurity,
    MailboxCreates,
    MailboxRules,
    Outcome,
    UnknownSenders,
    check_security,
    route,
)

IT = MailboxRules(
    address="it@acme.test",
    creates=MailboxCreates.INCIDENT,
    unknown_senders=UnknownSenders.CREATE_ALLOWED_DOMAINS,
    allowed_domains=("acme.test",),
)


def _route(**changes: object) -> Outcome:
    values: dict[str, object] = {
        "mailbox": IT,
        "automatic": None,
        "sender": "sara@acme.test",
        "own_addresses": ("it@acme.test", "support@supportx.test"),
        "recent_from_sender": 0,
        "answers_record": False,
        "sender_known": True,
    } | changes
    return route(**values).outcome  # type: ignore[arg-type]  # test table of keyword values


def test_a_known_person_creates_an_incident() -> None:
    assert _route() is Outcome.CREATED


def test_a_reply_goes_to_its_record_even_on_a_replies_only_mailbox() -> None:
    replies_only = MailboxRules("hr@acme.test", MailboxCreates.NOTHING, UnknownSenders.REJECT)
    assert _route(answers_record=True, mailbox=replies_only) is Outcome.REPLIED
    assert _route(mailbox=replies_only) is Outcome.REJECTED  # REQ-INT-051 AC2


@pytest.mark.parametrize("reason", ["auto_submitted", "bounce", "mailing_list"])
def test_automatic_mail_never_creates_or_notifies(reason: str) -> None:
    assert _route(automatic=reason, answers_record=True) is Outcome.AUTOMATIC  # REQ-INC-024 AC2


def test_our_own_address_is_a_loop() -> None:
    assert _route(sender="Support@SupportX.test") is Outcome.OWN_ADDRESS


def test_two_systems_answering_each_other_are_held() -> None:
    assert _route(recent_from_sender=PER_SENDER_LIMIT - 1) is Outcome.CREATED
    assert _route(recent_from_sender=PER_SENDER_LIMIT) is Outcome.HELD  # REQ-NTF-023 AC3


def test_unknown_senders_follow_the_mailbox_policy() -> None:
    """REQ-INC-027 AC1, AC2."""
    allowed = route(
        mailbox=IT,
        automatic=None,
        sender="new@acme.test",
        own_addresses=(),
        recent_from_sender=0,
        answers_record=False,
        sender_known=False,
    )
    assert (allowed.outcome, allowed.create_requester) == (Outcome.CREATED, True)
    assert _route(sender="new@elsewhere.test", sender_known=False) is Outcome.REJECTED
    anyone = MailboxRules("it@acme.test", MailboxCreates.INCIDENT, UnknownSenders.CREATE)
    assert _route(sender="new@elsewhere.test", sender_known=False, mailbox=anyone) is (
        Outcome.CREATED
    )


def test_a_message_too_large_is_refused() -> None:
    assert _route(size=MAX_MESSAGE_BYTES + 1) is Outcome.TOO_LARGE


def test_plain_connections_need_the_admins_say_so() -> None:
    assert check_security(ConnectionSecurity.NONE, allow_plain=False) == [
        "plain_connection_refused"
    ]
    assert check_security(ConnectionSecurity.NONE, allow_plain=True) == []
    assert check_security(ConnectionSecurity.TLS, allow_plain=False) == []
