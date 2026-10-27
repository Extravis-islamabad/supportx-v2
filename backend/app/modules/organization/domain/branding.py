"""Tenant branding rules (WP-017, REQ-ADM-055, REQ-PRT-016): colours, contrast, texts. No I/O.

The colour maths is the one used for the SupportX brand (D-078, docs/architecture/branding.md):
`tooling/brand_assets.py` imports it from here, and `frontend/packages/ui/src/theme.ts` derives
the same shades (same mix toward black or white), so the console, the portal, the sign-in page
and e-mails show the same colours in each mode.

A tenant chooses a primary colour and, optionally, the two ends of a decorative gradient. The
shades for hover, dark mode and high contrast are derived, never chosen, so one AA-checked choice
is enough. A colour that fails is refused (D-090); `nearest_passing` offers the closest colour
that passes, which the admin may apply in one click.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from app.modules.organization.domain import default_palette

if TYPE_CHECKING:
    from collections.abc import Mapping

RGB = tuple[int, int, int]

AA, AAA = 4.5, 7.0
WHITE: RGB = (255, 255, 255)
DARK_BG: RGB = (20, 20, 20)  # #141414, Ant Design's dark layout background
DARK_CONTAINER: RGB = (31, 31, 31)  # #1f1f1f, raised surfaces in dark mode
HOVER_DARKEN = 0.12
DARK_TEXT_LIGHTEN = 0.5
HIGH_CONTRAST_DARKEN = 0.35
GRADIENT_STEPS = 32

HEX = re.compile(r"^#[0-9a-f]{6}$")

LOCALES = ("en", "ar", "ur")
PRODUCT_NAME_MAX = 60
PORTAL_NAME_MAX = 60
WELCOME_MAX = 500


def parse_hex(value: str) -> RGB:
    """(r, g, b) of #rrggbb."""
    digits = value.removeprefix("#")
    return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)


def hex_colour(rgb: RGB) -> str:
    """#rrggbb."""
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def luminance(rgb: RGB) -> float:
    """WCAG 2.x relative luminance."""

    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4  # noqa: PLR2004

    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: RGB, b: RGB) -> float:
    """WCAG contrast ratio, 1 to 21."""
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mix(value: str, amount: float, target: int) -> str:
    """`value` moved `amount` (0..1) toward black (0) or white (255), as theme.ts does."""
    r, g, b = (round(c + (target - c) * amount) for c in parse_hex(value))
    return hex_colour((r, g, b))


def normalise_hex(value: str) -> str | None:
    """`#RRGGBB` or `#rgb` in any case as `#rrggbb`; None when it is not a colour."""
    text = value.strip().lower()
    if re.fullmatch(r"#[0-9a-f]{3}", text):
        text = "#" + "".join(ch * 2 for ch in text[1:])
    return text if HEX.fullmatch(text) else None


class CheckCode(StrEnum):
    """Each text/background pair the brand colours make (labels: `branding.check.<code>`)."""

    TEXT_ON_PRIMARY = "text_on_primary"
    LINKS_ON_WHITE = "links_on_white"
    TEXT_ON_HOVER = "text_on_hover"
    DARK_LINKS = "dark_links"
    DARK_LINKS_RAISED = "dark_links_raised"
    HIGH_CONTRAST = "high_contrast"
    TEXT_ON_GRADIENT = "text_on_gradient"


@dataclass(frozen=True)
class Check:
    """One contrast check: the ratio found and the one required."""

    code: CheckCode
    ratio: float
    required: float

    @property
    def passed(self) -> bool:
        """At or above the requirement (ratios are compared unrounded)."""
        return self.ratio >= self.required


