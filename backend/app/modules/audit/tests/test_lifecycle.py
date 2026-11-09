"""A save's lifecycle events (WP-064, ADR-045): the pure table, without I/O."""

import uuid
from datetime import UTC, datetime

from app.modules.audit.domain.catalogue import ACTIONS
from app.modules.audit.domain.integrity import entry_hash
from app.modules.audit.domain.lifecycle import (
    ASSET,
    FieldDiff,
    RecordAudit,
    ValueRule,
    events_of,
    lifecycle_codes,
)


def test_a_created_record_is_created_only() -> None:
    first = [FieldDiff("name", None, "Laptop"), FieldDiff("state_id", None, "s1")]
    assert events_of(ASSET, "created", first) == ("asset.created",)


def test_a_save_lists_every_event_it_stands_for_once() -> None:
    changed = [
        FieldDiff("state_id", "s1", "s2"),
        FieldDiff("site_id", "a", "b"),
        FieldDiff("location", "x", "y"),
    ]
    assert events_of(ASSET, "updated", changed) == ("asset.moved", "asset.relocated")


def test_a_plain_edit_is_updated() -> None:
    assert events_of(ASSET, "updated", [FieldDiff("name", "a", "b")]) == ("asset.updated",)


def test_the_trash_flag_names_delete_and_restore() -> None:
    assert events_of(ASSET, "deleted", [FieldDiff("deleted", old=False, new=True)]) == (
        "asset.deleted",
    )
    assert events_of(ASSET, "updated", [FieldDiff("deleted", old=True, new=False)]) == (
        "asset.restored",
    )


def test_the_route_code_leads_and_is_not_repeated() -> None:
    moved = [FieldDiff("state_id", "s1", "s2")]
    assert events_of(ASSET, "updated", moved, "asset.moved") == ("asset.moved",)
    assert events_of(ASSET, "updated", moved, "asset.disposed") == (
        "asset.disposed",
        "asset.moved",
    )
    restored = [FieldDiff("deleted", old=True, new=False)]
    assert events_of(ASSET, "updated", restored, "asset.restored") == ("asset.restored",)


def test_every_lifecycle_code_is_in_the_catalogue() -> None:
    # The catalogue's labels test then covers en/ar/ur for each of them.
    assert lifecycle_codes() <= set(ACTIONS)


def _row(events: list[str] | None) -> dict[str, object]:
    return {
        "id": uuid.UUID(int=1),
        "tenant_id": uuid.UUID(int=2),
        "occurred_at": datetime(2026, 11, 10, tzinfo=UTC),
        "action": "asset.updated",
        "category": "records",
        "module": "assets",
        "outcome": "done",
        "actor_type": "system",
        "client": "worker",
        "events": events,
    }


def test_events_are_hashed_and_older_entries_hash_as_before() -> None:
    without = _row(None)
    legacy = {k: v for k, v in without.items() if k != "events"}
    assert entry_hash(without) == entry_hash(legacy)  # NULL events: the pre-ADR-045 bytes
    listed = entry_hash(_row(["asset.updated"]))
    assert listed != entry_hash(without)
    assert listed != entry_hash(_row(["asset.updated", "asset.moved"]))  # an edit is caught


_TICKET = RecordAudit(
    record_type="ticket",
    module="test",
    kinds=frozenset({"created", "deleted", "restored", "status", "child_added", "child_removed"}),
    fields={"status": "status_changed", "group_id": "assigned"},
    values=(
        ValueRule("status", "resolved", new_in=frozenset({"resolved"})),
        ValueRule(
            "status",
            "reopened",
            old_in=frozenset({"resolved", "closed"}),
            new_not_in=frozenset({"resolved", "closed"}),
        ),
    ),
    parts={("child_added", "link"): "linked"},
)


def test_value_rules_name_what_a_status_change_was() -> None:
    resolved = [FieldDiff("status", "open", "resolved"), FieldDiff("group_id", "a", "b")]
    assert events_of(_TICKET, "status", resolved) == (
        "ticket.status_changed",
        "ticket.assigned",
        "ticket.resolved",
    )
    reopened = [FieldDiff("status", "closed", "in_progress")]
    assert events_of(_TICKET, "status", reopened) == ("ticket.status_changed", "ticket.reopened")
    moved_on = [FieldDiff("status", "resolved", "closed")]  # closing a resolved one is no reopen
    assert events_of(_TICKET, "status", moved_on) == ("ticket.status_changed",)


def test_a_named_part_replaces_the_generic_part_event() -> None:
    assert events_of(_TICKET, "child_added", [FieldDiff("link", None, "x")]) == ("ticket.linked",)
    assert events_of(_TICKET, "child_added", [FieldDiff("task", None, "x")]) == (
        "ticket.part_added",
    )
    assert "ticket.linked" in _TICKET.events()
    assert "ticket.reopened" in _TICKET.events()
