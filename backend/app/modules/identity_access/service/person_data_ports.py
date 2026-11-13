"""Lane B's person-data ports (ADR-052 §4): identity, organisation, audit, files, links, lists.

Registered from identity_access (`register_lane_b_ports`, at module import), which already
depends on organization and audit: their ports call those modules' public functions, so neither
has to import identity_access (that would be an import cycle). The shared services (files, list
settings, action links) have no module of their own to register from.

Each port is idempotent and returns counts by kind only. Mail is not a port: the job calls
`forget_recipient` in its own step 2, while the address still exists (ADR-052 §3). Not present on
this main and so not covered: security-notice read marks (notices are notifications, lane A's
notifications port erases them on `user.status_changed`).
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import ClassVar

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import erase_saved_searches
from app.modules.identity_access.domain.erasure import erased_email
from app.modules.identity_access.events import ApiKeyChanged, InvitationChanged
from app.modules.identity_access.infra.models import ApiKey, Invitation, UserCostRate, UserRole
from app.modules.identity_access.service import known_devices, sign_in_log
from app.modules.identity_access.service.person_data import (
    ERASE_BATCH,
    ErasureBatch,
    register_person_data,
)
from app.modules.identity_access.service.roles import revoke_roles
from app.modules.organization import erase_person_units
from app.shared.action_links import revoke_for_recipient
from app.shared.events import record_event
from app.shared.files.service.cleanup import forget_uploader
from app.shared.list_settings.infra.models import ListSetting


async def revoke_api_keys(session: AsyncSession, person_id: uuid.UUID, now: datetime) -> int:
    """The person's live API keys stop working now (step 1, freeze). How many."""
    keys = list(
        await session.scalars(
            select(ApiKey)
            .where(ApiKey.owner_id == person_id, ApiKey.revoked_at.is_(None))
            .with_for_update()
        )
    )
    for key in keys:
        key.revoked_at = now
        key.version += 1
    await session.flush()
    for key in keys:
        await record_event(
            session,
            ApiKeyChanged(change="revoked", owner_id=person_id),
            aggregate_id=key.id,
            aggregate_version=key.version,
        )
    return len(keys)


async def revoke_invitations(session: AsyncSession, person_id: uuid.UUID, now: datetime) -> int:
    """The person's pending invitations are withdrawn (step 1). Keycloak's side is step 3."""
    rows = list(
        await session.scalars(
            select(Invitation)
            .where(Invitation.user_id == person_id, Invitation.status == "pending")
            .with_for_update()
        )
    )
    for row in rows:
        row.status, row.revoked_at = "revoked", now
        row.version += 1
    await session.flush()
    for row in rows:
        await record_event(
            session,
            InvitationChanged(change="revoked", status="revoked"),
            aggregate_id=row.id,
            aggregate_version=row.version,
        )
    return len(rows)


