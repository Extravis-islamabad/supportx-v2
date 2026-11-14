"""Hard deletes on the erasure-only tables happen in the erasure ports alone (ADR-052; 0165).

Migration 0165 gives the app role DELETE on seven tables so the GDPR erasure can remove a
person's data for good (CLAUDE.md §6: a hard delete only through erasure). Everywhere else they
stay soft-delete or append-only. This scans the application code for a DELETE on any of them
(`delete(Model)` or `DELETE FROM table`) and fails if one appears outside the ports below
(the coordinator's condition, 2026-11-14).
"""

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"

TABLES = {
    "kb_votes": "KbVote",
    "dashboard_preferences": "DashboardPreference",
    "report_exports": "ReportExport",
    "reports": "Report",
    "report_folders": "ReportFolder",
    "dashboards": "Dashboard",
    "ai_calls": "AiCall",
}
ALLOWED = {
    "app/modules/knowledge/service/person_data.py",
    "app/modules/analytics/service/person_data.py",
    "app/modules/ai/service/person_data.py",
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


def test_only_the_erasure_ports_hard_delete_from_the_erasure_only_tables() -> None:
    offenders = {
        str(path.relative_to(BACKEND)): hits
        for path in APP.rglob("*.py")
        if "/tests/" not in str(path)
        and str(path.relative_to(BACKEND)) not in ALLOWED
        and (hits := _deletes(path))
    }
    assert offenders == {}, "hard deletes outside the erasure ports (ADR-052; 0165)"


def test_the_scan_sees_a_delete() -> None:
    """The scan itself works: the knowledge port deletes votes."""
    assert any(
        "KbVote" in hit for hit in _deletes(APP / "modules/knowledge/service/person_data.py")
    )


def test_the_models_named_are_the_tables() -> None:
    """A renamed model or table would blind the scan."""
    from app.modules.ai.infra.models import AiCall  # noqa: PLC0415
    from app.modules.analytics.infra.models import (  # noqa: PLC0415
        Dashboard,
        DashboardPreference,
        Report,
        ReportExport,
        ReportFolder,
    )
    from app.modules.knowledge.infra.models import KbVote  # noqa: PLC0415

    by_name = {
        model.__name__: model.__tablename__
        for model in (KbVote, DashboardPreference, ReportExport, Report, ReportFolder, Dashboard)
    }
    by_name["AiCall"] = AiCall.__tablename__
    assert {table: name for name, table in by_name.items()} == TABLES
