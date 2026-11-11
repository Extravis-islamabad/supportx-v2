"""Custom functions in workflows: the runner port only (WP-048b S2; REQ-WF-021; §6.7; ADR-011).

A workflow's function node never runs code in the API process (architecture.md §6.7). The node
writes a request to the outbox; automation's worker consumer hands it to the installation's
runner through this port and reports the result back to the node. Which sandbox runs the code is
the product owner's call (ADR-011), so no runner ships here: an installation registers one.

The node is offered only when the tenant's plan has both SANDBOX and CUSTOM_FUNCTIONS (the
entitlement interface, rule f) and a runner is registered; otherwise validation says so when the
workflow is saved, and a request that arrives anyway is refused with a stable code.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from app.modules import licensing
from app.modules.automation.domain.rules import JsonValue

NOT_OFFERED = "function_not_offered"


@dataclass(frozen=True)
class FunctionOutcome:
    """What a function returned: its outputs by name, or a stable refusal code."""

    ok: bool
    outputs: Mapping[str, JsonValue] = field(default_factory=dict)
    error: str | None = None


class FunctionRunner(Protocol):
    """Runs one tenant's named function with its inputs, within the timeout, outside the API."""

    async def run(
        self,
        *,
        tenant_id: uuid.UUID,
        function: str,
        inputs: Mapping[str, JsonValue],
        timeout_seconds: int,
    ) -> FunctionOutcome:
        """The function's outputs, or a stable refusal code (never an exception)."""
        ...


_runner: FunctionRunner | None = None


def register_function_runner(runner: FunctionRunner | None) -> None:
    """The installation's runner (None removes it, e.g. in tests)."""
    global _runner  # noqa: PLW0603 - the process's one registered runner, as the other ports
    _runner = runner


def function_runner() -> FunctionRunner | None:
    """The registered runner, if any."""
    return _runner


async def offered(tenant_id: uuid.UUID) -> bool:
    """Whether a function node may be used: a runner here, and both features on the plan."""
    if _runner is None:
        return False
    return await licensing.has_feature(
        tenant_id, licensing.Feature.SANDBOX
    ) and await licensing.has_feature(tenant_id, licensing.Feature.CUSTOM_FUNCTIONS)
