"""The authorization cache consumer bumps the tenant's generation (WP-016)."""

import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import valkey.asyncio

from app.modules.identity_access.service.authz_consumer import TRIGGERS, handler
from app.modules.identity_access.service.policy import ValkeySubjectCache
from app.shared.events import Actor, EventEnvelope
from conftest import make_settings
from tests.db.test_rate_limit import valkey_url

pytestmark = pytest.mark.valkey


async def test_each_trigger_bumps_the_generation() -> None:
    url = valkey_url()
    if url is None:
        pytest.skip("Valkey is not configured")
    prefix = f"test-{secrets.token_hex(6)}:"
    settings = make_settings(valkey_url=url, valkey_key_prefix=prefix)
    client: Any = valkey.asyncio.from_url(url)  # type: ignore[no-untyped-call]  # valkey-py ships no hints
    tenant = uuid.uuid4()
    cache = ValkeySubjectCache(client, prefix=prefix, ttl_seconds=60)
    try:
        handle = handler(lambda: settings)
        for number, event_type in enumerate(TRIGGERS, start=1):
            envelope = EventEnvelope(
                event_id=uuid.uuid4(),
                event_type=event_type,
                schema_version=1,
                tenant_id=tenant,
                actor=Actor.system("tests"),
                occurred_at=datetime.now(UTC),
                aggregate_type="x",
                aggregate_id="x",
                payload={},
            )
            await handle(envelope, None)
            assert int(await client.get(cache.generation_key(tenant))) == number
    finally:
        await client.delete(cache.generation_key(tenant))
        await client.aclose()
