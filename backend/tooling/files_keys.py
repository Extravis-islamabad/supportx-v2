"""`python -m tooling.files_keys check|rewrap|rotate`: the files key ring (D-082 D2, ADR-028).

Run where the API runs (same settings: SUPPORTX_DATABASE_URL and SUPPORTX_FILES_KEYS), e.g.
`kubectl exec deploy/supportx-api -- python -m tooling.files_keys check`.

- `check`: every tenant's data keys open with the configured key ring. Run it after a restore
  (backup and restore, docs/architecture/files.md): a missing installation key is named here,
  before anyone opens a file.
- `rewrap`: after putting a new installation key first in `files-keys` (keeping the old one listed),
  move every stored data key under it. Afterwards the old key can be removed from the ring.
- `rotate`: give every tenant a new data key for new files (old files keep theirs).

Exit code 0 when everything succeeded, 1 otherwise; the output names tenants by ID only.
"""

import asyncio
import sys
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database, create_engine
from app.core.tenancy import TenantContext
from app.shared.files.infra.models import TenantDataKey
from app.shared.files.keyring import KeyRing, KeyRingError
from app.shared.files.service.core import rewrap_data_keys, rotate_data_key, tenant_of

COMMANDS = ("check", "rewrap", "rotate")


@dataclass
class Report:
    """What a command did, per tenant."""

    done: dict[uuid.UUID, int] = field(default_factory=dict)
    failed: dict[uuid.UUID, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Whether every tenant succeeded."""
        return not self.failed


async def _check(session: AsyncSession, keyring: KeyRing) -> int:
    tenant = tenant_of(session)
    rows = list(await session.scalars(select(TenantDataKey)))
    for row in rows:
        keyring.unwrap(tenant, row.kek_id, row.wrapped)
    return len(rows)


async def _rotate(session: AsyncSession, keyring: KeyRing) -> int:
    await rotate_data_key(session, keyring)
    return 1


ACTIONS: dict[str, Callable[[AsyncSession, KeyRing], Awaitable[int]]] = {
    "check": _check,
    "rewrap": rewrap_data_keys,
    "rotate": _rotate,
}


async def run(database: Database, keyring: KeyRing, command: str) -> Report:
    """Apply `command` to every tenant, each in its own transaction."""
    action = ACTIONS[command]
    async with database.platform_session() as session:
        tenants = list((await session.scalars(text("SELECT audit_tenant_ids()"))).all())
    report = Report()
    for tenant in tenants:
        try:
            async with database.tenant_session(TenantContext(tenant)) as session:
                report.done[tenant] = await action(session, keyring)
        except KeyRingError as error:
            report.failed[tenant] = str(error)
    return report


def main(argv: list[str]) -> int:  # pragma: no cover - thin CLI over the tested `run`
    """Run one command against the configured database and key ring."""
    if len(argv) != 1 or argv[0] not in COMMANDS:
        sys.stderr.write(f"usage: python -m tooling.files_keys {'|'.join(COMMANDS)}\n")
        return 2
    settings = Settings()
    if settings.database_url is None or settings.files_keys is None:
        sys.stderr.write("SUPPORTX_DATABASE_URL and SUPPORTX_FILES_KEYS must be set\n")
        return 2
    keyring = KeyRing.parse(settings.files_keys.get_secret_value())
    database = Database(
        create_engine(settings.database_url.get_secret_value(), application_name="files-keys")
    )

    async def go() -> Report:
        try:
            return await run(database, keyring, argv[0])
        finally:
            await database.dispose()

    report = asyncio.run(go())
    for tenant, count in report.done.items():
        sys.stdout.write(f"{argv[0]}: tenant {tenant}: {count} key(s) ok\n")
    for tenant, reason in report.failed.items():
        sys.stdout.write(f"{argv[0]}: tenant {tenant}: FAILED: {reason}\n")
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main(sys.argv[1:]))
