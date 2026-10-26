"""Fail on breaking changes to the /api/v1 contract (architecture.md §10; WP-008).

    python -m tooling.openapi_diff BASE CURRENT     # CI: BASE = openapi.json on the target branch

Breaking (within a major version):
- an operation (path + method) disappears;
- a parameter disappears, or a new required parameter / required body field appears;
- a parameter or body field changes type, or an enum loses a value;
- a 2xx response loses a property or a property changes type;
- a required response property becomes optional (clients rely on it being there);
- a named schema in `components.schemas` disappears or is renamed (the generated TypeScript
  type of that name would vanish from packages/api-client).

Additive changes pass: new operations, new optional parameters and fields, new response
properties, new enum values (each has a label, rule 5d), wording. Breaking changes belong in
/api/v2 (§10 versioning).
"""

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_DEPTH = 8
METHODS = ("get", "put", "post", "patch", "delete")
_COSMETIC = frozenset({"title", "description", "examples", "example", "deprecated"})


class Resolver:
    """Follows local `$ref`s of one document."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        self.document = document

    def resolve(self, schema: Any) -> Any:  # noqa: ANN401 - JSON Schema
        """The schema a `$ref` points at (followed transitively), or `schema` itself."""
        seen = 0
        while isinstance(schema, dict) and "$ref" in schema and seen < 20:  # noqa: PLR2004 - loop guard
            node: Any = self.document
            for part in schema["$ref"].removeprefix("#/").split("/"):
                node = node.get(part) if isinstance(node, dict) else None
            if node is None:
                return None  # dangling reference: the missing schema is reported on its own
            schema, seen = node, seen + 1
        return schema


def _shape(schema: Any, resolver: Resolver, depth: int = 0) -> Any:  # noqa: ANN401 - JSON Schema
    """Comparable form of a schema: refs inlined (bounded), cosmetic keys dropped."""
    schema = resolver.resolve(schema)
    if depth > 6:  # noqa: PLR2004 - deep enough for our models, bounded for recursive ones
        return "…"
    if isinstance(schema, dict):
        return {k: _shape(v, resolver, depth + 1) for k, v in schema.items() if k not in _COSMETIC}
    if isinstance(schema, list):
        return [_shape(v, resolver, depth + 1) for v in schema]
    return schema


def _json_schema(container: Mapping[str, Any] | None) -> Any:  # noqa: ANN401 - JSON Schema
    content = (container or {}).get("content", {})
    for media in ("application/json", "application/problem+json"):
        if media in content:
            return content[media].get("schema")
    return None


def _param_key(parameter: Mapping[str, Any]) -> tuple[str, str]:
    return str(parameter.get("in")), str(parameter.get("name"))


def _compare_params(
    label: str, old: Mapping[str, Any], new: Mapping[str, Any], ro: Resolver, rn: Resolver
) -> list[str]:
    problems: list[str] = []
    old_params = {_param_key(p): p for p in old.get("parameters", [])}
    new_params = {_param_key(p): p for p in new.get("parameters", [])}
    for name, param in old_params.items():
        if name not in new_params:
            problems.append(f"{label}: parameter {name[1]!r} ({name[0]}) was removed")
        elif _shape(param.get("schema"), ro) != _shape(new_params[name].get("schema"), rn):
            problems.append(f"{label}: parameter {name[1]!r} changed type")
    for name, param in new_params.items():
        if name not in old_params and param.get("required"):
            problems.append(f"{label}: new required parameter {name[1]!r}")
    return problems


@dataclass(frozen=True)
class _Walk:
    """Compares one schema pair recursively with the additive rules for one direction."""

    ro: Resolver
    rn: Resolver
    response: bool  # True: the server sends it (may add fields); False: the client sends it

    def diff(self, label: str, old: Any, new: Any, depth: int = 0) -> list[str]:  # noqa: ANN401 - JSON Schema
        """Breaking differences between `old` and `new` at `label`."""
        old, new = self.ro.resolve(old) or {}, self.rn.resolve(new) or {}
        if depth > MAX_DEPTH or not isinstance(old, dict) or not isinstance(new, dict):
            return []
        if "properties" in old or "properties" in new:
            return self._object(label, old, new, depth)
        if "items" in old and "items" in new:
            return self.diff(f"{label}[]", old["items"], new["items"], depth + 1)
        for union in ("anyOf", "oneOf"):
            if union in old and union in new and len(old[union]) == len(new[union]):
                return [
                    problem
                    for a, b in zip(old[union], new[union], strict=True)
                    for problem in self.diff(label, a, b, depth + 1)
                ]
        return self._leaf(label, old, new)

    def _leaf(self, label: str, old: dict[str, Any], new: dict[str, Any]) -> list[str]:
        if "enum" in old and "enum" in new:
            # A new code is additive: every code has a label (rule 5d), so clients show it.
            # A code that disappears breaks callers that still send or expect it.
            if not set(old["enum"]) <= set(new["enum"]):
                return [f"{label} lost enum values"]
            old, new = {**old, "enum": []}, {**new, "enum": []}
        if _shape(old, self.ro) != _shape(new, self.rn):
            return [f"{label} changed type"]
        return []

    def _object(
        self, label: str, old: dict[str, Any], new: dict[str, Any], depth: int
    ) -> list[str]:
        problems: list[str] = []
        old_props, new_props = old.get("properties", {}), new.get("properties", {})
        old_required, new_required = set(old.get("required", [])), set(new.get("required", []))
        for field, schema in old_props.items():
            where = f"{label}.{field}"
            if field not in new_props:
                problems.append(f"{where} was removed")
            else:
                problems += self.diff(where, schema, new_props[field], depth + 1)
        if self.response:
            problems += [
                f"{label}.{f} became optional"
                for f in sorted((old_required - new_required) & set(new_props))
            ]
        else:
            problems += [
                f"{label}: new required field {f!r}" for f in sorted(new_required - old_required)
            ]
        return problems


def _compare_body(
    label: str, old: Mapping[str, Any], new: Mapping[str, Any], ro: Resolver, rn: Resolver
) -> list[str]:
    walk = _Walk(ro, rn, response=False)
    return walk.diff(
        f"{label}: body", _json_schema(old.get("requestBody")), _json_schema(new.get("requestBody"))
    )


def _compare_responses(
    label: str, old: Mapping[str, Any], new: Mapping[str, Any], ro: Resolver, rn: Resolver
) -> list[str]:
    walk = _Walk(ro, rn, response=True)
    problems: list[str] = []
    for status, response in old.get("responses", {}).items():
        if str(status).startswith("2"):
            new_response = new.get("responses", {}).get(status)
            problems += walk.diff(
                f"{label} {status}: response", _json_schema(response), _json_schema(new_response)
            )
    return problems


def breaking_changes(base: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    """Every breaking change from `base` to `current`."""
    ro, rn = Resolver(base), Resolver(current)
    old_names = set(base.get("components", {}).get("schemas", {}))
    new_names = set(current.get("components", {}).get("schemas", {}))
    problems = [f"schema {name!r} was removed or renamed" for name in sorted(old_names - new_names)]
    for path, operations in base.get("paths", {}).items():
        for method in METHODS:
            if method not in operations:
                continue
            label = f"{method.upper()} {path}"
            new = current.get("paths", {}).get(path, {}).get(method)
            if new is None:
                problems.append(f"{label}: operation was removed")
                continue
            old = operations[method]
            problems += _compare_params(label, old, new, ro, rn)
            problems += _compare_body(label, old, new, ro, rn)
            problems += _compare_responses(label, old, new, ro, rn)
    return problems


def main(argv: list[str]) -> int:
    """CLI: exit 1 and list the problems when CURRENT breaks BASE."""
    if len(argv) != 2:  # noqa: PLR2004 - two file arguments
        sys.stderr.write("usage: python -m tooling.openapi_diff BASE CURRENT\n")
        return 2
    base, current = (json.loads(Path(name).read_text(encoding="utf-8")) for name in argv)
    problems = breaking_changes(base, current)
    for problem in problems:
        sys.stderr.write(f"FAIL {problem}\n")
    if not problems:
        sys.stdout.write("OpenAPI: no breaking changes\n")
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main(sys.argv[1:]))
