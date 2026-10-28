"""Who saved a record after the version a client read (CLAUDE.md rule g; QA WP-029 BUG-05).

A 409 `version_conflict` opens the same dialog in every editor. It names the person and the time
of the save the user missed (`changed_by`, `changed_at`) and, where the record keeps field
history, the fields (`changed_fields`; otherwise empty and the dialog compares the two versions
it has). Every versioned row knows who saved it last (`updated_by`, `updated_at`), so any service
can say it:

    if row.version != expected_version:
        raise await stale_version(session, row, expected_version=expected_version)

People are named by the identity module, which registers its resolver (modules never read each
other's tables, CLAUDE.md rule e).
"""

import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict
from app.shared.history.history import explain_conflict

# (session, user ids) -> display names, in order (unknown ids left out)
PeopleNames = Callable[[AsyncSession, Sequence[str]], Awaitable[Sequence[str]]]

_people_names: PeopleNames | None = None


def register_people_names(resolver: PeopleNames | None) -> None:
    """Set (or with None, clear) how people are named in conflicts."""
    global _people_names  # noqa: PLW0603 - one registry, set once by the identity module
    _people_names = resolver


async def people_names(session: AsyncSession, user_ids: Sequence[str]) -> Sequence[str]:
    """Display names of these users, or nothing when no module names people."""
    if _people_names is None or not user_ids:
        return []
    return await _people_names(session, user_ids)


class Saved(Protocol):
    """A versioned row: who saved it last, and when."""

    @property
    def version(self) -> int:
        """The saved version."""

    @property
    def updated_by(self) -> uuid.UUID | None:
        """Who saved it last."""

    @property
    def updated_at(self) -> datetime:
        """When it was saved last."""


async def with_last_save(session: AsyncSession, conflict: Conflict, saved: Saved) -> Conflict:
    """The same 409, naming the last save of `saved` unless it already names someone."""
    if conflict.instance_code != "version_conflict" or conflict.params.get("changed_by"):
        return conflict
    params = dict(conflict.params)
    names = await people_names(session, [str(saved.updated_by)]) if saved.updated_by else []
    params["changed_by"] = names[0] if names else ""
    params["changed_at"] = saved.updated_at.isoformat()
    params.setdefault("changed_fields", "")
    return Conflict(code="version_conflict", params=params, headers=conflict.headers)


async def stale_version(
    session: AsyncSession,
    saved: Saved,
    *,
    expected_version: int,
    record_type: str | None = None,
    record_id: uuid.UUID | None = None,
) -> Conflict:
    """409 for a save at `expected_version` while `saved` is newer: who, when, which fields.

    With `record_type` (a record that keeps field history) the fields and people come from its
    history; otherwise from the row's last save.
    """
    conflict = Conflict(
        code="version_conflict",
        params={"expected_version": expected_version, "current_version": saved.version},
    )
    if record_type is not None and record_id is not None:
        conflict = await explain_conflict(
            session,
            conflict,
            record_type=record_type,
            record_id=record_id,
            names=lambda ids: people_names(session, ids),
        )
    return await with_last_save(session, conflict, saved)
