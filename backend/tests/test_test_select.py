"""CI test selection (tooling/test_select.py): a PR runs the tests its changes can reach.

The real import graph for the representative paths (grimp builds it in well under a second),
a small fake graph for the edge rules. The merge queue runs everything regardless
(tests/test_ci_triggers.py).
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tooling import test_select
from tooling.test_select import Graph, Selection, plan, select


@pytest.fixture(scope="module")
def graph() -> Graph:
    return test_select.build_graph()


ASSETS = "backend/app/modules/assets/service/imports.py"


def test_an_assets_change_selects_the_asset_tests_and_not_the_knowledge_ones(graph: Graph) -> None:
    chosen = select([ASSETS], graph)
    assert not chosen.all
    assert "tests/db/test_assets_api.py" in chosen.files
    assert "app/modules/assets/tests/test_assets_domain.py" in chosen.files
    assert not [
        f for f in chosen.files if f.startswith(("tests/db/test_kb_", "tests/db/test_knowledge"))
    ]
    assert chosen.modules == ["app.modules.assets"]
    assert chosen.app_files == ["app/modules/assets/service/imports.py"]


def test_the_top_level_quick_tests_always_run_with_any_backend_test(graph: Graph) -> None:
    chosen = select([ASSETS], graph)
    assert "tests/test_enum_labels.py" in chosen.files
    assert "tests/test_ci_triggers.py" in chosen.files


def test_the_app_factory_does_not_pull_every_test_in(graph: Graph) -> None:
    assert "app.main" not in graph.modules
    # tests/test_health.py builds the app (through app.main); a knowledge test does not.
    assert "tests/db/test_knowledge_api.py" not in select([ASSETS], graph).files


def test_a_changed_test_helper_selects_the_tests_importing_it(graph: Graph) -> None:
    chosen = select(["backend/tests/db/test_knowledge_api.py"], graph)
    assert "tests/db/test_knowledge_api.py" in chosen.files
    assert "tests/db/test_assets_api.py" in chosen.files  # imports _match and _new from it
    assert chosen.app_files == []


@pytest.mark.parametrize(
    "path",
    [
        "backend/app/shared/events.py",
        "backend/app/core/database.py",
        "backend/app/main.py",
        "backend/workers/relay.py",
        "backend/migrations/versions/0001_initial.py",
        "backend/tooling/test_select.py",
        "backend/conftest.py",
        "backend/tests/events/conftest.py",
        "backend/tests/db/shared_world.py",
        "backend/tests/__init__.py",
        "backend/pyproject.toml",
        "backend/uv.lock",
        "backend/alembic.ini",
        "backend/app/modules/assets/templates/label.html",  # not a .py file: unknown
        "backend/app/other.py",  # app outside the modules
        "backend/Dockerfile",
        "deploy/compose/docker-compose.yml",
        ".github/workflows/ci.yml",
        ".github/actions/setup-backend/action.yml",
        "Makefile",
        ".pre-commit-config.yaml",
    ],
)
def test_shared_or_unknown_paths_select_everything(path: str, graph: Graph) -> None:
    chosen = select([ASSETS, path], graph)
    assert chosen.all, path
    assert chosen.reason.startswith(path)


@pytest.mark.parametrize(
    "path",
    [
        "docs/PROGRESS.md",
        "frontend/apps/console/src/main.tsx",
        "mobile/App.tsx",
        "deploy/helm/supportx/values.yaml",
        "deploy/k3s/config-ha.yaml",
        "deploy/k3d/cluster.yaml",
        ".github/workflows/cluster.yml",
    ],
)
def test_paths_outside_the_backend_select_nothing(path: str, graph: Graph) -> None:
    assert select([path], graph) == Selection(all=False, reason="no backend change")


def test_no_changed_files_or_no_graph_selects_everything() -> None:
    assert select([], None).all
    assert select(["", "  "], None).all
    assert select([ASSETS], None) == Selection(
        all=True, reason="the import graph could not be built"
    )


@dataclass
class FakeGraph:
    imports: dict[str, set[str]] = field(default_factory=dict)  # module -> its closure

    @property
    def modules(self) -> set[str]:
        return set(self.imports)

    def find_upstream_modules(self, module: str, as_package: bool = False) -> set[str]:  # noqa: ARG002, FBT002 - grimp signature
        return self.imports[module]


FAKE = FakeGraph(
    {
        "tests.test_labels": set(),
        "tests.db.test_a": {"app.modules.a.service", "tests.db.helper"},
        "tests.db.test_b": {"app.modules.b.domain"},
        "tests.db.helper": set(),
        "app.modules.a.service": set(),
        "app.modules.b.domain": set(),
        "app.modules.b.tests.test_b_domain": {"app.modules.b.domain"},
    }
)


def test_a_module_change_counts_for_its_whole_package(tmp_path: Path) -> None:
    chosen = select(["backend/app/modules/b/service/new.py"], FAKE, root=tmp_path)
    assert chosen.files == [
        "app/modules/b/tests/test_b_domain.py",
        "tests/db/test_b.py",
        "tests/test_labels.py",
    ]
    assert chosen.app_files == []  # the file is not there: nothing to measure


def test_a_removed_test_file_nobody_names_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    chosen = select(["backend/tests/db/test_gone.py"], FAKE, root=tmp_path)
    assert chosen == Selection(all=False, modules=[], files=["tests/test_labels.py"])


def test_a_test_file_outside_the_graph_that_is_still_named_selects_everything(
    tmp_path: Path,
) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_user.py").write_text("from tests.db import test_gone\n")
    assert select(["backend/tests/db/test_gone.py"], FAKE, root=tmp_path).all
    (tmp_path / "tests" / "db").mkdir()
    (tmp_path / "tests" / "db" / "test_new.py").write_text("")  # there, but not in the graph
    assert select(["backend/tests/db/test_new.py"], FAKE, root=tmp_path).all


def test_a_helper_change_reaches_its_importers(tmp_path: Path) -> None:
    chosen = select(["backend/tests/db/helper.py"], FAKE, root=tmp_path)
    assert chosen.files == ["tests/db/test_a.py", "tests/test_labels.py"]


def test_the_shards_follow_the_selected_seconds() -> None:
    weights = {f"tests/db/test_{n}.py": 600.0 for n in range(40)}
    few = Selection(all=False, files=[f"tests/db/test_{n}.py" for n in range(4)])
    assert plan(few, weights) == (2400.0, 1)  # 2400 s over 4 workers: one shard
    many = Selection(all=False, files=list(weights))
    assert plan(many, weights) == (24000.0, 8)  # 10 wanted, at most 8
    one = Selection(all=False, files=["tests/db/test_0.py"])
    assert plan(one, {"tests/db/test_0.py": 9000.0}) == (9000.0, 1)  # never more than files
    assert plan(Selection(all=True), weights)[1] == 8
    assert plan(Selection(all=False), weights) == (0.0, 0)


def test_the_cli_writes_the_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    changed = tmp_path / "changed.txt"
    changed.write_text("backend/app/modules/b/domain.py\n")
    weights = tmp_path / "weights.json"
    weights.write_text(json.dumps({"tests/db/test_b.py": 100.0}))
    out = tmp_path / "selection.json"
    monkeypatch.setattr(test_select, "build_graph", lambda: FAKE)
    args = ["--changed", str(changed), "--weights", str(weights), "--out", str(out)]
    assert test_select.main(args) == 0
    found = json.loads(out.read_text())
    assert found["all"] is False
    assert found["shards"] == 1
    assert "tests/db/test_b.py" in found["files"]
    assert "3 test files" in capsys.readouterr().out

    def broken() -> Graph:
        msg = "syntax error somewhere"
        raise RuntimeError(msg)

    monkeypatch.setattr(test_select, "build_graph", broken)
    assert test_select.main(args) == 0
    assert json.loads(out.read_text())["all"] is True
    assert "All backend tests on 8 shards" in capsys.readouterr().out
    changed.write_text("docs/PROGRESS.md\n")
    assert test_select.main(args) == 0
    assert "No backend test is affected" in capsys.readouterr().out
