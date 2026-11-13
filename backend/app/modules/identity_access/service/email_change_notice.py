"""Tell the OLD address that a person's sign-in e-mail changed (WP-057 S2b-1; the coordinator).

The sign-in e-mail is where password resets go, so changing it can hand an account over (lane B,
#479). The change needs a recent confirmation (REQ-SEC-027) and is audited; this mail is the
other half: the address that is no longer theirs hears, in the person's language and the tenant's
brand, who changed it and when. There is no link in it, least of all one that undoes the change
silently: if it was not them, they contact their administrators.

Sent directly through the one mail sender (app/shared/mail), not the notification engine: the
old address is no person's address any more, so the engine has no recipient for it (lane A).
"""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from markupsafe import Markup
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SESSION_TENANT_KEY
from app.core.logging import get_logger
from app.modules.identity_access.infra.models import User
from app.modules.organization import email_branding, get_current_tenant
from app.shared.labels import LANGUAGES, html_label, plain_label
from app.shared.mail import Language, OutgoingMail, mail_configured, queue_mail, wrap_html

log = get_logger(__name__)


def _language(locale: str | None) -> Language:
    found = (locale or "en").split("-")[0]
    return found if found in LANGUAGES else "en"  # type: ignore[return-value]  # one of LANGUAGES


def _when(moment: datetime, zone: str | None) -> str:
    try:
        tz = ZoneInfo(zone) if zone else None
    except (ZoneInfoNotFoundError, ValueError):
        tz = None
    local = moment.astimezone(tz) if tz is not None else moment
    return local.strftime("%Y-%m-%d %H:%M %Z").strip()


async def send(  # noqa: PLR0913 - the person, the old address, who and when, keyword-only
    session: AsyncSession,
    settings: Settings,
    person: User,
    *,
    old_email: str,
    changed_by: uuid.UUID,
    changed_at: datetime,
) -> bool:
    """Queue the notice to `old_email`; False when outgoing mail is not set up (logged)."""
    if not mail_configured(settings):
        log.warning("email_change_notice_not_sent", reason="no_mail")
        return False
    language = _language(person.ui_locale or person.locale)
    context = session.info[SESSION_TENANT_KEY]
    brand = await email_branding(session, settings, context.tenant_id, language)
    tenant = await get_current_tenant(session)
    when = _when(changed_at, person.time_zone)
    if changed_by == person.id:
        key = "mail.email_changed.body_self"
        params: dict[str, object] = {"organisation": tenant.name, "when": when}
    else:
        actor = await session.get(User, changed_by)
        key = "mail.email_changed.body"
        params = {
            "organisation": tenant.name,
            "when": when,
            "who": actor.display_name if actor is not None else tenant.name,
        }
    subject = plain_label("mail.email_changed.subject", language, organisation=tenant.name)
    text = plain_label(key, language, **params)
    body_html = html_label(key, language, **params)
    await queue_mail(
        session,
        settings,
        OutgoingMail(
            kind="email_changed",
            to=(old_email,),
            language=language,
            subject=subject,
            text=text,
            html=wrap_html(
                Markup("<p>{}</p>").format(body_html), brand=brand, language=language, title=subject
            ),
            sender_name=tenant.name,
        ),
    )
    return True
