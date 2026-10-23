"""Guard: no code outside the licensing module may know whether it runs SaaS or on-prem.

CLAUDE.md rule f / architecture.md §1.2: "Licensing decides features, never the deployment model."
The scan parses every Python file under app/ and workers/ and flags identifiers, attribute names
and string literals that name a deployment mode, plus any use of the provider settings. Comments
and docstrings are prose and are not scanned. Allowed: app/modules/licensing/ (it owns the
providers) and the settings declaration in app/core/config.py.
"""

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[4]
SCANNED = ("app", "workers")
ALLOWED = (
    BACKEND / "app/modules/licensing",
    BACKEND / "app/core/config.py",
)
# Names that encode a deployment mode or reach for the provider choice.
_IDENTIFIER = re.compile(
    r"saas|on_?prem|onprem|air_?gapped|deployment_mode|deploy_mode|entitlement_provider|"
    r"licence_file|license_file",
    re.IGNORECASE,
)
_LITERAL = re.compile(
    r"^(saas|on[-_ ]?prem(ises)?|air[-_ ]?gapped|private[-_ ]cloud|licence_file)$",
    re.IGNORECASE,
)


def _docstrings(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                found.add(id(body[0].value))
    return found


def violations_in(source: str, name: str = "<source>") -> list[str]:
    """Every deployment-mode reference in `source` as 'name:line: text'."""
    tree = ast.parse(source)
    docstrings = _docstrings(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        text: str | None = None
        if isinstance(node, ast.Name):
            text = node.id
        elif isinstance(node, ast.Attribute):
            text = node.attr
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.arg):
            text = node.name if not isinstance(node, ast.arg) else node.arg
        elif isinstance(node, ast.keyword) and node.arg:
            text = node.arg
        if text is not None and _IDENTIFIER.search(text):
            found.append(f"{name}:{getattr(node, 'lineno', 0)}: {text}")
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
            and _LITERAL.match(node.value.strip())
        ):
            found.append(f"{name}:{node.lineno}: {node.value!r}")
    return found


def _allowed(path: Path) -> bool:
    return any(path == allowed or allowed in path.parents for allowed in ALLOWED)


def test_no_deployment_mode_checks_outside_licensing() -> None:
    found: list[str] = []
    for root in SCANNED:
        for path in sorted((BACKEND / root).rglob("*.py")):
            if _allowed(path):
                continue
            found += violations_in(path.read_text(encoding="utf-8"), str(path.relative_to(BACKEND)))
    assert found == [], (
        "Branch on entitlements (has_feature / check_limit), never on the deployment mode "
        "(CLAUDE.md rule f):\n" + "\n".join(found)
    )


def test_the_guard_catches_the_usual_shapes() -> None:
    planted = '''
"""Docstrings may talk about SaaS and on-prem freely."""
import os
# so may comments: if saas
IS_SAAS = os.environ.get("MODE") == "saas"
def handler(settings, deployment_mode):
    if settings.entitlement_provider == "licence_file":
        return "on-prem"
    if settings.profile == "dev":  # profiles are fine
        return 1
'''
    found = sorted(line.split(": ", 1)[1] for line in violations_in(planted))
    assert found == sorted(
        [
            "IS_SAAS",
            "'saas'",
            "deployment_mode",
            "entitlement_provider",
            "'licence_file'",
            "'on-prem'",
        ]
    )
