"""Which backend test files a pull request's changes can affect (CI test selection).

On 2026-11-11 the eight backend shards were most of the PR runner time, and most PRs touch one
module. A PR run therefore runs only the test files that can see its changes; the merge queue,
nightly, manual runs and PRs labelled full-ci keep running everything (.github/workflows/ci.yml,
backend/tests/test_ci_triggers.py), so every merge is still tested in full.

The rules, from the PR's changed paths (repository-relative):

- Anything shared, or anything this tool cannot place, selects ALL: app/core, app/shared,
  app/main.py, workers, migrations, tooling, any conftest.py, tests/db/shared_world.py, the
  project files, any backend file that is not a .py file in app/modules or tests, the dev
  compose stack, ci.yml, the composite actions, the Makefile and pre-commit's config. Also when
  the import graph cannot be built.
- A .py file in app/modules/<m> counts as a change to the whole module package: every test
  file whose import closure reaches app.modules.<m> runs. A test file (or a test helper other
  test files import) selects itself and every test file importing it.
- Paths outside the backend (frontend, docs, mobile, the Helm chart, k3s and k3d files, other
  workflows) select nothing.
- Whenever any backend test runs, the quick top-level tests/test_*.py (labels, CI guards) run
  too.

The import graph comes from grimp (import-linter's own library), with app.main taken out: the
app factory imports every router, so through it every test would reach every module. Tests that
reach a module only over HTTP through create_app are therefore not selected by it; the queue's
full run is the backstop for those.

CLI (from backend/): `uv run python -m tooling.test_select --changed <paths file> --weights
<json> --out <selection.json>`. Never imported by the app.
"""

import argparse
import json
import math
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from tooling.pytest_shards import WEIGHTS, fallback_seconds

BACKEND = Path(__file__).resolve().parents[1]
PACKAGES = ("app", "tests", "tooling", "workers")
APP_FACTORY = "app.main"
MAX_SHARDS = 8
WORKERS_PER_SHARD = 4  # pytest -n 4 in every shard
SHARD_SECONDS = 600.0  # about ten minutes of tests a shard
TOP_LEVEL_DEPTH = 2  # tests.test_x

# Outside backend/: what changes how the backend tests run. Everything else outside backend/
# (frontend, docs, mobile, deploy/helm, deploy/k3s, deploy/k3d, other workflows) selects nothing.
ALL_OUTSIDE = re.compile(
    r"^(deploy/compose/|\.github/workflows/ci\.yml$|\.github/actions/|Makefile$"
    r"|\.pre-commit-config\.yaml$)"
)
# Inside backend/: shared code and test infrastructure that every test depends on.
ALL_INSIDE = re.compile(
    r"^(app/core/|app/shared/|app/main\.py$|workers/|migrations/|tooling/"
    r"|tests/db/shared_world\.py$|tests/(.*/)?__init__\.py$|(.*/)?conftest\.py$)"
)
MODULE_FILE = re.compile(r"^app/modules/(?P<module>[a-z0-9_]+)/.+\.py$")
TEST_FILE = re.compile(r"^(tests/.+|app/modules/[a-z0-9_]+/tests/.+)\.py$")


class Graph(Protocol):
    """The part of grimp's ImportGraph this tool uses (a fake one in the unit tests)."""

    @property
    def modules(self) -> set[str]:
        """Every module in the graph."""
        ...

    def find_upstream_modules(self, module: str, as_package: bool = False) -> set[str]:  # noqa: FBT001, FBT002 - grimp's own signature
        """Every module the given one imports, directly or not."""
        ...


@dataclass
class Selection:
    """What to run: everything (`all`), or these test files (paths relative to backend/)."""

    all: bool
    files: list[str] = field(default_factory=list)
    reason: str = ""
    modules: list[str] = field(default_factory=list)  # the app.modules packages changed
    app_files: list[str] = field(default_factory=list)  # changed app .py files (coverage)


def build_graph() -> Graph:
    """The import graph of the backend's packages, without the app factory."""
    import grimp  # noqa: PLC0415 - only the CLI needs it; the unit tests pass a fake

    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    # No cache: CI starts clean, and a stale cache would select from yesterday's imports.
    graph = grimp.build_graph(*PACKAGES, cache_dir=None)
    if APP_FACTORY in graph.modules:
        graph.remove_module(APP_FACTORY)
    return graph


def module_name(path: str) -> str:
    """app/modules/assets/service/imports.py -> app.modules.assets.service.imports."""
    parts = path.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def module_path(module: str) -> str:
    """The test file of a test module (test modules are never packages)."""
    return module.replace(".", "/") + ".py"


def is_test(module: str) -> bool:
    """A test module: tests/**/test_*.py or app/modules/<m>/tests/**/test_*.py."""
    parts = module.split(".")
    if not parts[-1].startswith("test_"):
        return False
    return parts[0] == "tests" or (parts[:2] == ["app", "modules"] and "tests" in parts[3:])


def is_top_level_test(module: str) -> bool:
    """One of the quick tests/test_*.py, which run whenever any backend test runs."""
    parts = module.split(".")
    return len(parts) == TOP_LEVEL_DEPTH and parts[0] == "tests" and parts[1].startswith("test_")


