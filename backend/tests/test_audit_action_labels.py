"""Every audit action, and every notification recipient, has a label in each language (rule d).

QA9-V-06: 32 catalogue actions had no `audit.action.<code>` key, so the log's "What" column showed
the code's last word title-cased ("Changed", "Created"), in English even in Arabic. QA9-V-07: two
recipient kinds of service requests had no `notification_recipient.<kind>` key ("Approver").
Both lists come from the code (the audit catalogue, the registered record sources), so a new
action or recipient without labels fails here.
"""

import pytest

from app.core.modules import discover_modules
from app.modules.audit.domain.catalogue import ACTIONS
from app.shared.notifications.ports import record_sources
from tests.test_error_labels import label_keys


def recipient_kinds() -> set[str]:
    discover_modules()  # the modules register their record sources at import
    return {str(kind) for source in record_sources() for kind in source.recipient_kinds}


def test_the_lists_are_found() -> None:
    assert {"user.created", "service_request.approval_decided"} <= set(ACTIONS)
    assert {"requester", "approver", "approval_administrators"} <= recipient_kinds()


@pytest.mark.parametrize("locale", ["en", "ar", "ur"])
def test_every_action_and_recipient_has_a_label(locale: str) -> None:
    keys = label_keys(locale)
    missing = sorted(
        [f"audit.action.{a}" for a in ACTIONS if f"audit.action.{a}" not in keys]
        + [
            f"notification_recipient.{k}"
            for k in recipient_kinds()
            if f"notification_recipient.{k}" not in keys
        ]
    )
    assert missing == [], f"add these keys to packages/labels/src/resources/*/{locale}.ts"


@pytest.mark.parametrize("locale", ["en", "ar", "ur"])
def test_every_approval_decision_names_both_outcomes(locale: str) -> None:
    """QA9-F-03: a decision with `details.outcome` reads "Approved a …" or "Rejected a …"."""
    keys = label_keys(locale)
    decided = [a for a in ACTIONS if a.endswith(".approval_decided")]
    assert decided
    missing = [
        f"audit.decision.{a}.{o}"
        for a in decided
        for o in ("approved", "rejected")
        if f"audit.decision.{a}.{o}" not in keys
    ]
    assert missing == []
