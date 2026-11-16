"""Security notices to the person themselves (REQ-SEC-033; WP-057 S2b-1).

One notification source (record type "security"), through the one notification engine, in the
app and by e-mail, urgent and required. The person it is about is told (`the_person`), whoever made
the change (`notify_actor`: a person who changes their own password still hears of it). Locked,
so no admin can switch a notice off or redirect it either (#480; the admin may be the attacker).

A sign-in from a browser or device the person has not used before (S2b-1): its message names
the device and the approximate place, never the address, and links to their own sessions, where
"Sign out everywhere else" is. From Keycloak's user events (S2b-2, part 2): a lock-out, with the
earliest time the account opens again; a password change; an MFA method added or removed.
"""

import uuid
from datetime import datetime
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access.domain.place import Place
from app.modules.identity_access.events import AccountSecurityChanged, NewDeviceSignedIn
from app.modules.identity_access.infra.models import User
from app.modules.organization import site_names
from app.shared.events import EventEnvelope
from app.shared.labels import LANGUAGES, label
from app.shared.notifications.ports import (
    EventDefault,
    LabelRef,
    Localised,
    NotificationCategory,
    NotificationEvent,
    RecordAccess,
    RecordContext,
    Variable,
    VariableValue,
    register_record_source,
)

RECORD_TYPE = "security"
THE_PERSON = "the_person"
NEW_DEVICE = "security.new_device"
# AccountSecurityChanged's kinds, each its own notice (REQ-SEC-033 part 2).
ACCOUNT_KINDS = ("locked_out", "password_changed", "mfa_added", "mfa_removed")
CONSOLE_LINK = "/profile"  # My account: its sessions card
PORTAL_LINK = "/account"

_VARIABLES = (
    Variable("notice.device", "notification_variable.security.device"),
    Variable("notice.place", "notification_variable.security.place"),
    Variable("notice.when", "notification_variable.security.when"),
    Variable("notice.opens_at", "notification_variable.security.opens_at"),
    Variable("record.link", "notification_variable.record.link"),
    Variable("recipient.name", "notification_variable.recipient.name"),
)


def device_value(code: str | None) -> VariableValue:
    """The device in words in each language, as the UI's deviceText (Chrome on Windows)."""
    if code is None:
        return LabelRef("sign_in_device.unknown")
    browser, _, system = code.partition(":")
    return Localised(
        {
            language: label(
                "sign_in_device.on",
                language,
                browser=label(f"sign_in_device.browser.{browser or 'other'}", language),
                system=label(f"sign_in_device.system.{system or 'other'}", language),
            )
            for language in LANGUAGES
        }
    )


def place_value(stored: object, site_name: str | None = None) -> VariableValue:
    """The approximate place in words: the internal network, a mapped site, or a city.

    A mapped site is named as it is called now (`site_name`); a site gone since, or not found,
    says "a mapped site".
    """
    place = Place.from_dict(stored)
    if place is None:
        return LabelRef("sign_in_place.unknown")
    if place.kind == "internal":
        return LabelRef("sign_in_place.internal")
    if place.kind == "site":
        return site_name or LabelRef("sign_in_place.site_unknown")
    parts = [p for p in (place.city, place.country) if p]
    return ", ".join(parts) if parts else LabelRef("sign_in_place.unknown")


async def _site_name(session: AsyncSession, payload: dict[str, object]) -> str | None:
    """The mapped site's name now, when the notice's place is one (organization's lookup)."""
    place = Place.from_dict(payload.get("place"))
    if place is None or place.kind != "site" or place.site_id is None:
        return None
    return (await site_names(session, [place.site_id])).get(place.site_id)


def _moment(value: object) -> datetime | None:
    """A payload's ISO time, else None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class SecurityNotices:
    """The notification source of security notices to the person they are about."""

    record_type: ClassVar[str] = RECORD_TYPE
    channel_kind: ClassVar[str] = "users"
    events: ClassVar[tuple[NotificationEvent, ...]] = tuple(
        NotificationEvent(
            code,
            NotificationCategory.STATUS,
            EventDefault(enabled=True, recipients=(THE_PERSON,), notify_actor=True),
            required=True,  # people cannot switch it off
            locked=True,  # nor can an admin change or reset its rule (#480)
        )
        for code in (NEW_DEVICE, *(f"security.{kind}" for kind in ACCOUNT_KINDS))
    )
    recipient_kinds: ClassVar[tuple[str, ...]] = (THE_PERSON,)
    variables: ClassVar[tuple[Variable, ...]] = _VARIABLES
    conditions: ClassVar[tuple[str, ...]] = ()
    event_types: ClassVar[tuple[str, ...]] = (
        NewDeviceSignedIn.event_type,
        AccountSecurityChanged.event_type,
    )

    def events_for(self, envelope: EventEnvelope) -> tuple[str, ...]:
        """One notice per new-device sign-in, lock-out, or password or MFA change."""
        if envelope.event_type == NewDeviceSignedIn.event_type:
            return (NEW_DEVICE,)
        kind = envelope.payload.get("kind")
        if envelope.event_type == AccountSecurityChanged.event_type and kind in ACCOUNT_KINDS:
            return (f"security.{kind}",)
        return ()

    async def context(
        self, session: AsyncSession, event_code: str, envelope: EventEnvelope
    ) -> RecordContext | None:
        """The person, the device and the place (never the address)."""
        del event_code
        payload = envelope.payload
        user_id = uuid.UUID(str(payload["user_id"]))
        person = await session.get(User, user_id)
        if person is None:
            return None
        values: dict[str, VariableValue] = {
            "notice.device": device_value(payload.get("device")),
            "notice.place": place_value(payload.get("place"), await _site_name(session, payload)),
            # When it happened in Keycloak, not when the import read it.
            "notice.when": _moment(payload.get("occurred_at")) or envelope.occurred_at,
            "record.link": CONSOLE_LINK,
        }
        opens_at = _moment(payload.get("opens_at"))
        if opens_at is not None:
            values["notice.opens_at"] = opens_at
        return RecordContext(
            record_id=user_id,
            display_id=person.display_name,
            link=CONSOLE_LINK,
            public_link=PORTAL_LINK,
            variables=values,
            public_variables={**values, "record.link": PORTAL_LINK},
            relatives={THE_PERSON: frozenset({user_id})},
            conditions={},
            urgent=True,
        )

    async def access(
        self, session: AsyncSession, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> RecordAccess:
        """The person it is about only (lane A: never NONE for them, or the notice is dropped).

        A technician reads it in the console (FULL: its link is My account); anyone else in the
        portal (PUBLIC: its link is the portal's account page), where their sessions are.
        """
        if user_id != record_id:
            return RecordAccess.NONE
        person = await session.get(User, user_id)
        if person is not None and person.user_type == "technician":
            return RecordAccess.FULL
        return RecordAccess.PUBLIC


SOURCE = SecurityNotices()


def register() -> None:
    """Make security notices notify (idempotent; called when identity_access is imported)."""
    register_record_source(SOURCE)
