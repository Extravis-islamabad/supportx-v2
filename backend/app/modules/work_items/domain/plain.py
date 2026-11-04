"""Readable text from sanitised HTML (descriptions, replies, notes) for AI prompts. Pure."""

import html
import re

_BREAKS = re.compile(r"<\s*(br|/p|/li|/h[1-6]|/tr|/blockquote|/div)\b[^>]*>", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t\f\v]+")
_LINES = re.compile(r"\n\s*\n+")


def plain_text(value: str | None) -> str:
    """The text of sanitised HTML: line breaks kept at block ends, tags dropped, entities read."""
    if not value:
        return ""
    text = _BREAKS.sub("\n", value)
    text = html.unescape(_TAGS.sub(" ", text))
    text = _SPACES.sub(" ", text)
    lines = (line.strip() for line in text.splitlines())
    return _LINES.sub("\n\n", "\n".join(lines)).strip()
