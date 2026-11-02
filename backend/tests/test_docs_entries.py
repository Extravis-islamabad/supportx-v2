"""Decisions and session-log entries are one well-formed file each (D-123)."""

import re
from pathlib import Path

import pytest

from tooling import docs_entries
from tooling.docs_entries import EntryError, parse_decision, parse_log_entry


def test_every_decision_file_is_well_formed_and_numbers_are_unique() -> None:
    found = docs_entries.decisions()  # raises EntryError naming the bad file
    assert len(found) >= 100
    assert len({d.number for d in found}) == len(found)
    rendered = docs_entries.render_decisions()
    assert all(f"| {d.id} |" in rendered for d in found)


def test_every_session_log_file_is_well_formed() -> None:
    found = docs_entries.log_entries()
    assert found
    assert [e.date for e in found] == sorted((e.date for e in found), reverse=True)
    docs_entries.render_progress_log()


def test_the_shared_pages_hold_no_entries_so_lanes_never_conflict_there() -> None:
    decisions = (docs_entries.DOCS / "DECISIONS.md").read_text(encoding="utf-8")
    assert not re.search(r"^\| D-\d", decisions, re.MULTILINE), "add docs/decisions/D-NNN.md"
    progress = (docs_entries.DOCS / "PROGRESS.md").read_text(encoding="utf-8")
    assert not re.search(r"^### \d{4}-\d{2}-\d{2} ", progress, re.MULTILINE), (
        "add the session log entry to docs/progress-log/"
    )


GOOD_DECISION = (
    "# D-901 (2026-11-02)\n\n## Decision\n\nA.\n\n## Rationale\n\nB.\n\n## Affected docs\n\nC.\n"
)


@pytest.mark.parametrize(
    ("name", "text", "problem"),
    [
        ("D-901.md", GOOD_DECISION.replace("D-901 (", "D-902 ("), "the title says D-902"),
        ("D901.md", GOOD_DECISION, "named D-NNN.md"),
        ("D-901.md", GOOD_DECISION.replace("2026-11-02", "2026-13-02"), "is not a date"),
        ("D-901.md", GOOD_DECISION.replace("## Rationale\n\nB.\n\n", ""), "in that order"),
        ("D-901.md", GOOD_DECISION.replace("\nB.\n", "\n\n"), "'Rationale' is empty"),
        ("D-901.md", GOOD_DECISION.replace("## Affected", "## Notes"), "unexpected section"),
    ],
)
def test_a_malformed_decision_is_refused_with_the_reason(
    tmp_path: Path, name: str, text: str, problem: str
) -> None:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    with pytest.raises(EntryError, match=re.escape(problem)):
        parse_decision(path)


def test_a_decision_keeps_its_text_and_a_pipe_cannot_break_the_table(tmp_path: Path) -> None:
    path = tmp_path / "D-901.md"
    path.write_text(GOOD_DECISION.replace("\nA.\n", "\nOne | two\nlines.\n"), encoding="utf-8")
    decision = parse_decision(path)
    assert decision.decision == "One | two lines."
    assert docs_entries.cell(decision.decision) == "One \\| two lines."


@pytest.mark.parametrize(
    ("name", "text", "problem"),
    [
        ("2026-11-02-x.md", "### 2026-11-01 — T\n\nBody.\n", "the title's date is 2026-11-01"),
        ("2026-11-02-X.md", "### 2026-11-02 — T\n\nBody.\n", "lowercase-slug"),
        ("2026-11-02-x.md", "## 2026-11-02 — T\n\nBody.\n", "the first line is"),
        ("2026-11-02-x.md", "### 2026-11-02 — T\n", "the entry is empty"),
    ],
)
def test_a_malformed_log_entry_is_refused_with_the_reason(
    tmp_path: Path, name: str, text: str, problem: str
) -> None:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    with pytest.raises(EntryError, match=re.escape(problem)):
        parse_log_entry(path)
