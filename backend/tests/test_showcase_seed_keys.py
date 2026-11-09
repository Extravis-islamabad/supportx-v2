"""The seed's one definition of its own incidents (QA 2026-11-09, INC-62): no DB needed."""

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
