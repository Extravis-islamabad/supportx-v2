"""Names inside a downloaded archive (WP-046a S2; REQ-INC-080, lane B's rules). Pure.

Every entry name is built here from the stored file name, never from a client path: NFC, no
path separators, no `..`, no drive letters, no control characters, no leading dots, a length
cap that keeps the extension, and collisions numbered "name (2).ext".
"""

import re
import unicodedata

MAX_ENTRY_LEN = 120
MAX_EXTENSION = 10  # a longer "extension" is part of the name, cut like the rest
FALLBACK = "file"
MANIFEST = "manifest.txt"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_DRIVE = re.compile(r"^[A-Za-z]:")


def _clean(name: str) -> str:
    text = unicodedata.normalize("NFC", name)
    text = _CONTROL.sub("", text)
    text = _DRIVE.sub("", text)
    # The last path part only: a stored name never makes a folder.
    text = re.split(r"[\\/]", text)[-1]
    text = text.replace("..", "")
    text = text.strip().lstrip(".").strip()
    return text or FALLBACK


def _cap(name: str, max_len: int) -> str:
    if len(name) <= max_len:
        return name
    stem, dot, ext = name.rpartition(".")
    if dot and 0 < len(ext) <= MAX_EXTENSION and stem:
        return stem[: max_len - len(ext) - 1].rstrip() + "." + ext
    return name[:max_len].rstrip()


def safe_entry_name(name: str, *, taken: set[str], max_len: int = MAX_ENTRY_LEN) -> str:
    """A safe, unique entry name for `name`; adds it to `taken` (compared ignoring case)."""
    base = _cap(_clean(name), max_len)
    if base.casefold() == MANIFEST:  # the manifest's own name is never a file's
        base = f"{FALLBACK}-{base}"
    candidate = base
    number = 2
    while candidate.casefold() in taken:
        stem, dot, ext = base.rpartition(".")
        if dot and stem:
            candidate = _cap(f"{stem} ({number}).{ext}", max_len + 6)
        else:
            candidate = f"{base} ({number})"
        number += 1
    taken.add(candidate.casefold())
    return candidate


def manifest_text(left_out: list[tuple[str, str]], heading: str) -> str:
    """The manifest: a heading, then one line per file left out, by ID and reason only.

    Never a name: a file the reader may not see is named by nothing they could not know.
    """
    lines = [heading, ""]
    lines += [f"{file_id}\t{reason}" for file_id, reason in left_out]
    return "\n".join(lines) + "\n"


__all__ = ["MANIFEST", "MAX_ENTRY_LEN", "manifest_text", "safe_entry_name"]
