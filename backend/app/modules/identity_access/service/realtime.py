"""identity_access on realtime (WP-011; docs/architecture/realtime.md).

Channels it decides about:

    t:{tenant}:user:{user}       the user's own channel (only that user)
    t:{tenant}:broadcast         every signed-in user of the tenant (plan changes)
    t:{tenant}:users:{user}      one user record (profile, access drawer), with presence:
                                 the user themselves or whoever may see that user (users.view)
    t:{tenant}:queue:users…      the users list, one channel per audience (LiveList)
    t:{tenant}:queue:roles       the roles list (roles.view)

What its events change on screens, and whose access they change (connections cut, rejoin with
fresh tokens): role assignments, role edits, memberships, user status/type, plan changes.
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.identity_access.infra.models import GroupRole, Role, User, UserRole
from app.modules.identity_access.service.authz_consumer import handler as authz_handler
from app.modules.identity_access.service.directory import USERS
from app.modules.identity_access.service.policy import UNMAPPED_DEFAULT, authorize_stored
from app.modules.organization import memberships, users_in_groups
from app.shared.events import EventEnvelope
from app.shared.realtime import (
    BROADCAST,
    PERSONAL,
    ChannelAccess,
    ChannelRequest,
    ChannelSpec,
    LiveList,
    Publication,
    RealtimeEffects,
    RealtimeRoute,
    broadcast,
    personal,
    record,
)

if TYPE_CHECKING:
    from app.modules.identity_access.domain.policy import Subject

USER_RECORD = "users"
USERS_LIST = LiveList("users", "users.view")
ROLES_LIST = LiveList("roles", "roles.view")
IMPORTS_LIST = LiveList("people_imports", "users.manage")
# Admin > Sign-in and security (WP-039): the settings and SSO set-ups, for identity managers.
IDENTITY_LIST = LiveList("identity", "identity.manage")
# Invitations (WP-039 session 2): the security screen's list and each person's record.
INVITATIONS_LIST = LiveList("invitations", "users.manage")
# API keys (WP-041): every key for key managers; each owner hears of their own on their channel.
API_KEYS_LIST = LiveList("api_keys", "api_keys.manage")
# A person's cost per hour (REQ-INC-068): only for those who may see cost rates. The message
# names the person only; the screen refetches their rates (never an amount on a channel).
COST_RATES_LIST = LiveList("user_cost_rates", "users.view_cost_rates")
# Field access rules (ADR-047): the role editor's field access tab.
FIELD_ACCESS_LIST = LiveList("field_access", "roles.view")
# The sign-in log (REQ-AUD-015): only for those who may read it; the message names nothing.
SIGN_INS_LIST = LiveList("sign_ins", "identity.view_sign_ins")
KEY_SETTINGS = frozenset({"people_may_create_keys", "allow_non_expiring_keys"})

# Changes to these user fields change what the user may do: their connections are cut.
ACCESS_FIELDS = frozenset({"status", "user_type"})


# --- who may join ---------------------------------------------------------------------------------


async def _own_channel(request: ChannelRequest) -> ChannelAccess | None:
    return ChannelAccess() if request.channel.key == str(request.user_id) else None


async def _tenant_channel(request: ChannelRequest) -> ChannelAccess | None:
    # Signed in to this tenant is enough: the API only signs tokens for the session's tenant.
    return ChannelAccess() if request.channel.key is None else None


async def _user_record(request: ChannelRequest) -> ChannelAccess | None:
    try:
        target = uuid.UUID(request.channel.key or "")
    except ValueError:
        return None
    if target == request.user_id:
        return ChannelAccess(presence=True)
    subject: Subject = request.subject
    decision = await authorize_stored(
        request.session, subject, "users.view", USERS, User.id, target
    )
    return ChannelAccess(presence=True) if decision else None


CHANNELS = [
    ChannelSpec(kind=PERSONAL, authorize=_own_channel),
    ChannelSpec(kind=BROADCAST, authorize=_tenant_channel),
    ChannelSpec(kind=USER_RECORD, authorize=_user_record),
    USERS_LIST.spec(),
    ROLES_LIST.spec(),
    IMPORTS_LIST.spec(),
    IDENTITY_LIST.spec(),
    INVITATIONS_LIST.spec(),
    API_KEYS_LIST.spec(),
    COST_RATES_LIST.spec(),
    FIELD_ACCESS_LIST.spec(),
    SIGN_INS_LIST.spec(),
]


# --- what reaches screens -------------------------------------------------------------------------


async def _fresh_access(envelope: EventEnvelope) -> None:
    """Make the tenant's compiled permissions stale before anyone is told to refetch.

    The API process that made the change already did; this covers changes made elsewhere and
    keeps the order "cache stale, then message" independent of the authz consumer.
    """
    await authz_handler(get_settings)(envelope, None)


def _actor(envelope: EventEnvelope) -> str | None:
    return envelope.actor.id if envelope.actor.type == "user" else None


def _access_changed(tenant_id: uuid.UUID, user_ids: list[uuid.UUID]) -> list[Publication]:
    return [Publication(personal(tenant_id, u), "access.changed", ids=(str(u),)) for u in user_ids]


REPORTS_CHANGED = "users.reports_changed"


async def _user_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A user record was provisioned or edited: their record, the users lists, their own screens."""
    tenant = envelope.tenant_id
    user_id = uuid.UUID(str(envelope.payload["user_id"]))
    fields = tuple(envelope.payload.get("changed_fields", ()))
    if "status" in envelope.payload:  # identity_access.user.status_changed
        fields = ("status",)
    units = await memberships(session, user_id)
    publications = [
        Publication(
            record(tenant, USER_RECORD, user_id),
            "users.changed",
            ids=(str(user_id),),
            fields=fields,
            version=envelope.aggregate_version,
            actor_id=_actor(envelope),
        ),
        *USERS_LIST.publications(
            tenant,
            "users.changed",
            user_id,
            sites=sorted(units.site_ids),
            groups=sorted(units.group_ids),
            owners=[user_id],
            actor_id=_actor(envelope),
        ),
        # A new or former direct report: both managers' "from my direct reports" recount.
        *(
            Publication(personal(tenant, uuid.UUID(str(m))), REPORTS_CHANGED, ids=(str(user_id),))
            for m in envelope.payload.get("managers", ())
        ),
    ]
    revoke = [user_id] if ACCESS_FIELDS & set(fields) else []
    if revoke:
        await _fresh_access(envelope)
    return RealtimeEffects(publications=publications, revoke_users=revoke)


