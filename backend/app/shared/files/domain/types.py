"""What a file really is, and whether a tenant accepts it (WP-022, D-081, ADR-028 item 6).

Pure functions, no I/O. The type comes from the file's first bytes, never from the browser's
`Content-Type`; the name's extension is a second signal. A file is refused when its extension is
on the tenant's blocked list, or when its content is a native executable, a shebang script or a
Java archive whose family is on the list, whatever its name.
"""

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

SNIFF_BYTES = 8192
NAME_MAX_BYTES = 255

# D-081: executables and scripts are blocked by default; the list is the tenant's to edit.
DEFAULT_BLOCKED_EXTENSIONS: tuple[str, ...] = (
    "exe", "msi", "bat", "cmd", "com", "scr", "pif", "cpl", "dll", "sys", "msc",
    "ps1", "psm1", "vbs", "vbe", "js", "jse", "wsf", "wsh", "hta",
    "sh", "bash", "zsh", "csh", "ksh", "command",
    "jar", "apk", "app", "lnk", "reg",
)  # fmt: skip


class Kind(StrEnum):
    """How a file may be shown: an image or a PDF previews in the browser; others download."""

    IMAGE = "image"
    PDF = "pdf"
    OTHER = "other"


class Family(StrEnum):
    """Content that runs code, named after the extension that blocks it."""

    NATIVE = "exe"  # Windows PE, ELF, Mach-O
    SCRIPT = "sh"  # starts with a shebang
    JAVA = "jar"  # a ZIP carrying a Java manifest


@dataclass(frozen=True)
class Sniffed:
    """The content type found in the first bytes, how it previews, and what code it is, if any."""

    content_type: str
    kind: Kind
    family: Family | None = None
    # SVG and HTML can carry scripts: stored and downloaded, never rendered inline.
    active_markup: bool = False


_NATIVE = (
    b"MZ",  # Windows PE (exe, dll, scr, sys, cpl)
    b"\x7fELF",
    b"\xfe\xed\xfa\xce",  # Mach-O 32/64, both byte orders, and universal binaries
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
)
_MARKUP = re.compile(
    rb"^\s*(<\?xml[^>]*>\s*)?(<!--.*?-->\s*)*<(svg|!doctype html|html)\b",
    re.IGNORECASE | re.DOTALL,
)
# Checked in order: the Java manifest test must come before plain ZIP.
_SIGNATURES: tuple[tuple[Callable[[bytes], bool], Sniffed], ...] = (
    (lambda h: h.startswith(b"\x89PNG\r\n\x1a\n"), Sniffed("image/png", Kind.IMAGE)),
    (lambda h: h.startswith(b"\xff\xd8\xff"), Sniffed("image/jpeg", Kind.IMAGE)),
    (lambda h: h.startswith((b"GIF87a", b"GIF89a")), Sniffed("image/gif", Kind.IMAGE)),
    (lambda h: h[:4] == b"RIFF" and h[8:12] == b"WEBP", Sniffed("image/webp", Kind.IMAGE)),
    (lambda h: h.startswith(b"%PDF-"), Sniffed("application/pdf", Kind.PDF)),
    (
        lambda h: h.startswith(_NATIVE),
        Sniffed("application/x-executable", Kind.OTHER, Family.NATIVE),
    ),
    (lambda h: h.startswith(b"#!"), Sniffed("text/x-script", Kind.OTHER, Family.SCRIPT)),
    (
        lambda h: h.startswith(b"PK\x03\x04") and b"META-INF/MANIFEST.MF" in h,
        Sniffed("application/java-archive", Kind.OTHER, Family.JAVA),
    ),
    (lambda h: h.startswith(b"PK\x03\x04"), Sniffed("application/zip", Kind.OTHER)),
    (  # .doc, .xls, .msg, .msi
        lambda h: h.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
        Sniffed("application/x-ole-storage", Kind.OTHER),
    ),
)


def sniff(head: bytes) -> Sniffed:
    """The type of a file from its first bytes (at most SNIFF_BYTES are needed)."""
    for matches, found in _SIGNATURES:
        if matches(head):
            return found
    if _as_text(head) is None:
        return Sniffed("application/octet-stream", Kind.OTHER)
    if _MARKUP.match(head):
        svg = b"<svg" in head[:1024].lower()
        return Sniffed("image/svg+xml" if svg else "text/html", Kind.OTHER, active_markup=True)
    return Sniffed("text/plain", Kind.OTHER)


def _as_text(head: bytes) -> str | None:
    """The bytes as UTF-8 text (a cut-off character at the end is allowed), else None."""
    if b"\x00" in head:
        return None
    try:
        return head.decode("utf-8")
    except UnicodeDecodeError as error:
        if error.start >= len(head) - 3:  # a multi-byte character cut by the sniff window
            return head[: error.start].decode("utf-8", errors="strict")
        return None


def extension(name: str) -> str:
    """The lower-case extension without the dot ('' when there is none)."""
    base = name.rsplit("/", 1)[-1]
    if "." not in base.strip("."):
        return ""
    return base.rsplit(".", 1)[-1].lower()


def normalise_blocked(values: list[str]) -> list[str]:
    """A tenant's blocked list as stored: lower case, no dots, unique, sorted."""
    cleaned = {v.strip().lstrip(".").lower() for v in values}
    return sorted(v for v in cleaned if re.fullmatch(r"[a-z0-9]{1,16}", v))


def blocked_reason(name: str, sniffed: Sniffed, blocked: list[str]) -> str | None:
    """Why the file is refused (`blocked_extension` / `blocked_content`), or None."""
    listed = set(blocked)
    if extension(name) in listed:
        return "blocked_extension"
    if sniffed.family is not None and sniffed.family.value in listed:
        return "blocked_content"
    return None


def normalise_name(name: str) -> str:
    """A safe display and download name: NFC, no paths or control characters, at most 255 bytes.

    Arabic and Urdu names are kept as they are; only characters that could change where a file
    lands or how a header is read are removed.
    """
    text = unicodedata.normalize("NFC", name)
    text = text.replace("\\", "/").rsplit("/", 1)[-1]
    text = "".join(c for c in text if unicodedata.category(c)[0] != "C" and c not in '"<>|*?:')
    text = text.strip().strip(".") or "file"
    encoded = text.encode("utf-8")
    if len(encoded) > NAME_MAX_BYTES:
        ext = extension(text)
        keep = NAME_MAX_BYTES - (len(ext.encode()) + 1 if ext else 0)
        stem = encoded[:keep].decode("utf-8", errors="ignore").rstrip(".")
        text = f"{stem}.{ext}" if ext else stem
    return text


def inline_allowed(sniffed: Sniffed) -> bool:
    """Whether the browser may render the file itself (images and PDFs, never markup)."""
    return sniffed.kind in {Kind.IMAGE, Kind.PDF} and not sniffed.active_markup
