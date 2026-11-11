"""A save's lifecycle events (WP-064, ADR-045): the pure table, without I/O."""

import uuid
from datetime import UTC, datetime

from app.modules.audit.domain.catalogue import ACTIONS
from app.modules.audit.domain.integrity import entry_hash
from app.modules.audit.domain.lifecycle import (
    ASSET,
    RECORD_TYPES,
    FieldDiff,
    RecordAudit,
    ValueRule,
    events_of,
    events_of_saves,
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


def test_an_asset_held_given_back_lent_and_linked_names_its_own_codes() -> None:
    """WP-049a s4/s5 (#307): holder, loan and link saves use the codes their routes write."""
    for holder in ("owner_user_id", "department_id", "parent_asset_id"):
        given = [FieldDiff(holder, None, "u1")]
        assert events_of(ASSET, "updated", given) == ("asset.assigned",), holder
        back = [FieldDiff(holder, "u1", None)]
        assert events_of(ASSET, "updated", back) == ("asset.unassigned",), holder
    handed = [FieldDiff("owner_user_id", "u1", None), FieldDiff("department_id", None, "d1")]
    assert set(events_of(ASSET, "updated", handed)) == {"asset.assigned", "asset.unassigned"}
    lent = [FieldDiff("loanable", old=False, new=True)]
    assert events_of(ASSET, "updated", lent) == ("asset.loanable_set",)
    assert events_of(ASSET, "updated", [FieldDiff("relationship", None, "runs on SRV-1")]) == (
        "asset.linked",
    )
    assert events_of(ASSET, "updated", [FieldDiff("relationship", "runs on SRV-1", None)]) == (
        "asset.unlinked",
    )
    assert {"asset.assigned", "asset.unassigned", "asset.linked", "asset.loanable_set"} <= set(
        ASSET.events()
    )


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


def test_each_save_keeps_its_own_source_when_one_request_holds_several() -> None:
    """Lane A: a person's priority change and the SLA engine's due rewrite in one request."""
    incident = RECORD_TYPES["incident"]
    person = ("updated", [FieldDiff("priority", "low", "high")], "ui")
    engine = ("updated", [FieldDiff("resolution_due_at", "a", "b")], "sla")
    for saves in ([person, engine], [engine, person]):
        assert events_of_saves(incident, saves) == ("incident.priority_changed",)
    own_edit = ("updated", [FieldDiff("resolution_due_at", "a", "c")], "ui")
    assert events_of_saves(incident, [engine, own_edit], "incident.due_date_changed") == (
        "incident.due_date_changed",
    )


def test_release_stages_plans_and_people_name_their_events() -> None:
    release = RECORD_TYPES["release"]
    changes = [
        FieldDiff("schedule.build.scheduled_end", "a", "b"),
        FieldDiff("schedule.deploy.outcome", None, "successful"),
        FieldDiff("plan.backout", "x", "y"),
        FieldDiff("release_engineer_id", None, "u1"),
        FieldDiff("risk", "low", "high"),
    ]
    assert set(events_of(release, "updated", changes)) == {
        "release.assigned",
        "release.access_changed",
        "release.rescheduled",
        "release.stage_outcome_recorded",
        "release.plan_changed",
        "release.risk_changed",
    }
    assert "release.sla_paused" not in release.events()
    assert "release.emergency_override" not in release.events()
