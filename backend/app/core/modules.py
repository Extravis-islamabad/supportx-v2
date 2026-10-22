"""Module registry (architecture.md §6.1; WP-004). See app/modules/README.md.

Every package under `app/modules/` exposes one `module = ModuleSpec(...)` in its `__init__.py`.
The app factory discovers them, mounts their routers under /api/v1, runs their startup and
shutdown hooks in the lifespan, and collects their event handlers for the event bus (WP-007).
Adding a module therefore never requires editing main.py.
"""

import importlib
import pkgutil
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

from fastapi import APIRouter, FastAPI

LifecycleHook = Callable[[FastAPI], Awaitable[None]]
# Event payload typing arrives with the event envelope in WP-007.
EventHandler = Callable[[Mapping[str, Any]], Awaitable[None]]

MODULES_PACKAGE = "app.modules"


class ModuleRegistrationError(RuntimeError):
    """A package under app/modules/ does not declare a valid ModuleSpec."""


@dataclass(frozen=True)
class ModuleSpec:
    """Everything a module contributes to the running app."""

    name: str
    routers: Sequence[APIRouter] = ()
    on_startup: Sequence[LifecycleHook] = ()
    on_shutdown: Sequence[LifecycleHook] = ()
    # Event type (e.g. "work_items.created") -> handlers. Consumed by the outbox relay in WP-007.
    event_handlers: Mapping[str, Sequence[EventHandler]] = field(default_factory=dict)


def discover_modules(package: ModuleType | None = None) -> list[ModuleSpec]:
    """Import every sub-package of `package` (default app.modules) and return their specs.

    Specs are sorted by name so startup order is deterministic.
    """
    root = package or importlib.import_module(MODULES_PACKAGE)
    specs: list[ModuleSpec] = []
    for info in pkgutil.iter_modules(root.__path__):
        if not info.ispkg:
            continue
        imported = importlib.import_module(f"{root.__name__}.{info.name}")
        spec = getattr(imported, "module", None)
        if not isinstance(spec, ModuleSpec):
            msg = f"{imported.__name__} must define `module = ModuleSpec(...)` in __init__.py"
            raise ModuleRegistrationError(msg)
        if spec.name != info.name:
            msg = f"{imported.__name__}: ModuleSpec.name {spec.name!r} must equal the package name"
            raise ModuleRegistrationError(msg)
        specs.append(spec)
    return sorted(specs, key=lambda s: s.name)


@dataclass(frozen=True)
class ModuleRegistry:
    """The modules of one app instance, plus the operations the app factory needs."""

    modules: Sequence[ModuleSpec]

    def include_routers(self, router: APIRouter) -> None:
        """Mount every module's routers on `router` (the /api/v1 router)."""
        for spec in self.modules:
            for module_router in spec.routers:
                router.include_router(module_router)

    async def start(self, app: FastAPI) -> None:
        """Run startup hooks in module order."""
        for spec in self.modules:
            for hook in spec.on_startup:
                await hook(app)

    async def stop(self, app: FastAPI) -> None:
        """Run shutdown hooks in reverse module order (last started, first stopped)."""
        for spec in reversed(self.modules):
            for hook in reversed(spec.on_shutdown):
                await hook(app)

    def event_handlers(self) -> dict[str, list[EventHandler]]:
        """All handlers per event type across modules."""
        merged: dict[str, list[EventHandler]] = {}
        for spec in self.modules:
            for event_type, handlers in spec.event_handlers.items():
                merged.setdefault(event_type, []).extend(handlers)
        return merged

    @classmethod
    def from_specs(cls, specs: Iterable[ModuleSpec]) -> "ModuleRegistry":
        """Registry from explicit specs (tests, or a subset of modules)."""
        specs = list(specs)
        names = [s.name for s in specs]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            msg = f"duplicate module names: {sorted(duplicates)}"
            raise ModuleRegistrationError(msg)
        return cls(modules=tuple(specs))
