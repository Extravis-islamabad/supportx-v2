"""The mail service: the one outgoing mail sender (WP-039 session 2, D-089 D3).

Every module sends through this (identity, notifications WP-023, scheduled reports WP-035):
never a second sender. Interface and rules: docs/architecture/mail.md.
"""

from app.shared.mail.domain.layout import MailBrand, wrap_html
from app.shared.mail.domain.message import (
    MAX_ATTACHMENT_BYTES,
    Attachment,
    MailRefused,
    OutgoingMail,
)
from app.shared.mail.service.outgoing import MailNotConfigured, mail_configured, queue_mail

__all__ = [
    "MAX_ATTACHMENT_BYTES",
    "Attachment",
    "MailBrand",
    "MailNotConfigured",
    "MailRefused",
    "OutgoingMail",
    "mail_configured",
    "queue_mail",
    "wrap_html",
]
