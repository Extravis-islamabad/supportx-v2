"""Sync rules: which assets become CIs of which type, and how their fields map (REQ-CMDB-015).

Pure: no I/O. The service reads the assets through the assets module's public interface and
writes the CIs through the CI service's own save path; this decides what a run would do.

- **The field map** names, for each CI attribute it fills, the asset field it takes. Only asset
  fields assets marks syncable are offered (never money, personal, sealed or rule-restricted
  ones); the two sides must hold the same kind of value (text, a site, a group); `name` is
  always mapped, since a new CI needs one.
- **Each asset's outcome**: `created` (no CI yet), `updated` (a mapped value changed and the
  rule's source wins), `kept` (it changed but a stronger source set the CI's value; nothing is
  overwritten), `unchanged`, or `failed` (the CI's own checks refused a value).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.modules.cmdb.domain.sources import AttributeSource, Precedence, Stamp, wins
from app.modules.cmdb.domain.types import Problem

CUSTOM = "custom."
FIELD_MAP_MAX = 50
OUTCOMES_MAX = 500  # item outcomes a run keeps (the counts cover every asset)
NAME_MAX = 200


class SyncSourceKind(StrEnum):
    """What a rule reads (`cmdb_sync_source.<code>`); discovery comes with WP-050."""

    ASSETS = "assets"


class SyncTrigger(StrEnum):
    """Why a run started (`cmdb_sync_trigger.<code>`)."""

    SCHEDULE = "schedule"
    MANUAL = "manual"
    ASSET_CHANGED = "asset_changed"


class SyncRunStatus(StrEnum):
    """Where a run stands (`cmdb_sync_run_status.<code>`)."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SyncOutcome(StrEnum):
    """What a run did with one asset (`cmdb_sync_outcome.<code>`)."""

    CREATED = "created"
    UPDATED = "updated"
    KEPT = "kept"
    UNCHANGED = "unchanged"
    FAILED = "failed"


class SyncValueKind(StrEnum):
    """What a mapped field holds: both sides of a mapping must hold the same kind."""

    TEXT = "text"
    SITE = "site"
    GROUP = "group"


# The CI's own attributes a rule may fill (custom text fields of the target type come apart).
CI_TARGETS: Mapping[str, SyncValueKind] = {
    "name": SyncValueKind.TEXT,
    "description": SyncValueKind.TEXT,
    "site_id": SyncValueKind.SITE,
    "owner_group_id": SyncValueKind.GROUP,
    "managed_by_group_id": SyncValueKind.GROUP,
}
SOURCE = AttributeSource.ASSET_SYNC
# Problem codes (labelled `errors.field.<code>`).
NOT_SYNCABLE = "cmdb_sync_field_not_syncable"
UNKNOWN_TARGET = "cmdb_sync_target_unknown"
KIND_MISMATCH = "cmdb_sync_kind_mismatch"
NAME_REQUIRED = "cmdb_sync_name_required"
MAP_TOO_LONG = "cmdb_sync_field_map_too_long"
ITEM_REFUSED = "cmdb_sync_item_refused"  # a CI save refused for a reason that is not a field
FIELD_PROBLEMS = frozenset(
    {
        "cmdb_sync_field_not_syncable",
        "cmdb_sync_target_unknown",
        "cmdb_sync_kind_mismatch",
        "cmdb_sync_name_required",
        "cmdb_sync_field_map_too_long",
        "cmdb_sync_item_refused",
    }
)


def field_map_problems(
    field_map: Mapping[str, str],
    asset_fields: Mapping[str, SyncValueKind],
    custom_targets: Mapping[str, SyncValueKind],
) -> list[Problem]:
    """Every problem of a field map (CI attribute → asset field)."""
    if not field_map:
        return [Problem("field_map", "required")]
    if len(field_map) > FIELD_MAP_MAX:
        return [Problem("field_map", MAP_TOO_LONG)]
    problems: list[Problem] = []
    if "name" not in field_map:
        problems.append(Problem("field_map", NAME_REQUIRED))
    for target, source in sorted(field_map.items()):
        where = f"field_map.{target}"
        target_kind = (
            custom_targets.get(target[len(CUSTOM) :])
            if target.startswith(CUSTOM)
            else CI_TARGETS.get(target)
        )
        source_kind = asset_fields.get(source)
        if target_kind is None:
            problems.append(Problem(where, UNKNOWN_TARGET))
        elif source_kind is None:
            problems.append(Problem(where, NOT_SYNCABLE))
        elif source_kind is not target_kind:
            problems.append(Problem(where, KIND_MISMATCH))
    return problems


def _clean(value: object) -> object:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return value


def mapped(field_map: Mapping[str, str], asset: Mapping[str, Any]) -> dict[str, Any]:
    """The CI attribute values an asset gives (text trimmed; empty text is no value)."""
    return {target: _clean(asset.get(source)) for target, source in field_map.items()}


@dataclass(frozen=True)
class Plan:
    """What applying an asset's values to its CI would change, and what a stronger source keeps."""

    changes: dict[str, Any]
    kept: tuple[str, ...]

    @property
    def outcome(self) -> SyncOutcome:
        """`updated` when anything changes, else `kept` when something was held back."""
        if self.changes:
            return SyncOutcome.UPDATED
        return SyncOutcome.KEPT if self.kept else SyncOutcome.UNCHANGED


def plan(
    precedence: Precedence,
    current: Mapping[str, Any],
    current_stamps: Mapping[str, Stamp],
    incoming: Mapping[str, Any],
) -> Plan:
    """For each mapped attribute whose value differs: change it if the sync's source wins.

    A value a stronger source set is kept (named in `kept`, never overwritten). The name is
    never emptied: an asset without one leaves the CI's name as it is.
    """
    changes: dict[str, Any] = {}
    kept: list[str] = []
    for attribute, value in sorted(incoming.items()):
        if current.get(attribute) == value or (attribute == "name" and value is None):
            continue
        if wins(precedence, attribute, SOURCE, current_stamps.get(attribute)):
            changes[attribute] = value
        else:
            kept.append(attribute)
    return Plan(changes, tuple(kept))
