"""Field history: who changed what, from what to what (architecture.md §7.4; WP-012).

Every save of a versioned record writes one row per changed field into `field_changes`, in the
same transaction as the row itself and its outbox event:

    await record_changes(
        session, record_type="announcement", record_id=a.id, version=a.version,
        kind="updated", changes=[Change("title", "Old", "New")], source=source_of(request),
    )

The rows are append-only (the application role may insert and read, never update or delete),
tenant-scoped by RLS, and read back newest first (`history_page`). They also explain a 409:
`explain_conflict` adds *who* changed *which fields* since the version the client sent, so the
conflict dialog can say "Aisha changed Title and Body" instead of "someone changed something".

Values follow the record's field rules when read (a hidden field's history is hidden too), and a
field can be recorded as `redacted` (that it changed, not the values) by the writing module.
"""

from app.shared.history.conflicts import (
    people_names,
    register_people_names,
    stale_version,
    with_last_save,
)
from app.shared.history.history import (
    CLIENT_HEADER,
    Actors,
    AuditSink,
    Change,
    ChangeKind,
    ChangesSince,
    FieldChange,
    HistoryCursor,
    HistoryEntry,
    SavedRecord,
    Source,
    audit_sink,
    automated,
    changes_between,
    changes_since,
    count_saves,
    current_automation,
    explain_conflict,
    history_entries,
    history_page,
    in_batch,
    record_changes,
    record_subjects,
    recorded_change_ids,
    register_audit_sink,
    register_change_annotator,
    register_subject_resolver,
    register_subtype_resolver,
    source_of,
)

__all__ = [
    "CLIENT_HEADER",
    "Actors",
    "AuditSink",
    "Change",
    "ChangeKind",
    "ChangesSince",
    "FieldChange",
    "HistoryCursor",
    "HistoryEntry",
    "SavedRecord",
    "Source",
    "audit_sink",
    "automated",
    "changes_between",
    "changes_since",
    "count_saves",
    "current_automation",
    "explain_conflict",
    "history_entries",
    "history_page",
    "in_batch",
    "people_names",
    "record_changes",
    "record_subjects",
    "recorded_change_ids",
    "register_audit_sink",
    "register_change_annotator",
    "register_people_names",
    "register_subject_resolver",
    "register_subtype_resolver",
    "source_of",
    "stale_version",
    "with_last_save",
]
