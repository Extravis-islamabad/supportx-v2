"""The PDF worker image's test run never meets a missing import (nightly 42464872109, 42993721634).

The `worker-test` image (deploy/images/backend.Dockerfile) runs the `pdf`-marked tests with
WeasyPrint and Pango, the setup that ships. It holds only the application: no backend/conftest.py
and no top-level tests/ package. A test it runs that imports either fails there, at collection,
and only the nightly saw it. These checks make that fail in the pull request instead:

- the image runs exact files, every one of them exists, and every `pytest.mark.pdf` file under
  app/ is among them (a new PDF test is never silently left out of the image);
- none of those files imports `conftest` or anything from `tests`.
"""

import ast
import json
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DOCKERFILE = BACKEND.parent / "deploy/images/backend.Dockerfile"
_FORBIDDEN_ROOTS = frozenset({"conftest", "tests"})


def _image_test_paths() -> list[str]:
    """The paths the worker-test stage's CMD hands to pytest."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    stage = text.split("AS worker-test", 1)[1].split("\nFROM ", 1)[0]
    (cmd,) = re.findall(r"^CMD (\[.*\])$", stage, flags=re.MULTILINE)
    args: list[str] = json.loads(cmd)
    return [a for a in args if a.startswith("app/")]


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".", 1)[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_the_image_runs_exact_files_that_exist() -> None:
    paths = _image_test_paths()
    assert paths, "the worker-test CMD names no app/ test files"
    for name in paths:
        path = BACKEND / name
        assert name.endswith(".py"), f"{name}: name the file, not a folder (pytest imports all)"
        assert path.is_file(), f"{name}: not found"


def test_every_pdf_test_is_run_by_the_image() -> None:
    marked = {
        str(path.relative_to(BACKEND))
        for path in (BACKEND / "app").rglob("test_*.py")
        if re.search(r"\bpytest\.mark\.pdf\b|\bmark\.pdf\b", path.read_text(encoding="utf-8"))
    }
    missing = sorted(marked - set(_image_test_paths()))
    assert missing == [], f"add these to the worker-test CMD in {DOCKERFILE.name}: {missing}"


def test_the_image_tests_import_neither_conftest_nor_tests() -> None:
    found = {
        name: sorted(_imported_roots(BACKEND / name) & _FORBIDDEN_ROOTS)
        for name in _image_test_paths()
    }
    offending = {name: roots for name, roots in found.items() if roots}
    assert offending == {}, (
        f"the PDF worker image has no backend/conftest.py or tests/: {offending}"
    )
