"""Attribute sources and who wins (REQ-CMDB-016), and sync rule plans (REQ-CMDB-015). No I/O."""

from datetime import UTC, datetime
from itertools import permutations

import pytest

from app.modules.cmdb.domain import sources, sync
from app.modules.cmdb.domain.sources import DEFAULT_ORDER, AttributeSource, Precedence, Stamp

AT = datetime(2026, 11, 21, 9, 0, tzinfo=UTC)
AUTOMATED = [s for s in AttributeSource if s is not AttributeSource.HAND]


@pytest.mark.parametrize(("incoming", "current"), list(permutations(AttributeSource, 2)))
def test_every_pair_of_sources_follows_the_default_order(
    incoming: AttributeSource, current: AttributeSource
) -> None:
    held = Stamp(current, AT)
    expected = incoming is AttributeSource.HAND or (
        DEFAULT_ORDER.index(incoming) <= DEFAULT_ORDER.index(current)
    )
    assert sources.wins(Precedence(), "name", incoming, held) is expected


@pytest.mark.parametrize("source", list(AttributeSource))
def test_a_source_may_always_rewrite_its_own_value_or_an_unclaimed_one(
    source: AttributeSource,
) -> None:
    assert sources.wins(Precedence(), "name", source, Stamp(source, AT))
    assert sources.wins(Precedence(), "name", source, None)


@pytest.mark.parametrize("source", AUTOMATED)
def test_no_automated_source_overwrites_a_hand_value_by_default(source: AttributeSource) -> None:
    # REQ-CMDB-016 AC2: a MonetX import (or any other) does not overwrite where "hand" wins.
    assert not sources.wins(Precedence(), "name", source, Stamp(AttributeSource.HAND, AT))


def test_an_attribute_order_of_its_own_lets_a_sync_overwrite_hand_there_only() -> None:
    synced_first = (
        AttributeSource.ASSET_SYNC,
        *[s for s in DEFAULT_ORDER if s.value != "asset_sync"],
    )
    precedence = Precedence(overrides={"site_id": synced_first})
    hand = Stamp(AttributeSource.HAND, AT)
    assert sources.wins(precedence, "site_id", AttributeSource.ASSET_SYNC, hand)
    assert not sources.wins(precedence, "name", AttributeSource.ASSET_SYNC, hand)
    # A person's edit still applies where the sync ranks above hand.
    synced = Stamp(AttributeSource.ASSET_SYNC, AT)
    assert sources.wins(precedence, "site_id", AttributeSource.HAND, synced)


def test_the_tenant_order_names_every_source_once_with_hand_first() -> None:
    assert sources.precedence_problems(DEFAULT_ORDER, {}, []) == []
    short = sources.precedence_problems(DEFAULT_ORDER[:-1], {}, [])
    assert [p.code for p in short] == [sources.ORDER_INCOMPLETE]
    doubled = (*DEFAULT_ORDER[:-1], AttributeSource.HAND)
    assert [p.code for p in sources.precedence_problems(doubled, {}, [])] == [
        sources.ORDER_INCOMPLETE
    ]
    hand_last = (*DEFAULT_ORDER[1:], AttributeSource.HAND)
    assert [p.code for p in sources.precedence_problems(hand_last, {}, [])] == [sources.HAND_FIRST]


def test_an_attribute_order_is_for_a_known_attribute_and_complete() -> None:
    hand_last = (*DEFAULT_ORDER[1:], AttributeSource.HAND)
    assert sources.precedence_problems(DEFAULT_ORDER, {"name": hand_last}, ["name"]) == []
    found = sources.precedence_problems(
        DEFAULT_ORDER, {"nope": hand_last, "name": DEFAULT_ORDER[:2]}, ["name"]
    )
    assert {(p.field, p.code) for p in found} == {
        ("overrides.nope", sources.UNKNOWN_ATTRIBUTE),
        ("overrides.name", sources.ORDER_INCOMPLETE),
    }


