"""The vendor support allow-list's guards (WP-057 S4c-2, D-173, lane B (1), (6)).

Every permission in the catalogue has a decision; a new permission without one fails here with
its name, so nothing reaches support by default. The forbidden groups are `never` whole.
"""

from app.modules.identity_access.domain import support_access
from app.modules.identity_access.domain.support_access import (
    REASONS,
    SUPPORT_ACCESS,
    Grantable,
    Never,
    allowed,
    permissions_for,
)
from app.modules.identity_access.tests.test_role_matrix import _catalogue

# Groups support never holds anything in (D-173, lane B (6)): a new permission there can't slip
# in as `view`.
NEVER_GROUPS = (
    "users",
    "roles",
    "identity",
    "api_keys",
    "integrations",
    "mailboxes",
    "audit",
    "licence",
    "branding",
    "people",
    "ai",
    "settings",
    "announcements",
)


def test_every_permission_in_the_catalogue_has_a_decision() -> None:
    catalogue = set(_catalogue().permissions)
    missing = sorted(catalogue - set(SUPPORT_ACCESS))
    assert missing == [], f"decide these for vendor support (support_access.py): {missing}"
    stale = sorted(set(SUPPORT_ACCESS) - catalogue)
    assert stale == [], f"no longer in the catalogue: {stale}"


def test_every_never_has_a_known_reason() -> None:
    for key, decision in SUPPORT_ACCESS.items():
        if isinstance(decision, Never):
            assert decision.reason in REASONS, key


def test_the_forbidden_groups_are_never_whole() -> None:
    for key, decision in SUPPORT_ACCESS.items():
        if key.split(".", 1)[0] in NEVER_GROUPS:
            assert isinstance(decision, Never), key


def test_view_holds_only_reads_and_change_adds_work_never_more() -> None:
    view = permissions_for("view")
    change = permissions_for("view_and_change")
    assert view < change
    assert all(SUPPORT_ACCESS[k] is Grantable.VIEW for k in view)
    for never in ("incidents.reply", "incidents.approve", "users.manage", "audit.view"):
        assert never not in change
    assert "workflows.manage" in change  # drafts only: publishing refuses support
    assert "automation.manage" not in change  # no draft path yet (the coordinator)


def test_a_permission_without_a_decision_is_denied() -> None:
    """Lane B (1): deployed before the guard caught it, it is still never given."""
    assert not allowed("view_and_change", None)
    assert not allowed("view_and_change", Never("audit"))
    assert allowed("view", Grantable.VIEW)
    assert not allowed("view", Grantable.CHANGE)
    assert not allowed("view", Grantable.DRAFT)


def test_sensitive_fields_are_hidden_and_personal_ones_masked_unless_unmasked() -> None:
    marks = {
        "incident": [
            ("custom.salary", False, True),
            ("custom.home_phone", True, False),
            ("custom.both", True, True),
            ("custom.colour", False, False),
            ("impact_details", False, False),
        ]
    }
    masked = support_access.field_access(marks, unmask_personal=False)
    assert dict(masked["incident"]) == {
        "custom.both": "hidden",
        "custom.home_phone": "masked",
        "custom.salary": "hidden",
    }
    unmasked = support_access.field_access(marks, unmask_personal=True)
    # Unmasking never opens a sensitive field (D-173).
    assert dict(unmasked["incident"]) == {"custom.both": "hidden", "custom.salary": "hidden"}
    assert support_access.field_access({"ci": []}, unmask_personal=False) == {}


def test_a_support_request_without_its_facts_is_masked() -> None:
    """Lane B (3): no cached facts for the account means contacts masked, never shown."""
    import uuid  # noqa: PLC0415 - this test only

    from app.modules.identity_access.service.support_grants import judged_grant  # noqa: PLC0415

    grant, unmasked = judged_grant(uuid.uuid4(), uuid.uuid4())
    assert (grant, unmasked) == (None, False)


def test_a_support_request_without_its_facts_has_names_masked_too() -> None:
    """D-180 (0188): with no cached facts, names are masked as well (fails closed)."""
    import uuid  # noqa: PLC0415 - this test only

    from app.modules.identity_access.service.support_grants import (  # noqa: PLC0415
        judged_names_masked,
    )

    assert judged_names_masked(uuid.uuid4(), uuid.uuid4()) is True
