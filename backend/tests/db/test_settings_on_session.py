"""A session carries its process's Settings (lane B, cfb44245).

Whether a reply waits for mail or is queued follows the app or worker it is saved in, never
the developer's backend/.env.
"""

import pytest

from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.modules.work_items.service.conversations import email_channel_configured
from tests.db import test_incidents_api
from tests.db.test_incidents_api import World
from tests.db.test_notifications_api import MAIL, NO_MAIL

pytestmark = [pytest.mark.db]
world = test_incidents_api.world  # the incident world fixture, reused


async def test_whether_mail_is_set_up_follows_the_running_process(world: World) -> None:
    for settings, expected in ((MAIL, True), (NO_MAIL, False)):
        database = Database(create_engine(world.db.app_url, application_name="test"), settings)
        try:
            async with database.tenant_session(TenantContext(world.a.tenant)) as session:
                assert await email_channel_configured(session) is expected
        finally:
            await database.dispose()
