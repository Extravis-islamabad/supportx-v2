"""Which lifecycle events one save of a record represents (WP-064, D-150, ADR-045).

Every save of a registered record type writes ONE audit entry listing all the events it stands
for (Haider: a save that does several things is one entry naming all of them). This table turns a
save (its kind and the fields it changed) into those event codes. Pure: no I/O.

The before and after values are not stored here: they stay in record history
(`field_changes`). The field names, and for some events the values (a status category, an SLA
state), decide the events. The owning module adds facts history does not store (a status
code's category, `status_category`) to the copy the sink sees (app/shared/history annotators).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

# A kind of save (app/shared/history ChangeKind) -> its event, where the kind alone names one.
_KIND_EVENTS: Mapping[str, str] = {
    "created": "created",
    "deleted": "deleted",
    "restored": "restored",
    "status": "status_changed",
    "child_added": "part_added",
    "child_changed": "part_changed",
    "child_removed": "part_removed",
}
UPDATED = "updated"  # a save that matches no other event


@dataclass(frozen=True)
class ValueRule:
    """An event a field's change stands for only with certain values (a status going to resolved).

    Each given condition must hold: the new value is in `new_in` (or not in `new_not_in`), the
    old one in `old_in`. Values are compared as given (codes).
    """

    field: str
    event: str
    new_in: frozenset[object] | None = None
    new_not_in: frozenset[object] | None = None
    old_in: frozenset[object] | None = None
    # The save's source must not be one of these (the SLA engine's own saves, for due dates).
    not_from: frozenset[str] = frozenset()

    def matches(self, change: "FieldDiff", source: str | None = None) -> bool:
        """Whether this change of the field stands for the event."""
        if change.name != self.field or (source is not None and source in self.not_from):
            return False
        if self.new_in is not None and change.new not in self.new_in:
            return False
        if self.new_not_in is not None and change.new in self.new_not_in:
            return False
        return self.old_in is None or change.old in self.old_in


@dataclass(frozen=True)
class RecordAudit:
    """One record type's lifecycle events."""

    record_type: str
    module: str
    # The kinds of save this type has (a subset of _KIND_EVENTS; "updated" is always possible).
    kinds: frozenset[str]
    # Field name -> its event or events. Order matters: earlier ones come first in the list. A
    # name ending in "." stands for every field it starts (`role.` for role.line_manager ...).
    fields: Mapping[str, str | tuple[str, ...]] = field(default_factory=dict)
    # A boolean field whose change is a move to the trash (False -> True) or a restore.
    trash_field: str | None = None
    # Events that depend on the values (after the field events, in this order).
    values: tuple[ValueRule, ...] = ()
    # A part's kind of save and its field -> a named event instead of part_added/... .
    parts: Mapping[tuple[str, str], str] = field(default_factory=dict)

    def events(self) -> frozenset[str]:
        """Every event code this type can produce."""
        names = {_KIND_EVENTS[k] for k in self.kinds} | {UPDATED}
        names |= {event for value in self.fields.values() for event in _as_tuple(value)}
        names |= {rule.event for rule in self.values} | set(self.parts.values())
        if self.trash_field is not None:
            names |= {"deleted", "restored"}
        return frozenset(f"{self.record_type}.{name}" for name in names)


def _as_tuple(value: str | tuple[str, ...]) -> tuple[str, ...]:
    return (value,) if isinstance(value, str) else value


def _field_matches(key: str, names: set[str]) -> bool:
    return any(n.startswith(key) for n in names) if key.endswith(".") else key in names


@dataclass(frozen=True)
class FieldDiff:
    """One changed field of a save: its name, old and new value."""

    name: str
    old: object
    new: object


ASSET = RecordAudit(
    record_type="asset",
    module="assets",
    kinds=frozenset({"created", "deleted"}),
    fields={
        "state_id": "moved",  # moved to another state: the code the move route already writes
        "site_id": "relocated",
        "location": "relocated",
        "product_id": "product_changed",
    },
    trash_field="deleted",
)

# --- work items (lane A's review, 2026-11-10) ----------------------------------------------------
#
# Statuses by category, never by code: the staged types' codes carry their stage
# (closure_closed ...). work_items adds `status_category` old -> new to the sink's copy.
_DONE = frozenset({"resolved", "closed"})
_ACTIVE = frozenset({"open", "paused"})
_SLA_STATES = ("first_response_sla_state", "resolution_sla_state")
_BREACHES = ("first_response_breached", "resolution_breached")
_DUE = ("first_response_due_at", "resolution_due_at")
_ACCESS = "access_changed"  # D-150's permission-relevant fields: who may see or work on it

