"""The security overview's weak-choice flags (WP-057 S4d): recommendations, never enforced."""

import dataclasses
from typing import Any

from app.modules.identity_access.domain.security_overview import (
    Choices,
    Flag,
    SecurityArea,
    SecuritySeverity,
    flags,
)

SOUND = Choices(
    roles_without_mfa=0,
    admins_without_mfa=False,
    sso_required=False,
    password_min_length=12,
    password_breached_check=True,
    password_expiry_days=0,
    console_idle_seconds=3600,
    console_absolute_seconds=43200,
    console_network_rule=True,
    api_network_rule=True,
    allow_non_expiring_keys=False,
    key_max_lifetime_days=366,
    keys_out_of_policy=0,
    keys_unused=0,
    service_accounts_without_owner=0,
    sso_expiry_days_left=None,
    fields_not_sealed=0,
    failed_sign_ins=3,
    locked_sign_ins=0,
)


def _codes(c: Choices) -> list[str]:
    return [f.code for f in flags(c)]


def test_the_recommended_choices_raise_no_flag() -> None:
    assert flags(SOUND) == []


def test_each_weak_choice_raises_its_flag_and_clears_again() -> None:
    cases: dict[str, dict[str, Any]] = {
        "admins_without_mfa": {"admins_without_mfa": True},
        "roles_without_mfa": {"roles_without_mfa": 2},
        "password_short": {"password_min_length": 8},
        "password_breached_off": {"password_breached_check": False},
        "console_idle_long": {"console_idle_seconds": 4 * 3600},
        "console_session_long": {"console_absolute_seconds": 24 * 3600},
        "console_open_network": {"console_network_rule": False},
        "api_open_network": {"api_network_rule": False},
        "keys_never_expire": {"allow_non_expiring_keys": True},
        "keys_out_of_policy": {"keys_out_of_policy": 3},
        "keys_unused": {"keys_unused": 1},
        "service_accounts_without_owner": {"service_accounts_without_owner": 1},
        "fields_still_moving": {"fields_not_sealed": 1},
        "sign_ins_locked": {"locked_sign_ins": 2},
    }
    for code, change in cases.items():
        assert code in _codes(dataclasses.replace(SOUND, **change)), code
    assert flags(SOUND) == []  # back to the recommendations: every flag clears


def test_sso_expiry_is_flagged_at_30_and_7_days() -> None:
    def at(days: int | None) -> list[Flag]:
        return flags(dataclasses.replace(SOUND, sso_expiry_days_left=days))

    assert at(None) == []
    assert at(31) == []
    assert at(30) == [
        Flag("sso_credential_expires", SecurityArea.SIGN_IN, SecuritySeverity.MEDIUM, 30)
    ]
    assert at(7) == [
        Flag("sso_credential_expires_soon", SecurityArea.SIGN_IN, SecuritySeverity.HIGH, 7)
    ]
    assert at(-1) == [Flag("sso_credential_expired", SecurityArea.SIGN_IN, SecuritySeverity.HIGH)]


def test_password_flags_are_moot_when_sso_is_required() -> None:
    weak = dataclasses.replace(SOUND, password_min_length=6, password_breached_check=False)
    assert "password_short" in _codes(weak)
    assert _codes(dataclasses.replace(weak, sso_required=True)) == []


def test_expiry_without_a_breach_check_is_its_own_flag() -> None:
    weak = dataclasses.replace(SOUND, password_breached_check=False, password_expiry_days=90)
    assert "password_expiry_without_check" in _codes(weak)


def test_most_severe_first_then_the_tiles_order() -> None:
    many = dataclasses.replace(
        SOUND,
        keys_unused=1,
        admins_without_mfa=True,
        keys_out_of_policy=1,
        sso_expiry_days_left=3,
    )
    assert [(f.severity, f.code) for f in flags(many)] == [
        (SecuritySeverity.HIGH, "admins_without_mfa"),
        (SecuritySeverity.HIGH, "sso_credential_expires_soon"),
        (SecuritySeverity.MEDIUM, "keys_out_of_policy"),
        (SecuritySeverity.LOW, "keys_unused"),
    ]


def test_flags_hold_codes_and_numbers_only() -> None:
    """Lane B's condition 1: no names, e-mails or addresses."""
    for flag in flags(dataclasses.replace(SOUND, roles_without_mfa=2, keys_unused=5)):
        assert isinstance(flag.code, str)
        assert flag.count is None or isinstance(flag.count, int)


def test_a_stuck_support_removal_is_a_high_flag() -> None:
    """Lane B: a support account not confirmed gone a day after its grant ended is never silent."""
    found = flags(dataclasses.replace(SOUND, support_removals_stuck=2))
    stuck = [f for f in found if f.code == "support_removals_stuck"]
    assert [(f.area, f.severity, f.count) for f in stuck] == [
        (SecurityArea.VENDOR_SUPPORT, SecuritySeverity.HIGH, 2)
    ]
    assert not [f for f in flags(SOUND) if f.code == "support_removals_stuck"]
