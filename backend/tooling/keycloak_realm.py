"""`python -m tooling.keycloak_realm [--check]`: the production realm, derived from the dev one.

The dev realm (deploy/helm/supportx/files/keycloak/dev/supportx-realm.json) is imported by the
Compose stack and by the chart's dev profile. It contains demo organizations and users with
documented passwords, so production profiles (single-node, HA, SaaS) import the **base** realm
instead: the same settings, roles, clients and mappers, with no users and no organizations
(tenants and their administrators are created by provisioning, not by an import file).

`--check` (CI, `make lint`) fails when the committed base realm is out of date; without it the
base realm is rewritten.
"""

import json
import sys
from pathlib import Path
from typing import Any

KEYCLOAK_FILES = Path(__file__).resolve().parents[2] / "deploy/helm/supportx/files/keycloak"
DEV_REALM = KEYCLOAK_FILES / "dev/supportx-realm.json"
BASE_REALM = KEYCLOAK_FILES / "base/supportx-realm.json"
DEV_ONLY = ("users", "organizations")


def base_realm(dev: dict[str, Any]) -> dict[str, Any]:
    """The dev realm without its demo data."""
    return {key: value for key, value in dev.items() if key not in DEV_ONLY}


def render(realm: dict[str, Any]) -> str:
    """Stable JSON (same layout as the dev file)."""
    return json.dumps(realm, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:  # pragma: no cover - thin CLI over tested functions
    """Write or check the base realm."""
    expected = render(base_realm(json.loads(DEV_REALM.read_text(encoding="utf-8"))))
    if "--check" in argv:
        current = BASE_REALM.read_text(encoding="utf-8") if BASE_REALM.is_file() else ""
        if current != expected:
            sys.stderr.write(f"{BASE_REALM} is out of date: run make keycloak-realm\n")
            return 1
        sys.stdout.write("keycloak base realm: up to date\n")
        return 0
    BASE_REALM.write_text(expected, encoding="utf-8")
    sys.stdout.write(f"wrote {BASE_REALM}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main(sys.argv[1:]))
