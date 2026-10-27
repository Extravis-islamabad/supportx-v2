"""Send a MIME message over SMTP (standard library; WP-039 session 2).

`smtplib` blocks, so a send runs in a worker thread. A refusal the server says is permanent (5xx)
is `PermanentFailure` (not retried); anything else is `TemporaryFailure` (retried).
"""

import asyncio
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Literal

Security = Literal["starttls", "tls", "none"]
PERMANENT_FROM = 500


class TemporaryFailure(Exception):
    """Try again later (server unreachable, busy, timeout, 4xx)."""


class PermanentFailure(Exception):
    """The server refused for good (5xx): `code` for the record."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SmtpSettings:
    """Where and how to deliver."""

    host: str
    port: int
    security: Security
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    timeout: float = 15.0


def _send(settings: SmtpSettings, message: EmailMessage) -> None:
    context = ssl.create_default_context()
    smtp: smtplib.SMTP
    if settings.security == "tls":
        smtp = smtplib.SMTP_SSL(settings.host, settings.port, timeout=settings.timeout, context=context)
    else:
        smtp = smtplib.SMTP(settings.host, settings.port, timeout=settings.timeout)
    with smtp:
        if settings.security == "starttls":
            smtp.starttls(context=context)
        if settings.username:
            smtp.login(settings.username, settings.password or "")
        smtp.send_message(message)


async def send(settings: SmtpSettings, message: EmailMessage) -> None:
    """Deliver `message`, or raise TemporaryFailure / PermanentFailure."""
    try:
        await asyncio.to_thread(_send, settings, message)
    except smtplib.SMTPRecipientsRefused as exc:
        codes = [code for code, _ in exc.recipients.values()]
        if codes and min(codes) >= PERMANENT_FROM:
            raise PermanentFailure("recipient_refused") from exc
        raise TemporaryFailure from exc
    except smtplib.SMTPAuthenticationError as exc:
        raise PermanentFailure("authentication_failed") from exc
    except smtplib.SMTPResponseException as exc:
        if exc.smtp_code >= PERMANENT_FROM:
            raise PermanentFailure("message_refused") from exc
        raise TemporaryFailure from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise TemporaryFailure from exc
