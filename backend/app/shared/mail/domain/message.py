"""An outgoing e-mail, pure (WP-039 session 2, D-089 D3: the one mail sender).

Callers (identity, notifications WP-023, scheduled reports WP-035) build an `OutgoingMail`
with the subject and bodies already rendered in the recipient's language; the mail service
queues it and the worker sends it. Nothing here does I/O.

Rules every message follows, whoever builds it:
- the sender is the installation's (or the tenant's configured sender, REQ-SEC-018); never a
  person's own address (REQ-SEC-019): there is no field for one;
- header values never contain line breaks (no header injection);
- at most `MAX_RECIPIENTS` recipients, attachments at most `MAX_ATTACHMENT_BYTES` in total.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from typing import Literal

from app.shared.action_links.domain import LinkRequest

MAX_RECIPIENTS = 50
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_SUBJECT = 300
LANGUAGES = ("en", "ar", "ur")
RTL_LANGUAGES = frozenset({"ar", "ur"})
# Attachment types callers may send (reports: CSV, Excel, PDF; WP-035).
ATTACHMENT_TYPES = frozenset(
    {
        "text/csv",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/plain",
    }
)
_ADDRESS = re.compile(r"^[^@\s<>\"',;:\\]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

Language = Literal["en", "ar", "ur"]


class MailRefused(ValueError):
    """The message breaks a rule above (`code` names it, for a translated message)."""

    def __init__(self, *, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Attachment:
    """A file sent with the message."""

    name: str
    content_type: str
    content: bytes = field(repr=False)


@dataclass(frozen=True)
class MailLink:
    """A one-time link the sender makes as it sends (D-132): never stored, never logged.

    The bodies hold `action_links.marker(name)` where it goes; at send the sender mints a token
    for `request` and puts `prefix + token` there, in the outgoing copy only.
    """

    name: str
    prefix: str  # e.g. "https://acme.example/portal/approve?t=acme#"
    request: LinkRequest


def links_to_json(links: tuple[MailLink, ...]) -> list[dict[str, object]] | None:
    """The links as stored with a queued message or a waiting delivery (no token)."""
    if not links:
        return None
    return [
        {
            "name": link.name,
            "prefix": link.prefix,
            "recipient_id": str(link.request.recipient_id),
            "action": link.request.action,
            "object_type": link.request.object_type,
            "object_id": str(link.request.object_id),
            "object_version": link.request.object_version,
        }
        for link in links
    ]


def links_from_json(value: object) -> tuple[MailLink, ...]:
    """The stored links back (an empty tuple for none)."""
    if not isinstance(value, list):
        return ()
    return tuple(
        MailLink(
            name=str(item["name"]),
            prefix=str(item["prefix"]),
            request=LinkRequest(
                recipient_id=uuid.UUID(str(item["recipient_id"])),
                action=str(item["action"]),
                object_type=str(item["object_type"]),
                object_id=uuid.UUID(str(item["object_id"])),
                object_version=int(item["object_version"]),
            ),
        )
        for item in value
        if isinstance(item, dict)
    )


@dataclass(frozen=True)
class OutgoingMail:
    """One message, rendered. `kind` names its purpose (e.g. `report`, `notification`)."""

    kind: str
    to: tuple[str, ...]
    subject: str
    text: str
    language: Language = "en"
    html: str | None = None
    reply_to: str | None = None
    sender_name: str | None = None  # the tenant's sender name; else the installation's
    attachments: tuple[Attachment, ...] = ()
    links: tuple[MailLink, ...] = ()  # D-132: made at send, see MailLink


def _no_breaks(value: str) -> bool:
    return "\r" not in value and "\n" not in value


def check(mail: OutgoingMail) -> None:
    """Raise MailRefused when the message breaks a rule (module docstring)."""
    _check_addresses(mail)
    _check_headers(mail)
    _check_attachments(mail.attachments)


def _check_addresses(mail: OutgoingMail) -> None:
    if not mail.to or len(mail.to) > MAX_RECIPIENTS:
        raise MailRefused(code="mail_recipients")
    addresses = [*mail.to, *([mail.reply_to] if mail.reply_to is not None else [])]
    if any(not _ADDRESS.fullmatch(address) for address in addresses):
        raise MailRefused(code="mail_address_invalid")


def _check_headers(mail: OutgoingMail) -> None:
    if not mail.subject or len(mail.subject) > MAX_SUBJECT or not _no_breaks(mail.subject):
        raise MailRefused(code="mail_subject_invalid")
    if mail.sender_name is not None and not _no_breaks(mail.sender_name):
        raise MailRefused(code="mail_sender_invalid")
    if mail.language not in LANGUAGES:
        raise MailRefused(code="mail_language_invalid")
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,39}", mail.kind):
        raise MailRefused(code="mail_kind_invalid")


def _check_attachments(attachments: tuple[Attachment, ...]) -> None:
    total = 0
    for attachment in attachments:
        if attachment.content_type not in ATTACHMENT_TYPES:
            raise MailRefused(code="mail_attachment_type")
        if not attachment.name or not _no_breaks(attachment.name) or "/" in attachment.name:
            raise MailRefused(code="mail_attachment_name")
        total += len(attachment.content)
    if total > MAX_ATTACHMENT_BYTES:
        raise MailRefused(code="mail_attachments_too_large")


def build_mime(
    mail: OutgoingMail,
    *,
    from_address: str,
    from_name: str,
    message_id_domain: str,
    sent_at: datetime,
) -> EmailMessage:
    """The MIME message: text (and HTML) alternatives, attachments, safe headers."""
    check(mail)
    message = EmailMessage()
    message["From"] = Address(display_name=mail.sender_name or from_name, addr_spec=from_address)
    message["To"] = ", ".join(mail.to)
    if mail.reply_to is not None:
        message["Reply-To"] = mail.reply_to
    message["Subject"] = mail.subject
    message["Date"] = format_datetime(sent_at)
    message["Message-ID"] = make_msgid(domain=message_id_domain)
    message["Auto-Submitted"] = "auto-generated"  # RFC 3834: no auto-replies to it
    message.set_content(mail.text)
    if mail.html is not None:
        message.add_alternative(mail.html, subtype="html")
    for attachment in mail.attachments:
        main, _, sub = attachment.content_type.partition("/")
        message.add_attachment(
            attachment.content, maintype=main, subtype=sub, filename=attachment.name
        )
    # After the body: setting content replaces every Content-* header.
    message["Content-Language"] = mail.language
    return message
