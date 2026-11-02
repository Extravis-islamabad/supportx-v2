"""Incoming e-mail, read without I/O (WP-024; REQ-INC-023, -024, REQ-NTF-023).

`parse(raw)` turns one RFC 5322 message into an `InboundMessage`: who sent it, the threading
headers, the subject with our record token, the plain and HTML bodies, the attachments, and
whether it is automatic mail (auto-reply, bounce, mailing list) that must never create a record
or notify anyone. `reply_text(text)` drops quoted history and signatures from a reply, so only
what the person wrote lands on the record.

Pure functions over the standard library's `email` package: the fetchers (IMAP, later Graph and
Gmail) hand bytes to these and act on the result.
"""

import email
import email.policy
import hashlib
import re
from dataclasses import dataclass, field
from email.message import EmailMessage, MIMEPart
from email.utils import getaddresses, parseaddr

MAX_TEXT = 200_000  # characters of a body kept; the rest is cut (the original stays on the server)

# A display ID in a subject: "[INC-123]" (case-insensitive, any record prefix).
# Directional isolates (U+2066..U+2069), as app.shared.labels.strip_isolates removes them.
_ISOLATES = re.compile("[\u2066-\u2069]")
TOKEN = re.compile(r"\[([A-Z]{2,10}-\d{1,12})\]", re.IGNORECASE)


def with_token(subject: str, display_id: str) -> str:
    """The subject of mail about a record, with its token, so a reply finds it ("[INC-12] ...")."""
    if display_id.upper() in (t.upper() for t in TOKEN.findall(subject)):
        return subject
    return f"[{display_id}] {subject}"


_AUTO_SUBMITTED_NO = {"no", ""}
_BULK_PRECEDENCE = {"bulk", "list", "junk", "auto_reply"}
_BOUNCE_SENDERS = re.compile(
    r"^(mailer-daemon|postmaster|mail-daemon|noreply-bounce)@", re.IGNORECASE
)


@dataclass(frozen=True)
class InboundAttachment:
    """A file that came with the message (inline images too, with their Content-ID)."""

    name: str
    content_type: str
    data: bytes
    content_id: str | None = None  # "<…>" stripped; referenced from the HTML body as cid:…


@dataclass(frozen=True)
class InboundMessage:
    """One received message, ready for routing."""

    message_id: str  # the header, or a stable hash of the message when it has none
    sender: str  # address, lowercased
    sender_name: str
    to: tuple[str, ...]
    cc: tuple[str, ...]
    subject: str
    in_reply_to: tuple[str, ...]
    references: tuple[str, ...]
    text: str  # plain body (from the HTML when there is no plain part)
    html: str | None
    attachments: tuple[InboundAttachment, ...] = field(default_factory=tuple)
    automatic: str | None = None  # why it is automatic mail, or None for mail a person wrote

    @property
    def tokens(self) -> tuple[str, ...]:
        """Record display IDs named in the subject, uppercased (e.g. ("INC-12",))."""
        # Without directional marks: a token copied from a screen may carry them.
        return tuple(match.upper() for match in TOKEN.findall(_ISOLATES.sub("", self.subject)))

    @property
    def thread_ids(self) -> tuple[str, ...]:
        """Message IDs this one answers, nearest first (In-Reply-To, then References, newest)."""
        seen: list[str] = []
        for value in (*self.in_reply_to, *reversed(self.references)):
            if value not in seen:
                seen.append(value)
        return tuple(seen)


def _ids(value: str | None) -> tuple[str, ...]:
    return tuple(re.findall(r"<([^<>\s]+)>", value or ""))


def automatic_reason(message: EmailMessage, sender: str) -> str | None:
    """Why `message` is automatic (never a record, never a notification), or None."""
    auto = (message.get("Auto-Submitted") or "").strip().lower()
    checks = (
        ("auto_submitted", auto not in _AUTO_SUBMITTED_NO),
        ("bulk", (message.get("Precedence") or "").strip().lower() in _BULK_PRECEDENCE),
        ("mailing_list", bool(message.get("List-Id") or message.get("List-Unsubscribe"))),
        ("auto_reply", bool(message.get("X-Autoreply") or message.get("X-Autorespond"))),
        (
            "bounce",
            message.get_content_type() == "multipart/report"
            or bool(_BOUNCE_SENDERS.match(sender))
            or (message.get("Return-Path") or "").strip() == "<>",
        ),
    )
    return next((reason for reason, found in checks if found), None)


