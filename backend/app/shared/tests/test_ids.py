import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.shared.ids import id_created_at, new_id


def test_new_id_is_a_stdlib_uuid_version_7() -> None:
    value = new_id()
    assert isinstance(value, uuid.UUID)
    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_ids_are_unique_and_sort_by_creation() -> None:
    ids = [new_id() for _ in range(2000)]
    assert len(set(ids)) == len(ids)
    assert ids == sorted(ids)


def test_creation_time_is_recoverable() -> None:
    before = datetime.now(UTC) - timedelta(milliseconds=1)
    created = id_created_at(new_id())
    after = datetime.now(UTC) + timedelta(milliseconds=1)
    assert before <= created <= after
    assert created.tzinfo is UTC


def test_creation_time_rejects_other_versions() -> None:
    with pytest.raises(ValueError, match="not a UUIDv7"):
        id_created_at(uuid.uuid4())
