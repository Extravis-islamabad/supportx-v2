"""Search snippets as text and marks, never HTML (REQ-KB-053 AC4).

The database marks the matched words with two private-use characters (which the source text
cannot contain: they are removed first). Splitting on them here gives the screen plain text
parts, each marked or not, so a snippet can never carry markup into the page.
"""

from dataclasses import dataclass

MARK_START = ""
MARK_END = ""


@dataclass(frozen=True)
class SnippetPart:
    """A run of snippet text; `mark`: one of the searched words."""

    text: str
    mark: bool


def split_marks(headline: str) -> list[SnippetPart]:
    """`a b c` → [a ], [b, marked], [ c]. Unbalanced marks end at the text's end."""
    parts: list[SnippetPart] = []
    marked = False
    current: list[str] = []
    for char in headline:
        if char in (MARK_START, MARK_END):
            if current:
                parts.append(SnippetPart("".join(current), marked))
                current = []
            marked = char == MARK_START
            continue
        current.append(char)
    if current:
        parts.append(SnippetPart("".join(current), marked))
    return [p for p in parts if p.text.strip() or not p.mark]
