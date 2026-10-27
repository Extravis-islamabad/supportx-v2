# Mail: the one outgoing mail sender

WP-039 session 2 (D-089 D3, D-099). `app/shared/mail` is **the** mail sender of SupportX. Every
module sends through it: identity, notifications (WP-023), the email channel (WP-024, which
adds mailboxes and inbound), scheduled reports (WP-035). Never build a second sender.

## Interface

```python
from app.shared.mail import Attachment, OutgoingMail, mail_configured, queue_mail, wrap_html

if not mail_configured(settings):        # cheap: settings only, no connection
    ...                                  # e.g. the schedule form says mail is not set up

mail_id = await queue_mail(
    session,                             # the caller's tenant session (its transaction)
    settings,
    OutgoingMail(
        kind="report",                   # purpose code, lowercase snake case (2-40)
        to=("pat@acme.test",),           # 1 to 50 recipients
        language="ar",                   # en | ar | ur, chosen by the caller per message
        subject="…",                     # rendered, one line, at most 300 characters
        text="…",                        # plain-text body (always)
        html=wrap_html(content, brand=brand, language="ar", title="…"),   # optional
        reply_to="help@acme.test",       # optional: the tenant's reply-to (REQ-SEC-019 AC2)
        sender_name="Acme IT",           # optional: the tenant's sender name
        attachments=(Attachment("report.xlsx", XLSX, data),),   # optional, 10 MB in total
    ),
)
```

- **Transactional.** The message is stored and `system.mail.queued` recorded through the outbox
  in the caller's transaction: it is sent exactly when the caller's change commits, never if
  it rolls back.
- **Refusals.** `MailNotConfigured` (no mail server; check `mail_configured` first) and
  `MailRefused(code)`. The codes are `mail_recipients`, `mail_address_invalid`,
  `mail_subject_invalid` (empty, too long or a line break), `mail_sender_invalid`,
  `mail_language_invalid`, `mail_kind_invalid`, `mail_attachment_type`, `mail_attachment_name`
  and `mail_attachments_too_large`.
- **Attachment types.** CSV (`text/csv`), Excel (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`),
  PDF (`application/pdf`), plain text. Others need a decision.
- **Texts.** Callers render subject and bodies in the message's language from the shared
  server-side labels (lane C's `app.shared.labels`, D-100 D7); nothing here holds wording.
- **Brand.** `wrap_html` lays the content out with the tenant's brand (pass
  `organization.email_branding(...)`): logo, colours, right to left for Arabic and Urdu, inline
  styles only. It is a sandboxed Jinja2 template with autoescaping; `content` is trusted markup
  the caller built from escaped parts.

## What the sender guarantees

- From: the installation's address (`SUPPORTX_MAIL_FROM_ADDRESS`) with the tenant's sender name
  or the installation's. There is no field for a person's own address (REQ-SEC-019 AC1).
- Header values cannot carry line breaks (no header injection); `Auto-Submitted:
  auto-generated`, `Content-Language`, a `Message-ID` on the sender's domain.
- Delivery by the `system__mail_send` worker. A temporary failure (server down, 4xx) is tried
  again with backoff (1, 2, 4 … minutes, at most an hour) by the `system__mail_retry` schedule,
  up to `SUPPORTX_MAIL_MAX_ATTEMPTS` (5) times; a permanent refusal (5xx) is recorded at once.
  The message's row keeps its state (`queued`, `sent`, `failed`), attempts and reason.
- Bodies and attachments are personal data: cleared `SUPPORTX_MAIL_CONTENT_RETENTION_DAYS` (30)
  after the message is done; the record of what was sent, when and to whom stays.
- Tables `mail_messages` and `mail_attachments`, tenant-scoped with RLS.

## Configuration (one place, D-099)

| Setting | Chart (`mail.*`) | Notes |
|---|---|---|
| `SUPPORTX_MAIL_SMTP_HOST` | `smtpHost` | Empty = not configured |
| `SUPPORTX_MAIL_SMTP_PORT` | `smtpPort` | 587 |
| `SUPPORTX_MAIL_SMTP_SECURITY` | `smtpSecurity` | `starttls`, `tls` or `none` |
| `SUPPORTX_MAIL_SMTP_USERNAME` | `smtpUsername` | |
| `SUPPORTX_MAIL_SMTP_PASSWORD` | secret `mail-smtp-password` | Optional |
| `SUPPORTX_MAIL_FROM_ADDRESS` | `fromAddress` | Required to send |
| `SUPPORTX_MAIL_FROM_NAME` | `fromName` | SupportX |

The deploy's `keycloak-identity` step writes the same server into Keycloak's realm, so Keycloak's
password and invitation e-mails (D-099) leave from the same sender. In the Compose dev stack all
mail goes to the mail catcher (Mailpit, web UI on `MAILPIT_WEB_PORT`, default 28025).
