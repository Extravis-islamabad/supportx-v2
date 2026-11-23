"""Merging duplicate CIs and importing CIs: the rules (WP-053 S4b; REQ-CMDB-017, 018). Pure.

Merge: each field of the preview takes a side, the survivor's unless it has no value; the
suggested survivor is the CI linked to an asset, then the older one (never a value the merger may
not read: lane C (9)). The merged CI's relationships move to the survivor with duplicates and
self-links collapsed (AC1).

Import: the column headings a file may use, the modes and the row outcomes. A row is matched only
against what the importer may see: an unseen CI is "not there" (lane C (6)), so a missing and an
unseen one read the same (`not_found`), and an add that collides with an unseen one is the same
generic `row_conflict` as any other add that collides.
"""

import uuid
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.shared import sheets

CUSTOM = "custom."
# Core fields a merge chooses between (the type is the same on both sides; display IDs stay).
MERGE_FIELDS = (
    "name",
    "description",
    "state_id",
    "site_id",
    "owner_user_id",
    "owner_group_id",
    "managed_by_group_id",
    "business_impact",
    "criticality",
)


class CiMergeSide(StrEnum):
    """Which CI's value the survivor keeps (`cmdb_merge_side.<code>`)."""

    SURVIVOR = "survivor"
    MERGED = "merged"


@dataclass(frozen=True)
class Candidate:
    """What the survivor suggestion may look at: never a field value."""

    asset_linked: bool
    created_at: datetime


def suggest_survivor(first: Candidate, second: Candidate) -> int:
    """0 or 1: the CI linked to an asset, then the older one; the first on a tie."""
    if first.asset_linked != second.asset_linked:
        return 0 if first.asset_linked else 1
    return 1 if second.created_at < first.created_at else 0


def empty(value: object) -> bool:
    """No value: None or blank text."""
    return value is None or (isinstance(value, str) and not value.strip())


def default_side(survivor: object, merged: object) -> CiMergeSide:
    """The survivor's value unless it has none and the merged CI has one."""
    return CiMergeSide.MERGED if empty(survivor) and not empty(merged) else CiMergeSide.SURVIVOR


def mergeable_fields(
    survivor_custom: Mapping[str, Any], merged_custom: Mapping[str, Any], withheld: Collection[str]
) -> list[str]:
    """The core fields, then each custom field either CI holds that the merger may read."""
    keys = sorted((set(survivor_custom) | set(merged_custom)) - set(withheld))
    return [*MERGE_FIELDS, *(f"{CUSTOM}{k}" for k in keys)]


def choice_problems(choices: Mapping[str, str], allowed: Collection[str]) -> list[tuple[str, str]]:
    """(field, code) for each choice of an unknown or withheld field, or an unknown side."""
    sides = {s.value for s in CiMergeSide}
    problems: list[tuple[str, str]] = []
    for name, side in choices.items():
        if name not in allowed:
            problems.append((f"choices.{name}", "unknown_field"))
        elif side not in sides:
            problems.append((f"choices.{name}", "invalid_choice"))
    return problems


@dataclass(frozen=True)
class Link:
    """One live relationship: its ID, type and ends."""

    id: uuid.UUID
    type_id: uuid.UUID
    from_ci_id: uuid.UUID
    to_ci_id: uuid.UUID


@dataclass(frozen=True)
class LinkMove:
    """What a merge does with one of the merged CI's relationships."""

    link: Link
    from_ci_id: uuid.UUID
    to_ci_id: uuid.UUID
    collapse: bool  # a duplicate of a live one, or a link of the survivor to itself: removed


def move_links(
    links: Sequence[Link], merged: uuid.UUID, survivor: uuid.UUID, others: Iterable[Link]
) -> list[LinkMove]:
    """The merged CI's links re-pointed at the survivor (AC1: two links to one service end as one).

    `links`: the merged CI's live links; `others`: every other live link on the survivor. A move
    that would repeat a live link (same type and ends) or join the survivor to itself collapses.
    """
    taken = {(o.type_id, o.from_ci_id, o.to_ci_id) for o in others}
    moves: list[LinkMove] = []
    for link in sorted(links, key=lambda x: str(x.id)):
        start = survivor if link.from_ci_id == merged else link.from_ci_id
        end = survivor if link.to_ci_id == merged else link.to_ci_id
        key = (link.type_id, start, end)
        collapse = start == end or key in taken
        if not collapse:
            taken.add(key)
        moves.append(LinkMove(link, start, end, collapse))
    return moves


# --- import (REQ-CMDB-018) ------------------------------------------------------------------------

MAX_IMPORT_ROWS = 20_000  # as the assets' import (REQ-AST-053)
MAX_IMPORT_FILE_BYTES = 25 * 1024 * 1024
# D-092's limits (WP-021): columns, cells, zip entries and ratio as sheets' defaults; the unpacked
# cap grows with the file (10x), as the assets' import (coordinator, 2026-11-11).
IMPORT_LIMITS = sheets.SheetLimits(
    max_rows=MAX_IMPORT_ROWS,
    max_file_bytes=MAX_IMPORT_FILE_BYTES,
    max_unpacked_bytes=10 * MAX_IMPORT_FILE_BYTES,
)
MAX_IMPORT_PROBLEMS = 5000  # kept on the import; the counts stay exact beyond


