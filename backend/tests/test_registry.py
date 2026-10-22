import sys
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI

from app.core.config import Settings
from app.core.modules import (
    ModuleRegistrationError,
    ModuleRegistry,
    ModuleSpec,
    discover_modules,
)
from app.main import create_app


@pytest.fixture
def fake_modules(tmp_path: Path) -> Iterator[Callable[[dict[str, str]], ModuleType]]:
    """Create an importable `fakemods_<n>` package whose sub-packages have the given __init__."""
    created: list[str] = []

    def make(packages: dict[str, str]) -> ModuleType:
        root_name = f"fakemods_{len(created)}"
        root = tmp_path / root_name
        root.mkdir()
        (root / "__init__.py").write_text("")
        (root / "not_a_package.py").write_text("")
        for name, body in packages.items():
            (root / name).mkdir()
            (root / name / "__init__.py").write_text(body)
        created.append(root_name)
        return __import__(root_name)

    sys.path.insert(0, str(tmp_path))
    yield make
    sys.path.remove(str(tmp_path))
    for name in [m for m in sys.modules if m.startswith("fakemods_")]:
        del sys.modules[name]


SPEC = "from app.core.modules import ModuleSpec\nmodule = ModuleSpec(name={name!r})\n"


def test_discovers_every_module_sorted(
    fake_modules: Callable[[dict[str, str]], ModuleType],
) -> None:
    package = fake_modules({"zeta": SPEC.format(name="zeta"), "alpha": SPEC.format(name="alpha")})
    assert [spec.name for spec in discover_modules(package)] == ["alpha", "zeta"]


def test_discovers_the_real_system_module() -> None:
    assert "system" in [spec.name for spec in discover_modules()]


def test_package_without_spec_is_rejected(
    fake_modules: Callable[[dict[str, str]], ModuleType],
) -> None:
    package = fake_modules({"broken": "router = None\n"})
    with pytest.raises(ModuleRegistrationError, match="must define `module = ModuleSpec"):
        discover_modules(package)


def test_spec_name_must_match_package(fake_modules: Callable[[dict[str, str]], ModuleType]) -> None:
    package = fake_modules({"tickets": SPEC.format(name="work_items")})
    with pytest.raises(ModuleRegistrationError, match="must equal the package name"):
        discover_modules(package)


def test_duplicate_names_are_rejected() -> None:
    with pytest.raises(ModuleRegistrationError, match="duplicate"):
        ModuleRegistry.from_specs([ModuleSpec(name="a"), ModuleSpec(name="a")])


async def test_hooks_routers_and_event_handlers_are_wired(
    settings_factory: Callable[..., Settings], run_app: Callable[[FastAPI], Any]
) -> None:
    calls: list[str] = []

    def hook(label: str) -> Callable[[FastAPI], Any]:
        async def run(_app: FastAPI) -> None:
            calls.append(label)

        return run

    async def on_created(_event: Mapping[str, Any]) -> None:
        return None

    first_router = APIRouter(prefix="/first")

    @first_router.get("/ping")
    async def ping() -> dict[str, str]:
        return {"module": "first"}

    registry = ModuleRegistry.from_specs(
        [
            ModuleSpec(
                name="first",
                routers=[first_router],
                on_startup=[hook("first.start")],
                on_shutdown=[hook("first.stop.1"), hook("first.stop.2")],
                event_handlers={"tickets.created": [on_created]},
            ),
            ModuleSpec(
                name="second",
                on_startup=[hook("second.start")],
                on_shutdown=[hook("second.stop")],
                event_handlers={"tickets.created": [on_created], "sla.breached": [on_created]},
            ),
        ]
    )
    app = create_app(settings_factory(), registry)
    async with run_app(app) as client:
        assert calls == ["first.start", "second.start"]
        assert (await client.get("/api/v1/first/ping")).json() == {"module": "first"}

    assert calls[2:] == ["second.stop", "first.stop.2", "first.stop.1"]
    assert {k: len(v) for k, v in app.state.event_handlers.items()} == {
        "tickets.created": 2,
        "sla.breached": 1,
    }
