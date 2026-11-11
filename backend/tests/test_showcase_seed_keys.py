"""The seed's one definition of its own incidents (QA 2026-11-09, INC-62): no DB needed."""

from decimal import Decimal

from app.modules.assets.domain.catalogue import SEED_TYPES, AssetTypeKind
from tooling import showcase_assets as assets
from tooling import showcase_seed as seed


def _people() -> dict[str, str]:
    return {p.email: f"id-{p.email}" for p in seed.PEOPLE}


def test_every_defined_incident_is_the_seeds_and_a_hand_made_one_is_not() -> None:
    people = _people()
    defined = seed.defined_incidents(people)
    requesters = {people[p.email] for p in seed.PEOPLE if p.user_type == "requester"}
    assert defined  # the sixty incidents, by their (subject, requester) key
    assert {subject for subject, _ in defined} == {s[0] for s in seed.SUBJECTS}
    assert {requester for _, requester in defined} <= requesters
    subject, requester = next(iter(defined))
    assert seed.is_seed_incident({"subject": subject, "requester_id": requester}, people)
    # INC-62's shape: someone's own subject, or a seed subject from another requester.
    assert not seed.is_seed_incident(
        {"subject": "QA-2026-11-09 made by hand", "requester_id": requester}, people
    )
    assert not seed.is_seed_incident({"subject": subject, "requester_id": "someone-else"}, people)


def test_showcase_consumables_are_consumable_have_stable_keys_and_one_runs_low() -> None:
    """WP-049b s1: of consumable types, a key per write, and one at or below its minimum."""
    consumable_types = {
        t.api_name
        for top in SEED_TYPES
        if top.kind == AssetTypeKind.CONSUMABLE
        for t in (top, *top.children)
    }
    sites = {name for name, _ in seed.SITES}
    keys: list[str] = []
    low: list[str] = []
    for spec in assets.CONSUMABLES:
        name = spec.product.name
        assert spec.product.type_api_name in consumable_types
        keys += [seed.key("asset", "product", name), seed.key("asset", "consumable", name)]
        keys += [seed.key("asset", "receipt", name, r.site) for r in spec.receipts]
        keys += [seed.key("asset", "issue", name, i.site) for i in spec.issues]
        held: dict[str, Decimal] = {}
        for receipt in spec.receipts:
            assert receipt.site in sites
            assert (receipt.lot is not None) == spec.batch_tracked
            held[receipt.site] = held.get(receipt.site, Decimal(0)) + Decimal(receipt.quantity)
        for issue in spec.issues:
            assert issue.to in {"user", "department"}
            held[issue.site] -= Decimal(issue.quantity)
            assert held[issue.site] >= 0  # never more than there is
        if spec.minimum is not None:
            site, minimum = spec.minimum
            keys.append(seed.key("asset", "stock-rule", name))
            if held[site] <= Decimal(minimum):
                low.append(name)
    keys.append(seed.key("asset", "booking", assets.BOOKED))
    assert len(set(keys)) == len(keys)  # one key per write, the same every run
    assert keys[0] == seed.key("asset", "product", assets.CONSUMABLES[0].product.name)
    assert low == [assets.TONER]  # the "low" state to show
    assert any(r.expires_in_days for c in assets.CONSUMABLES for r in c.receipts)
    assert assets.BOOKED in {a.tag for a in assets.ASSETS if a.holder == "loan"}  # loanable
    assert assets.BOOKING_IN_DAYS > assets.LOAN_DAYS  # booked after the loan is due back
