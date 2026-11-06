"""Tooling that seeds data registers every module's tables first (QA 2026-11-05).

`make showcase-seed` crashed with NoReferencedTableError: a catalog item's template is a
work_items table, and the seed's bare process had not imported that module. Each entry point is
imported in a fresh interpreter (as `make` runs it). Every foreign key of the catalog tables
must then resolve.
"""

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
CHECK = """
import importlib, sys
importlib.import_module(sys.argv[1])
from app.shared.db.models import Base
for name, table in Base.metadata.tables.items():
    if name.startswith("catalog_"):
        for fk in table.foreign_keys:
            fk.column  # raises NoReferencedTableError when the target is not registered
print("ok")
"""


@pytest.mark.parametrize("entry", ["tooling.catalog_starter", "tooling.showcase_seed"])
def test_seeding_tools_register_every_table(entry: str) -> None:
    done = subprocess.run(  # noqa: S603 - our own interpreter and a fixed script
        [sys.executable, "-c", CHECK, entry],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip() == "ok"
