"""Personal data in an article made from a record (REQ-KB-016, D-121 (4)); pure, no I/O.

A resolution written for one person often carries their e-mail address, phone number, an account
number or a password. The new draft says what was found and where, so the author can take it
out before anyone else reads it. It warns, never blocks: the author decides.
"""

import re
from dataclasses import dataclass
from typing import Literal

Field = Literal["title", "body"]
Kind = Literal["email", "phone", "account_number", "password"]

_TAGS = re.compile(r"<[^>]+>")
_ENTITIES = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'"}
# Arabic-Indic (U+0660..0669) and Eastern Arabic-Indic (U+06F0..06F9) digits count as digits.
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<![\w])\+?\d[\d \-().]{5,}\d(?![\w])")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
_PASSWORD = re.compile(
    r"(?:password|passwd|pwd|pass code|passcode|كلمة المرور|كلمة السر|پاس ورڈ)\s*[:=]",
    re.IGNORECASE,
)
PHONE_DIGITS_MIN = 7


@dataclass(frozen=True)
class Finding:
    """One kind of personal data in one field: `email`, `phone`, `account_number`, `password`."""

    field: Field
    kind: Kind


def plain_text(html: str) -> str:
    """The text of sanitised HTML, tags dropped and the common entities read."""
    text = _TAGS.sub(" ", html)
    for entity, char in _ENTITIES.items():
        text = text.replace(entity, char)
    return text


def _kinds(text: str) -> list[Kind]:
    western = text.translate(_DIGITS)
    found: list[Kind] = []
    if _EMAIL.search(western):
        found.append("email")
    if any(
        sum(c.isdigit() for c in match.group(0)) >= PHONE_DIGITS_MIN
        for match in _PHONE.finditer(western)
    ):
        found.append("phone")
    if _IBAN.search(western.upper()):
        found.append("account_number")
    if _PASSWORD.search(western):
        found.append("password")
    return found


def find_personal_data(title: str, body_html: str) -> list[Finding]:
    """What looks like personal data, by field, in a fixed order (title first)."""
    return [Finding("title", k) for k in _kinds(title)] + [
        Finding("body", k) for k in _kinds(plain_text(body_html))
    ]
