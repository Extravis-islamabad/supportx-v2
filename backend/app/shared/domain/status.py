"""Status machines: which actions move a record from which status to which (WP-012).

Pure domain code (no I/O). A module declares its machine once:

    MACHINE = StatusMachine(
        {
            "draft":     {"publish": "published", "archive": "archived"},
            "published": {"unpublish": "draft", "archive": "archived"},
            "archived":  {"reopen": "draft"},
        },
        order=("publish", "unpublish", "archive", "reopen"),
    )

and every status change goes through `MACHINE.apply(current, action)`: an action that is not
allowed from the current status raises InvalidTransition, which services turn into 409
`invalid_transition`. Statuses therefore never change by editing a field, only through named
actions, and the UI offers exactly `MACHINE.actions_from(status)`. (ServiceDesk Plus lets a
status be set by hand and only flags the workflow as "violated" afterwards; we refuse up front.)
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType


class InvalidTransition(ValueError):
    """`action` is not allowed from `status`."""

    def __init__(self, status: str, action: str) -> None:
        super().__init__(f"{action!r} is not allowed from {status!r}")
        self.status = status
        self.action = action


@dataclass(frozen=True)
class StatusMachine:
    """status → {action → next status}. `order`: the order the UI shows the actions in.

    Without `order`, actions keep their first appearance in the table. With it, it must name
    every action exactly once (so buttons never jump around between statuses).
    """

    transitions: Mapping[str, Mapping[str, str]]
    order: tuple[str, ...] = ()
    actions: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        """Check every target exists; freeze the table; fix the action order."""
        statuses = set(self.transitions)
        for status, moves in self.transitions.items():
            for action, target in moves.items():
                if target not in statuses:
                    msg = f"{status}.{action} leads to unknown status {target!r}"
                    raise ValueError(msg)
        ordered: list[str] = []
        for moves in self.transitions.values():
            ordered += [action for action in moves if action not in ordered]
        if self.order:
            if sorted(self.order) != sorted(ordered):
                msg = f"order {self.order!r} must name each action once: {sorted(ordered)!r}"
                raise ValueError(msg)
            ordered = list(self.order)
        object.__setattr__(self, "actions", tuple(ordered))
        object.__setattr__(
            self,
            "transitions",
            MappingProxyType({s: MappingProxyType(dict(m)) for s, m in self.transitions.items()}),
        )

    @property
    def statuses(self) -> Sequence[str]:
        """Every status, in declaration order."""
        return tuple(self.transitions)

    def actions_from(self, status: str) -> list[str]:
        """Actions allowed from `status`, in the machine's fixed action order."""
        allowed = self.transitions.get(status, {})
        return [action for action in self.actions if action in allowed]

    def apply(self, status: str, action: str) -> str:
        """The next status; InvalidTransition when `action` is not allowed from `status`."""
        target = self.transitions.get(status, {}).get(action)
        if target is None:
            raise InvalidTransition(status, action)
        return target
