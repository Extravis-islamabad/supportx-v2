"""Where a message's link goes, by what the reader may see (WP-028, REQ-PRT-024 AC2; lane B review).

FULL readers open the record in the console; PUBLIC readers (the requester's side) open it in
the portal when the source gives a portal path, else the portal's home; the {{record.link}}
variable and the button are always the same link.
"""

import uuid
from zoneinfo import ZoneInfo

import pytest

from app.modules.identity_access import NotifiablePerson
from app.modules.notifications.service.engine import compose
from app.shared.notifications.ports import RecordAccess, RecordContext

CONSOLE = "https://acme.example/"
PORTAL = "https://acme.example/portal/"
RECORD = uuid.uuid4()


def _origin(access: RecordAccess) -> str:
    return CONSOLE if access is RecordAccess.FULL else PORTAL


def _context(public_link: str | None) -> RecordContext:
    return RecordContext(
        record_id=RECORD,
        display_id="INC-7",
        link=f"/incidents/{RECORD}",
        variables={"record.display_id": "INC-7", "record.title": "Mail"},
        public_variables={"record.display_id": "INC-7", "record.title": "Mail"},
        relatives={},
        conditions={},
        public_link=public_link,
    )


def _link(access: RecordAccess, public_link: str | None) -> tuple[str, str]:
    message = compose(
        "incident.status_changed",
        context=_context(public_link),
        access=access,
        person=NotifiablePerson("Sam", "sam@acme.example", "en", None),
        language="en",
        zone=ZoneInfo("UTC"),
        origin=_origin,
        offered=frozenset(
            {
                "record.link",
                "record.status",
                "record.priority",
                "requester.name",
                "assignee.name",
                "actor.name",
                "change.from_status",
                "recipient.name",
            }
        ),
    )
    return message.link, message.email.body


def test_full_readers_open_the_record_in_the_console_unchanged() -> None:
    for public_link in (None, f"/requests/{RECORD}"):
        link, _ = _link(RecordAccess.FULL, public_link)
        assert link == f"{CONSOLE}incidents/{RECORD}"


def test_public_readers_without_a_portal_path_get_the_portal_home() -> None:
    link, _ = _link(RecordAccess.PUBLIC, None)
    assert link == PORTAL


def test_public_readers_open_the_record_in_the_portal() -> None:
    link, body = _link(RecordAccess.PUBLIC, f"/requests/{RECORD}")
    assert link == f"{PORTAL}requests/{RECORD}"
    assert f"/incidents/{RECORD}" not in body  # never the console path


def test_a_portal_path_must_be_a_path() -> None:
    with pytest.raises(ValueError, match="must start with"):
        _context("https://elsewhere.example/x")
