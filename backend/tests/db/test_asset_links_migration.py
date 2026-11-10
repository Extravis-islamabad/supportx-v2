"""Migration 0127 (asset links, REQ-AST-025) runs up, down and up again.

The links themselves are tested in tests/db/test_asset_links_api.py; here the chain:
the downgrade drops the table while no asset is linked, and a second upgrade applies cleanly.
"""

from collections.abc import Iterator

import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0126"  # 0127's down revision


@pytest.fixture
def before(db_config: db_testing.DbTestConfig) -> Iterator[db_testing.ThrowawayDatabase]:
    """A throwaway database migrated to just before 0127."""
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        yield database
    finally:
        db_testing.destroy(db_config, database)


def test_0127_upgrades_downgrades_and_upgrades_again(
    before: db_testing.ThrowawayDatabase,
) -> None:
    db_testing.migrate(before.migrator_url, "0127")
    db_testing.downgrade(before.migrator_url, BEFORE)
    db_testing.migrate(before.migrator_url, "0127")
