"""The connector catalogue without I/O (WP-040; REQ-INT-001 AC2, REQ-INT-013)."""

import uuid
from collections.abc import Iterator, Sequence
from types import MappingProxyType
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity_access import Subject
from app.modules.integrations.domain.mailboxes import connector_status
from app.modules.integrations.service import catalogue
from app.shared.connectors.ports import (
    ConnectorCategory,
    ConnectorInstance,
    ConnectorKind,
    ConnectorStatus,
    register_connector,
    registered_connectors,
    unregister_connector,
)

SESSION = cast("AsyncSession", object())  # the fake sources never touch it
TENANT = uuid.uuid4()


class FakeSource:
    def __init__(self) -> None:
        self.asked = 0

    async def instances(self, session: AsyncSession) -> Sequence[ConnectorInstance]:
        del session
        self.asked += 1
        return [ConnectorInstance(uuid.uuid4(), "probe", ConnectorStatus.ACTIVE)]


def subject(*permissions: str) -> Subject:
    return Subject(
        tenant_id=TENANT,
        user_id=uuid.uuid4(),
        role_keys=frozenset({"technician"}),
        is_tenant_admin=False,
        # Route-level checks look at the keys only; scopes do not matter for set-up rights.
        grants=MappingProxyType(dict.fromkeys(permissions, ())),
    )


@pytest.fixture
def kinds(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, FakeSource]]:
    """Two test kinds, one outside the edition; the real registry is saved and restored."""
    saved = registered_connectors()
    for registered in saved:
        unregister_connector(registered.kind.code)
    sources = {"probe_in": FakeSource(), "probe_out": FakeSource()}
    register_connector(
        ConnectorKind("probe_out", ConnectorCategory.MONITORING, "/x", "x_reason", feature="paid"),
        sources["probe_out"],
    )
    register_connector(
        ConnectorKind("probe_in", ConnectorCategory.COLLABORATION, "/y", "y_reason"),
        sources["probe_in"],
    )

    async def has_feature(tenant_id: uuid.UUID, feature: str) -> bool:
        assert tenant_id == TENANT
        return feature != "paid"

    monkeypatch.setattr(catalogue, "has_feature", has_feature)
    yield sources
    for code in sources:
        unregister_connector(code)
    for registered in saved:
        register_connector(registered.kind, registered.source)


async def test_a_kind_outside_the_edition_is_shown_disabled_with_nothing_read(
    kinds: dict[str, FakeSource],
) -> None:
    entries = await catalogue.catalogue(SESSION, subject("integrations.manage_monitoring"))
    by_code = {e.kind.code: e for e in entries}
    outside = by_code["probe_out"]
    assert (outside.available, outside.can_manage) == (False, False)
    assert outside.manage_reason == "not_in_edition"  # even with the set-up permission
    assert outside.instances == ()
    assert kinds["probe_out"].asked == 0


async def test_set_up_rights_are_per_category(kinds: dict[str, FakeSource]) -> None:
    del kinds
    holder = subject("integrations.manage_collaboration")
    entries = {e.kind.code: e for e in await catalogue.catalogue(SESSION, holder)}
    assert (entries["probe_in"].can_manage, entries["probe_in"].manage_reason) == (True, None)
    other = {e.kind.code: e for e in await catalogue.catalogue(SESSION, subject())}
    assert other["probe_in"].manage_reason == "no_permission"
    assert [i.name for i in other["probe_in"].instances] == ["probe"]  # read-only, still listed


def test_kinds_come_in_category_order(kinds: dict[str, FakeSource]) -> None:
    del kinds
    assert [r.kind.code for r in registered_connectors()] == ["probe_in", "probe_out"]


def test_email_keeps_the_mailbox_permission_until_it_moves() -> None:
    assert catalogue.manage_permission(ConnectorCategory.EMAIL) == "mailboxes.manage"
    assert catalogue.manage_permission(ConnectorCategory.IDENTITY) == "integrations.manage_identity"


@pytest.mark.parametrize(
    ("state", "enabled", "status"),
    [
        ("not_set_up", True, ConnectorStatus.NOT_SET_UP),
        ("working", True, ConnectorStatus.ACTIVE),
        ("failing", True, ConnectorStatus.FAILED),
        ("failing", False, ConnectorStatus.PAUSED),
        ("working", False, ConnectorStatus.PAUSED),
    ],
)
def test_a_mailbox_state_maps_to_a_catalogue_status(
    state: str, enabled: bool, status: ConnectorStatus
) -> None:
    assert connector_status(state, enabled=enabled) == status
