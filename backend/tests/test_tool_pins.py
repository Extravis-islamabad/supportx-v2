"""Every tool CI uses is pinned to an exact version (product owner, 2026-10-28).

An upstream release must never change a build: pnpm 12.16.1 came out and every PR's pre-commit
failed (#119). Tools change only through a deliberate PR (Dependabot proposes them weekly). This
test fails when a version is left floating, or when two places that must agree drift apart.
"""

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GITHUB = ROOT / ".github"
EXACT = re.compile(r"^\d+\.\d+\.\d+$")
SHA = re.compile(r"^[0-9a-f]{40}$")


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _workflow_files() -> list[Path]:
    return sorted([*GITHUB.rglob("*.yml"), *GITHUB.rglob("*.yaml")])


def test_node_is_exact_and_the_web_image_uses_it() -> None:
    node = _read(".nvmrc").strip()
    assert EXACT.match(node), f".nvmrc must name an exact Node version, not {node!r}"
    image = re.search(r"ARG NODE_IMAGE=node:([\d.]+)-", _read("deploy/images/web.Dockerfile"))
    assert image is not None
    assert image.group(1) == node, "web.Dockerfile's Node and .nvmrc must agree"


def test_python_is_exact_everywhere() -> None:
    python = _read("backend/.python-version").strip()
    assert EXACT.match(python), f"backend/.python-version must be exact, not {python!r}"
    setup = re.search(
        r'python-version: "([^"]+)"', _read(".github/actions/setup-backend/action.yml")
    )
    assert setup is not None
    assert setup.group(1) == python, "CI's Python and backend/.python-version must agree"
    image = re.search(
        r"ARG PYTHON_IMAGE=python:([\d.]+)-", _read("deploy/images/backend.Dockerfile")
    )
    assert image is not None
    # Same minor version: the image follows the official Python images, CI the newest patch
    # the pinned uv can install (3.12.14 with uv 0.12.19); both are exact, neither floats.
    assert EXACT.match(image.group(1))
    assert image.group(1).rsplit(".", 1)[0] == python.rsplit(".", 1)[0]
    requires = tomllib.loads(_read("backend/pyproject.toml"))["project"]["requires-python"]
    assert requires == ">=3.12,<3.13"
    assert python.startswith("3.12.")


def test_pnpm_is_pinned_where_corepack_looks_from_anywhere() -> None:
    root = json.loads(_read("package.json"))["packageManager"]
    frontend = json.loads(_read("frontend/package.json"))["packageManager"]
    assert root == frontend, "the repo-root and frontend pnpm pins must agree"
    name, _, version = root.partition("@")
    assert name == "pnpm"
    assert EXACT.match(version.split("+")[0]), f"pnpm must be exact, not {version!r}"
    assert "COREPACK_DEFAULT_TO_LATEST=0" in _read(".github/actions/setup-frontend/action.yml")


def test_uv_is_exact_in_ci_and_the_image() -> None:
    setup = re.search(r'version: "([^"]+)"', _read(".github/actions/setup-backend/action.yml"))
    assert setup is not None
    assert EXACT.match(setup.group(1))
    image = re.search(
        r"ARG UV_IMAGE=ghcr\.io/astral-sh/uv:([\d.]+)", _read("deploy/images/backend.Dockerfile")
    )
    assert image is not None
    assert image.group(1) == setup.group(1), "CI's uv and the image's uv must agree"


def test_every_action_is_pinned_by_commit_sha() -> None:
    loose = []
    for path in _workflow_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            found = re.search(r"uses:\s*([^\s#]+)", line)
            if found is None or found.group(1).startswith("./"):
                continue
            _, _, ref = found.group(1).partition("@")
            if not SHA.match(ref):
                loose.append(f"{path.relative_to(ROOT)}:{number}: {found.group(1)}")
    assert loose == [], "pin actions by commit SHA (version in a comment)"


def test_pre_commit_hook_repositories_are_pinned_by_commit_sha() -> None:
    revs = re.findall(r"^\s+rev:\s*(\S+)", _read(".pre-commit-config.yaml"), re.MULTILINE)
    assert revs, "the pre-commit config has remote hooks"
    assert all(SHA.match(rev) for rev in revs), f"pin hook repositories by SHA: {revs}"


def test_nothing_floats_on_latest() -> None:
    floating = re.compile(r"(:latest\b|@latest\b)")
    found = [
        f"{path.relative_to(ROOT)}:{number}"
        for path in [*_workflow_files(), ROOT / "Makefile", ROOT / ".pre-commit-config.yaml"]
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if floating.search(line) and not line.lstrip().startswith("#")
    ]
    assert found == [], "name an exact version instead of latest"
