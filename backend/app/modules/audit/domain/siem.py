r"""What a security monitoring system receives, and how it is framed (REQ-AUD-011, WP-057 S5a).

Pure. An audit entry is sent as its chain content (`entry_content`), never its personal values:
those live in `audit_personal` and stay there, as in the audit export (the coordinator's
condition 2). The salted commitments are left out too: a receiver can't use them.

- **JSON:** one object per entry, sorted keys, the kind (`audit` or `sign_in`) named.
- **CEF:** `CEF:0|Extravis|SupportX|<version>|<action>|<action>|<severity>|<extension>`, with
  the header and extension escaping of the CEF spec (`\\` and `|` in the header; `\\`, `=` and
  line breaks in values).
- **Syslog:** RFC 5424 lines (facility "security/authorization", 10), framed for TCP with
  RFC 6587 octet counting so a message with a line break stays one message.
"""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

VENDOR = "Extravis"
PRODUCT = "SupportX"
FACILITY = 10  # security/authorization messages (RFC 5424 §6.2.1)
APP_NAME = "supportx"
NIL = "-"
DESTINATIONS_MAX = 5  # per tenant
BATCH_MAX = 200  # entries sent per attempt

# Never sent: salted commitments to personal values a receiver can't check.
_LEFT_OUT = frozenset({"personal_commitments"})


class SiemKind(StrEnum):
    """How a destination is reached (`siem_destination_kind.<code>`)."""

    SYSLOG = "syslog"  # TCP with TLS, RFC 5424 framed by RFC 6587
    WEBHOOK = "webhook"  # HTTPS POST of a JSON batch, signed (app/shared/crypto/signing.py)


class SiemFormat(StrEnum):
    """What each entry looks like (`siem_format.<code>`); a webhook always sends JSON."""

    JSON = "json"
    CEF = "cef"


class SiemStream(StrEnum):
    """What a destination receives (`siem_stream.<code>`)."""

    AUDIT = "audit"
    SIGN_INS = "sign_ins"


def payload(kind: SiemStream, content: Mapping[str, Any]) -> dict[str, Any]:
    """The JSON object for one entry: its content and its kind, nothing personal."""
    sent = {k: v for k, v in content.items() if k not in _LEFT_OUT}
    return {"kind": kind.value, **sent}


def to_json(kind: SiemStream, content: Mapping[str, Any]) -> str:
    """One entry as compact JSON with sorted keys (the same bytes for the same entry)."""
    return json.dumps(payload(kind, content), sort_keys=True, separators=(",", ":"), default=str)


def _header(value: object) -> str:
    return (
        str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("\r", " ")
    )


def _value(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    return (
        text.replace("\\", "\\\\")
        .replace("=", "\\=")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _severity(content: Mapping[str, Any]) -> int:
    """0-10: a refusal or a failure stands out; a security category a little."""
    outcome = str(content.get("outcome") or "")
    if outcome in {"refused", "failed", "locked", "mfa_failed"}:
        return 7
    if str(content.get("category") or "") == "security":
        return 5
    return 3


# CEF extension keys (the dictionary's own names where one fits; cs1..cs6 with labels else).
_EXTENSION: tuple[tuple[str, str], ...] = (
    ("rt", "occurred_at"),
    ("outcome", "outcome"),
    ("suid", "actor_id"),
    ("cs1", "actor_type"),
    ("cs2", "object_type"),
    ("cs3", "object_id"),
    ("cs4", "module"),
    ("cs5", "category"),
    ("externalId", "id"),
    ("requestClientApplication", "client"),
)
_LABELS = {
    "cs1": "actorType",
    "cs2": "objectType",
    "cs3": "objectId",
    "cs4": "module",
    "cs5": "category",
    "cs6": "details",
}


def to_cef(kind: SiemStream, content: Mapping[str, Any], *, version: str) -> str:
    """One entry as a CEF line."""
    action = str(content.get("action") or kind.value)
    parts: list[str] = []
    for key, field in _EXTENSION:
        value = content.get(field)
        if value is None or value == "":
            continue
        parts.append(f"{key}={_value(value)}")
        if key in _LABELS:
            parts.append(f"{key}Label={_LABELS[key]}")
    details = content.get("details")
    if details:
        parts.append(f"cs6={_value(details)}")
        parts.append("cs6Label=details")
    parts.append(f"cat={_value(kind.value)}")
    head = "|".join(
        _header(x) for x in (VENDOR, PRODUCT, version, action, action, _severity(content))
    )
    return f"CEF:0|{head}|{' '.join(parts)}"


def _timestamp(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def syslog_line(message: str, *, hostname: str, at: datetime, severity: int = 6) -> str:
    """An RFC 5424 message (PRI = facility * 8 + severity; no structured data)."""
    pri = FACILITY * 8 + severity
    host = hostname.strip() or NIL
    return f"<{pri}>1 {_timestamp(at)} {host} {APP_NAME} {NIL} audit {NIL} {message}"


def frame(line: str) -> bytes:
    """RFC 6587 octet counting: `<length> <message>`, so a line break never splits it."""
    data = line.encode("utf-8")
    return str(len(data)).encode("ascii") + b" " + data


def body(kind: SiemStream, content: Mapping[str, Any], fmt: SiemFormat, *, version: str) -> str:
    """One entry in the destination's format."""
    return (
        to_cef(kind, content, version=version) if fmt is SiemFormat.CEF else to_json(kind, content)
    )
