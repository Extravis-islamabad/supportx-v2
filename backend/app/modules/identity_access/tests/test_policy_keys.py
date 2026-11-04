"""An API key's narrowed subject and the refusal it gets (REQ-INT-021 AC1, D-128). No I/O."""

import uuid
from types import MappingProxyType

import pytest

from app.core.errors import PermissionDenied
from app.modules.identity_access.domain.policy import Grant, Subject
from app.modules.identity_access.service.policy import PolicyService, for_key

ALL = (Grant(scope="all"),)


def _owner(*permissions: str) -> Subject:
    return Subject(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role_keys=frozenset({"technician"}),
        is_tenant_admin=False,
        grants=MappingProxyType(dict.fromkeys(permissions, ALL)),
    )


def _refusal(subject: Subject, permissions: list[str]) -> PermissionDenied:
    # require reads only its arguments, so the service's collaborators are not needed here.
    service = object.__new__(PolicyService)
    with pytest.raises(PermissionDenied) as raised:
        service.require(subject, permissions)
    return raised.value


def test_a_key_keeps_only_what_its_scopes_cover() -> None:
    key = for_key(_owner("users.view", "users.manage"), frozenset({"users:read"}))
    assert key.holds("users.view")
    assert not key.holds("users.manage")


def test_the_refusal_names_a_scope_the_key_lacks_not_the_first_permission() -> None:
    # The owner holds incidents.update, not users.view; the key covers users:read only. Of the
    # two permissions either of which would do, only incidents.update is beyond the key.
    key = for_key(_owner("incidents.update"), frozenset({"users:read"}))
    refusal = _refusal(key, ["users.view", "incidents.update"])
    assert refusal.instance_code == "api_scope_missing"
    assert refusal.params == {"scope": "incidents:write"}


def test_what_the_owner_lacks_is_a_plain_refusal() -> None:
    key = for_key(_owner(), frozenset({"users:read"}))
    assert _refusal(key, ["users.view"]).instance_code == "permission_denied"
