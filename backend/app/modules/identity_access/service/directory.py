"""User directory: list, read and the SupportX-owned preferences (WP-008).

Since WP-021 SupportX owns the whole person record (D-092): admins edit it in people.py, and a
sign-in only records the time. The user edits their own preferences here (reply signature, time
zone, layout, language), with optimistic concurrency, and
each change emits `identity_access.user.updated` in the same transaction (CLAUDE.md rules b, g).

Permissions (WP-016 policy layer; the route checks the permission, this layer the record):
- list and read other users: `users.view`, filtered to the subject's scope;
- read yourself: any signed-in user;
- change preferences: `profile.edit`, own record only.
Field visibility: `last_login_at` only for subjects holding `users.manage`.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from zoneinfo import available_timezones

from sqlalchemy import false, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, FieldError, PermissionDenied, ValidationFailed
from app.modules.identity_access.domain.identity import FormDensity, NavLayout, UserType
from app.modules.identity_access.domain.policy import RecordFacts, Subject
from app.modules.identity_access.events import UserUpdated
from app.modules.identity_access.infra.models import User
from app.modules.identity_access.service.policy import (
    PEOPLE,
    FieldRule,
    ResourceType,
    authorize,
    authorize_stored,
    require,
    scope_filter,
)
from app.modules.organization import users_in_groups, users_in_sites
from app.shared.api.filters import FieldType, FilterField, ResourceFields
from app.shared.api.listing import ListQuery, PageResult, paginate
from app.shared.db.repository import Repository
from app.shared.events import record_event
from app.shared.history import (
    Change,
    Source,
    explain_conflict,
    record_changes,
    register_people_names,
)
from app.shared.mail import Language
from app.shared.search import ENGINE

USER_RECORD_TYPE = "user"

EDITABLE_FIELDS = frozenset({"signature", "time_zone", "nav_layout", "form_density", "ui_locale"})
UI_LOCALES = frozenset({"en", "ar", "ur"})
MAX_SIGNATURE_LENGTH = 2000

USER_FIELDS = ResourceFields(
    name="users",
    fields={
        "id": FilterField(User.id, FieldType.UUID),
        "email": FilterField(User.email, FieldType.STRING, sortable=True),
        "display_name": FilterField(User.display_name, FieldType.STRING, sortable=True),
        "user_type": FilterField(
            User.user_type, FieldType.ENUM, values=frozenset(t.value for t in UserType)
        ),
        "status": FilterField(
            User.status, FieldType.ENUM, values=frozenset({"active", "disabled"})
        ),
        "locale": FilterField(User.locale, FieldType.ENUM, values=frozenset({"en", "ar", "ur"})),
        "created_at": FilterField(User.created_at, FieldType.DATETIME, sortable=True, simple=False),
        "updated_at": FilterField(User.updated_at, FieldType.DATETIME, simple=False),
        "last_login_at": FilterField(
            User.last_login_at, FieldType.DATETIME, sortable=True, simple=False
        ),
        # The person record (WP-021): the people views filter on these.
        "employee_id": FilterField(User.employee_id, FieldType.STRING),
        "job_title": FilterField(User.job_title, FieldType.STRING),
        "site_id": FilterField(User.site_id, FieldType.UUID),
        "department_id": FilterField(User.department_id, FieldType.UUID),
        "manager_id": FilterField(User.manager_id, FieldType.UUID),
        "vip": FilterField(User.vip, FieldType.BOOLEAN),
        "can_sign_in": FilterField(User.can_sign_in, FieldType.BOOLEAN),
    },
    id_column=User.id,
    default_sort=("display_name",),
)


class UserRepository(Repository[User]):
    """Users of the session's tenant."""

    model = User


def users_resource() -> ResourceType:
    """How the policy applies to user records (WP-016).

    own = the user themselves; site/group = users sharing one of the subject's sites/groups;
    the last sign-in time is only shown to subjects who manage users.
    """
    return ResourceType(
        name="users",
        fields=USER_FIELDS,
        owner_columns=(User.id,),
        site_scope=lambda ids: User.id.in_(users_in_sites(ids)),
        group_scope=lambda ids: User.id.in_(users_in_groups(ids)),
        field_rules={
            "last_login_at": FieldRule("users.manage"),
            "description": FieldRule("users.manage"),
            "invited_at": FieldRule("users.manage"),
        },
    )


USERS = users_resource()


