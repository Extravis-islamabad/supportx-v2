"""Attachments that come with support mail (WP-024 session 2; REQ-INC-023).

Every file goes through the one upload path of WP-022 (`app.shared.files.service.uploads`), as
the person who sent the mail: the owner check (may they attach here?), the tenant's size limit and
blocked types, the storage quota, encryption, and the virus scan (files wait in "scanning" until
the scanner clears them). There is no second way in.

A file the rules refuse is never dropped silently: `screen` checks each one against the tenant's
rules before the record is made, and the record's text then names what was not kept and why, in
the sender's language. Inline images (Content-ID) are kept as attachments; the description is
built from the plain text, so nothing points at them.
"""

import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from markupsafe import escape
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SESSION_TENANT_KEY
from app.core.errors import AppError
from app.core.logging import get_logger
from app.modules.identity_access import mail_recipients, subject_for
from app.shared.files.domain.types import SNIFF_BYTES, blocked_reason, normalise_name, sniff
from app.shared.files.ports import OwnerType
from app.shared.files.service.core import FileServices, FilesNotConfiguredError, rules
from app.shared.files.service.uploads import Target, upload
from app.shared.labels import label
from app.shared.mail.domain.inbound import InboundAttachment
from app.shared.storage import StorageNotConfigured, StorageUnavailable

log = get_logger(__name__)


_SERVICES: list[FileServices] = []


def file_services(settings: Settings) -> FileServices:
    """The process's file services, built from settings once.

    The system module builds its own the same way; it has no public interface to share them.
    """
    if not _SERVICES:
        _SERVICES.append(FileServices.from_settings(settings))
    return _SERVICES[0]


def use_services(replacement: FileServices | None) -> None:
    """Tests: real storage with a fake scanner (None: back to the settings)."""
    _SERVICES[:] = [] if replacement is None else [replacement]


@dataclass(frozen=True)
class NotKept:
    """An attachment that was not stored, and why (label `mail_attachment.<reason>`)."""

    name: str
    reason: str
    params: dict[str, str | int]


@dataclass(frozen=True)
class Screened:
    """What the tenant's file rules let in, and what they refuse."""

    keep: tuple[InboundAttachment, ...]
    not_kept: tuple[NotKept, ...]


async def screen(session: AsyncSession, attachments: Sequence[InboundAttachment]) -> Screened:
    """Check each attachment against the tenant's file rules (no bytes stored yet)."""
    found = await rules(session)
    keep: list[InboundAttachment] = []
    refused: list[NotKept] = []
    for attachment in attachments:
        name = normalise_name(attachment.name)
        if len(keep) >= found.max_batch:
            refused.append(NotKept(name, "too_many", {"max": found.max_batch}))
        elif len(attachment.data) > found.max_file_bytes:
            refused.append(NotKept(name, "too_large", {"limit_mb": found.max_file_mb}))
        elif blocked_reason(name, sniff(attachment.data[:SNIFF_BYTES]), found.blocked):
            refused.append(NotKept(name, "blocked", {}))
        else:
            keep.append(attachment)
    return Screened(tuple(keep), tuple(refused))


async def language_of(session: AsyncSession, person: uuid.UUID) -> str:
    """The language a person reads (their interface language; English when unknown)."""
    known = await mail_recipients(session, [person])
    return known[person].language if person in known else "en"


def not_kept_html(not_kept: Sequence[NotKept], language: str) -> str:
    """A paragraph for the record's text naming the files that were not kept ("" when none)."""
    if not not_kept:
        return ""
    items = "".join(
        f"<li>{escape(item.name)}: "
        f"{escape(label(f'mail_attachment.{item.reason}', language, **item.params))}</li>"
        for item in not_kept
    )
    return f"<p>{escape(label('mail_attachment.not_kept', language))}</p><ul>{items}</ul>"


async def _bytes(data: bytes) -> AsyncIterator[bytes]:
    yield data


async def keep(  # noqa: PLR0913 - the files, who sent them and where they go, explicit
    session: AsyncSession,
    settings: Settings,
    attachments: Sequence[InboundAttachment],
    *,
    sender_id: uuid.UUID,
    owner_type: OwnerType,
    owner_id: uuid.UUID,
) -> list[NotKept]:
    """Upload the screened attachments as the sender; what still could not be kept.

    Each upload runs in a savepoint, so one refusal (quota, permission) never undoes the record.
    Object storage being down is not a refusal: it propagates, the transaction rolls back and the
    message stays on the mail server for the next fetch.
    """
    if not attachments:
        return []
    services = file_services(settings)
    if services.storage is None or services.keyring is None:
        return [NotKept(normalise_name(a.name), "files_not_configured", {}) for a in attachments]
    tenant = session.info[SESSION_TENANT_KEY].tenant_id
    sender = await subject_for(session, tenant, sender_id)
    target = Target(owner_type, owner_id)
    refused: list[NotKept] = []
    for attachment in attachments:
        name = normalise_name(attachment.name)
        try:
            async with session.begin_nested():
                await upload(
                    session,
                    services,
                    sender,
                    target,
                    name=name,
                    declared_size=len(attachment.data),
                    body=_bytes(attachment.data),
                    source="email",
                )
        except (StorageNotConfigured, FilesNotConfiguredError):
            refused.append(NotKept(name, "files_not_configured", {}))
        except StorageUnavailable:
            raise  # transient: the message waits on the mail server
        except AppError as exc:
            # Logged by code only: never the file's name or content (personal data).
            log.warning("mail_attachment_not_kept", reason=exc.instance_code)
            refused.append(NotKept(name, "not_allowed", {}))
    return refused
