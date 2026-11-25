"""The committed route-permission map matches the code (D-168).

docs/security/route-permissions.md is code-owned instead of every module's api/ folder, so it
must change whenever a route's access or a role's permissions change: regenerated in memory here,
no database or Docker needed.
"""

from pathlib import Path

import pytest

from tooling import route_permissions

STALE = "run make route-permissions and commit the result (D-168: the map is code-owned)"


@pytest.fixture(scope="module")
def page() -> str:
    """Generated once per module: building the app takes a few seconds."""
    return route_permissions.generate()


def _check(committed: Path, page: str) -> None:
    assert committed.exists(), STALE
    assert committed.read_text(encoding="utf-8") == page, STALE


def test_the_committed_map_matches_the_code(page: str) -> None:
    _check(route_permissions.TARGET, page)


def test_a_stale_map_fails_with_the_fix(tmp_path: Path, page: str) -> None:
    stale = tmp_path / "route-permissions.md"
    stale.write_text(page.replace("| GET |", "| PUT |", 1), encoding="utf-8")
    with pytest.raises(AssertionError, match="run make route-permissions"):
        _check(stale, page)
    with pytest.raises(AssertionError, match="run make route-permissions"):
        _check(tmp_path / "missing.md", page)


def test_the_map_lists_routes_and_roles(page: str) -> None:
    assert "| GET | `/api/v1/users` | `users.view` |" in page
    assert "| GET | `/api/v1/health` | public | - |" in page
    # Public to the permission guard, but behind the BFF's own session check: never shown 'public'.
    assert "| POST | `/api/v1/auth/logout` | session (BFF) | - |" in page
    assert "| GET | `/api/v1/auth/login` | public | - |" in page
    assert "| technician | `incidents.view` | group, own | all, own |" in page


# The Feature column (#578's follow-up, lane C): where each route's licence gate is declared.


@pytest.fixture(scope="module")
def features() -> dict[str, str]:
    """Generated once per module: building the app takes a few seconds."""
    return route_permissions.feature_table(
        route_permissions.build_app(), route_permissions.build_catalogue()
    )


def test_the_feature_column_names_the_level_that_gates(features: dict[str, str]) -> None:
    # A module's feature, which its permissions also name.
    assert features["GET /api/v1/changes"] == "`change` (module, permission)"
    # A single route narrower than its router (`requires_feature`); its list is not gated.
    assert features["POST /api/v1/audit/siem/destinations"] == "`siem_stream` (route)"
    assert features["PATCH /api/v1/audit/siem/destinations/{destination_id}"] == (
        "`siem_stream` (route)"
    )
    assert features["GET /api/v1/audit/siem/destinations"] == "-"
    # Every route has a cell, and the health probe needs no plan.
    assert features["GET /api/v1/health"] == "-"


def test_every_named_feature_is_a_licence_feature(features: dict[str, str]) -> None:
    from app.modules.licensing import Feature  # noqa: PLC0415 - this test only

    known = {f.value for f in Feature}
    named = {
        part.split("`")[1] for cell in features.values() if cell != "-" for part in cell.split("; ")
    }
    assert named <= known, named - known
