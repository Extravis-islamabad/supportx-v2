"""The password policy's rules and Keycloak string, pure (WP-039 session 2, REQ-SEC-005)."""

from dataclasses import replace

from app.modules.identity_access.domain import password_policy as rules


def test_the_defaults_are_appendix_a_with_the_breached_list() -> None:
    assert rules.to_keycloak(rules.PasswordPolicy()) == (
        "length(12) and maxLength(128) and upperCase(1) and lowerCase(1) and digits(1)"
        " and specialChars(1) and notUsername and notEmail and passwordHistory(5)"
        " and passwordBlacklist(supportx-breached.txt)"
    )


def test_switched_off_rules_are_left_out_and_expiry_added() -> None:
    policy = rules.PasswordPolicy(
        min_length=8,
        upper=False,
        lower=False,
        digits=False,
        special=False,
        history=0,
        expiry_days=90,
        breached_check=False,
    )
    assert rules.to_keycloak(policy) == (
        "length(8) and maxLength(128) and notUsername and notEmail"
        " and forceExpiredPasswordChange(90)"
    )


def test_values_out_of_range_are_named_at_their_fields_with_the_limits() -> None:
    assert rules.problems(rules.PasswordPolicy()) == []
    found = rules.problems(
        replace(rules.PasswordPolicy(), min_length=7, history=25, expiry_days=-1)
    )
    assert [(p.field, p.params) for p in found] == [
        ("password_min_length", {"min": 8, "max": 64}),
        ("password_history", {"min": 0, "max": 24}),
        ("password_expiry_days", {"min": 0, "max": 365}),
    ]
    assert {p.code for p in found} == {"password_policy_out_of_range"}
