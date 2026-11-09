"""Dev-only quick sign-in's pure rules (D-151)."""

from datetime import UTC, datetime

import pytest

from app.modules.identity_access.domain.quick_sign_in import (
    PERSONAS,
    candidate_steps,
    is_local,
    persona,
    refusal,
    time_step,
    totp,
    totp_value,
)


def test_totp_matches_rfc_6238() -> None:
    # RFC 6238 Appendix B, SHA-1, secret "12345678901234567890", T=59 s: 94287082 (8 digits).
    assert totp("12345678901234567890", time_step(datetime.fromtimestamp(59, UTC))) == "287082"


def test_each_persona_has_its_own_secret_from_the_key() -> None:
    key = b"k" * 32
    values = {totp_value(key, p.email) for p in PERSONAS}
    assert len(values) == len(PERSONAS)
    assert totp_value(key, "Admin@Showcase.test") == totp_value(key, "admin@showcase.test")
    assert totp_value(b"other" * 8, "admin@showcase.test") != totp_value(key, "admin@showcase.test")


def test_one_persona_is_left_to_set_up_two_step_sign_in() -> None:
    assert [p.code for p in PERSONAS if not p.enrolled] == ["new_starter"]
    assert {p.code for p in PERSONAS} >= {"admin", "technician", "lead", "approver", "requester"}
    assert persona("nobody") is None


def test_a_second_sign_in_in_the_same_window_takes_the_next_step() -> None:
    assert candidate_steps(100) == (100, 101)


@pytest.mark.parametrize(
    ("error", "description", "reason"),
    [
        ("invalid_grant", "Account is not fully set up", "mfa_setup_required"),
        ("invalid_grant", "Account temporarily disabled", "account_locked"),
        ("invalid_grant", "Invalid user credentials", "credentials_refused"),
        ("unauthorized_client", "Client not allowed for direct access grants", "grant_not_allowed"),
        ("invalid_request", None, "keycloak_refused"),
    ],
)
def test_keycloak_refusals_become_reason_codes(
    error: str, description: str | None, reason: str
) -> None:
    assert refusal(error, description) == reason


@pytest.mark.parametrize(
    ("client", "host", "forwarded", "local"),
    [
        ("127.0.0.1", "localhost:5173", [], True),
        ("::1", "[::1]:8000", [], True),
        ("127.0.0.1", "127.0.0.1:8000", ["127.0.0.1"], True),
        ("10.0.0.5", "localhost:5173", [], False),  # not loopback
        ("127.0.0.1", "showcase.supportx.example", [], False),  # a real host name
        ("127.0.0.1", "localhost.evil.example", [], False),
        ("127.0.0.1", "localhost:5173", ["203.0.113.9"], False),  # forwarded from outside
        ("127.0.0.1", "localhost:5173", ['for="198.51.100.2";proto=http'], False),
        (None, "localhost", [], False),
    ],
)
def test_only_loopback_with_a_localhost_host(
    client: str | None, host: str, forwarded: list[str], local: bool
) -> None:
    assert is_local(client, host, forwarded) is local


def test_a_tunnel_naming_another_host_is_not_local() -> None:
    assert is_local("127.0.0.1", "localhost:5173", [], ["localhost:5173"]) is True
    assert is_local("127.0.0.1", "localhost:5173", [], ["abc.ngrok.example"]) is False
