"""Helpers every catalog service shares: who may manage, who counts as staff, 422 problems."""

from collections.abc import Sequence

from app.core.errors import FieldError, PermissionDenied, ValidationFailed
from app.modules.identity_access import Subject

MANAGE = "catalog_items.manage"


def invalid(problems: Sequence[tuple[str, str]]) -> ValidationFailed:
    """A 422 naming each field and its code (the labels say the words)."""
    return ValidationFailed(
        errors=[
            FieldError(field=f"body.{at}", code=code, message_key=f"errors.field.{code}")
            for at, code in problems
        ]
    )


def is_staff(subject: Subject) -> bool:
    """Catalog managers, technicians and admins see every item, drafts and retired ones too."""
    return subject.holds(MANAGE) or "technician" in subject.role_keys or subject.is_tenant_admin


def require_manage(subject: Subject) -> None:
    """Writing needs `catalog_items.manage` (403 otherwise)."""
    if not subject.holds(MANAGE):
        raise PermissionDenied(params={"permission": MANAGE, "reason": "no_permission"})


__all__ = ["MANAGE", "invalid", "is_staff", "require_manage"]
