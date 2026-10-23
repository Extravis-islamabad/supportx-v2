"""Every reason the API gives for a refused or disabled action has a label (rule d, WP-012).

Reasons travel as params (`permission_denied.reason`, `cannot_publish.reason`) and in the
announcement's `actions[].reason`; the UI shows them as `action_reason.<code>`. Collected from
the code itself, so a new reason without labels fails here.
"""

import re
from pathlib import Path

import pytest

from app.modules.announcements.domain.announcement import PUBLISH_PROBLEMS
from app.modules.announcements.service.announcements import NO_PERMISSION, NOT_FROM_STATUS
from tests.test_error_labels import label_keys

APP_DIR = Path(__file__).resolve().parents[1] / "app"
_DECISION_REASON = re.compile(r"Decision\(allowed=False, reason=\"([a-z_]+)\"\)")
_SOD_CODE = re.compile(r"SodRule\(\"([a-z_]+)\"")


def reason_codes() -> set[str]:
    codes = {*PUBLISH_PROBLEMS, NO_PERMISSION, NOT_FROM_STATUS}
    for source in APP_DIR.rglob("*.py"):
        if "tests" in source.parts:
            continue
        text = source.read_text(encoding="utf-8")
        codes |= set(_DECISION_REASON.findall(text)) | set(_SOD_CODE.findall(text))
    return codes


def test_the_scan_finds_the_known_reasons() -> None:
    assert {"four_eyes", "no_permission", "out_of_scope", "audience_empty"} <= reason_codes()


@pytest.mark.parametrize("locale", ["en", "ar", "ur"])
def test_every_action_reason_has_a_label(locale: str) -> None:
    keys = label_keys(locale)
    missing = sorted(
        f"action_reason.{c}" for c in reason_codes() if f"action_reason.{c}" not in keys
    )
    assert missing == [], f"add these keys to packages/labels/src/resources/{locale}.ts"
