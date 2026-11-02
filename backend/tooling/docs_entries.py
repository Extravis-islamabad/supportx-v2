"""One file per decision and per session-log entry, rendered on demand (D-123).

Every lane appended to the same table in docs/DECISIONS.md and to the top of the session log in
docs/PROGRESS.md, so every merge knocked the other lanes' PRs out of the queue. Now each entry is
its own file, and two lanes only collide when they really take the same number:

- docs/decisions/D-NNN.md: `# D-NNN (YYYY-MM-DD)`, then `## Decision`, `## Rationale`,
  `## Affected docs`.
- docs/progress-log/YYYY-MM-DD-<slug>.md: `### YYYY-MM-DD — title`, then the entry.

`make decisions` and `make progress-log` write the combined views to docs/_build/ (not committed);
tests/test_docs_entries.py checks every entry is well-formed.

Usage: uv run python -m tooling.docs_entries decisions|progress-log|check
"""

import datetime as dt
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
DECISIONS_DIR = DOCS / "decisions"
LOG_DIR = DOCS / "progress-log"
BUILD = DOCS / "_build"

DECISION_FILE = re.compile(r"^D-(\d{3,})\.md$")
DECISION_TITLE = re.compile(r"^# (D-\d{3,}) \((\d{4}-\d{2}-\d{2})\)$")
SECTIONS = ("Decision", "Rationale", "Affected docs")
LOG_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
LOG_TITLE = re.compile(r"^### (\d{4}-\d{2}-\d{2}) — (\S.*)$")


class EntryError(ValueError):
    """An entry file that does not follow the format above (the message names the file)."""


def _bad(path: Path, reason: str) -> EntryError:
    return EntryError(f"{path.name}: {reason}")


@dataclass(frozen=True)
class Decision:
    """One product owner decision (docs/decisions/D-NNN.md)."""

    id: str
    date: dt.date
    decision: str
    rationale: str
    affected: str

    @property
    def number(self) -> int:
        """D-007 -> 7."""
        return int(self.id.removeprefix("D-"))


@dataclass(frozen=True)
class LogEntry:
    """One session-log entry (docs/progress-log/)."""

    name: str
    date: dt.date
    title: str
    text: str  # the whole entry, title line included


def _date(value: str, path: Path) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise _bad(path, f"{value} is not a date") from None


def _sections(path: Path, lines: list[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in lines:
        if line.startswith("## "):
            heading = line.removeprefix("## ").strip()
            if heading not in SECTIONS or heading in found:
                raise _bad(path, f"unexpected section '{heading}'")
            current = found.setdefault(heading, [])
        elif current is not None:
            current.append(line)
        elif line.strip():
            raise _bad(path, "text before '## Decision'")
    if list(found) != list(SECTIONS):
        raise _bad(path, f"the sections are {', '.join(SECTIONS)}, in that order")
    return found


def parse_decision(path: Path) -> Decision:
    """Read one decision file, or raise EntryError saying what is wrong."""
    named = DECISION_FILE.match(path.name)
    if named is None:
        raise _bad(path, "a decision file is named D-NNN.md")
    lines = path.read_text(encoding="utf-8").splitlines()
    title = DECISION_TITLE.match(lines[0]) if lines else None
    if title is None:
        raise _bad(path, "the first line is '# D-NNN (YYYY-MM-DD)'")
    if title.group(1) != path.name.removesuffix(".md"):
        raise _bad(path, f"the title says {title.group(1)}")
    found = _sections(path, lines[1:])
    texts = {name: " ".join(" ".join(body).split()) for name, body in found.items()}
    for name, value in texts.items():
        if not value:
            raise _bad(path, f"'{name}' is empty")
    return Decision(
        id=title.group(1),
        date=_date(title.group(2), path),
        decision=texts["Decision"],
        rationale=texts["Rationale"],
        affected=texts["Affected docs"],
    )


def parse_log_entry(path: Path) -> LogEntry:
    """Read one session-log file, or raise EntryError saying what is wrong."""
    named = LOG_FILE.match(path.name)
    if named is None:
        raise _bad(path, "a log file is named YYYY-MM-DD-<lowercase-slug>.md")
    text = path.read_text(encoding="utf-8").strip()
    first, _, rest = text.partition("\n")
    title = LOG_TITLE.match(first)
    if title is None:
        raise _bad(path, "the first line is '### YYYY-MM-DD — title'")
    if title.group(1) != named.group(1):
        raise _bad(path, f"the title's date is {title.group(1)}")
    if not rest.strip():
        raise _bad(path, "the entry is empty")
    return LogEntry(
        name=path.name, date=_date(title.group(1), path), title=title.group(2), text=text
    )


def decisions() -> list[Decision]:
    """Every decision, by number. Any other file in the folder is an error."""
    found = [parse_decision(path) for path in sorted(DECISIONS_DIR.iterdir())]
    numbers = [d.number for d in found]
    if len(numbers) != len(set(numbers)):  # D-07 and D-007 would both parse
        raise _bad(DECISIONS_DIR, "the same number is used twice")
    return sorted(found, key=lambda d: d.number)


def log_entries() -> list[LogEntry]:
    """Every session-log entry, newest first (same day: by file name, last first)."""
    found = [parse_log_entry(path) for path in LOG_DIR.iterdir()]
    return sorted(found, key=lambda e: (e.date, e.name), reverse=True)


def cell(text: str) -> str:
    """Text safe inside a Markdown table cell."""
    return text.replace("|", "\\|")


def render_decisions() -> str:
    """Every decision as one table, by number."""
    rows = [
        f"| {d.id} | {d.date.isoformat()} | {cell(d.decision)} | {cell(d.rationale)}"
        f" | {cell(d.affected)} |"
        for d in decisions()
    ]
    return "\n".join(
        [
            "# Product owner decision log (rendered from docs/decisions/, do not edit)",
            "",
            "| ID | Date | Decision | Rationale | Affected docs |",
            "|---|---|---|---|---|",
            *rows,
            "",
        ]
    )


def render_progress_log() -> str:
    """Every session-log entry, newest first."""
    parts = ["## Session log (newest first, rendered from docs/progress-log/, do not edit)", ""]
    for entry in log_entries():
        parts += [entry.text, ""]
    return "\n".join(parts)


def main(argv: list[str]) -> int:
    """Render one view to docs/_build/, or only check every entry."""
    command = argv[0] if argv else ""
    renders = {
        "decisions": ("DECISIONS.md", render_decisions),
        "progress-log": ("PROGRESS-log.md", render_progress_log),
    }
    try:
        if command == "check":
            sys.stdout.write(
                f"{len(decisions())} decisions, {len(log_entries())} log entries: OK\n"
            )
            return 0
        if command not in renders:
            sys.stdout.write("usage: python -m tooling.docs_entries decisions|progress-log|check\n")
            return 2
        name, render = renders[command]
        text = render()
    except EntryError as error:
        sys.stderr.write(f"error: {error}\n")
        return 1
    BUILD.mkdir(exist_ok=True)
    (BUILD / name).write_text(text, encoding="utf-8")
    sys.stdout.write(f"wrote {(BUILD / name).relative_to(REPO)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
