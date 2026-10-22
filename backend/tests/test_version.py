import tomllib
from pathlib import Path

from app import __version__


def test_app_version_matches_pyproject() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject.open("rb") as f:
        assert tomllib.load(f)["project"]["version"] == __version__
