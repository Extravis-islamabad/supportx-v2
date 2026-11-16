"""Custom values leave work_items only through `visible_custom*` (WP-057 S3b-2; lane A's guard).

A sealed value is `sx2:` text: handed to a reader as stored, it would show ciphertext, and a
withheld one would skip ADR-047's strip. So:
- in `work_items/api`, a record's `.custom` is read only inside a call to
  `custom_values.visible_custom` / `visible_custom_many` (or as `view.custom`, the service's
  opened values);
- in `work_items/service`, only the files below read `.custom`, each for a stated reason. A new
  reader elsewhere fails here until it goes through `custom_values`.
"""

import ast
from pathlib import Path

WORK_ITEMS = Path(__file__).resolve().parents[1] / "app" / "modules" / "work_items"

# Service files that read stored custom values, and why that is safe.
SERVICE_READERS: dict[str, str] = {
    "custom_values.py": "the one place values are opened and sealed",
    "work_items.py": "writers (through _custom_columns) and system opens (custom_values.opened)",
    "search_rebuild.py": "search text, from which sealed keys are withheld",
    "closing.py": "required-field presence checks: never the value",
    "person_data.py": "the erasure writer, through redact_fields (_custom_columns)",
    "person_mentions.py": "the erasure mentions port (system cipher, lane B's conditions)",
    "record_copies.py": "copies: custom_values.opened, then sealed again",
    "change_links.py": "copies: custom_values.opened, then sealed again",
}


def _reads(tree: ast.AST) -> list[ast.Attribute]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "custom"]


def _inside_visible_call(tree: ast.AST, node: ast.Attribute) -> bool:
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in {"visible_custom", "visible_custom_many"} and any(
            child is node for child in ast.walk(call)
        ):
            return True
    return False


def test_api_code_reads_custom_values_only_through_visible_custom() -> None:
    offenders: list[str] = []
    for path in sorted((WORK_ITEMS / "api").glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in _reads(tree):
            opened = isinstance(node.value, ast.Name) and node.value.id == "view"
            if opened or _inside_visible_call(tree, node):
                continue
            offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], "read through custom_values.visible_custom* (WP-057 S3b-2)"


def test_only_known_service_files_read_stored_custom_values() -> None:
    readers = {
        path.name
        for path in (WORK_ITEMS / "service").glob("*.py")
        if _reads(ast.parse(path.read_text(), filename=str(path)))
    }
    assert readers <= set(SERVICE_READERS), sorted(readers - set(SERVICE_READERS))


def test_the_guard_sees_a_read() -> None:
    """The scan works: the record route's page goes through visible_custom_many."""
    routes = ast.parse((WORK_ITEMS / "api" / "routes.py").read_text())
    assert _reads(routes)
