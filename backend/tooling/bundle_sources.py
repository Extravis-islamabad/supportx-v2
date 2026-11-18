"""`make mobile-bundle-check`: no source of a forbidden package in the shipped mobile bundles.

D-174 accepts picomatch's advisory (CVE-2026-112366 / GHSA-fc5q-39xc-vjpf, no fixed release) for
`mobile/pnpm-lock.yaml` only while picomatch never reaches the app. The production bundles are
exported with source maps; a map's `sources` names every original file Metro bundled, however
minified the code is. This reads them and fails if any comes from `node_modules/picomatch/`.

It fails closed: no map, a map without a readable non-empty `sources` list, or invalid JSON is an
error, never a pass.

    uv run python -m tooling.bundle_sources <the export directory>
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN = ("node_modules/picomatch/",)


class BundleCheckError(Exception):
    """The bundles could not be checked: treated as a failure, never as a pass."""


@dataclass(frozen=True)
class Result:
    """How many bundled sources were read, and those from a forbidden package."""

    sources: int
    forbidden: list[str]


def _sources(path: Path) -> list[str]:
    try:
        found = json.loads(path.read_text(encoding="utf-8")).get("sources")
    except (OSError, ValueError, AttributeError) as error:
        msg = f"{path}: not a readable source map ({error})"
        raise BundleCheckError(msg) from error
    if not isinstance(found, list) or not found:
        msg = f"{path}: no sources listed"
        raise BundleCheckError(msg)
    return [s for s in found if isinstance(s, str)]


def check(directory: Path) -> Result:
    """Every source map under `directory`; BundleCheckError when there is none or one is bad."""
    maps = sorted(p for p in directory.rglob("*.map") if p.is_file())
    if not maps:
        msg = f"{directory}: the export wrote no source maps"
        raise BundleCheckError(msg)
    total = 0
    forbidden: list[str] = []
    for path in maps:
        sources = _sources(path)
        total += len(sources)
        forbidden += [s for s in sources if any(f in s.replace("\\", "/") for f in FORBIDDEN)]
    return Result(total, forbidden)


def main(argv: list[str]) -> int:
    """Exit 0 only when every map was read and none names a forbidden package."""
    if len(argv) != 1:
        sys.stderr.write("usage: python -m tooling.bundle_sources <export directory>\n")
        return 2
    try:
        result = check(Path(argv[0]))
    except BundleCheckError as error:
        sys.stderr.write(f"D-174: {error}\n")
        return 1
    if result.forbidden:
        sys.stderr.write(
            f"D-174: picomatch is in the shipped mobile bundle ({len(result.forbidden)} sources, "
            f"e.g. {result.forbidden[0]}): remove the mobile Trivy ignore and fix it before any "
            "release\n"
        )
        return 1
    sys.stdout.write(
        f"D-174: picomatch is in no shipped mobile bundle ({result.sources} sources checked)\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
