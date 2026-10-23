"""`python -m tooling.realtime_burst [count] [interval_ms]`: a burst of real changes (WP-011).

For the realtime load test (frontend/e2e/perf): changes the signature of the e2e scroll-fixture
users (`e2e-scroll-NN@demo.test`, created by tooling.e2e_fixtures) one after another, each in
its own transaction with its `identity_access.user.updated` event in the outbox, exactly like a
profile save. Prints one JSON line per commit: {"id": <user id>, "committed_ms": <epoch ms>}.
Only those fixture rows are touched (CLAUDE.md rule h). Refuses production.
"""

import asyncio
import json
import sys
import time

from sqlalchemy import select, update

from app.core.config import Settings
from app.core.database import Database
from app.core.tenancy import TenantContext
from app.modules.identity_access.events import UserUpdated
from app.modules.identity_access.infra.models import User
from app.shared.events import Actor, record_event
from tooling.e2e_fixtures import PATTERN
from tooling.seed_dev import DEMO_TENANT_ID


async def burst(settings: Settings, count: int, interval_ms: int) -> None:
    """Commit `count` changes, `interval_ms` apart, round-robin over the fixture users."""
    database = Database.from_settings(settings)
    if database is None:
        msg = "SUPPORTX_DATABASE_URL is not set (make backend-env)"
        raise SystemExit(msg)
    context = TenantContext(DEMO_TENANT_ID)
    try:
        async with database.tenant_session(context) as session:
            users = list(
                await session.scalars(
                    select(User.id).where(User.email.like(PATTERN)).order_by(User.email)
                )
            )
        if not users:
            msg = "no fixture users: run `uv run python -m tooling.e2e_fixtures create` first"
            raise SystemExit(msg)
        for n in range(count):
            user_id = users[n % len(users)]
            async with database.tenant_session(context) as session:
                version = await session.scalar(
                    update(User)
                    .where(User.id == user_id)
                    .values(signature=f"burst {n}", version=User.version + 1)
                    .returning(User.version)
                )
                await record_event(
                    session,
                    UserUpdated(user_id=user_id, changed_fields=["signature"]),
                    aggregate_id=user_id,
                    aggregate_version=version,
                    actor=Actor.system("realtime_burst"),
                )
            print(json.dumps({"id": str(user_id), "committed_ms": time.time() * 1000}), flush=True)  # noqa: T201 - the output is the point
            await asyncio.sleep(interval_ms / 1000)
    finally:
        await database.dispose()


def main(argv: list[str]) -> int:
    """Entry point."""
    settings = Settings.load(service_name="supportx-realtime-burst")
    if settings.profile == "production":
        print("refusing to run against production", file=sys.stderr)  # noqa: T201
        return 2
    count = int(argv[0]) if argv else 40
    interval_ms = int(argv[1]) if len(argv) > 1 else 25
    asyncio.run(burst(settings, count, interval_ms))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
