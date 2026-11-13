"""Commands written at the top of a mail (WP-046a S6; REQ-INC-025). Pure, no I/O.

A sender may start a new incident's mail with lines such as

    priority = p1
    category = Network
    group = Service desk

The block is the first lines of the body that read `name = value`, before any other text, and at
most `MAX_LINES` of them; the mail's text is kept as it is either way. Each line is applied, or
reported back, by the service (`service.mail_commands`): only for a type that allows commands, a
field it allows, a sender the mailbox's server vouched for, and a change that sender's own rights
would allow through the API. A line that cannot be applied is skipped; the incident is still made.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

MAX_LINES = 20
VALUE_MAX = 200
_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z _-]{0,29}?)\s*=\s*(.*?)\s*$")


class CommandField(StrEnum):
    """What a mail may set (a type's settings choose among these)."""

    CATEGORY = "category"
    PRIORITY = "priority"
    GROUP = "group"
    TECHNICIAN = "technician"
    TEMPLATE = "template"


class LineProblem(StrEnum):
    """Why one line was not applied (labels: mail_command_problem.<code>)."""

    UNKNOWN_FIELD = "unknown_field"
    NOT_ALLOWED = "not_allowed"  # the type does not let mail set this field
    REPEATED = "repeated"  # the field was named on an earlier line
    EMPTY = "empty"
    TOO_LONG = "too_long"
    NOT_FOUND = "not_found"  # no such category, group, person or template
    REFUSED = "refused"  # the sender's rights, or the record's rules, do not allow it


@dataclass(frozen=True)
class Command:
    """One `name = value` line, numbered from 1 within the block."""

    line: int
    field: CommandField
    value: str


@dataclass(frozen=True)
class Rejected:
    """One line not applied, and why."""

    line: int
    text: str  # the line as written, cut to VALUE_MAX
    problem: LineProblem


@dataclass(frozen=True)
class Block:
    """The commands of a mail, and the lines already known not to apply."""

    commands: tuple[Command, ...]
    rejected: tuple[Rejected, ...]

    @property
    def empty(self) -> bool:
        """No command line at all."""
        return not self.commands and not self.rejected


def _field(name: str) -> CommandField | None:
    key = re.sub(r"[\s-]+", "_", name.strip().lower())
    try:
        return CommandField(key)
    except ValueError:
        return None


def read_block(text: str, allowed: frozenset[CommandField]) -> Block:
    """The command lines at the top of `text` (blank lines before them skipped)."""
    lines = text.replace("\r\n", "\n").split("\n")
    start = next((i for i, line in enumerate(lines) if line.strip()), len(lines))
    commands: list[Command] = []
    rejected: list[Rejected] = []
    seen: set[CommandField] = set()
    for number, line in enumerate(lines[start : start + MAX_LINES], start=1):
        match = _LINE.match(line)
        if match is None:
            break  # the block ends at the first line that is not a command
        name, value = match.group(1), match.group(2)
        written = line.strip()[:VALUE_MAX]
        field = _field(name)
        problem: LineProblem | None = None
        if field is None:
            problem = LineProblem.UNKNOWN_FIELD
        elif field not in allowed:
            problem = LineProblem.NOT_ALLOWED
        elif field in seen:
            problem = LineProblem.REPEATED
        elif not value:
            problem = LineProblem.EMPTY
        elif len(value) > VALUE_MAX:
            problem = LineProblem.TOO_LONG
        if problem is not None or field is None:
            rejected.append(Rejected(number, written, problem or LineProblem.UNKNOWN_FIELD))
            continue
        seen.add(field)
        commands.append(Command(number, field, value))
    return Block(tuple(commands), tuple(rejected))
