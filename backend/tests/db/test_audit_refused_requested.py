"""A refused audited request names its target under `requested` (lane A's #612 nit; lane B).

A route fills its note from the request before its service runs; when the service refuses, the
error observer writes the refused entry with those IDs under `requested` (unverified: they came
from the request), never free text. A test route stands in for #612's delegation create.
"""

import uuid
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends

from app.core.authorization import require_signed_in
from app.core.errors import PermissionDenied
from app.modules.audit.service.recording import AuditNote, audited
from app.modules.identity_access import Subject
from tests.db.shared_world import MODULE_LOOP, module_world, shared_world
from tests.db.test_audit_api import by_action
from tests.db.test_incidents_api import World

pytestmark = [pytest.mark.db, MODULE_LOOP]

__all__ = ["module_world", "shared_world"]  # the fixtures, used by name

_PATH = f"/api/v1/_tests/refused-{uuid.uuid4().hex[:8]}"


def _add_route(world: World, target: uuid.UUID) -> None:
    router = APIRouter()

    @router.post(_PATH, status_code=204)
    async def refuse(
        note: Annotated[AuditNote, audited("asset.deleted", object_type="asset")],
        subject: Annotated[Subject, Depends(require_signed_in())],
    ) -> None:
        del subject
        note.details.update({"delegate_id": str(target), "reason": "free text, never logged"})
        raise PermissionDenied(code="permission_denied", params={"reason": "self_appointed"})

    world.app.include_router(router)


async def test_a_refused_request_names_its_target_under_requested(world: World) -> None:
    a = world.a
    target = uuid.uuid4()
    _add_route(world, target)
    refused = await world.call("POST", _PATH.removeprefix("/api/v1"), a, a.tech_a)
    assert refused.status_code == 403, refused.text
    found = [
        e
        for e in await by_action(world, a, "asset.deleted")
        if (e.get("details") or {}).get("requested", {}).get("delegate_id") == str(target)
    ]
    assert len(found) == 1, found
    details = found[0]["details"]
    assert details["status"] == 403
    assert details["requested"] == {"delegate_id": str(target)}
    assert "free text" not in str(details)
