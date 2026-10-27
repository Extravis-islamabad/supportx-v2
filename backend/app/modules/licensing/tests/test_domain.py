"""Licensing domain: catalogue, entitlement state machine, limits, licence parsing. No I/O."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.modules.licensing.domain.catalogue import (
    EDITION_DEFAULT_LIMITS,
    EDITION_FEATURES,
    EDITION_RATE_LIMIT_MULTIPLIER,
    Edition,
    Feature,
    LimitKey,
    unknown_features,
)
from app.modules.licensing.domain.entitlement import (
    Entitlement,
    EntitlementState,
    StateReason,
    Term,
    days_left,
)
from app.modules.licensing.domain.licence import LicenceRejectedError, parse_licence

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)
DAY = timedelta(days=1)


def plan(edition: Edition = Edition.PROFESSIONAL, **term: Any) -> Entitlement:  # noqa: ANN401
    values = {"starts_at": NOW - 30 * DAY, **term}
    return Entitlement.build(edition, term=Term(**values))


# --- catalogue ------------------------------------------------------------------------------------


def test_each_edition_includes_the_one_below() -> None:
    essentials, professional, enterprise = (EDITION_FEATURES[e] for e in Edition)
    assert essentials < professional < enterprise
    assert enterprise == frozenset(Feature)  # every catalogue feature is sold somewhere


def test_every_edition_has_every_limit_and_a_rate_multiplier() -> None:
    for edition in Edition:
        assert set(EDITION_DEFAULT_LIMITS[edition]) == set(LimitKey)
        assert EDITION_RATE_LIMIT_MULTIPLIER[edition] >= 1


def test_itil_practices_from_professional_and_esm_msp_only_in_enterprise() -> None:
    # product-plan.md §9 / §9.1
    itil = {Feature.PROBLEM, Feature.CHANGE, Feature.RELEASE, Feature.CATALOG, Feature.CMDB}
    assert itil <= EDITION_FEATURES[Edition.PROFESSIONAL]
    assert not itil & EDITION_FEATURES[Edition.ESSENTIALS]
    assert Feature.ESM not in EDITION_FEATURES[Edition.PROFESSIONAL]
    assert Feature.MSP in EDITION_FEATURES[Edition.ENTERPRISE]


def test_unknown_features() -> None:
    assert unknown_features({"change", "teleport"}) == {"teleport"}


# --- features and limits --------------------------------------------------------------------------


def test_add_ons_and_overrides_on_top_of_the_edition() -> None:
    entitlement = Entitlement.build(
        Edition.ESSENTIALS,
        term=Term(starts_at=NOW),
        extra_features=frozenset({Feature.CMDB}),
        limit_overrides={LimitKey.TECHNICIANS: 3, LimitKey.ASSETS: None},
    )
    assert entitlement.has_feature("cmdb")
    assert entitlement.has_feature(Feature.INCIDENT)
    assert not entitlement.has_feature("change")
    assert entitlement.limit(LimitKey.TECHNICIANS) == 3
    assert entitlement.limit(LimitKey.ASSETS) is None  # unlimited
    assert entitlement.limit(LimitKey.DESKS) == 1  # edition default


@pytest.mark.parametrize(
    ("limit", "used", "adding", "allowed", "remaining"),
    [
        (5, 4, 1, True, 1),
        (5, 5, 1, False, 0),
        (5, 7, 1, False, 0),  # over after a downgrade: never negative
        (5, 3, 3, False, 2),
        (None, 10_000, 1, True, None),
        (0, 0, 1, False, 0),
    ],
)
def test_limit_check(
    limit: int | None, used: int, adding: int, allowed: bool, remaining: int | None
) -> None:
    entitlement = Entitlement.build(
        Edition.ENTERPRISE, term=Term(starts_at=NOW), limit_overrides={LimitKey.ASSETS: limit}
    )
    check = entitlement.check(LimitKey.ASSETS, used=used, adding=adding)
    assert (check.allowed, check.remaining) == (allowed, remaining)


def test_no_entitlement_has_nothing() -> None:
    none = Entitlement.none()
    assert none.features == frozenset()
    assert all(none.limit(key) == 0 for key in LimitKey)
    assert none.status(NOW).state is EntitlementState.INVALID
    assert none.status(NOW).reason is StateReason.NO_ENTITLEMENT
    assert not none.upgrade_allowed(NOW)


# --- state machine (§13.6) ------------------------------------------------------------------------


def test_active_inside_the_term_and_open_ended() -> None:
    assert plan(expires_at=NOW + DAY).status(NOW).state is EntitlementState.ACTIVE
    assert plan().status(NOW).state is EntitlementState.ACTIVE


def test_grace_after_expiry_then_read_only() -> None:
    entitlement = plan(expires_at=NOW, grace_days=14)
    in_grace = entitlement.status(NOW + 13 * DAY)
    assert (in_grace.state, in_grace.reason) == (EntitlementState.GRACE, StateReason.EXPIRED)
    assert in_grace.grace_ends_at == NOW + 14 * DAY
    assert in_grace.allows_writes
    assert days_left(in_grace, NOW + 13 * DAY) == 1
    after = entitlement.status(NOW + 14 * DAY)
    assert (after.state, after.reason) == (EntitlementState.READ_ONLY, StateReason.EXPIRED)
    assert not after.allows_writes
    assert days_left(after, NOW + 14 * DAY) is None


def test_zero_grace_days_goes_straight_to_read_only() -> None:
    assert plan(expires_at=NOW, grace_days=0).status(NOW).state is EntitlementState.READ_ONLY


def test_suspended_is_read_only_and_not_yet_valid_is_invalid() -> None:
    suspended = Entitlement.build(Edition.ENTERPRISE, term=Term(starts_at=NOW), suspended=True)
    assert suspended.status(NOW).state is EntitlementState.READ_ONLY
    assert suspended.status(NOW).reason is StateReason.SUSPENDED
    early = plan(starts_at=NOW + DAY).status(NOW)
    assert (early.state, early.reason) == (EntitlementState.INVALID, StateReason.NOT_YET_VALID)


def test_failing_licence_check_starts_the_grace_period_before_expiry() -> None:
    """WP-013 sets degraded_since on a fingerprint mismatch: grace, then read-only (§13.6)."""
    entitlement = Entitlement.build(
        Edition.ENTERPRISE,
        term=Term(starts_at=NOW - 90 * DAY, expires_at=NOW + 300 * DAY),
        degraded_since=NOW - 2 * DAY,
    )
    status = entitlement.status(NOW)
    assert (status.state, status.reason) == (EntitlementState.GRACE, StateReason.LICENCE_MISMATCH)
    assert entitlement.status(NOW + 12 * DAY).state is EntitlementState.READ_ONLY


def test_maintenance_window_controls_upgrades() -> None:
    entitlement = plan(maintenance_until=NOW)
    assert entitlement.upgrade_allowed(NOW - DAY)
    assert not entitlement.upgrade_allowed(NOW + DAY)
    assert plan().upgrade_allowed(NOW + 999 * DAY)


def test_serialisation_round_trip() -> None:
    entitlement = Entitlement.build(
        Edition.PROFESSIONAL,
        term=Term(starts_at=NOW, expires_at=NOW + DAY, maintenance_until=NOW, grace_days=3),
        extra_features=frozenset({Feature.ESM}),
        limit_overrides={LimitKey.TECHNICIANS: 2, LimitKey.ASSETS: None},
        suspended=True,
        degraded_since=NOW,
    )
    restored = Entitlement.from_dict(json.loads(json.dumps(entitlement.to_dict())))
    assert restored == entitlement
    assert Entitlement.from_dict(Entitlement.none().to_dict()) == Entitlement.none()


# --- licence document (§13.3) ---------------------------------------------------------------------

SPEC_EXAMPLE: dict[str, Any] = {
    "licence_id": "LIC-2027-00418",
    "customer": "Example Bank PJSC",
    "installation_id": "0b9c-e21",
    "fingerprint": {"algo": "v1", "components": {"cpu": "h:52"}, "min_match": 3},
    "edition": "enterprise",
    "features": ["problem", "change", "cmdb", "assets", "ai_agents", "discovery"],
    "limits": {"technicians": 250, "assets": 5000, "desks": 10},
    "issued_at": "2027-01-10",
    "expires_at": "2028-01-09",
    "maintenance_until": "2028-01-09",
    "grace_days": 14,
    "signature": "ed25519:MEUCIQ",
}


def raw(**changes: Any) -> bytes:  # noqa: ANN401
    return json.dumps({**SPEC_EXAMPLE, **changes}).encode()


def test_parses_the_spec_example() -> None:
    document = parse_licence(raw())
    entitlement = document.entitlement
    assert document.licence_id == "LIC-2027-00418"
    assert document.signature == "ed25519:MEUCIQ"
    assert entitlement.edition is Edition.ENTERPRISE
    assert entitlement.limit(LimitKey.DESKS) == 10
    assert entitlement.term is not None
    # Valid from the start of the issue day through the END of the expiry day (UTC).
    assert entitlement.term.starts_at == datetime(2027, 1, 10, tzinfo=UTC)
    assert entitlement.term.expires_at == datetime(2028, 1, 10, tzinfo=UTC)
    last_minute = datetime(2028, 1, 9, 23, 59, tzinfo=UTC)
    assert entitlement.status(last_minute).state is EntitlementState.ACTIVE


def test_signed_payload_covers_every_field_but_the_signature() -> None:
    base = parse_licence(raw()).signed_payload
    assert parse_licence(raw(signature="ed25519:OTHER")).signed_payload == base
    for field, value in [("limits", {"technicians": 251}), ("expires_at", "2029-01-09")]:
        assert parse_licence(raw(**{field: value})).signed_payload != base
    assert b"signature" not in base


def test_unsigned_licence_parses_with_no_signature() -> None:
    assert parse_licence(raw(signature=None)).signature is None
    assert parse_licence(raw(signature="")).signature is None


@pytest.mark.parametrize(
    "content",
    [
        b"not json",
        b"[]",
        raw(edition="platinum"),
        raw(features=["teleport"]),
        raw(limits={"technicians": -1}),
        raw(limits={"robots": 3}),
        raw(grace_days=365),
        raw(issued_at="yesterday"),
        raw(customer=""),
        raw(signature=42),
        b"{" + b" " * 70_000 + b"}",
    ],
)
def test_malformed_licences_are_rejected(content: bytes) -> None:
    with pytest.raises(LicenceRejectedError) as caught:
        parse_licence(content)
    assert caught.value.reason == "licence_malformed"
