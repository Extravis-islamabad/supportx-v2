"""Incidents from an outside system's problems (WP-053 S7a, D-050; lane B's MonetX). Pure, no I/O.

One outside problem maps to one incident for life: a key of (source kind, source, external ID)
with the last version applied. The rules here are the decisions alone; the service reads and
writes. Agreed with lane B and the coordinator on 2026-11-25
(plans/wp-053-s7a-entry-point-stub-lane-a.md):

- an equal or older version changes nothing (`stale_version`);
- nothing is reopened: a resolved or closed incident ignores later events (`closed_noop`);
- recovery resolves only an **untouched** incident: one no person has changed since it was made.
  Rules, workflows, the SLA, integrations, imports and AI agents acting alone are not people (an
  AI suggestion a person applies is their own `ui` change, so it counts).
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

ExternalKind = Literal["monetx", "alert_webhook"]
EXTERNAL_KINDS: frozenset[str] = frozenset({"monetx", "alert_webhook"})

NoteCode = Literal[
    "external_problem.opened",
    "external_problem.updated",
    "external_problem.recovered",
    "external_problem.recovered_kept_open",
]
NOTE_CODES: frozenset[str] = frozenset(
    {
        "external_problem.opened",
        "external_problem.updated",
        "external_problem.recovered",
        "external_problem.recovered_kept_open",
    }
)

Decision = Literal[
    "created",
    "exists",
    "stale_version",
    "updated",
    "resolved",
    "noted",
    "closed_noop",
    "record_deleted",
]

RefusalCode = Literal[
    "template_unusable",
    "ci_not_linkable",
    "group_gone",
    "priority_unknown",
    "requester_unusable",
]

EXTERNAL_ID_MAX = 200

# History sources a person changes a record through; every other source is not a touch.
PERSON_SOURCES: frozenset[str] = frozenset({"ui", "api", "portal", "email"})


@dataclass(frozen=True, slots=True)
class ExternalSource:
    """Where a problem comes from: its kind (closed list) and that connection or endpoint."""

    kind: ExternalKind
    source_id: uuid.UUID

    def __post_init__(self) -> None:
        """Refuse a kind outside the closed list (a typo must never become a new source)."""
        if self.kind not in EXTERNAL_KINDS:
            msg = f"unknown external source kind {self.kind!r}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ExternalRecordRef:
    """What happened, for the caller's own record of it (codes and IDs only)."""

    record_id: uuid.UUID | None  # None only with decision "record_deleted"
    display_id: str | None
    created: bool
    decision: Decision


class ExternalProblemRefused(Exception):
    """A labelled refusal, never a 500: the caller records the code as its decision."""

    def __init__(self, code: RefusalCode, params: Mapping[str, str] | None = None) -> None:
        super().__init__(code)
        self.code: RefusalCode = code
        self.params: dict[str, str] = dict(params or {})


@dataclass(frozen=True, slots=True)
class HistoryTouch:
    """One history row as the touched rule needs it."""

    source: str
    by_person: bool  # actor_type user, and not a service account


@dataclass(frozen=True, slots=True)
class Facts:
    """What the service read about an existing key's record."""

    last_version: int
    deleted: bool
    finished: bool  # resolved, closed or canceled: nothing more happens to it
    touches: tuple[HistoryTouch, ...] = field(default_factory=tuple)


def valid_external_id(external_id: str) -> bool:
    """1 to 200 printable characters (lane B also checks it at intake)."""
    return 0 < len(external_id) <= EXTERNAL_ID_MAX and external_id.isprintable()


def is_newer(version: int, last_version: int) -> bool:
    """Only a strictly newer version is applied."""
    return version > last_version


def touched(touches: tuple[HistoryTouch, ...]) -> bool:
    """A person changed it: a person's change through a person's way in (the rule agreed)."""
    return any(t.by_person and t.source in PERSON_SOURCES for t in touches)


def before_update(facts: Facts, version: int) -> Decision | None:
    """Why an update or recovery does nothing, or None to go on."""
    if facts.deleted:
        return "record_deleted"
    if not is_newer(version, facts.last_version):
        return "stale_version"
    if facts.finished:
        return "closed_noop"
    return None


def on_recovery(facts: Facts, *, resolve: bool) -> Decision:
    """`resolved` when asked and untouched; else `noted` (D-050: never under a technician)."""
    return "resolved" if resolve and not touched(facts.touches) else "noted"


def plain(text: str) -> str:
    """Outside free text as plain text: control characters (C0, C1) become spaces."""
    return "".join(" " if not ch.isprintable() else ch for ch in text)


__all__ = [
    "EXTERNAL_ID_MAX",
    "EXTERNAL_KINDS",
    "NOTE_CODES",
    "PERSON_SOURCES",
    "Decision",
    "ExternalKind",
    "ExternalProblemRefused",
    "ExternalRecordRef",
    "ExternalSource",
    "Facts",
    "HistoryTouch",
    "NoteCode",
    "RefusalCode",
    "before_update",
    "is_newer",
    "on_recovery",
    "plain",
    "touched",
    "valid_external_id",
]
