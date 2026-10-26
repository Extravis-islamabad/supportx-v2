"""Server-side sanitising of rich text (architecture.md §11, §11.4; D-036, D-051).

Every stored rich-text value (work item descriptions now; notes, replies, resolutions and
knowledge articles later) goes through `sanitize_html` before it is saved: the server never trusts
what an editor or an inbound email sends. The allow-list is exactly what the console's Tiptap
editor produces (StarterKit, link, table, and since WP-020b alignment, indent, text colour,
highlight and mentions; packages/ui/src/richtext), so a value written in the editor survives
unchanged and anything else (scripts, event handlers, styles, fonts, sizes, iframes, images until
file storage exists, WP-022) is removed.

Colours, alignment and indent are codes in `data-*` attributes, never inline styles: the palette
is fixed (no free colour, font or size), and each theme (light, dark, high contrast) decides the
actual colour so text stays readable everywhere. Alignment is logical (start/end), so it is right
in both reading directions.

Implemented with nh3 (the maintained binding of the Rust `ammonia` sanitiser, MIT/Apache-2.0).
"""

import re

import nh3

# Tags the editor produces. Images come with file storage (WP-022).
ALLOWED_TAGS = frozenset(
    {
        "p",
        "br",
        "strong",
        "em",
        "u",
        "s",
        "code",
        "pre",
        "blockquote",
        "ul",
        "ol",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "a",
        "table",
        "tbody",
        "thead",
        "tr",
        "th",
        "td",
        "colgroup",
        "col",
        "span",  # text colour, mentions
        "mark",  # highlight
    }
)
# Removed together with everything inside them (not just the tag).
DROPPED_WITH_CONTENT = frozenset({"script", "style", "iframe", "object", "embed", "template"})
ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href"},  # target: only _blank (tag_attribute_values)
    "th": {"colspan", "rowspan", "colwidth"},
    "td": {"colspan", "rowspan", "colwidth"},
    "col": {"span"},
    "ol": {"start"},
    "span": {"data-id", "data-label"},  # mentions (data-id checked as a UUID)
}
URL_SCHEMES = frozenset({"http", "https", "mailto"})
# Fixed palettes (the console's editor and its CSS use the same codes).
TEXT_COLOURS = frozenset({"brand", "red", "orange", "green", "blue", "grey"})
HIGHLIGHTS = frozenset({"yellow", "green", "blue", "pink"})
ALIGNMENTS = frozenset({"start", "center", "end", "justify"})
INDENT_LEVELS = frozenset({"1", "2", "3", "4", "5", "6"})
BLOCK_FORMAT_TAGS = ("p", "h2", "h3", "h4")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
# Right-to-left text: block elements may say which direction they read in.
DIRECTION_TAGS = ("p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "td", "th")
DIRECTION_VALUES = {"rtl", "ltr", "auto"}
_EMPTY = re.compile(r"^(?:\s|<p>\s*</p>|<br\s*/?>)*$")


# A link left without an address (refused scheme, or none at all) after cleaning.
_DEAD_LINK = re.compile(r"<a(?:\s+(?:target|rel)=\"[^\"]*\")*\s*>(.*?)</a>", re.DOTALL)


def sanitize_html(value: str) -> str:
    """The allow-listed form of `value` (scripts, handlers, styles and unknown tags removed).

    A link whose address is refused keeps its words as plain text (QA C4), never a dead
    underlined fragment that goes nowhere.
    """
    attributes = {tag: set(names) for tag, names in ALLOWED_ATTRIBUTES.items()}
    values: dict[str, dict[str, set[str]]] = {
        tag: {"dir": set(DIRECTION_VALUES)} for tag in DIRECTION_TAGS
    }
    for tag in BLOCK_FORMAT_TAGS:
        values[tag] |= {"data-align": set(ALIGNMENTS), "data-indent": set(INDENT_LEVELS)}
    values |= {
        "a": {"target": {"_blank"}},
        "span": {"data-color": set(TEXT_COLOURS), "data-type": {"mention"}},
        "mark": {"data-color": set(HIGHLIGHTS)},
    }
    cleaned = nh3.clean(
        value,
        tags=set(ALLOWED_TAGS),
        clean_content_tags=set(DROPPED_WITH_CONTENT),
        attributes=attributes,
        tag_attribute_values=values,
        attribute_filter=_attribute,
        url_schemes=set(URL_SCHEMES),
        link_rel="noopener noreferrer nofollow",
        strip_comments=True,
    )
    return _DEAD_LINK.sub(r"\1", cleaned)


def _attribute(tag: str, name: str, value: str) -> str | None:
    """A mention's data-id must be a user ID; everything else was checked by the lists above."""
    if tag == "span" and name == "data-id":
        return value if _UUID.fullmatch(value) else None
    return value


def is_blank(html: str) -> bool:
    """True for empty editor output such as `<p></p>`."""
    return _EMPTY.fullmatch(html) is not None
