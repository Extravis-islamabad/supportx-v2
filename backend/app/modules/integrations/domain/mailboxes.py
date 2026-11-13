"""Mailboxes and what an incoming message becomes (WP-024). Pure rules, no I/O.

Requirements: REQ-INT-051, REQ-INC-023, REQ-INC-024, REQ-INC-027, REQ-NTF-023.

For each fetched message, in this order:

1. automatic mail (auto-reply, bounce, list) → logged on the record it answers, nothing created,
   nobody notified (REQ-NTF-023, REQ-INC-024 AC2);
2. one of our own addresses as sender → ignored (a loop with ourselves);
2b. a block rule matches → blocked: nothing created, kept for review (REQ-INC-026);
3. more than `PER_SENDER_LIMIT` messages from one address in the last hour → held, admins told
   (two systems answering each other, REQ-NTF-023 AC3);
4. it answers a record (threading headers or the subject token) → a reply on that record;
5. the mailbox only threads replies → refused with the configured answer (REQ-INT-051 AC2);
6. the sender is unknown → the mailbox's policy: create the requester (any address, or only the
   allowed domains), or refuse with a polite answer (REQ-INC-027); hold for review comes later;
7. otherwise → a new record of the mailbox's kind, in its group and desk.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.shared.connectors.ports import ConnectorStatus

PER_SENDER_LIMIT = 10  # messages per address per hour before holding (proposed default)
POLL_SECONDS = 120  # Appendix A (file 12): every 2 minutes
MAX_MESSAGE_BYTES = 35 * 1024 * 1024  # Appendix A: largest accepted message


class MailboxProtocol(StrEnum):
    """How a mailbox is read."""

    IMAP = "imap"
    GRAPH = "graph"  # Microsoft 365 through Microsoft Graph (OAuth 2.0, D-109 (2))
    GMAIL = "gmail"  # Google Workspace through the Gmail API (OAuth 2.0)


class AuthModel(StrEnum):
    """How an API mailbox signs in (docs/guides/mail-oauth-apps.md)."""

    APP = "app"  # Graph application permission: no one signs in (model A)
    DELEGATED = "delegated"  # someone signs in as the mailbox once; a refresh token is kept


class CredentialKind(StrEnum):
    """What proves the customer's OAuth app (client) to Microsoft or Google."""

    SECRET = "secret"  # noqa: S105 - a kind of credential, not a password
    CERTIFICATE = "certificate"  # Microsoft only: a private key signs each token request


# Least privilege (D-109 (2), listed in docs/guides/mail-oauth-apps.md): read, mark and move mail.
# Never sending, never full mailbox access.
GRAPH_APP_SCOPES = ("https://graph.microsoft.com/.default",)  # the app's granted Mail.ReadWrite
GRAPH_DELEGATED_SCOPES = ("offline_access", "https://graph.microsoft.com/Mail.ReadWrite")
GMAIL_SCOPES = ("https://www.googleapis.com/auth/gmail.modify",)
CREDENTIAL_WARNING_DAYS = 14  # an expiring client secret or certificate is announced this early


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


CONNECTOR_KIND = "mailbox"  # the catalogue's code for mailboxes (WP-040)
# The provider refused the credential, or there is none: failing at once, not after 3 runs.
AUTH_FAILURES = frozenset(
    {
        "imap_login_failed",
        "mailbox_no_password",
        "mailbox_secret_unreadable",
        "mailbox_key_ring_missing",
        "oauth_certificate_invalid",
        "oauth_client_rejected",
        "oauth_consent_revoked",
        "oauth_not_allowed",
        "oauth_not_connected",
        "oauth_wrong_account",
    }
)
SECRET_FALLBACK = "secret_store_fallback"  # noqa: S105 - a reason code (degraded), no secret


def connector_status(
    state: str, *, enabled: bool, secret_fallback: bool = False
) -> ConnectorStatus:
    """How the connector catalogue shows a mailbox (REQ-INT-001): switched off is "paused".

    A working mailbox whose secret came from the old column instead of the secrets store is
    "degraded" (WP-040): it works, but the move needs an admin's look.
    """
    if not enabled:
        return ConnectorStatus.PAUSED
    if state == MailboxState.WORKING.value and secret_fallback:
        return ConnectorStatus.DEGRADED
    return {
        MailboxState.WORKING.value: ConnectorStatus.ACTIVE,
        MailboxState.FAILING.value: ConnectorStatus.FAILED,
    }.get(state, ConnectorStatus.NOT_SET_UP)


