"""What a SIEM receives (REQ-AUD-011, WP-057 S5a): pure rules, and a CEF escaping fuzz."""

import json
import random
import re
import string
from datetime import UTC, datetime

from app.modules.audit.domain import siem

ENTRY = {
    "id": "01900000-0000-7000-8000-000000000001",
    "tenant_id": "01900000-0000-7000-8000-0000000000aa",
    "occurred_at": "2026-11-20T10:00:00.000000Z",
    "action": "support_grant.created",
    "category": "security",
    "module": "identity_access",
    "outcome": "done",
    "reason_code": None,
    "actor_type": "person",
    "actor_id": "01900000-0000-7000-8000-000000000101",
    "on_behalf_id": None,
    "object_type": "support_grant",
    "object_id": "01900000-0000-7000-8000-000000000201",
    "details": {"access": "view"},
    "client": "console",
    "request_id": "req-1",
    "change_id": None,
    "personal_commitments": {"01900000-0000-7000-8000-000000000101": "c0ffee"},
}


def test_json_is_the_chain_content_without_commitments_and_stable() -> None:
    sent = json.loads(siem.to_json(siem.SiemStream.AUDIT, ENTRY))
    assert sent["kind"] == "audit"
    assert sent["action"] == "support_grant.created"
    assert "personal_commitments" not in sent
    assert siem.to_json(siem.SiemStream.AUDIT, ENTRY) == siem.to_json(
        siem.SiemStream.AUDIT, dict(ENTRY)
    )


def test_cef_has_its_header_and_labelled_extension() -> None:
    line = siem.to_cef(siem.SiemStream.AUDIT, ENTRY, version="2.0")
    assert line.startswith(
        "CEF:0|Extravis|SupportX|2.0|support_grant.created|support_grant.created|5|"
    )
    assert "suid=01900000-0000-7000-8000-000000000101" in line
    assert "cs2=support_grant cs2Label=objectType" in line
    assert "personal_commitments" not in line
    assert "c0ffee" not in line
    refused = siem.to_cef(siem.SiemStream.SIGN_INS, {**ENTRY, "outcome": "refused"}, version="2.0")
    assert refused.split("|")[6] == "7"


def _unescaped(line: str) -> list[str]:
    """Split a CEF line's header on its unescaped pipes, as a SIEM parser does.

    A backslash escapes the next character, so `\\|` is an escaped backslash then a separator.
    """
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for char in line:
        if len(fields) == 7:
            current.append(char)  # the extension: pipes are plain text there
            continue
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    fields.append("".join(current))
    return fields


def _unescaped_equals(extension: str) -> list[int]:
    """Positions of the extension's unescaped "=" signs."""
    found: list[int] = []
    escaped = False
    for index, char in enumerate(extension):
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "=":
            found.append(index)
    return found


def test_cef_escaping_never_lets_a_value_break_the_line() -> None:
    """A fuzz: hostile action names and values keep 8 header fields and one line."""
    rng = random.Random(20261120)  # noqa: S311 - a repeatable fuzz, not a secret
    alphabet = string.printable + "|=\\\r\n"
    for _ in range(500):
        hostile = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        content = {**ENTRY, "action": hostile, "object_id": hostile, "details": {"x": hostile}}
        line = siem.to_cef(siem.SiemStream.AUDIT, content, version="2.0")
        assert "\n" not in line
        assert "\r" not in line
        assert len(_unescaped(line)) == 8
        extension = _unescaped(line)[7]
        # Every unescaped "=" in the extension follows a key (a value never makes one).
        for at in _unescaped_equals(extension):
            assert re.search(r"(^| )[A-Za-z0-9]+$", extension[:at]), extension


def test_syslog_lines_are_rfc5424_and_octet_framed() -> None:
    at = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    line = siem.syslog_line("hello\nworld", hostname="tenant.example", at=at, severity=5)
    assert line.startswith("<85>1 2026-11-20T10:00:00.000000Z tenant.example supportx - audit - ")
    framed = siem.frame(line)
    length, _, rest = framed.partition(b" ")
    assert int(length) == len(rest) == len(line.encode())
    assert siem.frame("é").startswith(b"2 ")  # bytes, not characters
