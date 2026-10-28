"""Mailboxes and what an incoming message becomes (WP-024). Pure rules, no I/O.

Requirements: REQ-INT-051, REQ-INC-023, REQ-INC-024, REQ-INC-027, REQ-NTF-023.

For each fetched message, in this order:

1. automatic mail (auto-reply, bounce, list) → logged on the record it answers, nothing created,
   nobody notified (REQ-NTF-023, REQ-INC-024 AC2);
2. one of our own addresses as sender → ignored (a loop with ourselves);
3. more than `PER_SENDER_LIMIT` messages from one address in the last hour → held, admins told
   (two systems answering each other, REQ-NTF-023 AC3);
4. it answers a record (threading headers or the subject token) → a reply on that record;
5. the mailbox only threads replies → refused with the configured answer (REQ-INT-051 AC2);
6. the sender is unknown → the mailbox's policy: create the requester (any address, or only the
   allowed domains), or refuse with a polite answer (REQ-INC-027); hold for review comes later;
7. otherwise → a new record of the mailbox's kind, in its group and desk.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

PER_SENDER_LIMIT = 10  # messages per address per hour before holding (proposed default)
POLL_SECONDS = 120  # Appendix A (file 12): every 2 minutes
MAX_MESSAGE_BYTES = 35 * 1024 * 1024  # Appendix A: largest accepted message


class MailboxProtocol(StrEnum):
    """How a mailbox is read."""

    IMAP = "imap"


class ConnectionSecurity(StrEnum):
    """Transport security of an IMAP or SMTP connection."""

    TLS = "tls"  # implicit TLS (IMAPS 993)
    STARTTLS = "starttls"
    NONE = "none"  # refused unless the admin allows it (REQ-INT-050 AC3), audited


class AfterFetch(StrEnum):
    """What happens to a message on the mail server once it is in SupportX (REQ-ADM-067)."""

    MARK_READ = "mark_read"  # the default: nothing is deleted
    MOVE = "move"  # to the chosen folder
    DELETE = "delete"  # only when the admin chooses it


class MailboxCreates(StrEnum):
    """What a new (non-reply) message to the mailbox becomes."""

    INCIDENT = "incident"
    NOTHING = "nothing"  # replies only


class UnknownSenders(StrEnum):
    """What mail from an address SupportX does not know does (REQ-INC-027)."""

    CREATE = "create"  # any address becomes a requester
    CREATE_ALLOWED_DOMAINS = "create_allowed_domains"
    REJECT = "reject"  # a polite answer, nothing created


class MailboxState(StrEnum):
    """What the mail page shows for a mailbox (REQ-ADM-066 AC1)."""

    NOT_SET_UP = "not_set_up"
    WORKING = "working"
    FAILING = "failing"


class Outcome(StrEnum):
    """What one fetched message became (the ledger, and the mail page's counts)."""

    CREATED = "created"
    REPLIED = "replied"
    AUTOMATIC = "automatic"
    OWN_ADDRESS = "own_address"
    HELD = "held"
    REJECTED = "rejected"
    TOO_LARGE = "too_large"


@dataclass(frozen=True)
class MailboxRules:
    """The parts of a mailbox the routing needs."""

    address: str
    creates: MailboxCreates
    unknown_senders: UnknownSenders
    allowed_domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class Routing:
    """The decision for one message; `reason` says why when nothing is created."""

    outcome: Outcome
    reason: str | None = None
    create_requester: bool = False  # the sender becomes a new requester first


def domain_of(address: str) -> str:
    """`sara@Acme.Test` → `acme.test`."""
    return address.rsplit("@", 1)[-1].lower() if "@" in address else ""


def route(  # noqa: PLR0911, PLR0913 - one decision per rule in the module docstring, in order
    *,
    mailbox: MailboxRules,
    automatic: str | None,
    sender: str,
    own_addresses: Iterable[str],
    recent_from_sender: int,
    answers_record: bool,
    sender_known: bool,
    size: int = 0,
) -> Routing:
    """What one message becomes, by the rules above."""
    if size > MAX_MESSAGE_BYTES:
        return Routing(Outcome.TOO_LARGE, "too_large")
    if automatic is not None:
        return Routing(Outcome.AUTOMATIC, automatic)
    if sender.lower() in {a.lower() for a in own_addresses}:
        return Routing(Outcome.OWN_ADDRESS, "own_address")
    if recent_from_sender >= PER_SENDER_LIMIT:
        return Routing(Outcome.HELD, "sender_rate")
    if answers_record:
        return Routing(Outcome.REPLIED)
    if mailbox.creates is MailboxCreates.NOTHING:
        return Routing(Outcome.REJECTED, "replies_only")
    if sender_known:
        return Routing(Outcome.CREATED)
    policy = mailbox.unknown_senders
    if policy is UnknownSenders.CREATE:
        return Routing(Outcome.CREATED, create_requester=True)
    allowed = {d.lower().lstrip("@") for d in mailbox.allowed_domains}
    if policy is UnknownSenders.CREATE_ALLOWED_DOMAINS and domain_of(sender) in allowed:
        return Routing(Outcome.CREATED, create_requester=True)
    return Routing(Outcome.REJECTED, "unknown_sender")


def check_security(security: ConnectionSecurity, *, allow_plain: bool) -> list[str]:
    """Field problems of a connection's security (REQ-INT-050 AC3, REQ-INT-053 AC3)."""
    if security is ConnectionSecurity.NONE and not allow_plain:
        return ["plain_connection_refused"]
    return []
