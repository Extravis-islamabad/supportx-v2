"""The tenant's brand for outgoing e-mails (WP-017, REQ-ADM-055, REQ-PRT-016 AC1; REQ-NTF-015).

E-mails are read outside SupportX, so every image URL is absolute and public (the generated
variants, cached by version). Mail clients ignore dark mode and stylesheets unevenly: the header is
the light logo on white with a thin bar in the brand gradient, inline styles only.

The mail foundation (WP-039, `app/shared/mail`, D-089) renders its layout with `email_branding()`;
until it exists, `header_html()` is the one piece of markup, escaped with the standard library.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from app.modules.organization.domain.branding import text_for
from app.modules.organization.service.branding import get_branding
from app.modules.organization.service.tenants import get_current_tenant

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.config import Settings

PUBLIC_PREFIX = "/api/v1/public/branding"
DEFAULT_PRODUCT_NAME = "SupportX"


@dataclass(frozen=True)
class EmailBranding:
    """What an e-mail shows of the tenant's brand, ready to render."""

    product_name: str
    primary_colour: str
    gradient: tuple[str, str]
    logo_url: str | None  # None: the product name is written instead
    portal_url: str
    console_url: str = ""  # the console on the tenant's address, ending in "/" (WP-023 links)
    tenant_slug: str = ""  # names the tenant in e-mailed links where the address does not (D-132)


def tenant_origin(settings: Settings, slug: str, base_url: str | None = None) -> str:
    """Where the tenant's people reach SupportX: its subdomain when there are subdomains.

    `base_url` (default: the console's) gives the scheme and port. They differ only where an app
    has its own port, as the portal does on the dev and CI stack (localhost:5174).
    """
    parts = urlsplit(base_url or settings.console_url)
    if settings.tenant_base_domain:
        port = f":{parts.port}" if parts.port else ""
        return f"{parts.scheme}://{slug}.{settings.tenant_base_domain.strip('.')}{port}"
    return f"{parts.scheme}://{parts.netloc}"


async def email_branding(
    session: AsyncSession, settings: Settings, tenant_id: uuid.UUID, locale: str
) -> EmailBranding:
    """The session tenant's brand for an e-mail in `locale` (English, then the default)."""
    tenant = await get_current_tenant(session)
    view = await get_branding(session, tenant_id)
    origin = tenant_origin(settings, tenant.slug)
    logo = None
    if "logo.png" in view.assets:
        logo = f"{origin}{PUBLIC_PREFIX}/{tenant_id}/logo.png?v={view.assets_version or '0'}"
    # The portal at its own origin: deployed it shares the console's (under /portal/), on the
    # dev stack it has its own port, and a link on the console's would land on the console.
    portal_origin = tenant_origin(settings, tenant.slug, settings.portal_url)
    portal_path = urlsplit(settings.portal_url).path.rstrip("/")
    return EmailBranding(
        product_name=text_for(view.product_name, locale) or DEFAULT_PRODUCT_NAME,
        primary_colour=view.colours.primary,
        gradient=view.colours.gradient,
        logo_url=logo,
        portal_url=f"{portal_origin}{portal_path}/",
        console_url=f"{origin}{urlsplit(settings.console_url).path.rstrip('/')}/",
        tenant_slug=tenant.slug,
    )


def header_html(brand: EmailBranding) -> str:
    """The e-mail header: logo (or name) on white over a bar in the brand gradient."""
    if brand.logo_url is not None:
        mark = (
            f'<img src="{escape(brand.logo_url)}" alt="{escape(brand.product_name)}" height="40" '
            'style="display:block;height:40px;width:auto;border:0">'
        )
    else:
        mark = (
            f'<span style="font:600 20px Arial,sans-serif;color:{brand.primary_colour}">'
            f"{escape(brand.product_name)}</span>"
        )
    start, end = brand.gradient
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="background:#ffffff">'
        f'<tr><td style="padding:16px 24px">{mark}</td></tr>'
        f'<tr><td style="height:4px;background:{end};'
        f'background-image:linear-gradient(90deg,{start},{end})"></td></tr>'
        "</table>"
    )
