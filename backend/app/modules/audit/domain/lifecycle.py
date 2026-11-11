"""Which lifecycle events one save of a record represents (WP-064, D-150, ADR-045).

Every save of a registered record type writes ONE audit entry listing all the events it stands
for (Haider: a save that does several things is one entry naming all of them). This table turns a
save (its kind and the fields it changed) into those event codes. Pure: no I/O.

The before and after values are not stored here: they stay in record history
(`field_changes`). The field names, and for some events the values (a status category, an SLA
state), decide the events. The owning module adds facts history does not store (a status
code's category, `status_category`) to the copy the sink sees (app/shared/history annotators).
"""

import fnmatch
from collections.abc import Iterable, Mapping, Sequence
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
    # name ending in "." stands for every field it starts (`role.` for role.line_manager ...);
    # one with "*" is a pattern (`schedule.*.outcome` for a stage's outcome).
    fields: Mapping[str, str | tuple[str, ...]] = field(default_factory=dict)
    # A boolean field whose change is a move to the trash (False -> True) or a restore.
    trash_field: str | None = None
    # Events that depend on the values (after the field events, in this order).
    values: tuple[ValueRule, ...] = ()
    # A part's kind of save and its field -> a named event instead of part_added/... .
    parts: Mapping[tuple[str, str], str] = field(default_factory=dict)
    # The record type its saves are written to history with, when not `record_type` (every
    # work item is `work_item` there). The verifier reads `field_changes` by it (WP-064 S2).
    history_type: str | None = None
    # Fields holding personal data (free text), named like `fields` (`plan.`, `schedule.*.x`).
    # Their values are fingerprinted with the salts of the record's data subjects, so erasing
    # a subject crypto-shreds them in the chain (ADR-046). IDs are never personal (ADR-027).
    personal: tuple[str, ...] = ()
    # Whose personal data those fields are: the record's fields naming people (the subject
    # resolver of app/shared/history reads them from the record when it is saved).
    data_subjects: tuple[str, ...] = ()

    @property
    def history_record_type(self) -> str:
        """The record type of this type's rows in `field_changes`."""
        return self.history_type or self.record_type

    @property
    def reasons_personal(self) -> bool:
        """Whether a save's free-text reasons are its data subjects' personal data.

        Yes for a type with data subjects (work items: a pause or priority reason is about the
        ticket's people); otherwise they stay in the ordinary, unsalted half (assets).
        """
        return bool(self.data_subjects)

    def is_personal(self, name: str) -> bool:
        """Whether a changed field's values are personal data (see `personal`)."""
        return _field_matches_one(name, self.personal)

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
    if "*" in key:  # schedule.*.outcome: a stage's field
        return any(fnmatch.fnmatchcase(n, key) for n in names)
    return any(n.startswith(key) for n in names) if key.endswith(".") else key in names


