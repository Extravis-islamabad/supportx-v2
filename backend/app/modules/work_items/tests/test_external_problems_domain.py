"""The external-problem rules (WP-053 S7a, D-050): versions, finished records, the touched rule."""

import uuid

import pytest

from app.modules.work_items.domain.external_problems import (
    ExternalSource,
    Facts,
    HistoryTouch,
    before_update,
    on_recovery,
    plain,
    touched,
    valid_external_id,
)


def _facts(**changes: object) -> Facts:
    base: dict[str, object] = {"last_version": 3, "deleted": False, "finished": False}
    base.update(changes)
    return Facts(**base)  # type: ignore[arg-type]  # test helper over the dataclass's fields


def test_only_a_strictly_newer_version_goes_on() -> None:
    assert before_update(_facts(), 4) is None
    assert before_update(_facts(), 3) == "stale_version"  # equal: a replay
    assert before_update(_facts(), 2) == "stale_version"


def test_deleted_wins_then_stale_then_finished() -> None:
    assert before_update(_facts(deleted=True, finished=True), 9) == "record_deleted"
    assert before_update(_facts(finished=True), 3) == "stale_version"
    assert before_update(_facts(finished=True), 4) == "closed_noop"  # never reopened


@pytest.mark.parametrize("source", ["rule", "workflow", "sla", "integration", "system", "import",
                                    "asset_sync", "ai_agent"])  # fmt: skip
def test_automation_never_touches_it(source: str) -> None:
    # An auto-assign rule on new incidents must not block auto-resolve (lane B's amendment).
    assert not touched((HistoryTouch(source, by_person=False),))
    assert not touched((HistoryTouch(source, by_person=True),))  # not a person's way in


@pytest.mark.parametrize("source", ["ui", "api", "portal", "email"])
def test_a_persons_change_touches_it_but_a_service_accounts_does_not(source: str) -> None:
    assert touched((HistoryTouch(source, by_person=True),))
    assert not touched((HistoryTouch(source, by_person=False),))  # another integration's account


def test_recovery_resolves_only_untouched_and_only_when_asked() -> None:
    rule = HistoryTouch("rule", by_person=False)
    person = HistoryTouch("ui", by_person=True)
    assert on_recovery(_facts(touches=(rule,)), resolve=True) == "resolved"
    assert on_recovery(_facts(touches=(rule, person)), resolve=True) == "noted"
    assert on_recovery(_facts(), resolve=False) == "noted"


def test_plain_text_and_external_ids() -> None:
    assert plain("Disk\x00full\x1b[31m on\u0085db1") == "Disk full [31m on db1"
    assert valid_external_id("P-123")
    assert not valid_external_id("")
    assert not valid_external_id("x" * 201)
    assert not valid_external_id("bad\nid")


def test_a_source_kind_is_a_closed_list() -> None:
    ExternalSource("monetx", uuid.uuid4())
    with pytest.raises(ValueError, match="unknown external source kind"):
        ExternalSource("nagios", uuid.uuid4())  # type: ignore[arg-type]  # refused on purpose