class Outcome(StrEnum):
    """What one fetched message became (the ledger, and the mail page's counts)."""

    CREATED = "created"
    REPLIED = "replied"
    AUTOMATIC = "automatic"
    OWN_ADDRESS = "own_address"
    HELD = "held"
    REJECTED = "rejected"
    TOO_LARGE = "too_large"
    DISCARDED = "discarded"  # an admin discarded it from the review queue
    BLOCKED = "blocked"  # a block rule matched: kept for review for the quarantine days


# What waits in the review queue on Admin > Mail (held mail is never invisible, D-109 (9)).
WAITING = (Outcome.HELD, Outcome.TOO_LARGE, Outcome.BLOCKED)
# Held for a reason a second try can overcome: a flood (the admin vouches), no record owner yet,
# or the owning module's refusal (fixed since, e.g. a required field). The rest is discard-only:
# staff reply in the console, and too-large mail was never taken in.
NOT_RELEASABLE = frozenset({"not_requester"})


def releasable(outcome: Outcome, reason: str | None) -> bool:
    """Whether an admin may hand a waiting message in again."""
    if outcome is Outcome.BLOCKED:  # an admin may let blocked mail through (REQ-INC-026 AC2)
        return True
    return outcome is Outcome.HELD and reason not in NOT_RELEASABLE


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


def route(  # noqa: C901, PLR0911, PLR0913 - one decision per rule in the module docstring, in order
    *,
    mailbox: MailboxRules,
    automatic: str | None,
    sender: str,
    own_addresses: Iterable[str],
    recent_from_sender: int,
    answers_record: bool,
    sender_known: bool,
    size: int = 0,
    blocked: bool = False,
) -> Routing:
    """What one message becomes, by the rules above."""
    if size > MAX_MESSAGE_BYTES:
        return Routing(Outcome.TOO_LARGE, "too_large")
    if automatic is not None:
        return Routing(Outcome.AUTOMATIC, automatic)
    if sender.lower() in {a.lower() for a in own_addresses}:
        return Routing(Outcome.OWN_ADDRESS, "own_address")
    if blocked:
        return Routing(Outcome.BLOCKED, "block_rule")
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


def oauth_problems(  # noqa: PLR0913 - one check per field, explicit
    protocol: MailboxProtocol,
    *,
    auth_model: AuthModel | None,
    credential_kind: CredentialKind | None,
    client_id: str | None,
    directory_id: str | None,
    has_credential: bool,
) -> list[tuple[str, str]]:
    """(field, code) problems of an API mailbox's sign-in settings; none for IMAP."""
    if protocol is MailboxProtocol.IMAP:
        return []
    problems: list[tuple[str, str]] = []
    if not client_id:
        problems.append(("client_id", "required"))
    if not has_credential:
        problems.append(("client_secret", "required"))
    if protocol is MailboxProtocol.GRAPH:
        if not directory_id:
            problems.append(("directory_id", "required"))
        if auth_model is None:
            problems.append(("auth_model", "required"))
    elif auth_model is AuthModel.APP:
        # Gmail without someone signing in needs domain-wide delegation, not offered (it reaches
        # every mailbox of the Workspace).
        problems.append(("auth_model", "mailbox_auth_model_unsupported"))
    if protocol is MailboxProtocol.GMAIL and credential_kind is CredentialKind.CERTIFICATE:
        problems.append(("credential_kind", "mailbox_auth_model_unsupported"))
    return problems


def scopes_for(protocol: MailboxProtocol, auth_model: AuthModel) -> tuple[str, ...]:
    """The OAuth scopes SupportX asks for: the least that reads, marks and moves mail."""
    if protocol is MailboxProtocol.GMAIL:
        return GMAIL_SCOPES
    return GRAPH_APP_SCOPES if auth_model is AuthModel.APP else GRAPH_DELEGATED_SCOPES


def needs_sign_in(protocol: MailboxProtocol, auth_model: AuthModel | None) -> bool:
    """Whether someone must sign in as the mailbox (a consent screen) before it can be read."""
    return protocol is not MailboxProtocol.IMAP and auth_model is not AuthModel.APP


def credential_warning_due(
    expires_at: datetime | None, warned_at: datetime | None, now: datetime
) -> bool:
    """Whether to announce an expiring credential now (once per expiry date)."""
    if expires_at is None or expires_at - now > timedelta(days=CREDENTIAL_WARNING_DAYS):
        return False
    return warned_at is None or warned_at < expires_at - timedelta(days=CREDENTIAL_WARNING_DAYS)


