"""Audit module (WP-018, ADR-027): the tamper-evident audit log (architecture.md §7.4).

Security-relevant actions are written to an append-only log, separate from field history, and
sealed into a per-tenant hash chain with signed anchors. Reading the log is audited too.

Public interface for other modules:

* `audited(action, object_type=..., object_param=...)`: route dependency for privileged writes
  (`note: Annotated[AuditNote, audited(...)]` to add details);
* `audit_read(ReadCategory.X, ...)`: route dependency for sensitive reads;
* `record_alone(database, context, action_code=..., facts=...)`: entries outside a route
  transaction (sign-in);
* `erase_subject(session, user_id)`: personal-data erasure that keeps the chain verifiable;
* `entries_for_changes(session, change_ids)`: which field-history saves have an audit entry
  (record history shows the link only to holders of `audit.view`, REQ-AUD-006).
"""

from fastapi import FastAPI

from app.core.authorization import PermissionSpec
from app.core.errors import register_error_observer, unregister_error_observer
from app.core.modules import ModuleSpec
from app.modules.audit.api.routes import EXPORT, MANAGE, VERIFY, VIEW, router
from app.modules.audit.domain.catalogue import AuditCategory, ReadCategory
from app.modules.audit.events import EVENTS
from app.modules.audit.service.erasure import erase_subject
from app.modules.audit.service.jobs import (
    anchor_all,
    ensure_partitions,
    expire_all_exports,
    expire_all_restored,
    on_entry_recorded,
    on_export_requested,
    on_restore_requested,
    on_verification_requested,
    run_retention,
    seal_sweep,
    verify_due,
)
from app.modules.audit.service.queries import entries_for_changes
from app.modules.audit.service.realtime import CHANNELS, ROUTES
from app.modules.audit.service.recording import (
    AuditNote,
    RequestFacts,
    audit_read,
    audited,
    log_refusal,
    record_alone,
)
from app.shared.events import ConsumerSpec
from app.shared.schedules import ScheduleSpec

AUDITOR = "auditor"

# Separation of duties (D-076): auditors read, search, export and verify, and change nothing;
# settings stay with tenant administrators. Nobody can change or delete an entry.
PERMISSIONS = (
    PermissionSpec(VIEW, defaults=((AUDITOR, "all"),)),
    PermissionSpec(EXPORT, defaults=((AUDITOR, "all"),)),
    PermissionSpec(VERIFY, defaults=((AUDITOR, "all"),)),
    PermissionSpec(MANAGE),
)


async def _startup(app: FastAPI) -> None:
    del app
    register_error_observer(log_refusal)


async def _shutdown(app: FastAPI) -> None:
    del app
    unregister_error_observer(log_refusal)


module = ModuleSpec(
    name="audit",
    routers=[router],
    on_startup=[_startup],
    on_shutdown=[_shutdown],
    events=EVENTS,
    permissions=PERMISSIONS,
    channels=CHANNELS,
    realtime=ROUTES,
    consumers=[
        ConsumerSpec(
            name="audit__seal",
            event_types=("audit.entry.recorded",),
            handler=on_entry_recorded,
        ),
        ConsumerSpec(
            name="audit__export",
            event_types=("audit.export.requested",),
            handler=on_export_requested,
            ack_wait_seconds=900,
        ),
        ConsumerSpec(
            name="audit__verify_on_demand",
            event_types=("audit.verification.requested",),
            handler=on_verification_requested,
            ack_wait_seconds=900,
        ),
        ConsumerSpec(
            name="audit__restore",
            event_types=("audit.archive.restore_requested",),
            handler=on_restore_requested,
            ack_wait_seconds=900,
        ),
    ],
    schedules=[
        ScheduleSpec("audit__seal_sweep", 60, seal_sweep),
        ScheduleSpec("audit__anchor", 300, anchor_all),
        ScheduleSpec("audit__verify", 900, verify_due),
        ScheduleSpec("audit__partitions", 86400, ensure_partitions),
        ScheduleSpec("audit__exports_expire", 3600, expire_all_exports),
        ScheduleSpec("audit__retention", 86400, run_retention),
        ScheduleSpec("audit__restored_expire", 3600, expire_all_restored),
    ],
)

__all__ = [
    "AUDITOR",
    "AuditCategory",
    "AuditNote",
    "ReadCategory",
    "RequestFacts",
    "audit_read",
    "audited",
    "entries_for_changes",
    "erase_subject",
    "module",
    "record_alone",
]
