"""Every audit action has a label in English, Arabic and Urdu (CLAUDE.md rule d, D-006).

The audit log renders `audit.action.<code>` through the labels package; an action without one
shows its raw code. Every action in the catalogue is checked, so a new one cannot ship unlabelled.
"""

import pytest

from app.modules.audit.domain.catalogue import ACTIONS
from tests.test_error_labels import label_keys


@pytest.mark.parametrize("locale", ["en", "ar", "ur"])
def test_every_audit_action_has_a_label(locale: str) -> None:
    keys = label_keys(locale)
    missing = sorted(
        f"audit.action.{code}" for code in ACTIONS if f"audit.action.{code}" not in keys
    )
    assert missing == [], f"add these keys to packages/labels/src/resources/audit/{locale}.ts"
