"""Automation on realtime (WP-029): changed rules, settings, availability or a stopped loop.

The message names nothing: the admin tabs and availability switches refetch what they show.
Workflows (WP-048b S3): an instance or a job that moved on reaches the overview's list channel
(for `workflows.manage` holders) and an instance its record's channel, IDs only (rule c).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.events import EventEnvelope
from app.shared.files.ports import record_channel_kind
from app.shared.realtime import (
    LiveList,
    Publication,
    RealtimeEffects,
    RealtimeRoute,
    broadcast,
    queue,
    record,
)

CHANGED = "automation.changed"
INSTANCES_CHANGED = "workflow_instances.changed"
JOBS_CHANGED = "workflow_jobs.changed"
WORKFLOWS = LiveList("workflows", "workflows.manage")  # the overview (REQ-WF-025)
CHANNELS = [WORKFLOWS.spec()]


async def _changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    return RealtimeEffects(publications=[Publication(broadcast(envelope.tenant_id), CHANGED)])


async def _instance_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    payload, tenant = envelope.payload, envelope.tenant_id
    instance = str(payload["instance_id"])
    found = [
        Publication(
            queue(tenant, WORKFLOWS.name), INSTANCES_CHANGED, ids=(instance,), coalesce=True
        )
    ]
    kind = record_channel_kind(str(payload["record_type"]))
    if kind is not None:  # the record's execution view (REQ-WF-023 AC1)
        found.append(
            Publication(
                record(tenant, kind, uuid.UUID(str(payload["record_id"]))),
                INSTANCES_CHANGED,
                ids=(instance,),
                version=int(payload["version"]),
            )
        )
    return RealtimeEffects(publications=found)


async def _job_progressed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    del session
    job = str(envelope.payload["job_id"])
    channel = queue(envelope.tenant_id, WORKFLOWS.name)
    return RealtimeEffects(publications=[Publication(channel, JOBS_CHANGED, ids=(job,))])


ROUTES = [
    RealtimeRoute(
        (
            "automation.definition.changed",
            "automation.availability.changed",
            # A stopped loop: the admins' banner and the record's automation panel (REQ-RUL-028).
            "automation.loop.stopped",
        ),
        _changed,
    ),
    RealtimeRoute(("automation.workflow_instance.changed",), _instance_changed),
    RealtimeRoute(("automation.workflow_job.progressed",), _job_progressed),
]