async def list_users(
    session: AsyncSession, subject: Subject, query: ListQuery, *, text: str | None = None
) -> PageResult[User]:
    """One page of the users the subject may see (users.view, scope-filtered).

    `text` searches names and emails (word forms, Arabic and Urdu spellings, typos; WP-027); the
    page keeps the requested sort, so paging stays stable.
    """
    visible_rows = select(User).where(
        User.deleted_at.is_(None), scope_filter(subject, "users.view", USERS)
    )
    if text:
        found = await ENGINE.match(session, PEOPLE, text)
        # Typed, but nothing searchable (only punctuation): nobody matches.
        visible_rows = visible_rows.where(found.predicate if found is not None else false())
    return await paginate(session, visible_rows, query)


async def people_matching(session: AsyncSession, text: str, *, limit: int = 200) -> list[uuid.UUID]:
    """IDs of the tenant's people whose name or email matches `text`, best first.

    For other modules' searches by person ("incidents requested by Ahmed"): they filter their own
    records by these IDs and their own scope, so this reveals nothing on its own.
    """
    found = await ENGINE.match(session, PEOPLE, text)
    if found is None:
        return []
    rows = await session.scalars(
        select(User.id)
        .where(User.deleted_at.is_(None), found.predicate)
        .order_by(found.rank.desc(), User.id)
        .limit(limit)
    )
    return list(rows)


async def get_user(session: AsyncSession, subject: Subject, user_id: uuid.UUID) -> User:
    """Yourself always; anyone else with users.view in scope (404 if absent)."""
    user = await UserRepository(session).get(user_id)
    if user_id != subject.user_id:
        require(
            await authorize_stored(session, subject, "users.view", USERS, User.id, user_id),
            "users.view",
        )
    return user