class IdentityAccessData:
    """identity_access: keys, invitations, cost rates, roles, sign-in traces (owned band)."""

    module: ClassVar[str] = "identity_access"
    order: ClassVar[int] = 510
    kinds: ClassVar[frozenset[str]] = frozenset(
        {
            "api_keys_revoked",
            "api_key_traces_cleared",
            "invitations_revoked",
            "invitation_addresses_cleared",
            "cost_rates_deleted",
            "roles_removed",
            "sign_ins_cleared",
            "known_devices_deleted",
        }
    )

    async def erase_person(  # noqa: PLR0913 - the port contract (ADR-052 §4)
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        """Keys, invitations, rates, roles and sign-in traces of the person.

        Keys revoked and their last address cleared; invitations withdrawn and their address
        replaced; cost rates deleted (D3a: worklog amounts stay); roles taken; sign-in log
        entries lose address and device; known devices deleted.
        """
        del successor_id, keep_files, cursor
        keys = await revoke_api_keys(session, person_id, now)
        traces = await session.execute(
            update(ApiKey)
            .where(
                ApiKey.owner_id == person_id,
                (ApiKey.last_used_ip.is_not(None)) | (func.cardinality(ApiKey.ip_allowlist) > 0),
            )
            .values(last_used_ip=None, ip_allowlist=[], version=ApiKey.version + 1)
            .execution_options(synchronize_session=False)
        )
        invitations = await revoke_invitations(session, person_id, now)
        address = erased_email(person_id)
        addresses = await session.execute(
            update(Invitation)
            .where(Invitation.user_id == person_id, Invitation.email != address)
            .values(email=address, version=Invitation.version + 1)
            .execution_options(synchronize_session=False)
        )
        rates = await session.execute(delete(UserCostRate).where(UserCostRate.user_id == person_id))
        roles = list(
            await session.scalars(select(UserRole.role_id).where(UserRole.user_id == person_id))
        )
        if roles:
            await revoke_roles(session, person_id, roles)
        return ErasureBatch(
            {
                "api_keys_revoked": keys,
                "api_key_traces_cleared": _count(traces),
                "invitations_revoked": invitations,
                "invitation_addresses_cleared": _count(addresses),
                "cost_rates_deleted": _count(rates),
                "roles_removed": len(roles),
                "sign_ins_cleared": await sign_in_log.forget_person(session, person_id),
                "known_devices_deleted": await known_devices.forget(session, person_id),
            },
            None,  # a person holds few keys, invitations and rates: one call
        )


class OrganizationData:
    """organization: memberships go, groups led and departments headed to the successor."""

    module: ClassVar[str] = "organization"
    order: ClassVar[int] = 120
    kinds: ClassVar[frozenset[str]] = frozenset(
        {"site_memberships", "group_memberships", "groups_led", "departments_headed"}
    )

    async def erase_person(  # noqa: PLR0913 - the port contract (ADR-052 §4)
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        """See organization.erase_person_units."""
        del keep_files, now, cursor
        return ErasureBatch(await erase_person_units(session, person_id, successor_id=successor_id))


class ActionLinksData:
    """Action links sent to the person: revoked (the freeze step did it already; idempotent)."""

    module: ClassVar[str] = "action_links"
    order: ClassVar[int] = 110
    kinds: ClassVar[frozenset[str]] = frozenset({"action_links_revoked"})

    async def erase_person(  # noqa: PLR0913 - the port contract (ADR-052 §4)
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        """Open links to the person stop working; the rows hold IDs and a digest only."""
        del successor_id, keep_files, now, cursor
        return ErasureBatch(
            {"action_links_revoked": await revoke_for_recipient(session, person_id)}
        )


class ListSettingsData:
    """Their list settings, saved views and favourites: private, deleted (owned band)."""

    module: ClassVar[str] = "list_settings"
    order: ClassVar[int] = 520
    kinds: ClassVar[frozenset[str]] = frozenset({"list_settings_deleted"})

    async def erase_person(  # noqa: PLR0913 - the port contract (ADR-052 §4)
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        """Every row of theirs goes, soft-deleted ones too (DELETE granted by migration 0161)."""
        del successor_id, keep_files, now, cursor
        gone = await session.execute(delete(ListSetting).where(ListSetting.user_id == person_id))
        return ErasureBatch({"list_settings_deleted": _count(gone)})


class AuditData:
    """Their saved audit searches: private, deleted. The log itself is step 6's."""

    module: ClassVar[str] = "audit"
    order: ClassVar[int] = 530
    kinds: ClassVar[frozenset[str]] = frozenset({"audit_searches_deleted"})

    async def erase_person(  # noqa: PLR0913 - the port contract (ADR-052 §4)
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        """See audit.erase_saved_searches."""
        del successor_id, keep_files, now, cursor
        return ErasureBatch(
            {"audit_searches_deleted": await erase_saved_searches(session, person_id)}
        )


class FilesData:
    """Files they uploaded: deleted unless the admin kept them (D-171 b).

    Owned band, last of lane B's, so records' own ports have run before the files under them go.
    """

    module: ClassVar[str] = "files"
    order: ClassVar[int] = 590
    kinds: ClassVar[frozenset[str]] = frozenset({"files_deleted"})

    async def erase_person(  # noqa: PLR0913 - the port contract (ADR-052 §4)
        self,
        session: AsyncSession,
        person_id: uuid.UUID,
        *,
        successor_id: uuid.UUID,
        keep_files: Mapping[uuid.UUID, str],
        now: datetime,
        cursor: str | None,
    ) -> ErasureBatch:
        """See files.forget_uploader; the job audits each kept file with its reason."""
        del successor_id, now, cursor  # each batch finds the files still live: no cursor needed
        done = await forget_uploader(session, person_id, keep=set(keep_files), limit=ERASE_BATCH)
        # A full batch may have left more: call again (a final, smaller batch ends it).
        return ErasureBatch({"files_deleted": done.deleted}, "more" if done.full else None)


def _count(result: object) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


LANE_B_PORTS = (
    ActionLinksData(),
    OrganizationData(),
    IdentityAccessData(),
    ListSettingsData(),
    AuditData(),
    FilesData(),
)


def register_lane_b_ports() -> None:
    """Register lane B's ports (identity_access's import does; idempotent)."""
    for port in LANE_B_PORTS:
        register_person_data(port)