def _still_imported(stem: str, root: Path) -> bool:
    """Whether any backend source still names a removed module (then it is not safe to skip)."""
    word = re.compile(rf"\b{re.escape(stem)}\b")
    for package in PACKAGES:
        for source in (root / package).rglob("*.py"):
            if word.search(source.read_text(encoding="utf-8", errors="replace")):
                return True
    return False


@dataclass
class _Changes:
    """What the changed backend paths touch, path by path."""

    packages: set[str] = field(default_factory=set)  # app.modules.<m>, changed as a whole
    modules: set[str] = field(default_factory=set)  # test modules and test helpers
    app_files: set[str] = field(default_factory=set)
    backend: bool = False


def _note(path: str, graph: Graph | None, root: Path, changes: _Changes) -> str | None:
    """Record one changed path; the reason to run everything, or None."""
    if not path.startswith("backend/"):
        return path if ALL_OUTSIDE.match(path) else None
    changes.backend = True
    inner = path.removeprefix("backend/")
    if ALL_INSIDE.match(inner):
        return path
    if TEST_FILE.match(inner):
        name = module_name(inner)
        if graph is None or name in graph.modules:
            changes.modules.add(name)
        elif (root / inner).exists() or _still_imported(name.rsplit(".", 1)[-1], root):
            return f"{path} (not in the import graph)"
        return None  # in the graph, or removed and named nowhere any more
    found = MODULE_FILE.match(inner)
    if found is None:
        return f"{path} (not a module or test .py file)"
    changes.packages.add(f"app.modules.{found.group('module')}")
    if (root / inner).exists():
        changes.app_files.add(inner)
    return None


def select(
    changed: Iterable[str],
    graph: Graph | None,
    *,
    root: Path = BACKEND,
) -> Selection:
    """The tests the changed paths (repository-relative) can affect. `graph` None: unbuildable."""
    paths = sorted({p.strip() for p in changed if p.strip()})
    if not paths:
        return Selection(all=True, reason="no list of changed files")
    changes = _Changes()
    for path in paths:
        if (reason := _note(path, graph, root, changes)) is not None:
            return Selection(all=True, reason=reason)
    if not changes.backend:
        return Selection(all=False, reason="no backend change")
    if graph is None:
        return Selection(all=True, reason="the import graph could not be built")
    chosen: list[str] = []
    for test in sorted(m for m in graph.modules if is_test(m)):
        reach = graph.find_upstream_modules(test) | {test}
        if (
            is_top_level_test(test)
            or reach & changes.modules
            or any(_inside(m, changes.packages) for m in reach)
        ):
            chosen.append(module_path(test))
    return Selection(
        all=False,
        files=chosen,
        modules=sorted(changes.packages),
        app_files=sorted(changes.app_files),
    )


def _inside(module: str, packages: set[str]) -> bool:
    return any(module == p or module.startswith(p + ".") for p in packages)


def plan(selection: Selection, weights: dict[str, float]) -> tuple[float, int]:
    """The selected files' seconds and the shards to spread them over (8 for everything)."""
    if selection.all:
        return sum(weights.values()), MAX_SHARDS
    if not selection.files:
        return 0.0, 0
    seconds = sum(weights.get(f, fallback_seconds(weights, f)) for f in selection.files)
    wanted = math.ceil(seconds / WORKERS_PER_SHARD / SHARD_SECONDS)
    # Never more shards than files: a shard left without a file would collect nothing and fail.
    return seconds, max(1, min(MAX_SHARDS, wanted, len(selection.files)))


def _weights(given: Path | None) -> dict[str, float]:
    """The committed weights, overlaid with the given ones (the same rule as the shards)."""
    found: dict[str, float] = json.loads(WEIGHTS.read_text()) if WEIGHTS.is_file() else {}
    if given is not None and given.is_file():
        found |= json.loads(given.read_text())
    return found


def summary(selection: Selection, seconds: float, shards: int) -> str:
    """One line for the job log and summary."""
    if selection.all:
        return f"All backend tests on {shards} shards: {selection.reason}"
    if not selection.files:
        return f"No backend test is affected ({selection.reason})"
    reached = ", ".join(selection.modules) or "no module package (test files only)"
    return (
        f"{len(selection.files)} test files (about {seconds / 60:.0f} min of tests) on {shards} "
        f"shard(s); changed modules: {reached}"
    )


def main(argv: list[str] | None = None) -> int:
    """Write the selection for the changed paths, and say what it is."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--changed", type=Path, required=True, help="one changed path per line")
    parser.add_argument("--weights", type=Path, help="file seconds (JSON) over the committed ones")
    parser.add_argument("--out", type=Path, required=True, help="where to write selection.json")
    args = parser.parse_args(argv)
    changed = args.changed.read_text(encoding="utf-8").splitlines()
    try:
        graph: Graph | None = build_graph()
    except Exception as error:  # noqa: BLE001 - any failure to build means: run everything
        sys.stdout.write(f"The import graph could not be built: {error!r}\n")
        graph = None
    selection = select(changed, graph)
    seconds, shards = plan(selection, _weights(args.weights))
    result = {
        "all": selection.all,
        "files": selection.files,
        "seconds": round(seconds, 1),
        "shards": shards,
        "reason": selection.reason,
        "modules": selection.modules,
        "app_files": selection.app_files,
    }
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(summary(selection, seconds, shards) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
