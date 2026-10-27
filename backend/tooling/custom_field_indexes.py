"""`python -m tooling.custom_field_indexes`: one index pass by hand or from the deploy (D-088).

The index worker (`workers.custom_field_indexes`) builds requested custom field indexes within a
minute or so. This runs the same pass once: from each deploy's migrate Job, as a fallback, and by
hand (`make custom-field-indexes`). If the worker is building right now, the pass skips (one
builder at a time) and the worker finishes the job.

Environment: SUPPORTX_MIGRATION_DATABASE_URL (migrator).
"""

import asyncio
import sys

from app.core.config import Settings
from app.core.database import Database, create_engine
from app.core.modules import discover_modules
from workers.custom_field_indexes.indexer import run_pass


async def run(migrator_url: str) -> dict[str, int] | None:
    """One pass; fields made active and failed, or None when the worker holds the lock."""
    discover_modules()
    database = Database(
        create_engine(migrator_url, application_name="custom-field-indexes", use_null_pool=True)
    )
    try:
        return await run_pass(database)
    finally:
        await database.dispose()


def main() -> int:  # pragma: no cover - thin CLI over the tested functions
    """CLI entry point."""
    settings = Settings()
    if settings.migration_database_url is None:
        sys.stderr.write("custom field indexes need SUPPORTX_MIGRATION_DATABASE_URL\n")
        return 2
    outcome = asyncio.run(run(settings.migration_database_url.get_secret_value()))
    if outcome is None:
        sys.stdout.write("custom field indexes: the index worker is building; skipped\n")
        return 0
    sys.stdout.write(
        f"custom field indexes: {outcome['active']} active, {outcome['failed']} failed\n"
    )
    return 1 if outcome["failed"] else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
