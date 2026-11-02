"""SLA permissions (WP-025): who reads and who sets up calendars, holidays and policies."""

from app.core.errors import PermissionDenied
from app.modules.identity_access import Subject

VIEW = "sla.view"  # read calendars, holidays and (session 2) policies
MANAGE = "sla.manage"  # change them: admins by default


def require(subject: Subject, permission: str) -> None:
    """403 naming the permission when the subject does not hold it at all."""
    if not subject.holds(permission):
        raise PermissionDenied(params={"permission": permission})
