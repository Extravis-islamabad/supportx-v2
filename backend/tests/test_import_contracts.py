import grimp
import pytest

from tooling.import_contracts import ModuleBoundariesContract, owning_module


def make_graph(*imports: tuple[str, str]) -> grimp.ImportGraph:
    graph = grimp.ImportGraph()
    for name in (
        "app",
        "app.core",
        "app.modules",
        "app.modules.sla",
        "app.modules.sla.domain",
        "app.modules.sla.events",
        "app.modules.work_items",
        "app.modules.work_items.service",
        "app.modules.work_items.domain",
    ):
        graph.add_module(name)
    for importer, imported in imports:
        graph.add_import(importer=importer, imported=imported, line_number=1, line_contents="")
    return graph


def check(graph: grimp.ImportGraph) -> bool:
    contract = ModuleBoundariesContract(
        name="module boundaries",
        session_options={},
        contract_options={"container": "app.modules", "public_submodules": ["events"]},
    )
    return contract.check(graph, verbose=False).kept


@pytest.mark.parametrize(
    "imported",
    ["app.modules.sla", "app.modules.sla.events"],
)
def test_importing_another_modules_public_surface_is_allowed(imported: str) -> None:
    assert check(make_graph(("app.modules.work_items.service", imported)))


def test_importing_another_modules_internals_is_forbidden() -> None:
    assert not check(make_graph(("app.modules.work_items.service", "app.modules.sla.domain")))


def test_importing_own_internals_is_allowed() -> None:
    graph = make_graph(("app.modules.work_items.service", "app.modules.work_items.domain"))
    assert check(graph)


def test_owning_module() -> None:
    assert owning_module("app.modules.sla.domain.timer", "app.modules") == "app.modules.sla"
    assert owning_module("app.core.config", "app.modules") is None


def test_broken_contract_report_names_the_illegal_import(
    capsys: pytest.CaptureFixture[str],
) -> None:
    contract = ModuleBoundariesContract(
        name="module boundaries",
        session_options={},
        contract_options={"container": "app.modules", "public_submodules": ["events"]},
    )
    graph = make_graph(("app.modules.work_items.service", "app.modules.sla.domain"))

    contract.render_broken_contract(contract.check(graph, verbose=False))

    assert "app.modules.work_items.service -> app.modules.sla.domain" in capsys.readouterr().out
