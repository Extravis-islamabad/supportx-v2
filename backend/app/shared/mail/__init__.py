"""The mail service: the one outgoing mail sender (WP-039 session 2, D-089 D3).

Every module sends through this (identity, notifications WP-023, scheduled reports WP-035):
never a second sender. Interface and rules: docs/architecture/mail.md.
"""

from app.shared.mail.domain.inbound import with_token
from app.shared.mail.domain.layout import MailBrand, wrap_html
from app.shared.mail.domain.message import (
    MAX_ATTACHMENT_BYTES,
    Attachment,
    Language,
    MailRefused,
    OutgoingMail,
)
from app.shared.mail.service.outgoing import (
    MailNotConfigured,
    MailState,
    mail_configured,
    mail_states,
    mails_with_message_ids,
    queue_mail,
)

__all__ = [
    "MAX_ATTACHMENT_BYTES",
    "Attachment",
    "Language",
    "MailBrand",
    "MailNotConfigured",
    "MailRefused",
    "MailState",
    "OutgoingMail",
    "mail_configured",
    "mail_states",
    "mails_with_message_ids",
    "queue_mail",
    "with_token",
    "wrap_html",
]