async def _role_assignment(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A role was given or taken: the user's access, their record, the role counts."""
    del session
    await _fresh_access(envelope)
    tenant = envelope.tenant_id
    user_id = uuid.UUID(str(envelope.payload["user_id"]))
    role_id = str(envelope.payload["role_id"])
    return RealtimeEffects(
        publications=[
            Publication(
                record(tenant, USER_RECORD, user_id),
                "users.changed",
                ids=(str(user_id),),
                fields=("roles",),
                actor_id=_actor(envelope),
            ),
            *ROLES_LIST.publications(tenant, "roles.changed", uuid.UUID(role_id)),
            *_access_changed(tenant, [user_id]),
        ],
        revoke_users=[user_id],
    )


async def _group_role_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A group gained or lost a role: every member's access, and the role's list entry."""
    await _fresh_access(envelope)
    tenant = envelope.tenant_id
    group_id = uuid.UUID(str(envelope.payload["group_id"]))
    role_id = uuid.UUID(str(envelope.payload["role_id"]))
    members = list(await session.scalars(users_in_groups(frozenset({group_id}))))
    return RealtimeEffects(
        publications=[
            *ROLES_LIST.publications(tenant, "roles.changed", role_id),
            *_access_changed(tenant, members),
        ],
        revoke_users=members,
    )


async def _role_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A role was created, edited or deleted: the roles list; holders' access if it changed."""
    await _fresh_access(envelope)
    tenant = envelope.tenant_id
    role_id = uuid.UUID(str(envelope.payload["role_id"]))
    holders: list[uuid.UUID] = []
    if envelope.payload.get("change") != "created":
        holders = list(
            await session.scalars(select(UserRole.user_id).where(UserRole.role_id == role_id))
        )
    return RealtimeEffects(
        publications=[
            *ROLES_LIST.publications(tenant, "roles.changed", role_id, actor_id=_actor(envelope)),
            *_access_changed(tenant, holders),
        ],
        revoke_users=holders,
    )


async def _role_holders(session: AsyncSession, role_id: uuid.UUID) -> list[uuid.UUID]:
    """Everyone holding a role: directly, through a group, or as their type's default role."""
    holders = set(
        await session.scalars(select(UserRole.user_id).where(UserRole.role_id == role_id))
    )
    groups = frozenset(
        await session.scalars(select(GroupRole.group_id).where(GroupRole.role_id == role_id))
    )
    if groups:
        holders |= set(await session.scalars(users_in_groups(groups)))
    key = await session.scalar(select(Role.key).where(Role.id == role_id))
    types = [t for t, default in UNMAPPED_DEFAULT.items() if default == key]
    if types:
        holders |= set(
            await session.scalars(
                select(User.id).where(
                    User.user_type.in_(types),
                    User.roles_mapped_at.is_(None),
                    User.deleted_at.is_(None),
                    ~User.id.in_(select(UserRole.user_id)),
                )
            )
        )
    return sorted(holders)


async def _field_access_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A field access rule changed (ADR-047): subjects stale, then the list and the role's holders.

    Holders' records refetch with what they may now see. Channels stay open: a field rule changes
    what a record shows, never who may follow it.
    """
    await _fresh_access(envelope)
    tenant = envelope.tenant_id
    role_id = uuid.UUID(str(envelope.payload["role_id"]))
    return RealtimeEffects(
        publications=[
            *FIELD_ACCESS_LIST.publications(
                tenant, "field_access.changed", role_id, actor_id=_actor(envelope)
            ),
            *_access_changed(tenant, await _role_holders(session, role_id)),
        ]
    )


async def _membership_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A user joined or left a site/group: their access, their record, that unit's users list."""
    del session
    await _fresh_access(envelope)
    tenant = envelope.tenant_id
    user_id = uuid.UUID(str(envelope.payload["user_id"]))
    unit = uuid.UUID(str(envelope.payload["unit_id"]))
    kind = str(envelope.payload["kind"])
    unit_list = (
        USERS_LIST.publications(tenant, "users.changed", user_id, sites=[unit])
        if kind == "site"
        else USERS_LIST.publications(tenant, "users.changed", user_id, groups=[unit])
    )
    return RealtimeEffects(
        publications=[
            Publication(
                record(tenant, USER_RECORD, user_id),
                "users.changed",
                ids=(str(user_id),),
                fields=(f"{kind}s",),
                actor_id=_actor(envelope),
            ),
            *unit_list,
            *_access_changed(tenant, [user_id]),
        ],
        revoke_users=[user_id],
    )


async def _import_progressed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A people import moved on: its progress on the imports screen (counts are refetched)."""
    del session
    import_id = uuid.UUID(str(envelope.payload["import_id"]))
    return RealtimeEffects(
        publications=IMPORTS_LIST.publications(
            envelope.tenant_id, "people_imports.changed", import_id, actor_id=_actor(envelope)
        )
    )


async def _identity_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """Sign-in settings or an SSO set-up changed: other admins' security screens refetch.

    When people may now (or no longer) change their own numbers, everyone's My account
    refetches their own record (WP-028, rule 5c): a signal with no content, on the tenant's
    channel, as the API decides what each person may do.

    A change to the API key settings also reaches everyone's own key screen (WP-041), as a
    tenant-wide signal that names nothing: each screen refetches what it may offer.
    """
    del session
    publications = IDENTITY_LIST.publications(
        envelope.tenant_id,
        "identity.changed",
        uuid.UUID(str(envelope.aggregate_id)),
        actor_id=_actor(envelope),
    )
    changed = set(envelope.payload.get("changed_fields") or ())
    if "people_edit_contact" in changed:
        publications.append(Publication(broadcast(envelope.tenant_id), CONTACT_EDITING_CHANGED))
    if changed & KEY_SETTINGS:
        publications.append(Publication(broadcast(envelope.tenant_id), "api_keys.rules_changed"))
    return RealtimeEffects(publications=publications)


CONTACT_EDITING_CHANGED = "identity_access.contact_editing_changed"


async def _invitation_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """An invitation was sent, resent, accepted or withdrawn: people managers' screens refetch."""
    del session
    return RealtimeEffects(
        publications=INVITATIONS_LIST.publications(
            envelope.tenant_id,
            "invitations.changed",
            uuid.UUID(str(envelope.aggregate_id)),
            actor_id=_actor(envelope),
        )
    )


async def _api_key_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A key was made or revoked: key managers' list and the owner's own keys refetch."""
    del session
    return RealtimeEffects(
        publications=API_KEYS_LIST.publications(
            envelope.tenant_id,
            "api_keys.changed",
            uuid.UUID(str(envelope.aggregate_id)),
            owners=[uuid.UUID(str(envelope.payload["owner_id"]))],
            actor_id=_actor(envelope),
        )
    )


async def _cost_rate_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A person's rate was set, changed or removed: open rate cards of that person refetch."""
    del session
    return RealtimeEffects(
        publications=COST_RATES_LIST.publications(
            envelope.tenant_id,
            "user_cost_rates.changed",
            uuid.UUID(str(envelope.payload["user_id"])),
            actor_id=_actor(envelope),
        )
    )


async def _sign_in_recorded(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """A sign-in, refusal or sign-out was logged: open sign-in logs refetch (rule 5c)."""
    del session
    return RealtimeEffects(
        publications=SIGN_INS_LIST.publications(
            envelope.tenant_id,
            "sign_ins.changed",
            uuid.UUID(str(envelope.aggregate_id)),
            actor_id=None,
        )
    )


async def _plan_changed(envelope: EventEnvelope, session: AsyncSession) -> RealtimeEffects:
    """The tenant's plan changed: permissions depend on features, so everyone rejoins.

    (The banner message itself is licensing's route.)
    """
    await _fresh_access(envelope)
    users = list(await session.scalars(select(User.id).where(User.status == "active")))
    return RealtimeEffects(revoke_users=users)


ROUTES = [
    RealtimeRoute(
        (
            "identity_access.user.provisioned",
            "identity_access.user.created",
            "identity_access.user.updated",
            "identity_access.user.status_changed",
            # A login changes "last login" in the users list.
            "identity_access.user.logged_in",
        ),
        _user_changed,
    ),
    RealtimeRoute(("identity_access.user_role.changed",), _role_assignment),
    RealtimeRoute(("identity_access.group_role.changed",), _group_role_changed),
    RealtimeRoute(("identity_access.role.changed",), _role_changed),
    RealtimeRoute(("identity_access.field_access.changed",), _field_access_changed),
    RealtimeRoute(("organization.membership.changed",), _membership_changed),
    RealtimeRoute(("licensing.entitlement.changed",), _plan_changed),
    # The technician defaults changed (D-073): like a plan change, everyone's access is redone.
    RealtimeRoute(("identity_access.access_settings.changed",), _plan_changed),
    RealtimeRoute(("identity_access.people_import.progressed",), _import_progressed),
    RealtimeRoute(
        (
            "identity_access.identity_settings.changed",
            "identity_access.sso_provider.changed",
            "identity_access.mfa.changed",
        ),
        _identity_changed,
    ),
    RealtimeRoute(
        ("identity_access.invitation.changed", "identity_access.invitation.link_copied"),
        _invitation_changed,
    ),
    RealtimeRoute(("identity_access.api_key.changed",), _api_key_changed),
    RealtimeRoute(("identity_access.user_cost_rate.changed",), _cost_rate_changed),
    RealtimeRoute(("identity_access.sign_in.recorded",), _sign_in_recorded),
]