def check_security(security: ConnectionSecurity, *, allow_plain: bool) -> list[str]:
    """Field problems of a connection's security (REQ-INT-050 AC3, REQ-INT-053 AC3)."""
    if security is ConnectionSecurity.NONE and not allow_plain:
        return ["plain_connection_refused"]
    return []


# The ports a tenant's IMAP host may be reached on (audit #3): never a port scanner.
IMAP_PORTS = frozenset({143, 993})


# --- whose Authentication-Results a mailbox believes (WP-046a S6; lane B's conditions) -------

TRUSTED_SERVERS_MAX = 5
QUARANTINE_DAYS = (1, 90)
_HOST_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def host_name(value: str) -> str | None:
    """A host name lowercased (`mx.google.com`), or None when it is not one.

    At least two labels of letters, digits and hyphens, 253 characters at most. No addresses,
    ports or wildcards.
    """
    name = value.strip().lower().rstrip(".")
    labels = name.split(".")
    if len(name) > 253 or len(labels) < 2 or not all(_HOST_LABEL.match(x) for x in labels):  # noqa: PLR2004 - RFC 1035 length, two labels
        return None
    return name


def trust_problems(
    protocol: MailboxProtocol, servers: Sequence[str], *, trust_provider: bool
) -> list[tuple[str, str]]:
    """(field, code) problems of what a mailbox trusts to vouch for senders."""
    problems: list[tuple[str, str]] = []
    if len(servers) > TRUSTED_SERVERS_MAX:
        problems.append(("trusted_servers", "trusted_servers_too_many"))
    if any(host_name(s) is None for s in servers):
        problems.append(("trusted_servers", "host_name_invalid"))
    if trust_provider and protocol is not MailboxProtocol.GRAPH:
        # Only Microsoft 365 writes its result without a name; anywhere else an id-less header
        # could be anyone's.
        problems.append(("trust_provider_results", "mailbox_provider_results_graph_only"))
    return problems


# --- unwanted mail (WP-046a S6; REQ-INC-026) ----------------------------------------------------


class BlockKind(StrEnum):
    """What a block rule looks at. Plain text only: never a pattern an admin types (ReDoS)."""

    SENDER = "sender"  # the address, exactly
    DOMAIN = "domain"  # the sender's domain, or any subdomain of it
    SUBJECT = "subject"  # text the subject contains
    BODY = "body"  # text the body contains


@dataclass(frozen=True)
class BlockRule:
    """One enabled rule, its value as stored."""

    kind: BlockKind
    value: str


BODY_SCANNED = 64 * 1024  # characters of a body a rule reads


def block_rule_problems(kind: BlockKind, value: str) -> list[tuple[str, str]]:
    """(field, code) problems of a rule's value."""
    text = value.strip()
    if not text:
        return [("value", "required")]
    if kind is BlockKind.SENDER and ("@" not in text or " " in text):
        return [("value", "mailbox_address_invalid")]
    if kind is BlockKind.DOMAIN and host_name(text.lstrip("@")) is None:
        return [("value", "host_name_invalid")]
    return []


def normalised_rule_value(kind: BlockKind, value: str) -> str:
    """How a rule's value is stored: trimmed; addresses and domains lowercased."""
    text = value.strip()
    if kind is BlockKind.SENDER:
        return text.lower()
    if kind is BlockKind.DOMAIN:
        return text.lstrip("@").lower().rstrip(".")
    return text


def blocked_by(rules: Iterable[BlockRule], *, sender: str, subject: str, text: str) -> bool:
    """Whether any rule matches the message (case-insensitive, plain text)."""
    address = sender.strip().lower()
    domain = domain_of(address)
    subject_cf = subject.casefold()
    body_cf = text[:BODY_SCANNED].casefold()
    for rule in rules:
        value = rule.value.strip()
        if not value:
            continue
        if rule.kind is BlockKind.SENDER and address == value.lower():
            return True
        if rule.kind is BlockKind.DOMAIN:
            wanted = value.lower().lstrip("@").rstrip(".")
            if domain == wanted or domain.endswith("." + wanted):
                return True
        if rule.kind is BlockKind.SUBJECT and value.casefold() in subject_cf:
            return True
        if rule.kind is BlockKind.BODY and value.casefold() in body_cf:
            return True
    return False
