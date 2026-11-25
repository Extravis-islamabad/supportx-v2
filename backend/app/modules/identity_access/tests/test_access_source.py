"""A session's access source and its compile's cache tag (WP-057 S5c-1b, D-188).

- The source comes only from what the sign-in stored: the verified broker claim and the
  break-glass mark (lane B's condition 3). A session from before S1b is a password sign-in.
- A password and an SSO session of the same person never share a compile; password and no
  sign-in compile the same, so they share one.
"""

import uuid

from app.core.tenancy import (
    ANY_SOURCE,
    NO_SIGN_IN,
    AccessSource,
    AccessSourceKind,
    TenantContext,
)
from app.modules.identity_access.service.auth import access_source_of
from app.modules.identity_access.service.policy import source_tag
from app.modules.identity_access.tests.test_domain import session as _session


def test_the_source_is_what_the_sign_in_stored() -> None:
    assert access_source_of(_session(identity_provider="sx_acme_1a2b")) == AccessSource(
        AccessSourceKind.SSO, "sx_acme_1a2b"
    )
    assert access_source_of(_session(identity_provider=None)) == AccessSource(
        AccessSourceKind.PASSWORD
    )
    # Before S1b there was no method stored: judged a password sign-in, the strict side.
    assert access_source_of(_session(sign_in_method=None, identity_provider=None)).kind is (
        AccessSourceKind.PASSWORD
    )


def test_break_glass_wins_over_a_stored_provider() -> None:
    session = _session(identity_provider="sx_acme_1a2b", break_glass=True)
    assert access_source_of(session) == AccessSource(AccessSourceKind.BREAK_GLASS)


def test_a_context_without_a_session_is_the_strict_side() -> None:
    assert TenantContext(uuid.uuid4()).access_source == NO_SIGN_IN
    assert TenantContext(uuid.uuid4(), uuid.uuid4()).access_source.kind is AccessSourceKind.NONE


def test_each_source_that_compiles_differently_has_its_own_tag() -> None:
    sso_a = source_tag(AccessSource(AccessSourceKind.SSO, "sx_a"))
    sso_b = source_tag(AccessSource(AccessSourceKind.SSO, "sx_b"))
    password = source_tag(AccessSource(AccessSourceKind.PASSWORD))
    glass = source_tag(AccessSource(AccessSourceKind.BREAK_GLASS))
    could_act = source_tag(ANY_SOURCE)
    assert len({sso_a, sso_b, password, glass, could_act}) == 5
    # Password and no sign-in admit the same (directory-managed access only): one compile.
    assert source_tag(NO_SIGN_IN) == password
