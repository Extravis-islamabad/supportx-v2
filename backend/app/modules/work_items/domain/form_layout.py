"""A template's form layout (WP-046a S5b; REQ-INC-036), without I/O.

The designer arranges the create form into sections, each one or two columns and optionally
collapsible, with the labels above or beside the fields. The technician layout is the console's;
the requester layout is the portal's, and when a template has none the portal uses the
technician one. A layout only arranges: what is shown, required or seen by a requester stays in
the template's field settings and form rules, so a field missing from a layout is never lost, it
goes to the end of the last section in the form's usual order (a new custom field appears
without anyone editing every layout).

Stored as `{"technician": Layout, "requester": Layout | null}`; null for the whole column means
the classic single list.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

SECTIONS_MAX = 20
SECTION_ID_MAX = 40
SECTION_NAME_MAX = 80
LANGUAGES = ("en", "ar", "ur")


class LabelPosition(StrEnum):
    """Where a field's label sits."""

    TOP = "top"
    START = "start"  # beside the field, on the reading side (left in English, right in Arabic)


class LayoutAudience(StrEnum):
    """Whose form a layout arranges."""

    TECHNICIAN = "technician"
    REQUESTER = "requester"


@dataclass(frozen=True)
class Section:
    """One section of a laid-out form."""

    id: str
    names: Mapping[str, str]  # its name per language; empty: no heading
    columns: int
    collapsible: bool
    collapsed: bool
    fields: Sequence[str]


@dataclass(frozen=True)
class Arranged:
    """A form laid out: its label position and its sections, every given field placed once."""

    label_position: LabelPosition
    sections: Sequence[Section]


def _section_problems(  # noqa: C901 - one check per part of a section, flat
    raw: Any,  # noqa: ANN401 - untrusted JSON
    path: str,
    known: frozenset[str],
    placed: set[str],
    ids: set[str],
) -> list[tuple[str, str]]:
    if not isinstance(raw, Mapping) or set(raw) - {
        "id",
        "names",
        "columns",
        "collapsible",
        "collapsed",
        "fields",
    }:
        return [(path, "invalid_value")]
    problems: list[tuple[str, str]] = []
    section_id = raw.get("id")
    if not isinstance(section_id, str) or not 0 < len(section_id) <= SECTION_ID_MAX:
        problems.append((f"{path}.id", "invalid_value"))
    elif section_id in ids:
        problems.append((f"{path}.id", "duplicate_value"))
    else:
        ids.add(section_id)
    names = raw.get("names", {})
    if not isinstance(names, Mapping) or any(
        lang not in LANGUAGES or not isinstance(text, str) or len(text) > SECTION_NAME_MAX
        for lang, text in names.items()
    ):
        problems.append((f"{path}.names", "invalid_value"))
    if raw.get("columns", 1) not in (1, 2):
        problems.append((f"{path}.columns", "invalid_choice"))
    problems.extend(
        (f"{path}.{flag}", "invalid_value")
        for flag in ("collapsible", "collapsed")
        if not isinstance(raw.get(flag, False), bool)
    )
    if raw.get("collapsed") and not raw.get("collapsible"):
        problems.append((f"{path}.collapsed", "needs_collapsible"))
    fields = raw.get("fields", [])
    if not isinstance(fields, list):
        return [*problems, (f"{path}.fields", "invalid_value")]
    for index, name in enumerate(fields):
        if name not in known:
            problems.append((f"{path}.fields.{index}", "unknown_field"))
        elif name in placed:
            problems.append((f"{path}.fields.{index}", "duplicate_value"))
        else:
            placed.add(name)
    return problems


def _layout_problems(raw: Any, path: str, known: frozenset[str]) -> list[tuple[str, str]]:  # noqa: ANN401 - untrusted JSON
    if not isinstance(raw, Mapping) or set(raw) - {"label_position", "sections"}:
        return [(path, "invalid_value")]
    problems: list[tuple[str, str]] = []
    if raw.get("label_position", "top") not in set(LabelPosition):
        problems.append((f"{path}.label_position", "invalid_choice"))
    sections = raw.get("sections")
    if not isinstance(sections, list) or not sections:
        return [*problems, (f"{path}.sections", "required")]
    if len(sections) > SECTIONS_MAX:
        return [*problems, (f"{path}.sections", "too_many_values")]
    placed: set[str] = set()
    ids: set[str] = set()
    for index, section in enumerate(sections):
        problems += _section_problems(section, f"{path}.sections.{index}", known, placed, ids)
    return problems


def layout_problems(raw: Any, fields: Iterable[str]) -> list[tuple[str, str]]:  # noqa: ANN401 - untrusted JSON
    """(path, code) for every part of a stored layout that is not valid; empty when it is."""
    if raw is None:
        return []
    known = frozenset(fields)
    if not isinstance(raw, Mapping) or set(raw) - {a.value for a in LayoutAudience}:
        return [("layout", "invalid_value")]
    if LayoutAudience.TECHNICIAN.value not in raw:
        return [("layout.technician", "required")]
    problems: list[tuple[str, str]] = []
    for audience in LayoutAudience:
        part = raw.get(audience.value)
        if part is None and audience is LayoutAudience.REQUESTER:
            continue
        problems += _layout_problems(part, f"layout.{audience.value}", known)
    return problems


def arrange(
    layout: Mapping[str, Any] | None, audience: LayoutAudience, fields: Sequence[str]
) -> Arranged:
    """`fields` (in the form's usual order) laid out for `audience`.

    A field the layout does not place goes to the end of the last section; a placed field not
    in `fields` (hidden, or a requester may not see it) is left out. A validated layout only.
    """
    part: Mapping[str, Any] | None = None
    if layout is not None:
        part = layout.get(audience.value) or layout.get(LayoutAudience.TECHNICIAN.value)
    if part is None:
        return Arranged(
            LabelPosition.TOP,
            [Section("main", {}, 1, collapsible=False, collapsed=False, fields=list(fields))],
        )
    wanted = set(fields)
    placed: set[str] = set()
    sections: list[Section] = []
    for raw in part["sections"]:
        own = [f for f in raw.get("fields", []) if f in wanted]
        placed.update(own)
        sections.append(
            Section(
                id=raw["id"],
                names=dict(raw.get("names", {})),
                columns=int(raw.get("columns", 1)),
                collapsible=bool(raw.get("collapsible", False)),
                collapsed=bool(raw.get("collapsed", False)),
                fields=own,
            )
        )
    rest = [f for f in fields if f not in placed]
    if rest:
        last = sections[-1]
        sections[-1] = Section(
            last.id,
            last.names,
            last.columns,
            last.collapsible,
            last.collapsed,
            [*last.fields, *rest],
        )
    return Arranged(LabelPosition(part.get("label_position", "top")), sections)


__all__ = [
    "SECTIONS_MAX",
    "Arranged",
    "LabelPosition",
    "LayoutAudience",
    "Section",
    "arrange",
    "layout_problems",
]
