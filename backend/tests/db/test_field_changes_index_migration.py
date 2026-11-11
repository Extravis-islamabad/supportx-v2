"""Migration 0135: the index on field_changes (tenant_id, change_id), built CONCURRENTLY.

It exists after the upgrade and is gone after the downgrade; nothing else changes.
"""

import asyncio

import pytest

from tests.db.test_asset_labels_audits_scans_migration import NEW, _shape
from tooling import db_testing

pytestmark = pytest.mark.db


def test_0135_adds_the_change_index_and_drops_only_it(db_config: db_testing.DbTestConfig) -> None:
    database = db_testing.create(db_config, migrate_to="0134")
    try:
        assert asyncio.run(_shape(database.admin_url))[2] == 0
        db_testing.migrate(database.migrator_url, "0135")
        assert asyncio.run(_shape(database.admin_url)) == (len(NEW), 2, 1)
        db_testing.downgrade(database.migrator_url, "0134")
        assert asyncio.run(_shape(database.admin_url)) == (len(NEW), 2, 0)
        db_testing.migrate(database.migrator_url, "0135")
        assert asyncio.run(_shape(database.admin_url))[2] == 1
    finally:
        db_testing.destroy(db_config, database)
