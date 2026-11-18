"""D-174's mobile bundle check can fail: fixture source maps, with and without picomatch."""

import json
from pathlib import Path

import pytest

from tooling import bundle_sources

CLEAN = ["../../node_modules/react/index.js", "app/(tabs)/index.tsx"]
PNPM_PICOMATCH = "../../node_modules/.pnpm/picomatch@2.3.2/node_modules/picomatch/lib/parse.js"


def _map(directory: Path, name: str, sources: object) -> None:
    path = directory / "_expo" / "static" / "js" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 3, "sources": sources, "mappings": ""}), "utf-8")


def test_a_clean_bundle_passes(tmp_path: Path) -> None:
    _map(tmp_path, "android.map", CLEAN)
    _map(tmp_path, "ios.map", CLEAN)
    assert bundle_sources.main([str(tmp_path)]) == 0
    assert bundle_sources.check(tmp_path).sources == 4


@pytest.mark.parametrize(
    "source",
    [PNPM_PICOMATCH, "node_modules/picomatch/index.js", "C:\\app\\node_modules\\picomatch\\x.js"],
)
def test_picomatch_in_a_bundle_fails(tmp_path: Path, source: str) -> None:
    _map(tmp_path, "android.map", CLEAN)
    _map(tmp_path, "ios.map", [*CLEAN, source])
    assert bundle_sources.main([str(tmp_path)]) == 1
    assert bundle_sources.check(tmp_path).forbidden == [source]


def test_no_maps_fails(tmp_path: Path) -> None:
    assert bundle_sources.main([str(tmp_path)]) == 1


@pytest.mark.parametrize("sources", [[], None, "not a list"])
def test_a_map_without_sources_fails(tmp_path: Path, sources: object) -> None:
    _map(tmp_path, "android.map", CLEAN)
    _map(tmp_path, "ios.map", sources)
    assert bundle_sources.main([str(tmp_path)]) == 1


def test_an_unreadable_map_fails(tmp_path: Path) -> None:
    _map(tmp_path, "android.map", CLEAN)
    (tmp_path / "_expo" / "static" / "js" / "ios.map").write_text("{not json", "utf-8")
    assert bundle_sources.main([str(tmp_path)]) == 1


def test_a_lookalike_name_passes(tmp_path: Path) -> None:
    """Only the package itself counts, not a file that merely mentions it."""
    _map(tmp_path, "android.map", [*CLEAN, "app/utils/picomatch-notes.ts"])
    assert bundle_sources.main([str(tmp_path)]) == 0
