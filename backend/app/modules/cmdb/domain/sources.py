"""Where each CI attribute's value came from, and which source wins (REQ-CMDB-016). Pure: no I/O.

- **A stamp per attribute** (`{source, at}`): each core field a person edits and each custom
  value (`custom.<key>`) records the source that last set it and when. The path that writes the
  value sets it (a hand edit, an asset sync rule, an import, MonetX, an integration), never the
  client.
- **Who wins** is an ordered list of sources, the tenant's for every attribute, with an optional
  order of its own for chosen attributes. A write from a source ranked below the one that set
  the value leaves it unchanged and is reported as `kept`, never an error.
- **A person's edit always applies**: ranking `hand` lower for an attribute means automated
  sources may overwrite a hand-set value there, never that a person's change is ignored. The
  tenant-wide order keeps `hand` first; only an attribute's own order may put it lower.

Shaped so assets' attribute sources (REQ-DSC-019, WP-050) can share it later.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.modules.cmdb.domain.types import Problem


class AttributeSource(StrEnum):
    """Where an attribute's value came from (`cmdb_attribute_source.<code>`)."""

    HAND = "hand"
    IMPORT = "import"
    ASSET_SYNC = "asset_sync"
    DISCOVERY = "discovery"
    MONETX = "monetx"
    INTEGRATION = "integration"


DEFAULT_ORDER: tuple[AttributeSource, ...] = (
    AttributeSource.HAND,
    AttributeSource.IMPORT,
    AttributeSource.ASSET_SYNC,
    AttributeSource.DISCOVERY,
    AttributeSource.MONETX,
    AttributeSource.INTEGRATION,
)
OVERRIDES_MAX = 200  # attributes with an order of their own
# Problem codes (labelled `errors.field.<code>`).
ORDER_INCOMPLETE = "cmdb_source_order_incomplete"
HAND_FIRST = "cmdb_source_hand_first"
UNKNOWN_ATTRIBUTE = "cmdb_source_unknown_attribute"
TOO_MANY = "too_many"
FIELD_PROBLEMS = frozenset({ORDER_INCOMPLETE, HAND_FIRST, UNKNOWN_ATTRIBUTE, TOO_MANY})


@dataclass(frozen=True)
class Stamp:
    """Who set one attribute's value, and when."""

    source: AttributeSource
    at: datetime


@dataclass(frozen=True)
class Precedence:
    """Which source wins: the tenant's order, and orders of their own for chosen attributes."""

    order: tuple[AttributeSource, ...] = DEFAULT_ORDER
    overrides: Mapping[str, tuple[AttributeSource, ...]] = field(default_factory=dict)

    def ranking(self, attribute: str) -> tuple[AttributeSource, ...]:
        """The order that decides for `attribute` (its own, else the tenant's)."""
        return self.overrides.get(attribute, self.order)

    def rank(self, attribute: str, source: AttributeSource) -> int:
        """0 for the strongest source; a source missing from an order ranks last."""
        ranking = self.ranking(attribute)
        return ranking.index(source) if source in ranking else len(ranking)


def wins(
    precedence: Precedence, attribute: str, incoming: AttributeSource, current: Stamp | None
) -> bool:
    """Whether a write from `incoming` may replace the attribute's current value.

    A person's edit always does; so does a source writing over its own value or over a value no
    source has claimed; otherwise the stronger (or equal) source wins.
    """
    if incoming is AttributeSource.HAND or current is None or current.source is incoming:
        return True
    return precedence.rank(attribute, incoming) <= precedence.rank(attribute, current.source)


def _source(value: object) -> AttributeSource | None:
    try:
        return AttributeSource(str(value))
    except ValueError:
        return None


def _order(values: object) -> tuple[AttributeSource, ...] | None:
    if not isinstance(values, list | tuple):
        return None
    found = tuple(s for s in (_source(v) for v in values) if s is not None)
    return found if len(found) == len(values) else None


def precedence_of(data: Mapping[str, Any] | None) -> Precedence:
    """The stored settings as a precedence; anything unreadable falls back to the defaults."""
    if not data:
        return Precedence()
    order = _order(data.get("order")) or DEFAULT_ORDER
    raw = data.get("overrides")
    overrides: dict[str, tuple[AttributeSource, ...]] = {}
    if isinstance(raw, Mapping):
        for attribute, values in raw.items():
            if (found := _order(values)) is not None:
                overrides[str(attribute)] = found
    return Precedence(order, overrides)


def precedence_json(precedence: Precedence) -> dict[str, Any]:
    """The stored form."""
    return {
        "order": [s.value for s in precedence.order],
        "overrides": {k: [s.value for s in v] for k, v in sorted(precedence.overrides.items())},
    }


def _complete(values: Iterable[AttributeSource]) -> bool:
    listed = list(values)
    return len(listed) == len(DEFAULT_ORDER) and set(listed) == set(DEFAULT_ORDER)


def precedence_problems(
    order: Iterable[AttributeSource],
    overrides: Mapping[str, Iterable[AttributeSource]],
    attributes: Iterable[str],
) -> list[Problem]:
    """What is wrong with a new order.

    Each order names every source once; `hand` leads the tenant's order; an attribute's own
    order is for a known attribute (`attributes`).
    """
    problems: list[Problem] = []
    listed = list(order)
    if not _complete(listed):
        problems.append(Problem("order", ORDER_INCOMPLETE))
    elif listed[0] is not AttributeSource.HAND:
        problems.append(Problem("order", HAND_FIRST))
    if len(overrides) > OVERRIDES_MAX:
        problems.append(Problem("overrides", TOO_MANY))
    known = set(attributes)
    for attribute, values in sorted(overrides.items()):
        if attribute not in known:
            problems.append(Problem(f"overrides.{attribute}", UNKNOWN_ATTRIBUTE))
        elif not _complete(values):
            problems.append(Problem(f"overrides.{attribute}", ORDER_INCOMPLETE))
    return problems


def stamps(data: Mapping[str, Any] | None) -> dict[str, Stamp]:
    """The stored stamps (an unreadable one is left out: as if no source had claimed it)."""
    found: dict[str, Stamp] = {}
    for attribute, raw in (data or {}).items():
        if not isinstance(raw, Mapping):
            continue
        source = _source(raw.get("source"))
        try:
            at = datetime.fromisoformat(str(raw.get("at")))
        except ValueError:
            continue
        if source is not None:
            found[str(attribute)] = Stamp(source, at)
    return found


def stamped(
    data: Mapping[str, Any] | None,
    attributes: Iterable[str],
    source: AttributeSource,
    at: datetime,
) -> dict[str, Any]:
    """The stored stamps with `attributes` now set by `source` at `at`."""
    out = dict(data or {})
    for attribute in attributes:
        out[attribute] = {"source": source.value, "at": at.isoformat()}
    return out


def unstamped(data: Mapping[str, Any] | None, attributes: Iterable[str]) -> dict[str, Any]:
    """The stored stamps without `attributes` (their values were dropped)."""
    gone = set(attributes)
    return {k: v for k, v in (data or {}).items() if k not in gone}


def shown(data: Mapping[str, Any] | None, withheld: Iterable[str]) -> dict[str, Stamp]:
    """The stamps a reader may see: never one of a withheld (hidden, masked, sealed) field."""
    out = set(withheld)
    return {k: v for k, v in stamps(data).items() if k not in out}
