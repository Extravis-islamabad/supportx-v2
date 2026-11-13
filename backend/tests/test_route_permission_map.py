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
    assert "| technician | `incidents.view` | group, own | all, own |" in page
