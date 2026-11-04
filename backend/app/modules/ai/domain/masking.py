"""Personal data masked before a model sees it, restored after (REQ-AI-018). Pure.

Masked: e-mail addresses, phone numbers, IP addresses, card numbers (Luhn-checked), national ID
numbers in the common regional formats, and the names the caller knows are on the record (the
requester, technicians, people mentioned). Each distinct value becomes a stable placeholder such
as `⟦EMAIL_1⟧`, the same value always the same placeholder within one call, so the model can
still refer to "the same person". The result is restored before anyone sees it.

Fields marked sensitive in the field designer and tenant-defined patterns join through
`extra_values` and `extra_patterns` when those settings exist.
"""

import ipaddress
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import partial

OPEN, CLOSE = "⟦", "⟧"

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_IPV4 = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
# IPv6 candidates (with :: compression), kept only when they parse as an address.
_IPV6 = re.compile(r"(?<![\w:])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?![\w:])")
# Pakistan CNIC 12345-1234567-1, UAE Emirates ID 784-1990-1234567-1, Saudi ID 1/2 + 9 digits.
_NATIONAL_ID = re.compile(r"\b(?:\d{5}-\d{7}-\d|784-\d{4}-\d{7}-\d|[12]\d{9})\b")
# 13 to 19 digits, optionally grouped by spaces or dashes; kept only when the Luhn check passes.
_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
# International or local phone numbers: at least 7 digits, with + ( ) - . and spaces between.
_PHONE = re.compile(r"(?<![\w+])\+?\(?\d[\d ()\-.]{6,}\d(?!\w)")


_CARD_DIGITS = range(13, 20)  # a card number has 13 to 19 digits
_PHONE_MIN_DIGITS = 7
_NAME_MIN_LENGTH = 2
_LUHN_FOLD = 9


def _luhn(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > _LUHN_FOLD:
                value -= _LUHN_FOLD
        total += value
    return total % 10 == 0


@dataclass
class _Masker:
    by_value: dict[tuple[str, str], str] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)

    def placeholder(self, kind: str, value: str) -> str:
        key = (kind, value)
        found = self.by_value.get(key)
        if found is None:
            self.counters[kind] = self.counters.get(kind, 0) + 1
            found = f"{OPEN}{kind}_{self.counters[kind]}{CLOSE}"
            self.by_value[key] = found
        return found

    def values(self) -> dict[str, str]:
        return {placeholder: value for (_, value), placeholder in self.by_value.items()}


def _replace(masker: _Masker, kind: str, match: re.Match[str]) -> str:
    return masker.placeholder(kind, match.group(0))


def mask(
    texts: Sequence[str],
    *,
    names: Iterable[str] = (),
    extra_values: Iterable[str] = (),
    extra_patterns: Iterable[re.Pattern[str]] = (),
) -> tuple[list[str], dict[str, str]]:
    """Mask every text with one shared set of placeholders; returns the texts and the values."""
    masker = _Masker()

    def literal(kind: str, values: Iterable[str]) -> list[tuple[str, re.Pattern[str]]]:
        # Longest first, so "Ali Raza" is masked before "Ali".
        wanted = sorted(
            {v.strip() for v in values if len(v.strip()) >= _NAME_MIN_LENGTH}, key=len, reverse=True
        )
        return [(kind, re.compile(rf"(?<!\w){re.escape(v)}(?!\w)", re.IGNORECASE)) for v in wanted]

    def ipv6(match: re.Match[str]) -> str:
        try:
            ipaddress.IPv6Address(match.group(0))
        except ValueError:
            return match.group(0)
        return masker.placeholder("IP", match.group(0))

    def card(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) in _CARD_DIGITS and _luhn(digits):
            return masker.placeholder("CARD", match.group(0))
        return match.group(0)

    rules: list[tuple[str, re.Pattern[str]]] = [
        ("EMAIL", _EMAIL),
        *literal("PERSON", names),
        *literal("SENSITIVE", extra_values),
        *(("SENSITIVE", pattern) for pattern in extra_patterns),
        ("NATIONAL_ID", _NATIONAL_ID),
        ("IP", _IPV4),
    ]
    out: list[str] = []
    for text in texts:
        # Brackets of our own kind already in the text become plain ones, so a person cannot plant
        # "⟦EMAIL_1⟧" and have restore fill in someone else's value (lane B, #188).
        result = text.replace(OPEN, "[").replace(CLOSE, "]")
        for kind, pattern in rules:
            result = pattern.sub(partial(_replace, masker, kind), result)
        result = _IPV6.sub(ipv6, result)
        result = _CARD.sub(card, result)
        result = _PHONE.sub(
            lambda m: (
                m.group(0)
                if len(re.sub(r"\D", "", m.group(0))) < _PHONE_MIN_DIGITS
                else masker.placeholder("PHONE", m.group(0))
            ),
            result,
        )
        out.append(result)
    return out, masker.values()


def restore(text: str, values: dict[str, str]) -> str:
    """Put the masked values back (placeholders the model invented are left as they are)."""
    for placeholder, value in values.items():
        text = text.replace(placeholder, value)
    return text
