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
    CHANGE_MANAGER,
    RELEASE_MANAGER,
    SERVICE_DESK_MANAGER,
    SYSTEM_ROLES,
    TEAM_LEAD,
    TECHNICIAN,
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


# Haider (D-153, 2026-11-10): the service desk manager configures the desk, never the tenant.
DESK_CONFIGURATION = frozenset(
    {
        "config.service_desk",  # incident and request setup: categories, templates, statuses
        "sla.manage",  # SLAs
        "automation.manage",  # business rules and routing
        "config.announcements",  # the desk's portal content and announcements
        "announcements.manage",
        "dashboards.create",  # desk views and dashboards
        "dashboards.share",
    }
)
TENANT_WIDE = frozenset(
    {
        "settings.manage",
        "identity.manage",  # sign-in and security
        "api_keys.manage",
        "integrations.manage_email",  # integrations
        "integrations.manage_identity",
        "mailboxes.manage",
        "users.manage",  # people and their import
        "roles.manage",
        "licence.manage",
        "branding.manage",
        "config.organisation",
        "audit.manage",
        "changes.manage_boards",  # change boards: the change manager and admins only (#327)
        "changes.emergency_override",
        "changes.manage_windows",  # change windows and the freeze override (WP-045c)
        "changes.override_freeze",
        "releases.override_freeze",  # a release's freeze override (WP-058b S2)
    }
)


def test_the_service_desk_manager_configures_the_desk_and_nothing_tenant_wide() -> None:
    catalogue = _catalogue()
    assert set(catalogue.permissions) >= TENANT_WIDE  # every refused right still exists
    for technician_scope in ("group", "all"):
        keys = {
            k
            for k, _ in catalogue.system_grants(
                SERVICE_DESK_MANAGER, technician_scope=technician_scope
            )
        }
        assert keys >= DESK_CONFIGURATION, sorted(DESK_CONFIGURATION - keys)
        assert keys.isdisjoint(TENANT_WIDE), sorted(keys & TENANT_WIDE)


def test_change_boards_and_the_override_belong_to_the_change_manager() -> None:
    grants = dict(_catalogue().system_grants(CHANGE_MANAGER))
    assert grants.get("changes.manage_boards") == "all"
    assert grants.get("changes.emergency_override") == "all"


def test_change_windows_and_the_freeze_override_belong_to_the_change_manager_and_admins() -> None:
    """WP-045c (lane B's review): the change manager holds both; administrators hold every
    permission, so they may pass a freeze too, as with the emergency override (D-144); no team
    lead or technician holds either, whatever the technicians' scope.
    """
    catalogue = _catalogue()
    manager = dict(catalogue.system_grants(CHANGE_MANAGER))
    assert (manager.get("changes.manage_windows"), manager.get("changes.override_freeze")) == (
        "all",
        "all",
    )
    admin = dict(catalogue.system_grants(TENANT_ADMIN))
    assert {"changes.manage_windows", "changes.override_freeze"} <= admin.keys()
    for role in (TEAM_LEAD, TECHNICIAN):
        for technician_scope in ("group", "all"):
            held = dict(catalogue.system_grants(role, technician_scope=technician_scope))
            assert held.keys().isdisjoint({"changes.manage_windows", "changes.override_freeze"}), (
                role,
                technician_scope,
            )


def test_a_releases_freeze_override_belongs_to_the_release_manager_and_admins() -> None:
    """WP-058b S2 (the coordinator; lane B's review): as a change's, the release manager and
    administrators hold it; no technician, team lead or service desk manager does.
    """
    catalogue = _catalogue()
    assert dict(catalogue.system_grants(RELEASE_MANAGER)).get("releases.override_freeze") == "all"
    assert "releases.override_freeze" in dict(catalogue.system_grants(TENANT_ADMIN))
    for role in (TEAM_LEAD, TECHNICIAN, SERVICE_DESK_MANAGER):
        for technician_scope in ("group", "all"):
            held = dict(catalogue.system_grants(role, technician_scope=technician_scope))
            assert "releases.override_freeze" not in held, (role, technician_scope)


def test_no_role_assigns_outside_a_records_group() -> None:
    """D-154a: the right is gone for every type, so no built-in role can hold it."""
    catalogue = _catalogue()
    assert not [k for k in catalogue.permissions if k.endswith(".assign_outside_group")]
    # The checked-in snapshot too (#347: a pre-merge snapshot re-added it for the release
    # manager), so a stale matrix cannot carry it unnoticed.
    snapshot: dict[str, dict[str, list[str]]] = json.loads(MATRIX.read_text())
    held = [
        (role, key)
        for role, grants in snapshot.items()
        for key in grants
        if key.endswith(".assign_outside_group")
    ]
    assert held == []


def test_a_team_lead_works_its_groups_changes_and_views_the_others() -> None:
    """D-153 (Haider, option a): a technician's change work, in its groups only; no boards."""
    catalogue = _catalogue()
    for technician_scope in ("group", "all"):
        grants = dict(catalogue.system_grants(TEAM_LEAD, technician_scope=technician_scope))
        assert grants.get("changes.view") == "all"
        assert grants.get("changes.create") == "all"  # raises one anywhere, like a technician
        for action in ("edit", "assign", "close"):
            assert grants.get(f"changes.{action}") == "group", action
        working = {
            k: s
            for k, s in grants.items()
            if k.startswith("changes.") and k not in {"changes.view", "changes.create"}
        }
        assert working, "a team lead works changes"
        assert set(working.values()) <= {"group", "own"}, working
        assert grants.keys().isdisjoint(
            {
                "changes.manage_boards",
                "changes.emergency_override",
                "changes.approve",
                "changes.manage_windows",
                "changes.override_freeze",
            }
        )
        assert grants.keys().isdisjoint(TENANT_WIDE)
