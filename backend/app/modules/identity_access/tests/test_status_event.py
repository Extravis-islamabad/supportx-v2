"""The user status event's contract (WP-040; agreed with lane A): v1 with defaulted fields."""

import uuid

from app.modules.identity_access.events import UserStatusChanged


def test_an_admin_change_reads_as_before_and_carries_the_defaults() -> None:
    event = UserStatusChanged(user_id=uuid.uuid4(), status="disabled")
    assert (event.reason, event.source) == ("admin", None)
    assert UserStatusChanged.schema_version == 1  # additive: consumers of v1 keep working


def test_a_directory_leaver_says_which_directory() -> None:
    user = uuid.uuid4()
    event = UserStatusChanged(user_id=user, status="disabled", reason="directory", source="entra")
    assert event.model_dump(mode="json") == {
        "user_id": str(user),
        "status": "disabled",
        "reason": "directory",
        "source": "entra",
    }


def test_an_event_recorded_before_the_new_fields_still_reads() -> None:
    old = UserStatusChanged.model_validate({"user_id": str(uuid.uuid4()), "status": "active"})
    assert (old.reason, old.source) == ("admin", None)
