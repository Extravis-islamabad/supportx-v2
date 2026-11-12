"""`unrestricted`: a grant over every record, so a just-saved record's scope check can be skipped.

Only scope "all" without an attribute condition counts (WP-049b, the asset import's per-row
scope check). No I/O.
"""

import uuid
from types import MappingProxyType

from app.modules.identity_access.domain.policy import Grant, Subject
from app.modules.identity_access.service.policy import unrestricted

MANAGE = "assets.manage"


def _subject(*grants: Grant) -> Subject:
    return Subject(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role_keys=frozenset({"technician"}),
        is_tenant_admin=False,
        grants=MappingProxyType({MANAGE: tuple(grants)} if grants else {}),
    )


def test_scope_all_without_a_condition_is_unrestricted() -> None:
    assert unrestricted(_subject(Grant("all")), MANAGE)
    assert unrestricted(_subject(Grant("site"), Grant("all")), MANAGE)  # any grant will do


def test_a_condition_a_narrower_scope_or_no_grant_is_not() -> None:
    assert not unrestricted(_subject(Grant("all", {"field": "site_id", "op": "eq"})), MANAGE)
    for scope in ("site", "group", "own"):
        assert not unrestricted(_subject(Grant(scope)), MANAGE)
    assert not unrestricted(_subject(), MANAGE)
    assert not unrestricted(_subject(Grant("all")), "assets.view")  # per permission
