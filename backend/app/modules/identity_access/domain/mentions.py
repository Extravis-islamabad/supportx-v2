"""Mentions of a person in other people's text (D-171 a, ADR-052 S1b). Pure Python, no I/O.

Before a second admin approves an erasure, the mentions report shows where the person is named
in text the erasure does not reach (other people's descriptions, file names, notes). A mention
is a place (record, field) and a kind (name, e-mail, phone) with a count, never the text.

The terms are built from the person's own row at the moment they are needed (report build,
redaction) and are never stored. Matching:

- **Names:** the display name and "first last", whole words, case-insensitive, any whitespace
  between the words. Single words are not used (a first name alone matches too many people).
- **E-mail:** the address, case-insensitive, not inside a longer address.
- **Phone:** the person's phone and mobile as digits; a run of digits in the text (with spaces,
  dots, dashes, brackets or a leading +) matches when its digits are the same, or, when both
  have at least 9, their last 9 digits are (so "+92 300 1234567" and "0300-1234567" match).

Redaction replaces each matched occurrence of one kind with the marker, nothing else.

Rich text (sanitised HTML: descriptions, notes, conversation bodies) goes through the `_html`
variants: only text between tags is matched and redacted, never a tag or an attribute (a name in
an `href` or `alt` is not counted, and markup is never rewritten; lane A's #506 review).
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

NAME_MIN = 3  # a name of several words shorter than this in all is not searched
# A one-word display name searched on its own needs this many characters (str length, so
# Arabic and Urdu count by letter): shorter ones ("Ali") match too many other people. The full
# first + last name is always searched, and the report says a short name was skipped (the
# coordinator, 2026-11-14).
SINGLE_NAME_MIN = 4
PHONE_MIN = 7  # phone numbers with fewer digits are not searched
PHONE_TAIL = 9  # numbers this long or longer compare by their last 9 digits
TERMS_MAX = 8  # names + addresses + numbers per person; a person has at most a handful


class MentionMatchKind(StrEnum):
    """What matched (`people_erasure.match_kind.<code>` labels)."""

    NAME = "name"
    EMAIL = "email"
    PHONE = "phone"


class MentionState(StrEnum):
    """A mention's state in the report (`people_erasure.mention_state.<code>` labels).

    found: listed, nothing done yet; redacted: the matched text was replaced by the marker;
    left: the erasure was approved with it in place (the approver saw it and left it).
    """

    FOUND = "found"
    REDACTED = "redacted"
    LEFT = "left"


@dataclass(frozen=True)
class MentionTerms:
    """What identifies the person in text. Built when needed, never stored or logged."""

    names: tuple[str, ...] = ()
    emails: tuple[str, ...] = ()
    phones: tuple[str, ...] = ()  # digits only
    # A one-word display name too short to search on its own was left out (said in the report).
    short_name_skipped: bool = False

    def empty(self) -> bool:
        """Nothing to search for."""
        return not (self.names or self.emails or self.phones)


def _spaced(text: str | None) -> str:
    return " ".join((text or "").split())


def digits(text: str | None) -> str:
    """The digits of a phone number, in order."""
    return "".join(ch for ch in (text or "") if ch.isdigit())


def build_terms(  # noqa: PLR0913 - the person's identifying fields, explicit
    *,
    display_name: str | None,
    first_name: str | None,
    last_name: str | None,
    email: str | None,
    phone: str | None,
    mobile: str | None,
) -> MentionTerms:
    """The person's terms: display name, first + last, e-mail, phone and mobile as digits.

    The full first + last name is always searched; a one-word display name only when it has at
    least SINGLE_NAME_MIN characters (`short_name_skipped` otherwise).
    """
    names: list[str] = []
    skipped = False
    full = _spaced(f"{first_name or ''} {last_name or ''}")
    shown = _spaced(display_name)
    for name, single in ((full, False), (shown, True)):
        if not name or name.casefold() in {n.casefold() for n in names}:
            continue
        if single and " " not in name and len(name) < SINGLE_NAME_MIN:
            skipped = True
            continue
        if " " in name or len(name) >= NAME_MIN:
            names.append(name)
    emails = [address] if (address := (email or "").strip()) and "@" in address else []
    phones: list[str] = []
    for number in (digits(phone), digits(mobile)):
        if len(number) >= PHONE_MIN and number not in phones:
            phones.append(number)
    # Longest first, so "Ali Khan Durrani" is replaced before "Ali Khan" would split it.
    return MentionTerms(
        names=tuple(sorted(names, key=len, reverse=True))[:TERMS_MAX],
        emails=tuple(emails),
        phones=tuple(phones),
        short_name_skipped=skipped,
    )


def _name_pattern(names: Iterable[str]) -> re.Pattern[str] | None:
    parts = [r"\s+".join(re.escape(word) for word in name.split()) for name in names]
    if not parts:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.IGNORECASE)


def _email_pattern(emails: Iterable[str]) -> re.Pattern[str] | None:
    parts = [re.escape(address) for address in emails]
    if not parts:
        return None
    return re.compile(r"(?<![\w.+-])(?:" + "|".join(parts) + r")(?![\w-]|\.\w)", re.IGNORECASE)


# A phone-like run: digits with the usual separators, at least PHONE_MIN digits in all.
_PHONE_RUN = re.compile(r"\+?\(?\d[\d\s().\-]{4,}\d")


def _same_number(found: str, phones: Iterable[str]) -> bool:
    if len(found) < PHONE_MIN:
        return False
    for number in phones:
        if found == number:
            return True
        if (
            len(found) >= PHONE_TAIL
            and len(number) >= PHONE_TAIL
            and found[-PHONE_TAIL:] == number[-PHONE_TAIL:]
        ):
            return True
    return False


def _spans(text: str, terms: MentionTerms, kind: MentionMatchKind) -> list[tuple[int, int]]:
    if kind is MentionMatchKind.PHONE:
        return [
            match.span()
            for match in _PHONE_RUN.finditer(text)
            if _same_number(digits(match.group()), terms.phones)
        ]
    pattern = (
        _name_pattern(terms.names)
        if kind is MentionMatchKind.NAME
        else _email_pattern(terms.emails)
    )
    return [] if pattern is None else [match.span() for match in pattern.finditer(text)]


def count_matches(text: str | None, terms: MentionTerms) -> dict[MentionMatchKind, int]:
    """How often each kind matches in the text (kinds with no match left out)."""
    if not text or terms.empty():
        return {}
    found = {kind: len(_spans(text, terms, kind)) for kind in MentionMatchKind}
    return {kind: count for kind, count in found.items() if count}


def redact(text: str, terms: MentionTerms, kind: MentionMatchKind, marker: str) -> tuple[str, int]:
    """The text with every match of `kind` replaced by `marker`, and how many were replaced."""
    spans = _spans(text, terms, kind)
    if not spans:
        return text, 0
    parts: list[str] = []
    last = 0
    for start, end in spans:
        parts += [text[last:start], marker]
        last = end
    parts.append(text[last:])
    return "".join(parts), len(spans)


# A tag, with quoted attribute values (which may hold `>`), as sanitised HTML writes it.
_TAG = re.compile(r"<(?:[^>\"']|\"[^\"]*\"|'[^']*')*>")


def _segments(html: str) -> list[tuple[bool, str]]:
    """(is_text, part) in order: text between tags, and the tags themselves."""
    parts: list[tuple[bool, str]] = []
    last = 0
    for match in _TAG.finditer(html):
        if match.start() > last:
            parts.append((True, html[last : match.start()]))
        parts.append((False, match.group()))
        last = match.end()
    if last < len(html):
        parts.append((True, html[last:]))
    return parts


def count_matches_html(html: str | None, terms: MentionTerms) -> dict[MentionMatchKind, int]:
    """As `count_matches`, over the text between tags only."""
    if not html or terms.empty():
        return {}
    total: dict[MentionMatchKind, int] = {}
    for is_text, part in _segments(html):
        if is_text:
            for kind, count in count_matches(part, terms).items():
                total[kind] = total.get(kind, 0) + count
    return total


def redact_html(
    html: str, terms: MentionTerms, kind: MentionMatchKind, marker: str
) -> tuple[str, int]:
    """As `redact`, in the text between tags only; tags and attributes are left as they are."""
    out: list[str] = []
    replaced = 0
    for is_text, part in _segments(html):
        done, count = redact(part, terms, kind, marker) if is_text else (part, 0)
        replaced += count
        out.append(done)
    return "".join(out), replaced
