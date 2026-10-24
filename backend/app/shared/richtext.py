"""Server-side sanitising of rich text (architecture.md §11, §11.4; D-036, D-051).

Every stored rich-text value (work item descriptions now; notes, replies, resolutions and
knowledge articles later) goes through `sanitize_html` before it is saved: the server never trusts
what an editor or an inbound email sends. The allow-list is exactly what the console's Tiptap
editor produces (StarterKit, link, table; packages/ui/src/richtext), so a value written in the
editor survives unchanged and anything else (scripts, event handlers, styles, iframes, images
until file storage exists) is removed.

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
}
URL_SCHEMES = frozenset({"http", "https", "mailto"})
# Right-to-left text: block elements may say which direction they read in.
DIRECTION_TAGS = ("p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "td", "th")
DIRECTION_VALUES = {"rtl", "ltr", "auto"}
_EMPTY = re.compile(r"^(?:\s|<p>\s*</p>|<br\s*/?>)*$")


def sanitize_html(value: str) -> str:
    """The allow-listed form of `value` (scripts, handlers, styles and unknown tags removed)."""
    attributes = {tag: set(names) for tag, names in ALLOWED_ATTRIBUTES.items()}
    return nh3.clean(
        value,
        tags=set(ALLOWED_TAGS),
        clean_content_tags=set(DROPPED_WITH_CONTENT),
        attributes=attributes,
        tag_attribute_values={tag: {"dir": set(DIRECTION_VALUES)} for tag in DIRECTION_TAGS}
        | {"a": {"target": {"_blank"}}},
        url_schemes=set(URL_SCHEMES),
        link_rel="noopener noreferrer nofollow",
        strip_comments=True,
    )


def is_blank(html: str) -> bool:
    """True for empty editor output such as `<p></p>`."""
    return _EMPTY.fullmatch(html) is not None
