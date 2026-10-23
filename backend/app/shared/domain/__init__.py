"""Pure domain helpers shared by modules (no I/O)."""

from app.shared.domain.status import InvalidTransition, StatusMachine

__all__ = ["InvalidTransition", "StatusMachine"]
