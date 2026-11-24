"""A refused entry names what the request named: IDs only, never free text (lane A's #612 nit)."""

import uuid

from app.modules.audit.service.recording import AuditNote, requested_ids


def test_only_ids_and_lists_of_ids_are_kept() -> None:
    one, two = uuid.uuid4(), uuid.uuid4()
    note = AuditNote(
        details={
            "delegate_id": str(one),
            "delegator_id": two,
            "group_ids": [str(one), str(two)],
            "reason": "on leave next week",  # free text: never in the log
            "count": 3,
            "mixed": [str(one), "not an id"],
            "empty": [],
        }
    )
    assert requested_ids(note) == {
        "delegate_id": str(one),
        "delegator_id": str(two),
        "group_ids": [str(one), str(two)],
    }


def test_no_note_or_nothing_named_gives_nothing() -> None:
    assert requested_ids(None) == {}
    assert requested_ids(AuditNote()) == {}


def test_an_id_is_logged_in_its_canonical_form() -> None:
    one = uuid.uuid4()
    note = AuditNote(details={"a_id": str(one).upper(), "b_ids": [f"{{{one}}}", one.urn]})
    assert requested_ids(note) == {"a_id": str(one), "b_ids": [str(one), str(one)]}