def test_stored_precedence_round_trips_and_unreadable_falls_back() -> None:
    hand_last = (*DEFAULT_ORDER[1:], AttributeSource.HAND)
    precedence = Precedence(overrides={"custom.rack": hand_last})
    assert sources.precedence_of(sources.precedence_json(precedence)) == precedence
    assert sources.precedence_of(None) == Precedence()
    assert sources.precedence_of({"order": ["hand", "nonsense"]}).order == DEFAULT_ORDER


def test_stamps_round_trip_and_a_withheld_field_never_shows_its_stamp() -> None:
    stored = sources.stamped({}, ["name", "custom.secret"], AttributeSource.ASSET_SYNC, AT)
    assert sources.stamps(stored)["name"] == Stamp(AttributeSource.ASSET_SYNC, AT)
    assert set(sources.shown(stored, ["custom.secret"])) == {"name"}
    assert sources.unstamped(stored, ["name"]) == {"custom.secret": stored["custom.secret"]}
    assert sources.stamps({"name": {"source": "nope", "at": AT.isoformat()}}) == {}


# --- sync rule plans --------------------------------------------------------------------------

ASSET_FIELDS = {"name": sync.SyncValueKind.TEXT, "site_id": sync.SyncValueKind.SITE}


def test_a_field_map_takes_only_syncable_fields_of_the_same_kind() -> None:
    assert sync.field_map_problems({"name": "name"}, ASSET_FIELDS, {}) == []
    found = sync.field_map_problems(
        {
            "description": "purchase_price",  # money is never syncable
            "site_id": "name",  # text into a site
            "nope": "name",
            "custom.rack": "name",  # a custom text field of the target type
        },
        ASSET_FIELDS,
        {"rack": sync.SyncValueKind.TEXT},
    )
    assert {(p.field, p.code) for p in found} == {
        ("field_map", sync.NAME_REQUIRED),
        ("field_map.description", sync.NOT_SYNCABLE),
        ("field_map.site_id", sync.KIND_MISMATCH),
        ("field_map.nope", sync.UNKNOWN_TARGET),
    }
    assert [p.code for p in sync.field_map_problems({}, ASSET_FIELDS, {})] == ["required"]


def test_a_plan_changes_what_the_sync_wins_and_keeps_the_rest() -> None:
    current = {"name": "Old", "site_id": "s1", "description": "typed"}
    stamps = {
        "name": Stamp(AttributeSource.ASSET_SYNC, AT),
        "description": Stamp(AttributeSource.HAND, AT),
    }
    incoming = {"name": "New", "site_id": "s1", "description": "from the asset"}
    found = sync.plan(Precedence(), current, stamps, incoming)
    assert found.changes == {"name": "New"}
    assert found.kept == ("description",)
    assert found.outcome is sync.SyncOutcome.UPDATED
    only_kept = sync.plan(Precedence(), current, stamps, {"description": "x"})
    assert only_kept.outcome is sync.SyncOutcome.KEPT
    same = sync.plan(Precedence(), current, stamps, {"name": "Old"})
    assert same.outcome is sync.SyncOutcome.UNCHANGED


def test_a_plan_never_empties_a_name() -> None:
    found = sync.plan(Precedence(), {"name": "Kept"}, {}, {"name": None})
    assert found.changes == {}


def test_mapped_values_trim_text_and_drop_empty_text() -> None:
    assert sync.mapped(
        {"name": "name", "description": "location"}, {"name": " A ", "location": " "}
    ) == {
        "name": "A",
        "description": None,
    }


def test_a_run_skips_a_custom_target_that_is_no_longer_plain() -> None:
    """Lane C (a): a field made sensitive, personal, sealed or retired since is left alone."""
    field_map = {"name": "name", "custom.rack": "location", "custom.owner": "tag"}
    live, skipped = sync.live_map(field_map, {"rack"})
    assert live == {"name": "name", "custom.rack": "location"}
    assert skipped == ["owner"]
    assert sync.live_map(field_map, {"rack", "owner"}) == (field_map, [])
    # The core targets never depend on the custom ones.
    assert sync.live_map({"name": "name"}, set()) == ({"name": "name"}, [])
