import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.identity_access.domain.identity import (
    ClaimsError,
    UserType,
    identity_from,
    memberships_from,
    safe_return_to,
    validate_claims,
)
from app.modules.identity_access.domain.session import ExpiryReason, Session, TenantChoice

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
TENANT = uuid.UUID("01900000-0000-7000-8000-00000000de30")


def claims(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "iss": "https://id/realms/supportx",
        "aud": "supportx-console",
        "sub": "user-1",
        "exp": int(NOW.timestamp()) + 300,
        "iat": int(NOW.timestamp()),
        "nonce": "n-1",
    }
    return {**base, **overrides}


def check(c: dict[str, object], nonce: str | None = "n-1") -> None:
    validate_claims(
        c, issuer="https://id/realms/supportx", client_id="supportx-console", nonce=nonce, now=NOW
    )


def test_valid_claims_pass() -> None:
    check(claims())
    check(claims(aud=["supportx-console", "account"], azp="supportx-console"))
    check(claims(nonce="anything"), nonce=None)  # refreshed tokens carry no fresh nonce


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"iss": "https://evil/realms/supportx"}, "issuer"),
        ({"aud": "supportx-portal"}, "audience"),
        ({"aud": ["supportx-console", "x"], "azp": "x"}, "authorized party"),
        ({"exp": int(NOW.timestamp()) - 120}, "expired"),
        ({"iat": int(NOW.timestamp()) + 600}, "future"),
        ({"nonce": "replayed"}, "nonce"),
        ({"sub": ""}, "subject"),
    ],
)
def test_bad_claims_are_rejected(override: dict[str, object], reason: str) -> None:
    with pytest.raises(ClaimsError, match=reason):
        check(claims(**override))


def test_memberships_skip_malformed_entries_and_sort_by_alias() -> None:
    raw = {
        "supportx_organizations": {
            "zeta": {"tenant_id": [str(TENANT)]},
            "alpha": {"tenant_id": ["01900000-0000-7000-8000-00000000a7e2"]},
            "no-attr": {"id": "x"},
            "two-values": {"tenant_id": ["a", "b"]},
            "not-uuid": {"tenant_id": ["acme"]},
            "string": "oops",
        }
    }
    memberships = memberships_from(raw)
    assert [m.alias for m in memberships] == ["alpha", "zeta"]
    assert memberships[1].tenant_id == TENANT
    assert memberships_from({}) == ()
    assert memberships_from({"supportx_organizations": ["demo"]}) == ()


def test_identity_normalises_profile_and_roles() -> None:
    identity = identity_from(
        {
            "sub": "s",
            "email": " Tech@Demo.Test ",
            "name": "Tariq",
            "locale": "ar",
            "supportx_roles": ["technician", "offline_access", "uma_authorization"],
            "sid": "kc-1",
        }
    )
    assert identity.email == "tech@demo.test"
    assert identity.locale == "ar"
    assert identity.roles == ("technician",)
    assert identity.user_type is UserType.TECHNICIAN
    assert identity.keycloak_session_id == "kc-1"
    requester = identity_from(
        {"sub": "s", "email": "u@x.test", "locale": "fr", "supportx_roles": ["requester"]}
    )
    assert requester.user_type is UserType.REQUESTER
    assert requester.locale == "en"  # unsupported locale falls back
    assert requester.display_name == "u@x.test"


@pytest.mark.parametrize(
    "value",
    [
        "/tickets",
        "/tickets?id=7&tab=notes",
        "/a/b#frag",
        "/%E2%9C%93",
    ],
)
def test_safe_return_to_keeps_relative_paths(value: str) -> None:
    assert safe_return_to(value) == value


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "https://evil.test/",
        "//evil.test/x",
        "/\\evil.test",
        "\\\\evil.test",
        "/%2F%2Fevil.test",
        "/%5Cevil.test",
        "javascript:alert(1)",
        "tickets",
        "/x\r\nSet-Cookie: a=b",
        "/x%0d%0aSet-Cookie:a=b",
        "/x y",
    ],
)
def test_safe_return_to_blocks_open_redirects(value: str | None) -> None:
    assert safe_return_to(value) == "/"


def session(**overrides: object) -> Session:
    base: dict[str, object] = {
        "subject": "s",
        "user_id": str(uuid.uuid4()),
        "tenant_id": str(TENANT),
        "tenant_name": "Demo",
        "tenants": [TenantChoice(str(TENANT), "Demo")],
        "email": "e",
        "display_name": "n",
        "locale": "en",
        "user_type": "technician",
        "roles": ["technician"],
        "client": "console",
        "csrf_token": "c",
        "created_at": NOW,
        "last_seen_at": NOW,
        "access_expires_at": NOW + timedelta(minutes=5),
        "access_token": "a",
        "refresh_token": "r",
        "id_token": "i",
    }
    return Session(**{**base, **overrides})  # type: ignore[arg-type]  # test builder


def test_session_expiry_rules() -> None:
    idle, absolute = timedelta(minutes=30), timedelta(hours=12)
    s = session()
    assert s.expiry(NOW + timedelta(minutes=29), idle=idle, absolute=absolute) is None
    assert s.expiry(NOW + timedelta(minutes=30), idle=idle, absolute=absolute) is ExpiryReason.IDLE
    busy = s.touched(NOW + timedelta(hours=11, minutes=59))
    assert (
        busy.expiry(NOW + timedelta(hours=12), idle=idle, absolute=absolute)
        is ExpiryReason.ABSOLUTE
    )
    assert s.ttl(NOW, idle=idle, absolute=absolute) == idle
    assert busy.ttl(
        NOW + timedelta(hours=11, minutes=59), idle=idle, absolute=absolute
    ) == timedelta(minutes=1)


def test_session_refresh_window_and_round_trip() -> None:
    s = session()
    assert not s.needs_refresh(NOW)
    assert s.needs_refresh(NOW + timedelta(minutes=4, seconds=31))
    assert Session.from_dict(s.to_dict()) == s
    for token_field in ("access_token", "refresh_token", "id_token"):
        assert token_field not in repr(s)  # tokens never end up in logs via repr
