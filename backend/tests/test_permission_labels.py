"""Every permission, permission module, scope and system role has en + ar labels (WP-016).

The role editor shows `permission.<key>` with `permission.<key>.description`, grouped under
`permission_module.<module>`; scopes as `scope.<code>`; system roles as `role.<key>`.
"""

import pytest

from app.core.authorization import ALL_SCOPES
from app.core.modules import ModuleRegistry, discover_modules
from app.modules.identity_access import build_catalogue
from app.modules.identity_access.domain.permissions import SYSTEM_ROLES
from tests.test_error_labels import label_keys

CATALOGUE = build_catalogue(ModuleRegistry.from_specs(discover_modules()))


def required_keys() -> set[str]:
    keys: set[str] = set()
    for key, spec in CATALOGUE.permissions.items():
        keys |= {
            f"permission.{key}",
            f"permission.{key}.description",
            f"permission_module.{spec.module}",
        }
    keys |= {f"scope.{scope}" for scope in ALL_SCOPES} | {
        f"scope.{scope}.description" for scope in ALL_SCOPES
    }
    keys |= {f"role.{role}" for role in SYSTEM_ROLES} | {
        f"role.{role}.description" for role in SYSTEM_ROLES
    }
    keys |= {
        f"permission_reason.{r}"
        for r in ("no_permission", "not_entitled", "out_of_scope", "condition_not_met")
    }
    return keys


@pytest.mark.parametrize("locale", ["en", "ar"])
def test_every_permission_has_a_label_and_description(locale: str) -> None:
    missing = sorted(required_keys() - label_keys(locale))
    assert missing == [], f"add these keys to packages/labels/src/resources/{locale}.ts"


def test_catalogue_has_the_reserved_itsm_permissions() -> None:
    assert {"requests.assign", "changes.approve", "cmdb.manage", "knowledge.manage"} <= set(
        CATALOGUE.permissions
    )
