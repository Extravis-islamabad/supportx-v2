"""Migration 0126 runs up, down and up again (D-154 "rules").

Its data step is tested on real saved levels in tests/db/test_d154_rules.py; here the chain:
the downgrade has nothing to undo, so a second upgrade after it must still apply cleanly.
"""

from collections.abc import Iterator

import pytest

from tooling import db_testing

pytestmark = pytest.mark.db

BEFORE = "0122"  # 0126's down revision


@pytest.fixture
def before(db_config: db_testing.DbTestConfig) -> Iterator[db_testing.ThrowawayDatabase]:
    """A throwaway database migrated to just before 0126."""
    database = db_testing.create(db_config, migrate_to=BEFORE)
    try:
        yield database
    finally:
        db_testing.destroy(db_config, database)


def test_0126_upgrades_downgrades_and_upgrades_again(
    before: db_testing.ThrowawayDatabase,
) -> None:
    db_testing.migrate(before.migrator_url, "0126")
    db_testing.downgrade(before.migrator_url, BEFORE)
    db_testing.migrate(before.migrator_url, "0126")
