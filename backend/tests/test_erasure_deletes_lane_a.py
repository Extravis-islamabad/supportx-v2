"""Hard deletes on lane A's erasure-only tables happen in the erasure ports alone (ADR-052; 0166).

Migration 0166 gives the app role DELETE on eight tables of a person's private rows so the GDPR
erasure removes them for good (CLAUDE.md §6: a hard delete only through erasure). Everywhere else
they stay soft-deleted: this scans the application code for a DELETE on any of them
(`delete(Model)` or `DELETE FROM table`) and fails if one appears outside the ports (the
coordinator's condition, 2026-11-14; the same check as lane C's tests/test_erasure_deletes.py).
Known gap, as there: `session.delete(row)` of a loaded row is not recognised by its model.
"""

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"

TABLES = {
    "work_item_followers": "WorkItemFollower",
    "work_item_list_settings": "WorkItemListSetting",
    "work_item_reminders": "WorkItemReminder",
    "work_item_timers": "WorkItemTimer",
    "work_item_views": "WorkItemView",
    "work_item_reply_templates": "WorkItemReplyTemplate",
    "notification_preferences": "NotificationPreference",
    "technician_availability": "TechnicianAvailability",
}
ALLOWED = {
    "app/modules/work_items/service/person_data.py",
    "app/modules/notifications/service/person_data.py",
    "app/modules/automation/service/person_data.py",
}
_SQL = re.compile(r"\bDELETE\s+FROM\s+(" + "|".join(TABLES) + r")\b", re.IGNORECASE)


def _deletes(path: Path) -> list[str]:
    """What a file hard-deletes from the tables: `delete(Model)` calls and raw SQL."""
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[str] = []
    models = set(TABLES.values())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "delete"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in models
        ):
            found.append(f"delete({node.args[0].id}) line {node.lineno}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found += [
                f"DELETE FROM {m.group(1)} line {node.lineno}"  # noqa: S608 - a message, not SQL
                for m in _SQL.finditer(node.value)
            ]
    return found


def test_only_the_erasure_ports_hard_delete_from_lane_a_s_erasure_tables() -> None:
    offenders = {
        str(path.relative_to(BACKEND)): hits
        for path in APP.rglob("*.py")
        if "/tests/" not in str(path)
        and str(path.relative_to(BACKEND)) not in ALLOWED
        and (hits := _deletes(path))
    }
    assert offenders == {}, f"hard delete outside the erasure ports (0166): {offenders}"


def test_the_check_finds_a_delete() -> None:
    """The scan itself works (a guard that finds nothing proves nothing)."""
    sample = APP.parent / "tests" / "_erasure_delete_sample.py"
    sample.write_text(
        "from sqlalchemy import delete\nfrom x import WorkItemTimer\n"
        "q = delete(WorkItemTimer)\nr = 'DELETE FROM work_item_views'\n"
    )
    try:
        assert len(_deletes(sample)) == 2
    finally:
        sample.unlink()
