"""Migration 0128 (restored_at) runs up, down and up again.

The restore itself is tested in tests/db/test_sla_safety_net.py; here the chain:
the downgrade drops the column, and a second upgrade applies cleanly.
"""

from collections.abc import Iterator

import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0127"  # 0128's down revision


@pytest.fixture
def before(db_config: db_testing.DbTestConfig) -> Iterator[db_testing.ThrowawayDatabase]:
    """A throwaway database migrated to just before 0128."""
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        yield database
    finally:
        db_testing.destroy(db_config, database)


def test_0128_upgrades_downgrades_and_upgrades_again(
    before: db_testing.ThrowawayDatabase,
) -> None:
    db_testing.migrate(before.migrator_url, "0128")
    db_testing.downgrade(before.migrator_url, BEFORE)
    db_testing.migrate(before.migrator_url, "0128")
