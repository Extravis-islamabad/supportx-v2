"""Server-side sanitising of rich text (architecture.md §11, §11.4; D-036, D-051).

Every stored rich-text value (work item descriptions now; notes, replies, resolutions and
knowledge articles later) goes through `sanitize_html` before it is saved: the server never trusts
what an editor or an inbound email sends. The allow-list is exactly what the console's Tiptap
editor produces (StarterKit, link, table, and since WP-020b alignment, indent, text colour,
highlight and mentions; packages/ui/src/richtext), so a value written in the editor survives
unchanged and anything else (scripts, event handlers, styles, fonts, sizes, iframes) is removed.

Images (WP-022, ADR-028): only `<img data-file-id="<uuid>" alt="…">`, a file stored and scanned by
SupportX. No `src` is ever stored: the screen asks the files API for the image, which checks the
reader's access and the scan state, so remote tracking images and `data:` URLs never get in.

Colours, alignment and indent are codes in `data-*` attributes, never inline styles: the palette
is fixed (no free colour, font or size), and each theme (light, dark, high contrast) decides the
actual colour so text stays readable everywhere. Alignment is logical (start/end), so it is right
in both reading directions.

Implemented with nh3 (the maintained binding of the Rust `ammonia` sanitiser, MIT/Apache-2.0).
"""

import re
from collections.abc import Iterable

import nh3

# Tags the editor produces.
ALLOWED_TAGS = frozenset(
    {
        "img",  # inline images: files by ID only (WP-022)
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
        "div",  # knowledge callouts only: data-callout from CALLOUTS, nothing else (D-108 (9))
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
    "img": {"data-file-id", "alt"},  # a stored file (data-file-id checked as a UUID)
}
URL_SCHEMES = frozenset({"http", "https", "mailto"})
# Fixed palettes (the console's editor and its CSS use the same codes).
TEXT_COLOURS = frozenset({"brand", "red", "orange", "green", "blue", "grey"})
HIGHLIGHTS = frozenset({"yellow", "green", "blue", "pink"})
ALIGNMENTS = frozenset({"start", "center", "end", "justify"})
INDENT_LEVELS = frozenset({"1", "2", "3", "4", "5", "6"})
# Knowledge article callouts (D-108 (9)): any other value is stripped.
CALLOUTS = frozenset({"info", "warning", "tip", "note"})
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
        # Restricted by value only (nh3: listing it in `attributes` would allow any value).
        "div": {"data-callout": set(CALLOUTS)},
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
    # An image that lost its file ID (a remote or pasted `src` only) has nothing to show: drop it.
    return _IMAGE_WITHOUT_FILE.sub("", _DEAD_LINK.sub(r"\1", cleaned))


def _attribute(tag: str, name: str, value: str) -> str | None:
    """IDs must be UUIDs (a mention's user, an image's file); the rest was checked by the lists."""
    if (tag, name) in {("span", "data-id"), ("img", "data-file-id")}:
        return value if _UUID.fullmatch(value) else None
    return value


_IMAGE_WITHOUT_FILE = re.compile(r"<img(?![^>]*\bdata-file-id=)[^>]*>")
_FILE_IDS = re.compile(r'<img[^>]*\bdata-file-id="([0-9a-fA-F-]{36})"')


def image_file_ids(html: str) -> list[str]:
    """The file IDs of the inline images in sanitised HTML, in order (WP-022)."""
    return _FILE_IDS.findall(html)


def is_blank(html: str) -> bool:
    """True for empty editor output such as `<p></p>`."""
    return _EMPTY.fullmatch(html) is not None


# Mentions as the editor writes them (packages/ui/src/richtext, Tiptap Mention): a span with
# data-type="mention" and data-id="<user uuid>", which the sanitiser keeps exactly. The same rule
# as work_items' conversation (WP-020b); records outside work items (asset notes, WP-049b s2)
# read mentions here, since modules never import each other's internals.
_MENTION_TAG = re.compile(
    r"(<span\b[^>]*\bdata-type=\"mention\"[^>]*>)(.*?)</span>", re.IGNORECASE | re.DOTALL
)
_MENTION_USER = re.compile(
    r"\bdata-id=\"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\"", re.IGNORECASE
)
_ANY_IMAGE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)


def mentioned_user_ids(html: str, limit: int = 20) -> list[str]:
    """User IDs mentioned in sanitised HTML, in order, each once (at most `limit`)."""
    found: list[str] = []
    for tag in _MENTION_TAG.finditer(html):
        match = _MENTION_USER.search(tag.group(1))
        if match is not None and (value := match.group(1).lower()) not in found:
            found.append(value)
    return found[:limit]


def without_mentions(html: str, user_ids: Iterable[str]) -> str:
    """`html` with the mentions of `user_ids` turned into their plain words."""
    wanted = {u.lower() for u in user_ids}
    if not wanted:
        return html

    def plain(match: re.Match[str]) -> str:
        found = _MENTION_USER.search(match.group(1))
        if found is not None and found.group(1).lower() in wanted:
            return match.group(2)
        return match.group(0)

    return _MENTION_TAG.sub(plain, html)


def without_images(html: str) -> str:
    """`html` without inline images (where a record keeps its files as attachments only)."""
    return _ANY_IMAGE.sub("", html)
