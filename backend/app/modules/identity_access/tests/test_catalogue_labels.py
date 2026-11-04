"""An unlabelled permission stops start-up in dev and test, never in production (REQ-ADM-016)."""

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from app.core.authorization import PermissionSpec
from app.core.modules import ModuleRegistry, discover_modules
from app.modules.identity_access import build_catalogue, check_catalogue_labels
from app.modules.identity_access.domain.permissions import Catalogue
from app.modules.licensing import Feature
from conftest import make_settings

if TYPE_CHECKING:
    from app.core.config import Settings

REGISTRY = ModuleRegistry.from_specs(discover_modules())


def test_the_real_catalogue_is_fully_labelled() -> None:
    check_catalogue_labels(build_catalogue(REGISTRY), make_settings())  # no error


def _unlabelled() -> Catalogue:
    real = [spec for module in REGISTRY.modules for spec in module.permissions]
    features = frozenset(f.value for f in Feature)
    return Catalogue.build([*real, PermissionSpec("zz_module.unlabelled")], features)


def test_a_missing_label_stops_dev_and_test() -> None:
    with pytest.raises(RuntimeError, match=r"en:permission\.zz_module\.unlabelled"):
        check_catalogue_labels(_unlabelled(), make_settings(profile="test"))


def test_production_only_logs() -> None:
    # Only the profile is read; a full production configuration needs real secrets.
    production = cast("Settings", SimpleNamespace(profile="production"))
    check_catalogue_labels(_unlabelled(), production)