class CiImportKind(StrEnum):
    """What a file holds (`cmdb_import_kind.<code>`)."""

    CIS = "cis"
    RELATIONSHIPS = "relationships"


class CiImportMode(StrEnum):
    """What a CI row does (`cmdb_import_mode.<code>`); relationship rows only ever add."""

    ADD = "add"
    UPDATE = "update"
    ADD_UPDATE = "add_update"


class CiImportMatch(StrEnum):
    """How a row names a CI (`cmdb_import_match.<code>`): by display ID, or by name."""

    DISPLAY_ID = "display_id"
    NAME = "name"


class CiImportStatus(StrEnum):
    """Where an import is (`cmdb_import_status.<code>`). `checked`: a dry run finished."""

    QUEUED = "queued"
    RUNNING = "running"
    CHECKED = "checked"
    DONE = "done"
    FAILED = "failed"


class CiRowOutcome(StrEnum):
    """What a row did (or, in a dry run, would do)."""

    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"  # the same values, or a relationship already there (AC2)


# Row problem codes (labelled `errors.field.<code>`).
NOT_FOUND = "not_found"  # missing, or not visible to the importer: the same (lane C (6))
ROW_CONFLICT = "row_conflict"  # an add that collides, with a CI seen or not (lane C (6))
AMBIGUOUS = "cmdb_import_ambiguous"  # the name fits more than one CI the importer sees
REQUIRED = "required"
TYPE_UNKNOWN = "cmdb_import_relationship_type_unknown"
NOT_PERMITTED = "cmdb_import_not_permitted"
INVALID = "invalid_value"

# Column heading (lowercase, spaces or underscores) -> field. Field codes and English headings.
CI_COLUMNS = {
    "display id": "display_id",
    "id": "display_id",
    "name": "name",
    "description": "description",
    "state": "state",
    "business impact": "business_impact",
    "criticality": "criticality",
}
RELATIONSHIP_COLUMNS = {
    "from": "from",
    "relationship": "relationship",
    "type": "relationship",
    "to": "to",
}


class ImportRefused(Exception):
    """The file cannot be imported at all: a sheet code or a header code."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        """`detail`: the unknown column's heading, or the row with a long cell."""
        super().__init__(code)
        self.code = code
        self.detail = detail


def _heading(cell: str) -> str:
    return " ".join(cell.strip().lower().replace("_", " ").split())


def header_fields(
    kind: CiImportKind, match: CiImportMatch, cells: Sequence[str]
) -> list[str | None]:
    """Each column's field (None: an empty heading); refuses unknown or missing columns."""
    columns = CI_COLUMNS if kind is CiImportKind.CIS else RELATIONSHIP_COLUMNS
    fields: list[str | None] = []
    for cell in cells:
        heading = _heading(cell)
        if not heading:
            fields.append(None)
            continue
        found = columns.get(heading)
        if found is None:
            msg = "cmdb_import_unknown_column"
            raise ImportRefused(msg, detail=cell.strip()[:100])
        if found in fields:
            msg = "cmdb_import_duplicate_column"
            raise ImportRefused(msg, detail=cell.strip()[:100])
        fields.append(found)
    needed = (
        {"from", "relationship", "to"}
        if kind is CiImportKind.RELATIONSHIPS
        else {"display_id" if match is CiImportMatch.DISPLAY_ID else "name"}
    )
    missing = sorted(needed - {f for f in fields if f})
    if missing:
        msg = "cmdb_import_missing_column"
        raise ImportRefused(msg, detail=missing[0])
    return fields


@dataclass(frozen=True)
class ImportRows:
    """The data rows as {field: text}, with their number in the file (the header is row 1)."""

    rows: list[tuple[int, dict[str, str]]]


def read_import(
    kind: CiImportKind, match: CiImportMatch, file_format: str, content: bytes
) -> ImportRows:
    """Every data row; refuses the whole file when a limit (D-092) or the header is wrong."""
    header: list[str | None] | None = None
    rows: list[tuple[int, dict[str, str]]] = []
    try:
        for number, cells in enumerate(sheets.raw_rows(file_format, content, IMPORT_LIMITS), 1):
            if header is None:
                header = header_fields(kind, match, cells)
                continue
            if not any(cell.strip() for cell in cells):
                continue
            rows.append(
                (
                    number,
                    {
                        name: cells[index].strip()
                        for index, name in enumerate(header)
                        if name and index < len(cells)
                    },
                )
            )
    except sheets.SheetRefused as refused:
        msg = f"cmdb_import_{refused.code}"
        raise ImportRefused(msg, refused.detail) from None
    if header is None:
        msg = f"cmdb_import_{sheets.FILE_EMPTY}"
        raise ImportRefused(msg)
    return ImportRows(rows)


# What a spreadsheet reads as a formula, or as one after a leading tab or return (OWASP).
FORMULA_STARTS = frozenset({"=", "+", "-", "@", "\t", "\r"})


def safe_cell(value: str) -> str:
    """A cell for a CSV a person opens: a leading formula character is neutralised."""
    return f"'{value}" if value[:1] in FORMULA_STARTS else value
