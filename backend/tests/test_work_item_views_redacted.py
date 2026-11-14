"""A staff record view is built in the two redacted places only (ADR-047 §4; lane B's review).

`service.WorkItemView` is what every staff response of a record is made from, and it carries
the fields the person may not read (`hidden`, `masked`). A view built by hand elsewhere would
default those to empty and send a withheld value back (the D-053 handover did, until this
check). This scans the application code for `WorkItemView(` calls and fails on any outside
`_view` and `_handed_away` in service/work_items.py.

The saved list views' model (`infra.models.WorkItemView`, a different class with the same name)
is skipped in the files that import it from infra.models.
"""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
SERVICE = "app/modules/work_items/service/work_items.py"
ALLOWED = {(SERVICE, "_view"), (SERVICE, "_handed_away")}


def _uses_the_list_model(tree: ast.Module) -> bool:
    """The file's `WorkItemView` is the saved list views' model, not the record view."""
    return any(
        isinstance(node, ast.ImportFrom)
        and (node.module or "").endswith("infra.models")
        and any(alias.name == "WorkItemView" for alias in node.names)
        for node in ast.walk(tree)
    )


def _builds(path: Path) -> list[tuple[str, int]]:
    """(enclosing function, line) of every `WorkItemView(...)` call in the file."""
    tree = ast.parse(path.read_text(), filename=str(path))
    if _uses_the_list_model(tree):
        return []
    found: list[tuple[str, int]] = []

    def walk(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = (
                child.name
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                else function
            )
            if isinstance(child, ast.Call):
                func = child.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                if name == "WorkItemView":
                    found.append((function, child.lineno))
            walk(child, inner)

    walk(tree, "<module>")
    return found


def test_record_views_are_built_only_where_they_are_redacted() -> None:
    offenders = [
        f"{path.relative_to(BACKEND)}:{line} in {function}"
        for path in sorted(APP.rglob("*.py"))
        for function, line in _builds(path)
        if (str(path.relative_to(BACKEND)), function) not in ALLOWED
    ]
    assert offenders == [], offenders


def test_the_check_sees_both_redacted_places() -> None:
    """The scan really finds calls (a renamed function would make the first test vacuous)."""
    assert {function for function, _ in _builds(BACKEND / SERVICE)} == {"_view", "_handed_away"}
