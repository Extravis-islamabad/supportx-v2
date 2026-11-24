"""Vendor support never records a CI downtime, even on a grant that edits CIs (D-173; S5b).

A hand-recorded downtime is an operational write outside desk configuration, so
`cmdb.record_downtime` is `never` for support (lane C's check on WP-053 S5b): a session on a
`view_and_change` grant holds `cmdb.edit`, yet recording a downtime is refused (403), and the
route's own permission gate refuses it the same way.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.core.errors import PermissionDenied
from app.core.tenancy import TenantContext
from app.modules.cmdb.service import downtimes
from app.modules.cmdb.service.catalogue import EDIT, RECORD_DOWNTIME
from app.modules.identity_access.domain import support_access
from tests.db.test_identity_api import World, world  # noqa: F401 - the fixture, reused
from tests.db.test_support_access_compile import _compiled, _support_user

pytestmark = pytest.mark.db


async def test_a_change_grant_edits_cis_but_never_records_their_downtimes(
    world: World,  # noqa: F811 - the reused fixture
) -> None:
    decided = support_access.SUPPORT_ACCESS[RECORD_DOWNTIME]
    assert isinstance(decided, support_access.Never)  # the decision itself
    assert decided.reason == "not_desk"
    _, user_id = await _support_user(
        world, access="view_and_change", change_reason="Fix the CMDB sync rule on CI-7"
    )
    subject = await _compiled(world, user_id)
    assert subject.support_grant_id is not None
    assert EDIT in subject.grants  # the grant does reach CI edits ...
    assert RECORD_DOWNTIME not in subject.grants  # ... and never downtimes
    async with world.app.state.db.tenant_session(TenantContext(world.a.tenant)) as session:
        with pytest.raises(PermissionDenied):
            await downtimes.record_manual(
                session,
                subject,
                uuid.uuid4(),  # refused before any CI is looked at
                starts_at=datetime.now(UTC),
                ends_at=None,
                kind=None,
                description=None,
                source="api",
            )