_WORK_FIELDS: Mapping[str, str | tuple[str, ...]] = {
    "status": "status_changed",
    "group_id": ("assigned", _ACCESS),
    "technician_id": ("assigned", _ACCESS),
    "priority": "priority_changed",
    "impact": "priority_changed",
    "urgency": "priority_changed",
    "approval_status": "approval_decided",
    "note_visibility": ("note_visibility_changed", _ACCESS),
    "requester_id": _ACCESS,
    "on_behalf_of_id": _ACCESS,
    "site_id": _ACCESS,
    "department_id": _ACCESS,
    "follower": _ACCESS,
    "follower_access": _ACCESS,
}
_STAGED_FIELDS: Mapping[str, str | tuple[str, ...]] = {
    **_WORK_FIELDS,
    "stage": "stage_changed",
    "stage_path": "stage_changed",
    "reapproval_restarted": "sent_back_for_approval",
    "emergency_override": "emergency_override",
    "pir_required": "pir_required",
    "standard_converted": "standard_converted",
    "risk": "risk_changed",
    "risk_chosen": "risk_changed",
    "role.": _ACCESS,  # stage role holders: they may work on the record
}
_WORK_VALUES: tuple[ValueRule, ...] = (
    ValueRule("status_category", "resolved", new_in=frozenset({"resolved"})),
    ValueRule("status_category", "closed", new_in=frozenset({"closed"})),
    ValueRule("status_category", "canceled", new_in=frozenset({"canceled"})),
    ValueRule("status_category", "reopened", old_in=_DONE, new_in=_ACTIVE),
    ValueRule("status", "merged", new_in=frozenset({"merged"})),  # a fixed system code
    *(ValueRule(f, "sla_paused", new_in=frozenset({"paused"})) for f in _SLA_STATES),
    *(
        ValueRule(f, "sla_resumed", old_in=frozenset({"paused"}), new_not_in=frozenset({"paused"}))
        for f in _SLA_STATES
    ),
    *(ValueRule(f, "sla_breached", new_in=frozenset({True})) for f in _BREACHES),
    *(ValueRule(f, "due_date_changed", not_from=frozenset({"sla"})) for f in _DUE),
)
_WORK_KINDS = frozenset(
    {"created", "deleted", "restored", "status", "child_added", "child_changed", "child_removed"}
)
_WORK_PARTS: Mapping[tuple[str, str], str] = {
    ("child_added", "link"): "linked",
    ("child_removed", "link"): "unlinked",
}


def _work_item(code: str, *, staged: bool) -> RecordAudit:
    return RecordAudit(
        record_type=code,
        module="work_items",
        kinds=_WORK_KINDS,
        fields=_STAGED_FIELDS if staged else _WORK_FIELDS,
        # Staged types never merge (only incidents, requests and problems have `merged`).
        values=tuple(r for r in _WORK_VALUES if not (staged and r.event == "merged")),
        parts=_WORK_PARTS,
    )


WORK_ITEMS = (
    _work_item("incident", staged=False),
    _work_item("service_request", staged=False),
    _work_item("problem", staged=False),
    _work_item("change", staged=True),
    _work_item("release", staged=True),
)

RECORD_TYPES: Mapping[str, RecordAudit] = {r.record_type: r for r in (ASSET, *WORK_ITEMS)}


def events_of(
    spec: RecordAudit,
    kind: str,
    changed: Iterable[FieldDiff],
    route_action: str | None = None,
    source: str | None = None,
) -> tuple[str, ...]:
    """The save's event codes, most significant first, without repeats.

    `route_action` is the code of the route that made the save (its `audited(...)` action). It
    comes first and becomes the entry's action, so everything that found the route's own entry
    before (filters, saved searches, exports, the SIEM stream) finds this one.
    """
    changes = list(changed)
    names = {c.name for c in changes}
    trash = next((c for c in changes if c.name == spec.trash_field), None)
    found: list[str] = []
    part = next((spec.parts[(kind, c.name)] for c in changes if (kind, c.name) in spec.parts), None)
    if trash is not None and bool(trash.new) != bool(trash.old):
        found.append("deleted" if trash.new else "restored")
    elif part is not None:
        found.append(part)
    elif kind in spec.kinds:
        found.append(_KIND_EVENTS[kind])
    if kind != "created":  # a new record's first values are not changes of state or place
        for key, events in spec.fields.items():
            if _field_matches(key, names):
                found.extend(_as_tuple(events))
        found.extend(r.event for r in spec.values if any(r.matches(c, source) for c in changes))
    if not found:
        found.append(UPDATED)
    codes = [f"{spec.record_type}.{name}" for name in found]
    if route_action is not None:
        codes.insert(0, route_action)
    return tuple(dict.fromkeys(codes))


def lifecycle_codes() -> frozenset[str]:
    """Every code the table can produce (each is in the audit catalogue, with labels)."""
    return frozenset().union(*(spec.events() for spec in RECORD_TYPES.values()))
