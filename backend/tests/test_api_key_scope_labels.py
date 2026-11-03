"""Every scope a key may carry shows as a label (WP-041, rule d).

The key screens name a scope's area with `permission_module.<area>`: each area must be a
permission module, whose label test_permission_labels.py already requires in en and ar (Urdu
follows the frozen list of older keys, D-006).
"""

import pytest

from app.core.modules import ModuleRegistry, discover_modules
from app.modules.identity_access import build_catalogue
from app.modules.identity_access.api.api_keys import known_scopes
from tests.test_error_labels import label_keys

CATALOGUE = build_catalogue(ModuleRegistry.from_specs(discover_modules()))


@pytest.mark.parametrize("locale", ["en", "ar"])
def test_every_scope_area_has_a_label(locale: str) -> None:
    areas = {s.partition(":")[0] for s in known_scopes(list(CATALOGUE.permissions))}
    missing = sorted(f"permission_module.{a}" for a in areas)
    assert sorted(set(missing) - label_keys(locale)) == []
