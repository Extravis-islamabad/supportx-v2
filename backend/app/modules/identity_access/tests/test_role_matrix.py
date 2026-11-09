"""Every built-in role holds exactly its row of the role table (D-152, D-153), nothing more.

The computed grants of each system role, from the real catalogue (every module's permissions and
their defaults), are compared with `role_matrix.json`. A new permission, or a new default for a
role, changes the matrix and fails here until the file is updated on purpose:

    SUPPORTX_UPDATE_ROLE_MATRIX=1 uv run pytest <this file>

Both answers to the tenant's first-run question (technicians see their groups, or everything) are
pinned, since they widen the technician's defaults.
"""

import json
import os
from pathlib import Path

import pytest

from app.core.modules import discover_modules
from app.modules.identity_access.domain.permissions import (
    SYSTEM_ROLES,
    TEAM_LEAD,
    TENANT_ADMIN,
    Catalogue,
)

MATRIX = Path(__file__).with_name("role_matrix.json")


def _catalogue() -> Catalogue:
    specs = [p for m in discover_modules() for p in m.permissions]
    return Catalogue.build(specs, frozenset(s.feature for s in specs if s.feature))


def _matrix(catalogue: Catalogue) -> dict[str, dict[str, list[str]]]:
    found: dict[str, dict[str, list[str]]] = {}
    for technician_scope in ("group", "all"):
        for role in SYSTEM_ROLES:
            if role == TENANT_ADMIN:
                continue  # everything, at its broadest: computed from the catalogue itself
            grants = catalogue.system_grants(role, technician_scope=technician_scope)
            found[f"{role}@{technician_scope}"] = {
                key: sorted({s for k, s in grants if k == key})
                for key in sorted({k for k, _ in grants})
            }
    return found


def test_every_built_in_role_holds_exactly_its_row() -> None:
    found = _matrix(_catalogue())
    if os.environ.get("SUPPORTX_UPDATE_ROLE_MATRIX") == "1":
        MATRIX.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip("role matrix rewritten: review the diff")
    assert found == json.loads(MATRIX.read_text(encoding="utf-8"))


def test_the_tenant_admin_holds_every_permission_at_its_broadest() -> None:
    catalogue = _catalogue()
    grants = dict(catalogue.system_grants(TENANT_ADMIN))
    assert grants == {key: spec.scopes[0] for key, spec in catalogue.permissions.items()}


def test_a_team_lead_works_only_its_groups_and_changes_no_settings() -> None:
    """D-152: group-scoped records, its own groups' management, no tenant settings."""
    catalogue = _catalogue()
    for technician_scope in ("group", "all"):
        grants = catalogue.system_grants(TEAM_LEAD, technician_scope=technician_scope)
        for key, scope in grants:
            family, action = key.split(".", 1)
            if family in {"incidents", "requests", "problems"} and action not in {
                "create",
                "approve",
            }:
                assert scope in {"group", "own"}, (key, scope)
        keys = {k for k, _ in grants}
        assert "groups.manage_own" in keys
        assert keys.isdisjoint(
            {"groups.manage", "settings.manage", "users.manage", "roles.manage", "assets.manage"}
        )
        assert {"changes.view", "assets.view", "cmdb.view"} <= keys
