"""Export the Core API's OpenAPI 3.1 document (architecture.md §10; WP-004).

`make openapi` writes frontend/packages/api-client/openapi.json, the input for the generated
TypeScript client (WP-010). `make openapi-check` (run in CI) fails when the committed file is out
of date, so an API change cannot merge without its contract.

Both modes also refuse a document where two models share a class name: FastAPI then names the
schemas by their full module path (`app__modules__knowledge__api__routes__SettingsOut`), and the
generated client silently changes the type an existing `components["schemas"]["SettingsOut"]`
points at. Rename one of the models instead (e.g. `KnowledgeSettingsOut`).

Usage: python -m tooling.export_openapi [--check] <output.json>
"""

import json
import sys
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.main import create_app


def build_schema() -> dict[str, Any]:
    """OpenAPI document of the app as configured for development (docs enabled)."""
    settings = Settings.load(
        env_file=None, profile="test", api_docs_enabled=True, tracing_enabled=False
    )
    return create_app(settings).openapi()


def name_clashes(schema: dict[str, Any]) -> list[str]:
    """Schemas FastAPI renamed by module path because two models share a class name."""
    names = schema.get("components", {}).get("schemas", {})
    return sorted(name for name in names if "__" in name)


def render(schema: dict[str, Any]) -> str:
    """Stable, diff-friendly JSON (sorted keys, trailing newline)."""
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    """Write the schema, or with --check compare it against the file and fail if they differ."""
    check = "--check" in argv
    paths = [arg for arg in argv if arg != "--check"]
    if len(paths) != 1:
        sys.stderr.write("usage: python -m tooling.export_openapi [--check] <output.json>\n")
        return 2
    target = Path(paths[0])
    schema = build_schema()
    clashes = name_clashes(schema)
    if clashes:
        sys.stderr.write(
            "Two API models share a class name; rename one so each schema name is unique:\n"
            + "".join(f"  {name}\n" for name in clashes)
        )
        return 1
    rendered = render(schema)
    if check:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current != rendered:
            sys.stderr.write(f"{target} is out of date. Run `make openapi` and commit it.\n")
            return 1
        sys.stdout.write(f"{target} is up to date.\n")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    sys.stdout.write(f"Wrote {target}.\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main(sys.argv[1:]))
