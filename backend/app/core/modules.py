"""Module registry (architecture.md §6.1; WP-004). See app/modules/README.md.

Every package under `app/modules/` exposes one `module = ModuleSpec(...)` in its `__init__.py`.
The app factory discovers them, mounts their routers under /api/v1 and runs their startup and
shutdown hooks in the lifespan. Their event classes form the event registry and their consumers
run in the consumer worker (WP-007, app/shared/events). Adding a module therefore never requires
editing main.py or the workers.
"""

import importlib
import pkgutil
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType, ModuleType

from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.entitlements import route_guard

LifecycleHook = Callable[[FastAPI], Awaitable[None]]
# Counts what a module owns for a counted licence limit (e.g. active technicians), inside the
# caller's tenant session. See app/modules/licensing and docs/architecture/entitlements.md.
UsageCounter = Callable[[AsyncSession], Awaitable[int]]

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
    # DomainEvent subclasses this module publishes (app/shared/events; core cannot import shared,
    # so the types are checked when the event registry is built).
    events: Sequence[type] = ()
    # ConsumerSpec instances (app/shared/events/consumers.py), validated by the consumer worker.
    consumers: Sequence[object] = ()
    # Licence feature key this module needs (WP-009), e.g. "change". Every route of the module is
    # then refused with 403 `entitlement_required` for tenants whose plan lacks it. None = core
    # platform module, available in every edition. Checked against the feature catalogue at startup.
    feature: str | None = None
    # Counted licence limits this module owns the numbers for: limit key -> counter.
    usage_counters: Mapping[str, UsageCounter] = field(default_factory=lambda: MappingProxyType({}))


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
        """Mount every module's routers on `router` (the /api/v1 router).

        Each route gets the entitlement guard for the module's feature (app/core/entitlements.py),
        so a module is gated by declaring `feature=` and its routes need no code for it.
        """
        for spec in self.modules:
            guard = Depends(route_guard(spec.feature))
            for module_router in spec.routers:
                router.include_router(module_router, dependencies=[guard])

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
