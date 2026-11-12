"""The linked records panel against a fake work-items port (WP-049b s4a; REQ-AST-044, D-158).

No I/O: the asset check is replaced, and the port is a fake with lane A's agreed signatures that
keeps records some viewers may not see. D-158: a record the viewer may not see is neither counted
nor listed.
"""

import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.modules.assets import LinkedRecord, register_linked_records, unregister_linked_records
from app.modules.assets.service import linked
from app.modules.identity_access import Subject

ASSET = uuid.uuid4()
SESSION: Any = object()  # never used: the fake port and the replaced asset check take no I/O


@dataclass(frozen=True)
class Viewer:
    """Stands in for a Subject: the fake port only reads who it is."""

    user_id: uuid.UUID


ALICE, BOB = Viewer(uuid.uuid4()), Viewer(uuid.uuid4())


def _record(kind: str, display_id: str, *, worked: bool) -> LinkedRecord:
    return LinkedRecord(
        id=uuid.uuid4(), kind=kind, display_id=display_id, subject=display_id,
        status="open" if worked else "closed", still_worked=worked, updated_at=datetime.now(UTC),
    )  # fmt: skip


INC_OPEN = _record("incident", "INC-1", worked=True)
INC_CLOSED = _record("incident", "INC-2", worked=False)
INC_HIDDEN = _record("incident", "INC-3", worked=True)  # Bob may not see it
CHG_HIDDEN = _record("change", "CHG-1", worked=True)  # nor this one


class FakePort:
    """Lane A's port, exactly as agreed: visible records only, for every call."""

    def __init__(self) -> None:
        self.records = [INC_OPEN, INC_CLOSED, INC_HIDDEN, CHG_HIDDEN]
        self.hidden_from = {BOB.user_id: {INC_HIDDEN.id, CHG_HIDDEN.id}}
        self.limits: list[int] = []

    def _visible(self, subject: Subject, asset_id: uuid.UUID) -> list[LinkedRecord]:
        assert asset_id == ASSET
        hidden = self.hidden_from.get(subject.user_id, set())
        return [r for r in self.records if r.id not in hidden]

    async def linked_counts(
        self, session: AsyncSession, subject: Subject, asset_id: uuid.UUID
    ) -> Mapping[str, tuple[int, int]]:
        del session
        counts: dict[str, tuple[int, int]] = {}
        for r in self._visible(subject, asset_id):
            worked, total = counts.get(r.kind, (0, 0))
            counts[r.kind] = (worked + r.still_worked, total + 1)
        return counts

    async def linked_page(
        self,
        session: AsyncSession,
        subject: Subject,
        asset_id: uuid.UUID,
        kind: str,
        *,
        cursor: str | None = None,
        limit: int = 25,
    ) -> tuple[Sequence[LinkedRecord], str | None]:
        del session, cursor
        self.limits.append(limit)
        return [r for r in self._visible(subject, asset_id) if r.kind == kind][:limit], None

    async def asset_ids_of(self, session: AsyncSession, work_item_id: uuid.UUID) -> list[uuid.UUID]:
        del session
        return [ASSET] if any(r.id == work_item_id for r in self.records) else []

    async def repoint_links(
        self,
        session: AsyncSession,
        from_asset_id: uuid.UUID,
        to_asset_id: uuid.UUID,
        *,
        from_label: str,
        to_label: str,
        source: str,
    ) -> int:
        del session, from_asset_id, to_asset_id, from_label, to_label, source
        return 0


@pytest.fixture(autouse=True)
def _no_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    async def visible(session: object, subject: object, asset_id: uuid.UUID) -> None:
        del session, subject
        if asset_id != ASSET:
            raise NotFound(code="asset_not_found")

    monkeypatch.setattr(linked, "get_asset", visible)
    registered = linked.linked_port()  # work items' own, once imported: put back afterwards
    unregister_linked_records()
    yield
    unregister_linked_records()
    if registered is not None:
        register_linked_records(registered)


def _as_subject(viewer: Viewer) -> Any:  # noqa: ANN401 - a stand-in for a Subject
    return viewer


async def test_without_a_port_the_panel_is_not_available() -> None:
    summary = await linked.linked_summary(SESSION, _as_subject(ALICE), ASSET)
    assert (summary.available, summary.kinds) == (False, [])
    with pytest.raises(NotFound) as refused:
        await linked.linked_page(SESSION, _as_subject(ALICE), ASSET, "incident")
    assert refused.value.instance_code == "linked_records_not_available"
    assert await linked.assets_of_work_item(SESSION, INC_OPEN.id) == []


async def test_with_a_port_the_counters_and_pages_come_from_it() -> None:
    port = FakePort()
    register_linked_records(port)
    summary = await linked.linked_summary(SESSION, _as_subject(ALICE), ASSET)
    assert summary.available
    assert [(k.kind, k.still_worked, k.total) for k in summary.kinds] == [
        ("change", 1, 1),
        ("incident", 2, 3),
    ]
    rows, cursor = await linked.linked_page(
        SESSION, _as_subject(ALICE), ASSET, "incident", limit=500
    )
    assert {r.display_id for r in rows} == {"INC-1", "INC-2", "INC-3"}
    assert cursor is None
    assert port.limits == [linked.PAGE_MAX]  # capped at 100
    assert await linked.assets_of_work_item(SESSION, INC_OPEN.id) == [ASSET]


async def test_d158_a_record_the_viewer_may_not_see_is_neither_counted_nor_listed() -> None:
    register_linked_records(FakePort())
    summary = await linked.linked_summary(SESSION, _as_subject(BOB), ASSET)
    # Bob sees two incidents (one still worked) and no change: CHG-1 leaves no counter at all.
    assert [(k.kind, k.still_worked, k.total) for k in summary.kinds] == [("incident", 1, 2)]
    rows, _ = await linked.linked_page(SESSION, _as_subject(BOB), ASSET, "incident")
    assert {r.display_id for r in rows} == {"INC-1", "INC-2"}
    changes, _ = await linked.linked_page(SESSION, _as_subject(BOB), ASSET, "change")
    assert list(changes) == []


async def test_an_asset_the_caller_may_not_see_is_never_counted() -> None:
    register_linked_records(FakePort())
    with pytest.raises(NotFound):
        await linked.linked_summary(SESSION, _as_subject(ALICE), uuid.uuid4())