def _field_matches_one(name: str, keys: Iterable[str]) -> bool:
    return any(_field_matches(key, {name}) for key in keys)


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
        "loanable": "loanable_set",  # WP-049a s5, the code its route writes
    },
    trash_field="deleted",
    # WP-049a s4/s5 (#307), by the codes their routes write: who holds it (a person, a
    # department or a parent asset), and its relationships (the target as the new value when
    # added, as the old one when removed).
    values=(
        *(
            rule
            for holder in ("owner_user_id", "department_id", "parent_asset_id")
            for rule in (
                ValueRule(holder, "assigned", new_not_in=frozenset({None})),
                ValueRule(holder, "unassigned", new_in=frozenset({None})),
            )
        ),
        ValueRule("relationship", "linked", new_not_in=frozenset({None})),
        ValueRule("relationship", "unlinked", new_in=frozenset({None})),
    ),
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
# Both staged types (changes and releases): stages, their schedules and outcomes, plans,
# downtime, role holders (lane A's and lane C's reviews).
_STAGED_FIELDS: Mapping[str, str | tuple[str, ...]] = {
    **_WORK_FIELDS,
    "stage": "stage_changed",
    "stage_path": "stage_changed",
    "reapproval_restarted": "sent_back_for_approval",
    "role.": _ACCESS,  # stage role holders: they may work on the record
    "schedule.*.scheduled_start": "rescheduled",
    "schedule.*.scheduled_end": "rescheduled",
    "schedule.*.outcome": "stage_outcome_recorded",
    "schedule.*.outcome_notes": "stage_outcome_recorded",
    "schedule.*.issues": "stage_outcome_recorded",
    "plan.": "plan_changed",  # a changed back-out plan is what auditors look for
    "downtime.": "downtime_changed",
}
_CHANGE_FIELDS: Mapping[str, str | tuple[str, ...]] = {
    **_STAGED_FIELDS,
    "emergency_override": "emergency_override",
    "pir_required": "pir_required",
    "standard_converted": "standard_converted",
    "risk": "risk_changed",
    "risk_chosen": "risk_changed",
}
_RELEASE_FIELDS: Mapping[str, str | tuple[str, ...]] = {
    **_STAGED_FIELDS,
    "release_manager_id": ("assigned", _ACCESS),
    "release_engineer_id": ("assigned", _ACCESS),
    "risk": "risk_changed",  # a release's own risk (REQ-REL-004 AC3); risk_chosen is change-only
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


_SLA_EVENTS = frozenset({"sla_paused", "sla_resumed", "sla_breached"})

# --- personal data (WP-064 S2, D-150 "Erasure", ADR-046) -----------------------------------------
#
# THE LISTS FOR REVIEW (lanes A and C). The free-text fields each type's history records: their
# values are personal data of the record's data subjects, fingerprinted with those people's
# salts. Names follow `fields` (a trailing "." is a prefix, "*" a pattern). IDs never appear:
# people are referred to by ID (ADR-027), and IDs are not personal.
#
# Work items, all five types: the text people write about themselves and their problem.
# - every type: subject, description, impact_details, resolution, tags, custom field values
#   (`custom.<key>`, any of them may be text), a task's title (`task`, `task.title`);
# - problems: the analysis (root cause, symptoms, workaround, review texts);
# - changes and releases: plan sections, a stage's outcome notes and issues, a downtime's
#   description; changes also the risk reason; releases also the release notes, version and
#   build reference (lane C).
# Every save's free-text reason (`field_changes.reason`: status moves, the priority reason,
# stage moves, set_fields, known-error comments, the SLA's by-hand reason) is personal too, for
# every type with data subjects (`RecordAudit.reasons_personal`, lane A's and C's reviews).
# Assets: none (a name, a location code and IDs; people hold assets by ID).
# People (identity) are not a lifecycle type yet: their name, email and phone fields join when
# they are (a later session), with the person themself as the data subject.
_WORK_PERSONAL: tuple[str, ...] = (
    "subject",
    "description",
    "impact_details",
    "resolution",
    "tags",
    "custom.",
    "task",
    "task.title",
)
_PROBLEM_PERSONAL: tuple[str, ...] = (
    *_WORK_PERSONAL,
    "root_cause",
    "symptoms",
    "workaround",
    "review_summary",
    "review_lessons",
    "review_actions",
)
_STAGED_PERSONAL: tuple[str, ...] = (
    *_WORK_PERSONAL,
    "plan.",
    "schedule.*.outcome_notes",
    "schedule.*.issues",
    "downtime.*.description",
)
_CHANGE_PERSONAL: tuple[str, ...] = (*_STAGED_PERSONAL, "risk_reason")
_RELEASE_PERSONAL: tuple[str, ...] = (
    *_STAGED_PERSONAL,
    "release_notes",
    "release_version",
    "build_ref",
)
# Whose: the requester and the person it was raised for (both, when both are set).
_WORK_SUBJECTS: tuple[str, ...] = ("requester_id", "on_behalf_of_id")
WORK_ITEM_HISTORY_TYPE = "work_item"


def _work_item(
    code: str,
    fields: Mapping[str, str | tuple[str, ...]],
    personal: tuple[str, ...],
    *,
    merges: bool,
    sla: bool,
) -> RecordAudit:
    return RecordAudit(
        record_type=code,
        module="work_items",
        kinds=_WORK_KINDS,
        fields=fields,
        # Only incidents, requests and problems merge; releases have no SLA (lane C).
        values=tuple(
            r
            for r in _WORK_VALUES
            if (merges or r.event != "merged") and (sla or r.event not in _SLA_EVENTS)
        ),
        parts=_WORK_PARTS,
        history_type=WORK_ITEM_HISTORY_TYPE,
        personal=personal,
        data_subjects=_WORK_SUBJECTS,
    )


WORK_ITEMS = (
    _work_item("incident", _WORK_FIELDS, _WORK_PERSONAL, merges=True, sla=True),
    _work_item("service_request", _WORK_FIELDS, _WORK_PERSONAL, merges=True, sla=True),
    _work_item("problem", _WORK_FIELDS, _PROBLEM_PERSONAL, merges=True, sla=True),
    _work_item("change", _CHANGE_FIELDS, _CHANGE_PERSONAL, merges=False, sla=True),
    _work_item("release", _RELEASE_FIELDS, _RELEASE_PERSONAL, merges=False, sla=False),
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


def events_of_saves(
    spec: RecordAudit,
    saves: Sequence[tuple[str, Sequence[FieldDiff], str | None]],
    route_action: str | None = None,
) -> tuple[str, ...]:
    """One record's several saves in one request (kind, changes, source each) as one list.

    Each save's events are worked out with its own kind and source (an SLA engine's save in
    the same request never counts as a person's due-date edit: lane A), then joined in order.
    `<type>.updated` stays only when no save named anything more.
    """
    codes: list[str] = []
    for kind, changes, source in saves:
        codes.extend(events_of(spec, kind, changes, None, source))
    updated = f"{spec.record_type}.{UPDATED}"
    named = [c for c in dict.fromkeys(codes) if c != updated]
    found = named or [updated]
    if route_action is not None:
        found.insert(0, route_action)
    return tuple(dict.fromkeys(found))


def lifecycle_codes() -> frozenset[str]:
    """Every code the table can produce (each is in the audit catalogue, with labels)."""
    return frozenset().union(*(spec.events() for spec in RECORD_TYPES.values()))
