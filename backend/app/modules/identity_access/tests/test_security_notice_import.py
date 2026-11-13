"""Which Keycloak user events tell the person, and when a lock-out ends (REQ-SEC-033 part 2)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.identity_access.domain.security_notice_import import (
    LOCKOUT,
    NoticeKind,
    kind_of,
    lockout_quiet,
)

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("event_type", "credential", "kind"),
    [
        ("USER_DISABLED_BY_TEMPORARY_LOCKOUT", None, NoticeKind.LOCKED_OUT),
        ("UPDATE_CREDENTIAL", "password", NoticeKind.PASSWORD_CHANGED),
        ("UPDATE_CREDENTIAL", "otp", NoticeKind.MFA_ADDED),
        ("UPDATE_CREDENTIAL", "webauthn", NoticeKind.MFA_ADDED),
        ("UPDATE_CREDENTIAL", "recovery-authn-codes", NoticeKind.MFA_ADDED),
        ("REMOVE_CREDENTIAL", "otp", NoticeKind.MFA_REMOVED),
        ("REMOVE_CREDENTIAL", "password", None),  # never a notice of its own
        ("UPDATE_CREDENTIAL", "something-new", None),
        ("UPDATE_CREDENTIAL", None, None),
        ("UPDATE_PASSWORD", "password", None),  # deprecated twin: never read, never twice
        ("LOGIN_ERROR", None, None),
    ],
)
def test_kind_of(event_type: str, credential: str | None, kind: NoticeKind | None) -> None:
    assert kind_of(event_type, credential) is kind


def test_a_first_lock_out_opens_after_the_increment() -> None:
    assert LOCKOUT.opens_at(NOW, []) == NOW + timedelta(minutes=15)


def test_each_lock_out_inside_the_window_waits_longer_up_to_the_cap() -> None:
    earlier = [NOW - timedelta(hours=1), NOW - timedelta(minutes=20)]
    assert LOCKOUT.opens_at(NOW, earlier) == NOW + timedelta(minutes=45)
    many = [NOW - timedelta(minutes=m) for m in (10, 20, 30, 40, 50)]
    assert LOCKOUT.opens_at(NOW, many) == NOW + timedelta(hours=1)  # the cap


def test_lock_outs_outside_the_window_or_later_do_not_count() -> None:
    old = [NOW - timedelta(hours=13), NOW + timedelta(minutes=1)]
    assert LOCKOUT.opens_at(NOW, old) == NOW + timedelta(minutes=15)


def test_the_realm_fields_are_the_lockout_policy() -> None:
    assert LOCKOUT.realm() == {
        "bruteForceProtected": True,
        "bruteForceStrategy": "LINEAR",
        "failureFactor": 5,
        "waitIncrementSeconds": 900,
        "maxFailureWaitSeconds": 3600,
        "maxDeltaTimeSeconds": 43200,
    }


def test_at_most_one_lock_out_notice_an_hour() -> None:
    assert not lockout_quiet(NOW, None)
    assert lockout_quiet(NOW, NOW - timedelta(minutes=15))
    assert not lockout_quiet(NOW, NOW - timedelta(hours=1))
