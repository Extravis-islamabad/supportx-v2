"""Who may sign in how, pure (REQ-SEC-009, REQ-SEC-026; domain/sign_in_policy.py)."""

import pytest

from app.modules.identity_access.domain.sign_in import SignInMethod
from app.modules.identity_access.domain.sign_in_policy import (
    BREAK_GLASS_NEEDS_MFA,
    LAST_BREAK_GLASS_ADMIN,
    NO_BREAK_GLASS_ADMIN,
    SSO_REQUIRED,
    Person,
    SsoRequired,
    change_refusal,
    judge,
    requires_supportx_mfa,
)

TECH = Person(technician=True, break_glass=False, mfa_enrolled=True)
REQUESTER = Person(technician=False, break_glass=False, mfa_enrolled=False)
GLASS = Person(technician=True, break_glass=True, mfa_enrolled=True)
GLASS_NO_MFA = Person(technician=True, break_glass=True, mfa_enrolled=False)
PASSWORD, SSO = SignInMethod.PASSWORD, SignInMethod.SINGLE_SIGN_ON


@pytest.mark.parametrize(
    ("rule", "person", "method", "refusal", "break_glass"),
    [
        (SsoRequired.OFF, TECH, PASSWORD, None, False),
        (SsoRequired.TECHNICIANS, TECH, PASSWORD, SSO_REQUIRED, False),  # AC1
        (SsoRequired.TECHNICIANS, TECH, SSO, None, False),
        (SsoRequired.TECHNICIANS, REQUESTER, PASSWORD, None, False),  # requesters out of scope
        (SsoRequired.EVERYONE, REQUESTER, PASSWORD, SSO_REQUIRED, False),
        (SsoRequired.EVERYONE, TECH, SignInMethod.DIRECTORY, SSO_REQUIRED, False),
        (SsoRequired.EVERYONE, GLASS, PASSWORD, None, True),  # break-glass: let in, alerted
        (SsoRequired.EVERYONE, GLASS_NO_MFA, PASSWORD, BREAK_GLASS_NEEDS_MFA, False),
        (SsoRequired.EVERYONE, GLASS, SSO, None, False),  # by SSO it is an ordinary sign-in
    ],
)
def test_req_sec_009_who_may_sign_in_how(
    rule: SsoRequired,
    person: Person,
    method: SignInMethod,
    refusal: str | None,
    *,
    break_glass: bool,
) -> None:
    verdict = judge(rule, person, method)
    assert (verdict.refusal, verdict.break_glass) == (refusal, break_glass)


def test_req_sec_009_ac2_turning_it_on_or_removing_the_last_admin_needs_one() -> None:
    assert change_refusal(SsoRequired.OFF, 0, removing_admin=False) is None
    assert change_refusal(SsoRequired.EVERYONE, 0, removing_admin=False) == NO_BREAK_GLASS_ADMIN
    assert change_refusal(SsoRequired.EVERYONE, 0, removing_admin=True) == LAST_BREAK_GLASS_ADMIN
    assert change_refusal(SsoRequired.TECHNICIANS, 1, removing_admin=True) is None


def test_req_sec_026_the_providers_mfa_is_trusted_unless_also_required() -> None:
    assert requires_supportx_mfa(SSO, also_require_mfa=False) is False  # AC1
    assert requires_supportx_mfa(SSO, also_require_mfa=True) is True  # AC2
    assert requires_supportx_mfa(PASSWORD, also_require_mfa=False) is True
