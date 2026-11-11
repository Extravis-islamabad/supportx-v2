"""Workflow runs and jobs on realtime (WP-048b S3b; REQ-WF-023 AC1, REQ-WF-025; rule c).

An instance that moved on reaches the overview's list channel and its record's channel; a job's
progress the overview's. IDs (and the record's version) only, never names or values.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.automation.service.realtime import ROUTES
from app.modules.work_items.service.file_access import FILE_ACCESS
from app.shared.events import EventEnvelope
from app.shared.files.ports import (
    record_channel_kind,
    register_owner_access,
    unregister_owner_access,
)

TENANT = uuid.uuid4()


@pytest.fixture(autouse=True)
def _record_channels() -> Iterator[None]:
    """The record types' channel kinds, as at startup: an app test's shutdown clears them."""
    register_owner_access(FILE_ACCESS)
    yield
    unregister_owner_access(FILE_ACCESS.owner_types)


def _envelope(event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope.model_validate(
        {
            "event_id": uuid.uuid4(),
            "event_type": event_type,
            "schema_version": 1,
            "tenant_id": TENANT,
            "actor": {"type": "system", "id": "worker"},
            "occurred_at": datetime.now(UTC),
            "aggregate_type": "workflow_instance",
            "aggregate_id": "x",
            "payload": payload,
        }
    )


async def _published(event_type: str, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    handler = next(r for r in ROUTES if event_type in r.event_types).route
    effects = await handler(_envelope(event_type, payload), None)  # type: ignore[arg-type]  # reads no rows
    return {p.channel.name: p.data() for p in effects.publications}


async def test_an_instance_change_reaches_the_overview_and_its_record_with_ids_only() -> None:
    instance, record = uuid.uuid4(), uuid.uuid4()
    found = await _published(
        "automation.workflow_instance.changed",
        {
            "instance_id": str(instance),
            "workflow_id": str(uuid.uuid4()),
            "record_type": "incident",
            "record_id": str(record),
            "status": "waiting",
            "version": 3,
        },
    )
    assert found[f"t:{TENANT}:queue:workflows"] == {
        "type": "workflow_instances.changed",
        "ids": [str(instance)],
    }
    kind = record_channel_kind("incident")
    assert kind is not None
    assert found[f"t:{TENANT}:{kind}:{record}"] == {
        "type": "workflow_instances.changed",
        "ids": [str(instance)],
        "version": 3,
    }


async def test_a_job_s_progress_reaches_the_overview() -> None:
    job = uuid.uuid4()
    found = await _published(
        "automation.workflow_job.progressed",
        {
            "job_id": str(job),
            "workflow_id": str(uuid.uuid4()),
            "kind": "retry",
            "status": "running",
            "processed": 3,
            "total": 10,
        },
    )
    assert found == {
        f"t:{TENANT}:queue:workflows": {"type": "workflow_jobs.changed", "ids": [str(job)]}
    }
