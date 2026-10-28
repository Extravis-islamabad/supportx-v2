"""Only the notification engine sends notifications (REQ-NTF-001 AC2, WP-023).

Modules raise events; the notifications module decides who hears about them. A few senders of
mail that is not a notification keep calling the mail sender directly, each for a stated reason;
any other module that starts calling it fails here.
"""

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
SENDS = re.compile(r"\bqueue_mail\b")

# Not notifications: messages a person must get whatever their preferences say, or that carry
# their own content (an attachment).
ALLOWED = {
    "shared/mail": "the mail sender itself",
    "modules/notifications": "the notification engine",
    "modules/identity_access": "account security mail (MFA reset): never switched off, D-104",
    "modules/analytics": "scheduled reports: the report file is the message, D-100",
}


def _owner(path: Path) -> str:
    parts = path.relative_to(APP).parts
    return "/".join(parts[:2])


def test_no_other_module_sends_mail_itself() -> None:
    senders = {
        _owner(path)
        for path in APP.rglob("*.py")
        if "tests" not in path.parts and SENDS.search(path.read_text(encoding="utf-8"))
    }
    assert senders - set(ALLOWED) == set(), "notify through app.shared.notifications.ports"
    assert {"shared/mail", "modules/notifications"} <= senders
