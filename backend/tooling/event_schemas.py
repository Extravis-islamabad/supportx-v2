"""Export event schemas and refuse breaking changes to a published event version (WP-007).

    python -m tooling.event_schemas write FILE           # make events-schemas
    python -m tooling.event_schemas check FILE           # make events-check (backend-lint, CI)
    python -m tooling.event_schemas check FILE --base B  # CI: B = the file on the target branch

`check` fails when FILE is not what `write` would produce now (forgot to export), and when any
event version in the baseline (FILE itself, or `--base`) changed incompatibly. CI passes the
target branch's copy as `--base`, so regenerating the file cannot hide a breaking change.

Allowed within one version (additive): new OPTIONAL payload fields, description/title edits, new
event types, new versions. Everything else is breaking: removing a version, removing or retyping a
field, adding a required field, making a required field optional or the reverse. A breaking change
is a new class with `schema_version + 1` (docs/architecture/events.md, "Versioning").
"""

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.core.modules import discover_modules
from app.shared.events import EventEnvelope, EventRegistry

FORMAT = 1
_COSMETIC = frozenset({"title", "description", "examples"})


def current_schemas() -> dict[str, Any]:
    """Schemas of the envelope and every registered event version, from the code."""
    registry = EventRegistry.from_modules(discover_modules())
    events: dict[str, dict[str, Any]] = {}
    for (event_type, version), model in registry:
        events.setdefault(event_type, {})[str(version)] = model.model_json_schema()
    return {"format": FORMAT, "envelope": EventEnvelope.model_json_schema(), "events": events}


def render(schemas: Mapping[str, Any]) -> str:
    """Stable text form (sorted keys, trailing newline) so diffs are reviewable."""
    return json.dumps(schemas, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _strip(value: Any) -> Any:  # noqa: ANN401 - arbitrary JSON Schema
    """The schema without cosmetic keys, recursively."""
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in _COSMETIC}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def compare_object(name: str, old: Mapping[str, Any], new: Mapping[str, Any]) -> list[str]:
    """Breaking differences between two object schemas of the same event version."""
    problems: list[str] = []
    old_props: Mapping[str, Any] = old.get("properties", {})
    new_props: Mapping[str, Any] = new.get("properties", {})
    for field, schema in old_props.items():
        if field not in new_props:
            problems.append(f"{name}: field {field!r} was removed")
        elif _strip(schema) != _strip(new_props[field]):
            problems.append(f"{name}: field {field!r} changed type or constraints")
    old_required, new_required = set(old.get("required", [])), set(new.get("required", []))
    problems.extend(
        f"{name}: field {field!r} became required" for field in sorted(new_required - old_required)
    )
    problems.extend(
        f"{name}: required field {field!r} became optional"
        for field in sorted((old_required - new_required) & set(new_props))
    )
    old_defs: Mapping[str, Any] = old.get("$defs", {})
    new_defs: Mapping[str, Any] = new.get("$defs", {})
    for definition, schema in old_defs.items():
        if definition in new_defs and _strip(schema) != _strip(new_defs[definition]):
            problems.append(f"{name}: shared definition {definition!r} changed")
    structural = {"properties", "required", "$defs"} | _COSMETIC
    rest = {k for k in set(old) | set(new) if k not in structural}
    if any(_strip(old.get(k)) != _strip(new.get(k)) for k in rest):
        problems.append(f"{name}: schema options changed")
    return problems


def breaking_changes(base: Mapping[str, Any], now: Mapping[str, Any]) -> list[str]:
    """Every breaking change from `base` to `now`."""
    problems = compare_object("envelope", base.get("envelope", {}), now.get("envelope", {}))
    now_events: Mapping[str, Mapping[str, Any]] = now.get("events", {})
    for event_type, versions in base.get("events", {}).items():
        for version, schema in versions.items():
            current = now_events.get(event_type, {}).get(version)
            label = f"{event_type} v{version}"
            if current is None:
                problems.append(f"{label}: version was removed (published versions are forever)")
            else:
                problems.extend(compare_object(label, schema, current))
    return problems


def main(argv: list[str]) -> int:
    """CLI (see module docstring)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["write", "check"])
    parser.add_argument("file", type=Path)
    parser.add_argument("--base", type=Path, help="baseline file (default: FILE itself)")
    args = parser.parse_args(argv)
    now = current_schemas()
    if args.command == "write":
        args.file.write_text(render(now), encoding="utf-8")
        sys.stdout.write(f"wrote {args.file}\n")
        return 0
    failures: list[str] = []
    committed = args.file.read_text(encoding="utf-8") if args.file.is_file() else ""
    if committed != render(now):
        failures.append(f"{args.file} is out of date: run `make events-schemas` and commit it")
    base_file: Path = args.base or args.file
    if base_file.is_file():
        failures.extend(breaking_changes(json.loads(base_file.read_text(encoding="utf-8")), now))
    for failure in failures:
        sys.stderr.write(f"FAIL {failure}\n")
    if not failures:
        sys.stdout.write("event schemas: up to date, no breaking changes\n")
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main(sys.argv[1:]))