def _decoded(part: MIMEPart) -> str:
    try:
        content = part.get_content()
    except (LookupError, ValueError):  # unknown charset: keep what can be read
        payload = part.get_payload(decode=True)
        content = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else ""
    return content if isinstance(content, str) else ""


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    from html import unescape  # noqa: PLC0415 - one use

    return re.sub(r"\n{3,}", "\n\n", unescape(text)).strip()


def parse(raw: bytes) -> InboundMessage:
    """One received message (bytes as fetched) as an InboundMessage."""
    message: EmailMessage = email.message_from_bytes(raw, policy=email.policy.default)
    sender_name, sender = parseaddr(str(message.get("From") or ""))
    sender = sender.strip().lower()
    message_id = next(iter(_ids(message.get("Message-ID"))), "")
    if not message_id:
        message_id = "sha256:" + hashlib.sha256(raw).hexdigest()
    plain = message.get_body(preferencelist=("plain",))
    rich = message.get_body(preferencelist=("html",))
    html = _decoded(rich) if rich is not None else None
    text = _decoded(plain) if plain is not None else _html_to_text(html or "")
    attachments: list[InboundAttachment] = []
    for part in message.iter_attachments():
        data = part.get_payload(decode=True)
        if not isinstance(data, bytes):
            continue
        content_id = (part.get("Content-ID") or "").strip().strip("<>") or None
        attachments.append(
            InboundAttachment(
                name=part.get_filename() or "attachment",
                content_type=part.get_content_type(),
                data=data,
                content_id=content_id,
            )
        )
    return InboundMessage(
        message_id=message_id,
        sender=sender,
        sender_name=sender_name.strip(),
        to=tuple(a.lower() for _, a in getaddresses(message.get_all("To") or []) if a),
        cc=tuple(a.lower() for _, a in getaddresses(message.get_all("Cc") or []) if a),
        subject=" ".join(str(message.get("Subject") or "").split())[:500],
        in_reply_to=_ids(message.get("In-Reply-To")),
        references=_ids(message.get("References")),
        text=text[:MAX_TEXT],
        html=html[:MAX_TEXT] if html is not None else None,
        attachments=tuple(attachments),
        automatic=automatic_reason(message, sender),
    )


# A reply's quoted history starts at one of these lines (en, ar, ur; common clients).
_QUOTE_STARTS = (
    re.compile(r"^On .{4,200} wrote:\s*$"),  # Gmail, Apple Mail, Thunderbird
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}", re.IGNORECASE),  # Outlook
    re.compile(r"^From:\s.+", re.IGNORECASE),  # Outlook header block
    re.compile(r"^_{10,}\s*$"),  # Outlook separator
    re.compile(r"^في .{4,200} كتب.*:\s*$"),  # Arabic Gmail
    re.compile(r"^من:\s.+"),  # Arabic Outlook header block
    re.compile(r"^.{4,200} نے لکھا:\s*$"),  # Urdu
)
_SIGNATURE = re.compile(r"^--\s?$")  # RFC 3676 signature separator
_MOBILE_SIGNATURES = re.compile(
    r"^(Sent from my |Get Outlook for |أُرسلت من |بھیجا گیا )", re.IGNORECASE
)


def reply_text(text: str) -> str:
    """What the person wrote: quoted history, quoted lines and the signature removed.

    Conservative: when nothing would be left (a message that is all quote), the whole text is
    kept, so nothing a person wrote is ever lost.
    """
    kept: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if any(pattern.match(stripped) for pattern in _QUOTE_STARTS):
            break
        if _SIGNATURE.match(line) or _MOBILE_SIGNATURES.match(stripped):
            break
        if stripped.startswith(">"):
            continue
        kept.append(line)
    result = "\n".join(kept).strip()
    return result or text.strip()


def request_text(text: str) -> str:
    """A new request's text: the signature block removed, everything else kept (REQ-INC-023).

    Unlike a reply, a new mail's quoted or forwarded part is often the request itself ("see
    below"), so only the lines from a signature separator up to the next quoted or forwarded part
    go. Nothing a person wrote is lost: a mail that is only a signature is kept whole.
    """
    kept: list[str] = []
    in_signature = False
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if _SIGNATURE.match(line) or _MOBILE_SIGNATURES.match(stripped):
            in_signature = True
            continue
        if in_signature and not any(pattern.match(stripped) for pattern in _QUOTE_STARTS):
            continue
        in_signature = False
        kept.append(line)
    result = "\n".join(kept).strip()
    return result or text.strip()
