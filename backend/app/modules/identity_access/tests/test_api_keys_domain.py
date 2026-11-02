"""API keys, the pure parts (REQ-INT-019, 021; D-128)."""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.identity_access.domain import api_keys as keys

TENANT = uuid.UUID("01900000-0000-7000-8000-00000000de30")
KEY = uuid.UUID("01900000-0000-7000-8000-0000000000aa")
SERVER = b"s" * 32
NOW = datetime(2026, 11, 3, tzinfo=UTC)


def test_a_key_carries_its_tenant_and_id_and_parses_back() -> None:
    made = keys.make_key(TENANT, KEY)
    assert made.text.startswith("sxk_")
    assert made.last_four == made.text[-4:]
    parsed = keys.parse_key(made.text)
    assert parsed is not None
    assert (parsed.tenant_id, parsed.key_id) == (TENANT, KEY)
    # The published scanner pattern finds it inside other text (docs/api/keys.md).
    assert re.search(keys.SCANNER_REGEX, f"token={made.text};") is not None


def test_two_keys_never_share_a_secret() -> None:
    assert keys.make_key(TENANT, KEY).text != keys.make_key(TENANT, KEY).text


@pytest.mark.parametrize(
    "text",
    [
        "",
        "sxk_",
        "Bearer something",
        "sxk_0123_456_abc",
        "sxk_" + "u" * 26 + "_" + "0" * 26 + "_" + "a" * 43,
    ],
)
def test_anything_else_is_not_a_key(text: str) -> None:
    assert keys.parse_key(text) is None  # "u" is not Crockford base32


def test_the_hash_is_keyed_bound_to_the_key_id_and_compared_in_constant_time() -> None:
    made = keys.make_key(TENANT, KEY)
    parsed = keys.parse_key(made.text)
    assert parsed is not None
    stored = keys.secret_hash(SERVER, KEY, parsed.secret)
    assert keys.secret_matches(SERVER, KEY, parsed.secret, stored)
    assert not keys.secret_matches(b"o" * 32, KEY, parsed.secret, stored)  # another server key
    assert not keys.secret_matches(SERVER, uuid.uuid4(), parsed.secret, stored)  # another key
    assert not keys.secret_matches(SERVER, KEY, parsed.secret[:-1] + "x", stored)


def test_scopes_come_from_the_permission_catalogue() -> None:
    assert keys.scope_of("incidents.view") == "incidents:read"
    assert keys.scope_of("reports.export") == "reports:read"
    assert keys.scope_of("incidents.create") == "incidents:write"
    assert keys.scope_of("knowledge.edit_any") == "knowledge:write"
    assert keys.scopes_for(["incidents.view", "incidents.create", "knowledge.view"]) == [
        "incidents:read",
        "incidents:write",
        "knowledge:read",
        "knowledge:write",
    ]
    only_read = frozenset({"incidents:read"})
    assert keys.covered("incidents.view", only_read)
    assert not keys.covered("incidents.create", only_read)


def test_expiry_defaults_and_limits() -> None:
    assert keys.expiry_problem(None, NOW, allow_non_expiring=False) == "api_key_expiry_required"
    assert keys.expiry_problem(None, NOW, allow_non_expiring=True) is None
    assert keys.expiry_problem(NOW - timedelta(days=1), NOW, allow_non_expiring=True) == (
        "api_key_expiry_past"
    )
    assert keys.expiry_problem(NOW + timedelta(days=400), NOW, allow_non_expiring=True) == (
        "api_key_expiry_too_far"
    )
    assert keys.expiry_problem(NOW + keys.DEFAULT_LIFETIME, NOW, allow_non_expiring=False) is None


def test_the_ip_allowlist() -> None:
    assert keys.parse_allowlist(["10.0.0.0/8", " 203.0.113.7 "]) == ["10.0.0.0/8", "203.0.113.7/32"]
    assert keys.parse_allowlist(["not an address"]) is None
    assert keys.address_allowed("198.51.100.1", [])  # no list: any address
    assert keys.address_allowed("10.1.2.3", ["10.0.0.0/8"])
    assert not keys.address_allowed("192.168.1.1", ["10.0.0.0/8"])
    assert not keys.address_allowed(None, ["10.0.0.0/8"])
