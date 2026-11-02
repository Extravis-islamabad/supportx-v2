"""Directory sync rules that need no I/O (WP-040 session 2; REQ-INT-063, REQ-INT-064).

A Microsoft Graph user (from `/users/delta`) becomes what SupportX keeps about a person, by a
tenant-editable mapping (D-041). Nothing is guessed: a value that does not fit (too long, not an
email address, a department or site SupportX does not know) is skipped with a reason and counted,
never cut or invented (D-091). People the directory removes or disables are leavers: disabled,
never deleted (REQ-INT-064).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

# Graph sends at most this many per page; the sync asks for it (fewer calls, same throttling).
PAGE_SIZE = 999
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Same limits as the person record (identity_access.domain.people.LENGTHS): refused, never cut.
LENGTHS: dict[str, int] = {
    "first_name": 100,
    "last_name": 100,
    "display_name": 200,
    "email": 254,
    "employee_id": 50,
    "job_title": 200,
    "phone": 50,
    "mobile": 50,
}


class DirectorySource(StrEnum):
    """Which directory a synced person comes from (UserStatusChanged.source)."""

    ENTRA = "entra"
    LDAP = "ldap"


class SyncScope(StrEnum):
    """Everyone in the directory, or only members of chosen groups."""

    ALL_USERS = "all_users"
    GROUPS = "groups"


class EmailFrom(StrEnum):
    """Which Graph attribute is the person's address."""

    MAIL = "mail"  # falls back to the user principal name when the mailbox has none
    USER_PRINCIPAL_NAME = "user_principal_name"


class SkipReason(StrEnum):
    """Why a person or one of their values was not taken (labels `directory_skip.<code>`)."""

    NO_ADDRESS = "no_address"  # no usable email: they could never sign in
    GUEST = "guest"  # an external guest of the directory, not one of its people
    TOO_LONG = "too_long"
    NOT_AN_EMAIL = "not_an_email"
    UNKNOWN_DEPARTMENT = "unknown_department"
    UNKNOWN_SITE = "unknown_site"
    UNKNOWN_MANAGER = "unknown_manager"


@dataclass(frozen=True)
class AttributeMapping:
    """Where each person field comes from (Appendix A defaults; tenant-editable, D-041)."""

    email_from: EmailFrom = EmailFrom.MAIL
    department_from: str = "department"
    site_from: str = "officeLocation"
    include_guests: bool = False

    def graph_select(self) -> str:
        """The `$select` for `/users/delta`: only what the mapping reads (least data)."""
        wanted = {
            "id",
            "accountEnabled",
            "displayName",
            "givenName",
            "surname",
            "mail",
            "userPrincipalName",
            "userType",
            "jobTitle",
            "employeeId",
            "mobilePhone",
            "businessPhones",
            "manager",
            self.department_from,
            self.site_from,
        }
        return ",".join(sorted(wanted))


@dataclass(frozen=True)
class DirectoryPerson:
    """One person as the directory says they are now (values already checked).

    A delta page carries only what changed, so a field is in `values` (or `refs`) only when the
    page had it: an absent key leaves SupportX's value alone, a present `None` clears it.
    """

    external_id: str
    enabled: bool | None  # None: the page did not say
    values: Mapping[str, str | None]  # person fields: first_name, email, job_title, ...
    refs: Mapping[str, str | None]  # "department", "site" (a name or code), "manager" (an id)
    skipped: tuple[tuple[str, SkipReason], ...] = ()  # (field, reason)


@dataclass(frozen=True)
class DirectoryRemoval:
    """The directory removed this person (deleted, or out of the synced groups)."""

    external_id: str


@dataclass(frozen=True)
class PersonSkipped:
    """Not a person SupportX takes (counted, with the reason)."""

    external_id: str
    reason: SkipReason


Change = DirectoryPerson | DirectoryRemoval | PersonSkipped


def _text(item: Mapping[str, object], key: str) -> str | None:
    value = item.get(key)
    if not isinstance(value, str):
        return None
    return " ".join(value.split()) or None


_TEXT = (
    ("first_name", "givenName"),
    ("last_name", "surname"),
    ("display_name", "displayName"),
    ("job_title", "jobTitle"),
    ("employee_id", "employeeId"),
    ("mobile", "mobilePhone"),
)


def _address(item: Mapping[str, object], mapping: AttributeMapping) -> tuple[bool, str | None]:
    """(whether the page says anything about the address, the address)."""
    upn = _text(item, "userPrincipalName")
    if mapping.email_from is EmailFrom.USER_PRINCIPAL_NAME:
        return "userPrincipalName" in item, upn
    mail = _text(item, "mail")
    if mail is not None or "userPrincipalName" in item:
        return True, mail or upn
    return False, None  # mail cleared or absent, and no principal name to fall back on


def _manager(item: Mapping[str, object]) -> str | None:
    manager = item.get("manager")
    if isinstance(manager, Mapping):
        found = manager.get("id")
        return found if isinstance(found, str) and found else None
    return None


def _phone(item: Mapping[str, object]) -> str | None:
    phones = item.get("businessPhones")
    first = phones[0] if isinstance(phones, list) and phones else None
    return (" ".join(first.split()) or None) if isinstance(first, str) else None


@dataclass
class _Values:
    values: dict[str, str | None] = field(default_factory=dict)
    skipped: list[tuple[str, SkipReason]] = field(default_factory=list)

    def put(self, name: str, value: str | None) -> None:
        if value is not None and len(value) > LENGTHS[name]:
            self.skipped.append((name, SkipReason.TOO_LONG))
            return
        self.values[name] = value


def _is_guest(item: Mapping[str, object]) -> bool:
    return _text(item, "userType") == "Guest" or "#EXT#" in (_text(item, "userPrincipalName") or "")


def from_graph(item: Mapping[str, object], mapping: AttributeMapping) -> Change:
    """One `/users/delta` item: a person, a removal, or a skipped entry with its reason."""
    external_id = str(item.get("id") or "")
    if "@removed" in item:
        return DirectoryRemoval(external_id)
    if not mapping.include_guests and _is_guest(item):
        return PersonSkipped(external_id, SkipReason.GUEST)
    out = _Values()
    said, address = _address(item, mapping)
    if said:
        if address is None or not _EMAIL.match(address) or len(address) > LENGTHS["email"]:
            return PersonSkipped(external_id, SkipReason.NO_ADDRESS)
        out.put("email", address.lower())
    for name, key in _TEXT:
        if key in item:
            out.put(name, _text(item, key))
    if "businessPhones" in item:
        out.put("phone", _phone(item))
    enabled = item.get("accountEnabled")
    return DirectoryPerson(
        external_id=external_id,
        enabled=enabled if isinstance(enabled, bool) else None,
        values=out.values,
        refs=_refs(item, mapping),
        skipped=tuple(out.skipped),
    )


def _refs(item: Mapping[str, object], mapping: AttributeMapping) -> dict[str, str | None]:
    refs: dict[str, str | None] = {}
    for name, key in (("department", mapping.department_from), ("site", mapping.site_from)):
        if key in item:
            refs[name] = _text(item, key)
    if "manager" in item:
        refs["manager"] = _manager(item)
    return refs


def leaves(change: Change) -> bool:
    """Whether this change makes the person a leaver (disabled in SupportX, never deleted)."""
    return isinstance(change, DirectoryRemoval) or (
        isinstance(change, DirectoryPerson) and change.enabled is False
    )
