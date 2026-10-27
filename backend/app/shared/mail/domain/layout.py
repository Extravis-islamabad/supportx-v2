"""The e-mail layout every SupportX message shares (WP-039 session 2; WP-017 brand contract).

Callers render their own content (in the recipient's language, from the shared labels) and pass
it here with the tenant's brand (`organization.email_branding()`, which satisfies `MailBrand`).
The layout is a Jinja2 template in a **sandboxed** environment with autoescaping (CLAUDE.md §3):
`content_html` is the only markup let through, and callers build it from escaped parts.

Mail clients ignore stylesheets and dark mode unevenly: inline styles only, the light logo on
white over a thin bar in the brand gradient, right to left for Arabic and Urdu.
"""

from typing import Protocol

from jinja2.sandbox import SandboxedEnvironment
from markupsafe import Markup

from app.shared.mail.domain.message import RTL_LANGUAGES, Language


class MailBrand(Protocol):
    """What the layout shows of the tenant's brand (organization's EmailBranding has it)."""

    @property
    def product_name(self) -> str: ...  # noqa: D102 - fields of the brand

    @property
    def primary_colour(self) -> str: ...  # noqa: D102

    @property
    def gradient(self) -> tuple[str, str]: ...  # noqa: D102

    @property
    def logo_url(self) -> str | None: ...  # noqa: D102

    @property
    def portal_url(self) -> str: ...  # noqa: D102


_LAYOUT = """\
<!DOCTYPE html>
<html lang="{{ language }}" dir="{{ direction }}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width">\
<title>{{ title }}</title></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;\
color:#262626;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" \
style="background:#f5f5f5;">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" \
style="max-width:600px;width:100%;background:#ffffff;border-radius:8px;overflow:hidden;">
<tr><td style="padding:20px 24px;text-align:{{ start }};">
{% if brand.logo_url %}<img src="{{ brand.logo_url }}" alt="{{ brand.product_name }}" height="40" \
style="display:block;height:40px;width:auto;border:0">\
{% else %}<span style="font-size:20px;font-weight:bold;">{{ brand.product_name }}</span>{% endif %}
</td></tr>
<tr><td style="height:4px;background:{{ brand.gradient[0] }};\
background-image:linear-gradient(90deg,{{ brand.gradient[0] }},{{ brand.gradient[1] }});"></td></tr>
<tr><td dir="{{ direction }}" style="padding:24px;font-size:15px;line-height:1.6;\
text-align:{{ start }};">{{ content }}</td></tr>
{% if footer %}<tr><td dir="{{ direction }}" style="padding:16px 24px;font-size:12px;\
color:#595959;border-top:1px solid #f0f0f0;text-align:{{ start }};">{{ footer }}</td></tr>\
{% endif %}
</table></td></tr></table>
</body></html>
"""

_ENVIRONMENT = SandboxedEnvironment(autoescape=True)
_TEMPLATE = _ENVIRONMENT.from_string(_LAYOUT)


def wrap_html(
    content_html: str | Markup,
    *,
    brand: MailBrand,
    language: Language,
    title: str,
    footer: str | None = None,
) -> str:
    """The whole HTML message around `content_html` (trusted markup the caller built)."""
    rtl = language in RTL_LANGUAGES
    return _TEMPLATE.render(
        brand=brand,
        language=language,
        direction="rtl" if rtl else "ltr",
        start="right" if rtl else "left",
        title=title,
        content=Markup(content_html),  # noqa: S704 - the caller's own escaped markup, by contract
        footer=footer,
    )
