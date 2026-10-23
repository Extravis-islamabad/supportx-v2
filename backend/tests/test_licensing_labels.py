"""Every licensing code the API returns has an English and an Arabic label (CLAUDE.md rule d).

GET /api/v1/entitlements and the entitlement problems return catalogue codes (edition, feature,
limit, state, reason); the UI renders them as `edition.<code>`, `feature.<code>` and so on.
"""

from enum import StrEnum

import pytest

from app.modules.licensing.domain.catalogue import Edition, Feature, LimitKey
from app.modules.licensing.domain.entitlement import EntitlementState, StateReason
from tests.test_error_labels import label_keys

PREFIXES: dict[str, type[StrEnum]] = {
    "edition": Edition,
    "feature": Feature,
    "limit": LimitKey,
    "entitlement_state": EntitlementState,
    "entitlement_reason": StateReason,
}


@pytest.mark.parametrize("locale", ["en", "ar"])
def test_every_catalogue_code_has_a_label(locale: str) -> None:
    keys = label_keys(locale)
    missing = sorted(
        f"{prefix}.{member.value}"
        for prefix, codes in PREFIXES.items()
        for member in codes
        if f"{prefix}.{member.value}" not in keys
    )
    assert missing == [], f"add these keys to packages/labels/src/resources/{locale}.ts"