def _validate(changes: Mapping[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    errors: list[FieldError] = []
    for name, value in changes.items():
        if name not in EDITABLE_FIELDS:
            errors.append(
                FieldError(
                    field=f"body.{name}", code="read_only", message_key="errors.field.read_only"
                )
            )
        elif name == "time_zone" and value is not None and value not in available_timezones():
            errors.append(
                FieldError(
                    field="body.time_zone",
                    code="invalid_choice",
                    message_key="errors.field.invalid_choice",
                )
            )
        elif name == "ui_locale" and value is not None and value not in UI_LOCALES:
            errors.append(
                FieldError(
                    field="body.ui_locale",
                    code="invalid_choice",
                    message_key="errors.field.invalid_choice",
                )
            )
        elif name == "nav_layout" and value not in {layout.value for layout in NavLayout}:
            errors.append(
                FieldError(
                    field="body.nav_layout",
                    code="invalid_choice",
                    message_key="errors.field.invalid_choice",
                )
            )
        elif name == "form_density" and value not in {d.value for d in FormDensity}:
            errors.append(
                FieldError(
                    field="body.form_density",
                    code="invalid_choice",
                    message_key="errors.field.invalid_choice",
                )
            )
        elif name == "signature" and value is not None and len(value) > MAX_SIGNATURE_LENGTH:
            errors.append(
                FieldError(
                    field="body.signature",
                    code="value_too_long",
                    message_key="errors.field.value_too_long",
                    params={"max_length": MAX_SIGNATURE_LENGTH},
                )
            )
        else:
            clean[name] = value
    if errors:
        raise ValidationFailed(errors=errors)
    return clean


async def update_preferences(  # noqa: PLR0913 - the record, the version and the change, explicit
    session: AsyncSession,
    subject: Subject,
    user_id: uuid.UUID,
    *,
    expected_version: int,
    changes: Mapping[str, Any],
    source: Source = "api",
) -> User:
    """Change your own preferences if the record is still at `expected_version`.

    Each save is kept in the field history; a stale version gets a 409 saying who changed which
    fields since (WP-012 follow-up).
    """
    if user_id != subject.user_id:
        raise PermissionDenied(code="own_profile_only")
    require(
        authorize(subject, "profile.edit", USERS, RecordFacts(owner_ids=frozenset({user_id}))),
        "profile.edit",
    )
    clean = _validate(changes)
    current = await UserRepository(session).get(user_id)
    changed = sorted(name for name, value in clean.items() if getattr(current, name) != value)
    if not changed:
        if current.version != expected_version:
            raise await explain_user_conflict(
                session,
                Conflict(
                    code="version_conflict",
                    params={
                        "expected_version": expected_version,
                        "current_version": current.version,
                    },
                ),
                user_id,
            )
        return current  # nothing to change: no new version, no event
    before = {name: getattr(current, name) for name in changed}
    try:
        updated = await UserRepository(session).update(
            user_id, expected_version=expected_version, changes={n: clean[n] for n in changed}
        )
    except Conflict as error:
        raise await explain_user_conflict(session, error, user_id) from error
    await record_changes(
        session,
        record_type=USER_RECORD_TYPE,
        record_id=user_id,
        version=updated.version,
        kind="updated",
        changes=[Change(name, before[name], clean[name]) for name in changed],
        source=source,
    )
    await record_event(
        session,
        UserUpdated(user_id=user_id, changed_fields=changed),
        aggregate_id=user_id,
        aggregate_version=updated.version,
    )
    return updated


async def explain_user_conflict(
    session: AsyncSession, error: Conflict, user_id: uuid.UUID
) -> Conflict:
    """The 409 for a stale person record: who changed which fields since (WP-012)."""
    return await explain_conflict(
        session,
        error,
        record_type=USER_RECORD_TYPE,
        record_id=user_id,
        names=lambda ids: display_names(session, ids),
    )


async def user_names(session: AsyncSession, user_ids: Sequence[str]) -> dict[str, str]:
    """{user id: display name} for users of the session's tenant (unknown IDs left out).

    For other modules' messages and history ("changed by Aisha Tech"): names only, nothing else.
    """
    wanted: list[uuid.UUID] = []
    for raw in user_ids:
        try:
            wanted.append(uuid.UUID(str(raw)))
        except ValueError:
            continue
    if not wanted:
        return {}
    rows = await session.execute(select(User.id, User.display_name).where(User.id.in_(wanted)))
    return {str(row.id): row.display_name for row in rows}


async def user_contacts(
    session: AsyncSession, user_ids: Sequence[str]
) -> dict[str, tuple[str, str]]:
    """{user id: (display name, email)} for users of the session's tenant.

    Pickers and record pages tell two people with the same name apart by their email (Area 15
    lesson). Unknown IDs are left out.
    """
    wanted: list[uuid.UUID] = []
    for raw in user_ids:
        try:
            wanted.append(uuid.UUID(str(raw)))
        except ValueError:
            continue
    if not wanted:
        return {}
    rows = await session.execute(
        select(User.id, User.display_name, User.email).where(User.id.in_(wanted))
    )
    return {str(row.id): (row.display_name, row.email) for row in rows}


async def display_names(session: AsyncSession, user_ids: Sequence[str]) -> list[str]:
    """Display names in the given order (unknown IDs skipped)."""
    names = await user_names(session, user_ids)
    return [names[str(user_id)] for user_id in user_ids if str(user_id) in names]


# Every module's 409 names who saved the record since (QA WP-029 BUG-05).
register_people_names(display_names)


@dataclass(frozen=True)
class MailRecipient:
    """Who gets a system e-mail and in which language (WP-035 scheduled reports)."""

    name: str
    email: str
    language: Language


def _mail_language(code: str | None) -> Language:
    # Imports and Keycloak can bring regional codes ("ar-SA"): the language part decides.
    base = (code or "en").split("-")[0].lower()
    return "ar" if base == "ar" else "ur" if base == "ur" else "en"


async def mail_recipients(
    session: AsyncSession, user_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, MailRecipient]:
    """Active users of the session's tenant with an e-mail address, in one query.

    The language is the user's interface language, else their locale, else English. Inactive,
    deleted, unknown and address-less users are left out, so nobody gets mail they should not.
    """
    if not user_ids:
        return {}
    rows = await session.execute(
        select(User.id, User.display_name, User.email, User.ui_locale, User.locale).where(
            User.id.in_(list(user_ids)),
            User.status == "active",
            User.deleted_at.is_(None),
        )
    )
    found: dict[uuid.UUID, MailRecipient] = {}
    for row in rows:
        if not row.email:
            continue
        found[row.id] = MailRecipient(
            name=row.display_name,
            email=row.email,
            language=_mail_language(row.ui_locale or row.locale),
        )
    return found


@dataclass(frozen=True)
class NotifiablePerson:
    """Who gets a notification, in which language and zone (WP-023, REQ-INC-133)."""

    name: str
    email: str | None  # in-app notifications need no address
    language: Language | None  # None: they chose none; the site's default applies
    time_zone: str | None  # None: the site's or the tenant's zone


async def notifiable_people(
    session: AsyncSession, user_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, NotifiablePerson]:
    """Active users of the session's tenant, in one query; inactive and unknown are left out."""
    if not user_ids:
        return {}
    rows = await session.execute(
        select(
            User.id, User.display_name, User.email, User.ui_locale, User.locale, User.time_zone
        ).where(
            User.id.in_(list(user_ids)),
            User.status == "active",
            User.deleted_at.is_(None),
        )
    )
    return {
        row.id: NotifiablePerson(
            name=row.display_name,
            email=row.email or None,
            language=_mail_language(code) if (code := row.ui_locale or row.locale) else None,
            time_zone=row.time_zone,
        )
        for row in rows
    }
