"""Asset labels (REQ-AST-039): what a label holds and how big it is. Pure, no I/O.

- A QR code holds only the console link to the asset (`{console}/assets/{id}`): no tag, name or
  any other asset data, so a stranger who scans it learns nothing (AC2); the console asks them
  to sign in, and a person who may not see the asset gets the usual "not found".
- A Code 128 barcode on an asset label holds its tag (printed beside it in plain text anyway).
- Vendor codes (the codes a supplier printed, typed in) are printed as they are.
- Two built-in layouts: a small cable label and a laptop label (REQ-AST-040, the designer, is
  later). Each label is one page, so a label printer cuts them apart.
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum

LABELS_MAX = 500  # per job (the coordinator's cap; the migration's check)
CODE_MAX = 120  # one vendor code (the asset barcode's length)
# The PDF's own caps (the shared renderer refuses beyond them): one page per label, and bytes.
PAGES_MAX = LABELS_MAX
BYTES_MAX = 25 * 1024 * 1024
LINK_DAYS = 7  # the file can be downloaded for a week


class LabelTarget(StrEnum):
    """What the labels are for."""

    ASSET = "asset"
    VENDOR_CODE = "vendor_code"


class LabelLayout(StrEnum):
    """The built-in label sizes."""

    CABLE = "cable"
    LAPTOP = "laptop"


class Symbology(StrEnum):
    """The code printed: a QR code or a Code 128 barcode."""

    QR = "qr"
    CODE128 = "code128"


class LabelJobStatus(StrEnum):
    """Where a label job stands."""

    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class LayoutSize:
    """A label's page size and the code's size on it, in millimetres."""

    width_mm: float
    height_mm: float
    code_mm: float  # QR side, or barcode height
    shows_name: bool


LAYOUTS: dict[LabelLayout, LayoutSize] = {
    # A flag around a cable: the code and the tag only.
    LabelLayout.CABLE: LayoutSize(width_mm=50, height_mm=18, code_mm=14, shows_name=False),
    # The lid or the base of a laptop: the code, the name and the tag.
    LabelLayout.LAPTOP: LayoutSize(width_mm=70, height_mm=32, code_mm=26, shows_name=True),
}


@dataclass(frozen=True, slots=True)
class Label:
    """One label as printed: the code's content and the text beside it."""

    content: str  # what the QR code or barcode encodes
    title: str | None  # the asset's name (laptop layout), or None
    caption: str  # the tag, or the vendor code


def asset_link(console_url: str, asset_id: uuid.UUID) -> str:
    """The QR content: the console's asset page, nothing else (AC2)."""
    return f"{console_url.rstrip('/')}/assets/{asset_id}"


def asset_label(
    console_url: str,
    asset_id: uuid.UUID,
    *,
    tag: str | None,
    name: str,
    symbology: Symbology,
) -> Label:
    """An asset's label: the link in a QR code, or the tag in a barcode."""
    caption = tag or ""
    if symbology is Symbology.QR:
        content = asset_link(console_url, asset_id)
    else:
        # A barcode needs something to encode: the tag, else the link (an asset always has one
        # of them; tags are given from the pattern, REQ-AST-008).
        content = tag or asset_link(console_url, asset_id)
    return Label(content=content, title=name, caption=caption)


def vendor_label(code: str) -> Label:
    """A vendor code's label: the code, encoded and in plain text."""
    return Label(content=code, title=None, caption=code)


def clean_codes(raw: list[str]) -> tuple[list[str], str | None]:
    """Vendor codes trimmed, blanks dropped; and the problem code when they are not printable."""
    codes = [" ".join(str(c).split()) for c in raw]
    codes = [c for c in codes if c]
    if not codes:
        return [], "required"
    if any(len(c) > CODE_MAX for c in codes):
        return [], "value_too_long"
    if any(not c.isprintable() for c in codes):
        return [], "invalid_value"
    if len(codes) > LABELS_MAX:
        return [], "too_many"
    return codes, None
