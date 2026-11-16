"""The command block at the top of a mail (WP-046a S6; REQ-INC-025)."""

from app.modules.work_items.domain.mail_commands import (
    MAX_LINES,
    VALUE_MAX,
    CommandField,
    LineProblem,
    read_block,
)

ALL = frozenset(CommandField)


def test_the_block_is_the_leading_name_value_lines() -> None:
    block = read_block("\n\nPriority = p1\ncategory= Network \n\nThe printer is down.", ALL)
    assert [(c.line, c.field, c.value) for c in block.commands] == [
        (1, CommandField.PRIORITY, "p1"),
        (2, CommandField.CATEGORY, "Network"),
    ]
    assert block.rejected == ()


def test_a_mail_without_commands_has_an_empty_block() -> None:
    assert read_block("Hello,\npriority = p1 is what I would like", ALL).empty
    assert read_block("", ALL).empty


def test_lines_after_the_first_other_line_are_text() -> None:
    block = read_block("priority = p1\nHi team\ngroup = Network", ALL)
    assert [c.field for c in block.commands] == [CommandField.PRIORITY]


def test_unknown_not_allowed_repeated_and_empty_lines_are_reported() -> None:
    block = read_block(
        "colour = red\ntechnician = sara@acme.test\npriority = p1\npriority = p2\ngroup =",
        frozenset({CommandField.PRIORITY, CommandField.GROUP}),
    )
    assert [c.field for c in block.commands] == [CommandField.PRIORITY]
    assert [(r.line, r.problem) for r in block.rejected] == [
        (1, LineProblem.UNKNOWN_FIELD),
        (2, LineProblem.NOT_ALLOWED),
        (4, LineProblem.REPEATED),
        (5, LineProblem.EMPTY),
    ]


def test_at_most_twenty_lines_are_read() -> None:
    text = "\n".join("colour = red" for _ in range(MAX_LINES + 5))
    block = read_block(text, ALL)
    assert len(block.rejected) == MAX_LINES


def test_a_too_long_value_is_reported_not_cut() -> None:
    block = read_block("category = " + "x" * (VALUE_MAX + 1), ALL)
    assert block.commands == ()
    assert block.rejected[0].problem is LineProblem.TOO_LONG
    assert len(block.rejected[0].text) == VALUE_MAX


def test_field_names_may_use_spaces_or_dashes() -> None:
    assert (
        read_block("Technician = sara@acme.test", ALL).commands[0].field is CommandField.TECHNICIAN
    )
