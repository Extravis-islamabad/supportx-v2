"""Every write that changes a row moves its `updated_at` (QA WP-029 BUG-05, lane B's review).

A 409 names when the save the user missed happened from the row's `updated_at`. SQLAlchemy
updates set it through the column's `onupdate`; three kinds of write do not go through that and
are checked here, so a new one cannot quietly skip it:

- raw SQL `UPDATE <table> SET ...` in the application, workers and tooling;
- PostgreSQL upserts (`insert(...).on_conflict_do_update(set_=...)`), which apply only `set_`;
- a model that redefines `updated_at` without `onupdate`.

Migrations are left out on purpose: their data steps (expand/contract backfills) are not saves,
never bump `version` and so cannot be the save a 409 is about; applied migrations are not edited.
"""

import ast
import re
from collections.abc import Iterator
from pathlib import Path

from app.shared.db.models import Base
from tests.test_error_labels import _import_application

BACKEND = Path(__file__).resolve().parents[1]
SOURCES = ("app", "workers", "tooling")
_UPDATE = re.compile(
    r"\bUPDATE\s+([a-z_][a-z0-9_]*)\s+SET\b(.*?)(?:\bWHERE\b|\bRETURNING\b|$)",
    re.DOTALL | re.IGNORECASE,
)


def stamped_tables() -> set[str]:
    _import_application()
    return {t.name for t in Base.metadata.sorted_tables if "updated_at" in t.c}


def sources() -> Iterator[tuple[Path, ast.Module]]:
    for root in SOURCES:
        for path in sorted((BACKEND / root).rglob("*.py")):
            if "tests" not in path.parts:
                yield path, ast.parse(path.read_text(encoding="utf-8"))


def _strings(tree: ast.Module) -> Iterator[ast.Constant]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node


def raw_updates_without_stamp(tables: set[str]) -> list[str]:
    found: list[str] = []
    for path, tree in sources():
        for node in _strings(tree):
            for table, assignments in _UPDATE.findall(str(node.value)):
                if table in tables and "updated_at" not in assignments:
                    found.append(f"{path.relative_to(BACKEND)}:{node.lineno} UPDATE {table}")
    return found


def _keys(node: ast.expr, scope: ast.AST) -> set[str]:
    """Keys a `set_` dict surely has: its literal keys, and those of a `**name` that is a dict
    literal assigned in the same function (anything else adds nothing, so it must be literal)."""
    if not isinstance(node, ast.Dict):
        return set()
    keys: set[str] = set()
    for key, value in zip(node.keys, node.values, strict=True):
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            keys.add(key.value)
        elif key is None and isinstance(value, ast.Name):
            for assigned in ast.walk(scope):
                if isinstance(assigned, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == value.id for t in assigned.targets
                ):
                    keys |= _keys(assigned.value, scope)
    return keys


def _model_tables() -> dict[str, str]:
    return {m.class_.__name__: str(m.persist_selectable.description) for m in Base.registry.mappers}


def upserts_without_stamp(tables: set[str]) -> list[str]:
    models = _model_tables()
    found: list[str] = []
    for path, tree in sources():
        functions = [
            n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        ]
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "on_conflict_do_update"
            ):
                continue
            target = node.func.value
            while isinstance(target, ast.Call) and isinstance(target.func, ast.Attribute):
                target = target.func.value
            name = (
                target.args[0].id
                if isinstance(target, ast.Call)
                and target.args
                and isinstance(target.args[0], ast.Name)
                else None
            )
            table = models.get(name or "")
            if table is None or table not in tables:
                continue
            scope = next(
                (f for f in functions if f.lineno <= node.lineno <= (f.end_lineno or f.lineno)),
                tree,
            )
            set_ = next((k.value for k in node.keywords if k.arg == "set_"), None)
            if set_ is None or "updated_at" not in _keys(set_, scope):
                found.append(f"{path.relative_to(BACKEND)}:{node.lineno} upsert {table}")
    return found


def test_raw_sql_updates_move_updated_at() -> None:
    assert raw_updates_without_stamp(stamped_tables()) == []


def test_upserts_move_updated_at() -> None:
    assert upserts_without_stamp(stamped_tables()) == []


def test_every_updated_at_column_moves_on_update() -> None:
    _import_application()
    missing = [
        t.name
        for t in Base.metadata.sorted_tables
        if "updated_at" in t.c and t.c.updated_at.onupdate is None
    ]
    assert missing == []


def test_the_checks_find_what_they_look_for() -> None:
    tables = {"work_items"}
    assert _UPDATE.findall("UPDATE work_items SET subject = $1 WHERE id = $2")[0][0] == "work_items"
    assert "updated_at" in _UPDATE.findall("UPDATE work_items SET a = 1, updated_at = now()")[0][1]
    assert raw_updates_without_stamp(tables) == []
