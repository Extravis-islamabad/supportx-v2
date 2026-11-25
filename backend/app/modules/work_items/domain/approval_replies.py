"""An approver's reply to an approval mail, read as a decision (WP-047a S4; REQ-SR-038). Pure.

The reply's first line of its own (above any quoted mail or signature) must be one decision word
with nothing but courtesy words and punctuation around it: "Approved, thanks" approves, "Reject."
rejects. Anything else on that line ("approve only if cheaper", "not approved", "no problem,
approved") is unclear and never applied: the service answers with the link instead. The lines
after it are the comment. No AI at V1 (the coordinator, Q3): this function is the one place a
shared reply reader (REQ-AI-056) would replace later.

The words are data, per language (English, Arabic and Urdu), and are compared after folding
case, Arabic diacritics and the tatweel, so "شكراً" and "شكرا" read the same.
"""

import re
import unicodedata
from dataclasses import dataclass

from app.modules.work_items.domain.approvals import COMMENT_MAX, Decision

APPROVE_WORDS = frozenset(
    {
        # English
        "approve",
        "approved",
        "approving",
        "yes",
        # Arabic
        "موافق",
        "موافقة",
        "أوافق",
        "اوافق",
        "نعم",
        # Urdu
        "منظور",
        "منظوری",
        "ہاں",
        "ہان",
    }
)
REJECT_WORDS = frozenset(
    {
        # English
        "reject",
        "rejected",
        "rejecting",
        "decline",
        "declined",
        # Arabic
        "رفض",
        "أرفض",
        "ارفض",
        "مرفوض",
        # Urdu
        "نامنظور",
        "مسترد",
    }
)
# Words that may follow the decision without changing it. Never a word that could qualify it:
# "only", "if", "not", "but" make the reply unclear.
COURTESY_WORDS = frozenset(
    {
        # English
        "thanks",
        "thank",
        "you",
        "ok",
        "okay",
        "please",
        "cheers",
        "regards",
        "sure",
        "done",
        "many",
        "much",
        "very",
        "kind",
        # Arabic
        "شكرا",
        "جزيلا",
        "لك",
        "لكم",
        # Urdu
        "شکریہ",
        "بہت",
        "جی",
        "مہربانی",
    }
)
# The quoted original or a signature starts here: nothing below is the approver's reply.
_QUOTE_START = re.compile(
    r"^\s*(>|-- ?$|_{5,}|-{5,}|On .+ wrote:|From:|Sent:|في .+ كتب|کو .+ نے لکھا)",
    re.IGNORECASE,
)
_ARABIC_MARKS = re.compile("[ؐ-ًؚ-ٰٟـ]")
_WORD = re.compile(r"\w+")


@dataclass(frozen=True)
class ReplyIntent:
    """What a reply asks: a decision and its comment, or nothing clear (`decision` None)."""

    decision: Decision | None
    comment: str | None = None


def _fold(text: str) -> str:
    return _ARABIC_MARKS.sub("", unicodedata.normalize("NFC", text)).casefold()


def _own_lines(text: str) -> list[str]:
    """The reply's own lines: everything above the quoted mail or the signature."""
    own: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if _QUOTE_START.match(line):
            break
        own.append(line.strip())
    while own and not own[-1]:
        own.pop()
    return own


def _decision(first_line: str) -> Decision | None:
    """The first line's decision: one decision word, only courtesy around it; else None."""
    words = _WORD.findall(_fold(first_line))
    # Courtesy may come first too ("Thanks, approved"; Urdu's "جی ہاں").
    lead = next((i for i, word in enumerate(words) if word not in COURTESY_WORDS), None)
    if lead is None:
        return None
    if any(word not in COURTESY_WORDS for word in words[lead + 1 :]):
        return None  # the line qualifies the decision: never applied
    head = words[lead]
    if head in APPROVE_WORDS:
        return Decision.APPROVE
    return Decision.REJECT if head in REJECT_WORDS else None


def read_reply(text: str) -> ReplyIntent:
    """The decision a reply's text asks for, or an unclear intent (never a guess)."""
    lines = _own_lines(text)
    first = next((i for i, line in enumerate(lines) if line), None)
    decision = None if first is None else _decision(lines[first])
    if first is None or decision is None:
        return ReplyIntent(None)
    comment = "\n".join(lines[first + 1 :]).strip()
    if len(comment) > COMMENT_MAX:
        return ReplyIntent(None)  # longer than a decision's comment may be: use the link
    return ReplyIntent(decision, comment or None)


__all__ = [
    "APPROVE_WORDS",
    "COURTESY_WORDS",
    "REJECT_WORDS",
    "ReplyIntent",
    "read_reply",
]