@dataclass(frozen=True)
class Colours:
    """A brand's chosen colours and the shades derived from them."""

    primary: str
    gradient: tuple[str, str]

    @property
    def hover(self) -> str:
        """Buttons darken on hover and press, so white text stays above AA in every state."""
        return mix(self.primary, HOVER_DARKEN, 0)

    @property
    def dark_text(self) -> str:
        """Links and selected text on dark backgrounds."""
        return mix(self.primary, DARK_TEXT_LIGHTEN, 255)

    @property
    def high_contrast(self) -> str:
        """Primary for high contrast (AAA with white)."""
        return mix(self.primary, HIGH_CONTRAST_DARKEN, 0)

    def primary_checks(self) -> list[Check]:
        """The checks that depend on the primary colour alone."""
        rgb = parse_hex
        pairs = [
            (CheckCode.TEXT_ON_PRIMARY, rgb(self.primary), WHITE, AA),
            (CheckCode.LINKS_ON_WHITE, rgb(self.primary), WHITE, AA),
            (CheckCode.TEXT_ON_HOVER, rgb(self.hover), WHITE, AA),
            (CheckCode.DARK_LINKS, rgb(self.dark_text), DARK_BG, AA),
            (CheckCode.DARK_LINKS_RAISED, rgb(self.dark_text), DARK_CONTAINER, AA),
            (CheckCode.HIGH_CONTRAST, rgb(self.high_contrast), WHITE, AAA),
        ]
        return [Check(code, contrast(fg, bg), need) for code, fg, bg, need in pairs]

    def gradient_check(self) -> Check:
        """White text anywhere along the gradient (the portal's welcome band carries text)."""
        return Check(CheckCode.TEXT_ON_GRADIENT, worst_on_gradient(self.gradient), AA)

    def checks(self) -> list[Check]:
        """Every text/background pair the brand colours make."""
        return [*self.primary_checks(), self.gradient_check()]

    @property
    def passes(self) -> bool:
        """Every check passes."""
        return all(check.passed for check in self.checks())


def worst_on_gradient(gradient: tuple[str, str]) -> float:
    """The lowest white-text contrast along a two-stop gradient."""
    a, b = parse_hex(gradient[0]), parse_hex(gradient[1])
    along = [
        (
            round(a[0] + (b[0] - a[0]) * n / GRADIENT_STEPS),
            round(a[1] + (b[1] - a[1]) * n / GRADIENT_STEPS),
            round(a[2] + (b[2] - a[2]) * n / GRADIENT_STEPS),
        )
        for n in range(GRADIENT_STEPS + 1)
    ]
    return min(contrast(colour, WHITE) for colour in along)


DEFAULT_COLOURS = Colours(
    primary=default_palette.PRIMARY,
    gradient=(default_palette.GRADIENT_START, default_palette.GRADIENT_END),
)


def nearest_passing_primary(primary: str) -> str | None:
    """The closest darker shade of `primary` that passes every primary check, or None.

    Darkening is the only direction that helps: the primary carries white text. The dark-mode
    link colour is primary lightened halfway to white, so a darker primary can, in theory, make
    it fail; such a colour has no passing shade and None is returned.
    """
    for step in range(101):
        candidate = mix(primary, step / 100, 0)
        checks = Colours(candidate, (candidate, candidate)).primary_checks()
        if all(check.passed for check in checks):
            return candidate
    return None


def nearest_passing_gradient(gradient: tuple[str, str]) -> tuple[str, str] | None:
    """Both ends darkened by the same, smallest amount that gives white text AA along it."""
    for step in range(101):
        candidate = (mix(gradient[0], step / 100, 0), mix(gradient[1], step / 100, 0))
        if worst_on_gradient(candidate) >= AA:
            return candidate
    return None


class TextField(StrEnum):
    """Translated brand texts (each one {locale: text}; English is the fallback)."""

    PRODUCT_NAME = "product_name"
    PORTAL_NAME = "portal_name"
    WELCOME_TEXT = "welcome_text"


TEXT_LIMITS: dict[TextField, int] = {
    TextField.PRODUCT_NAME: PRODUCT_NAME_MAX,
    TextField.PORTAL_NAME: PORTAL_NAME_MAX,
    TextField.WELCOME_TEXT: WELCOME_MAX,
}


@dataclass(frozen=True)
class FieldProblem:
    """What is wrong with one field (a code and params for a translated message)."""

    field: str
    code: str
    params: Mapping[str, object]


def clean_texts(value: Mapping[str, str] | None) -> dict[str, str]:
    """Trimmed, empty locales dropped. Validate with `text_problems` first."""
    if not value:
        return {}
    return {locale: text.strip() for locale, text in value.items() if text.strip()}


def text_problems(field: TextField, value: Mapping[str, str] | None) -> list[FieldProblem]:
    """Unknown locales, over-long texts, or translations without the English fallback."""
    problems: list[FieldProblem] = []
    texts = clean_texts(value)
    limit = TEXT_LIMITS[field]
    for locale, text in texts.items():
        if locale not in LOCALES:
            problems.append(FieldProblem(f"{field}.{locale}", "unknown_language", {}))
        elif len(text) > limit:
            problems.append(FieldProblem(f"{field}.{locale}", "value_too_long", {"max": limit}))
    if texts and "en" not in texts:
        problems.append(FieldProblem(f"{field}.en", "english_text_required", {}))
    return problems


def text_for(texts: Mapping[str, str], locale: str) -> str | None:
    """The text in `locale`, else English, else None (the caller's default applies)."""
    return texts.get(locale) or texts.get("en")
