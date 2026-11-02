"""Directory sync mapping (WP-040 session 2; REQ-INT-063, REQ-INT-064): no I/O."""

from app.modules.integrations.domain.directory import (
    AttributeMapping,
    DirectoryPerson,
    DirectoryRemoval,
    EmailFrom,
    PersonSkipped,
    SkipReason,
    from_graph,
    leaves,
)

DEFAULT = AttributeMapping()

ADA = {
    "id": "e-1",
    "accountEnabled": True,
    "displayName": "Ada  Lovelace",
    "givenName": "Ada",
    "surname": "Lovelace",
    "mail": "Ada@Alpha.test",
    "userPrincipalName": "ada@alpha.onmicrosoft.com",
    "userType": "Member",
    "jobTitle": "Analyst",
    "employeeId": "E-100",
    "mobilePhone": "+1 555 0100",
    "businessPhones": ["+1 555 0199", "+1 555 0198"],
    "department": "Finance",
    "officeLocation": "London",
    "manager": {"@odata.type": "#microsoft.graph.user", "id": "e-0"},
}


def _person(item: dict[str, object], mapping: AttributeMapping = DEFAULT) -> DirectoryPerson:
    change = from_graph(item, mapping)
    assert isinstance(change, DirectoryPerson), change
    return change


def test_a_full_user_maps_every_field_and_reference() -> None:
    person = _person(ADA)
    assert person.external_id == "e-1"
    assert person.enabled is True
    assert person.values == {
        "email": "ada@alpha.test",
        "first_name": "Ada",
        "last_name": "Lovelace",
        "display_name": "Ada Lovelace",
        "job_title": "Analyst",
        "employee_id": "E-100",
        "mobile": "+1 555 0100",
        "phone": "+1 555 0199",
    }
    assert person.refs == {"department": "Finance", "site": "London", "manager": "e-0"}
    assert person.skipped == ()
    assert not leaves(person)


def test_a_delta_change_touches_only_what_it_carries() -> None:
    # Graph sends the changed properties only: nothing else may be cleared.
    person = _person({"id": "e-1", "jobTitle": "Lead"})
    assert person.values == {"job_title": "Lead"}
    assert person.refs == {}
    assert person.enabled is None
    # A property sent as null clears it.
    cleared = _person({"id": "e-1", "jobTitle": None, "department": None, "manager": None})
    assert cleared.values == {"job_title": None}
    assert cleared.refs == {"department": None, "manager": None}


def test_the_address_falls_back_to_the_principal_name_or_follows_the_mapping() -> None:
    no_mail = {**ADA, "mail": None}
    assert _person(no_mail).values["email"] == "ada@alpha.onmicrosoft.com"
    upn = AttributeMapping(email_from=EmailFrom.USER_PRINCIPAL_NAME)
    assert _person(ADA, upn).values["email"] == "ada@alpha.onmicrosoft.com"


def test_people_who_could_never_sign_in_and_guests_are_skipped_with_the_reason() -> None:
    no_address = {**ADA, "mail": None, "userPrincipalName": "not an address"}
    assert from_graph(no_address, DEFAULT) == PersonSkipped("e-1", SkipReason.NO_ADDRESS)
    guest = {**ADA, "userType": "Guest"}
    assert from_graph(guest, DEFAULT) == PersonSkipped("e-1", SkipReason.GUEST)
    external = {**ADA, "userPrincipalName": "bob_partner.test#EXT#@alpha.onmicrosoft.com"}
    assert from_graph(external, DEFAULT) == PersonSkipped("e-1", SkipReason.GUEST)
    assert isinstance(from_graph(guest, AttributeMapping(include_guests=True)), DirectoryPerson)


def test_a_value_too_long_is_skipped_never_cut() -> None:
    person = _person({**ADA, "jobTitle": "x" * 201})
    assert "job_title" not in person.values
    assert person.skipped == (("job_title", SkipReason.TOO_LONG),)


def test_removed_and_disabled_people_are_leavers() -> None:
    removed = from_graph({"id": "e-1", "@removed": {"reason": "deleted"}}, DEFAULT)
    assert removed == DirectoryRemoval("e-1")
    assert leaves(removed)
    assert leaves(_person({"id": "e-1", "accountEnabled": False}))
    assert not leaves(PersonSkipped("e-1", SkipReason.GUEST))


def test_the_select_asks_only_for_what_the_mapping_reads() -> None:
    chosen = AttributeMapping(site_from="city").graph_select().split(",")
    assert "city" in chosen
    assert "officeLocation" not in chosen
    assert "manager" in chosen
