"""The index worker names why a build failed (D-088): SQLSTATE → reason, through any wrapper."""

import pytest

from app.modules.metadata.domain.fields import IndexFailure
from workers.custom_field_indexes.indexer import failure_of


class _Driver(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


class _Wrapped(Exception):
    def __init__(self, orig: BaseException) -> None:
        super().__init__("wrapped")
        self.orig = orig


@pytest.mark.parametrize(
    ("sqlstate", "reason"),
    [
        ("57014", IndexFailure.TIMED_OUT),
        ("55P03", IndexFailure.BUSY),
        ("40P01", IndexFailure.BUSY),
        ("53100", IndexFailure.DISK_FULL),
        ("53200", IndexFailure.OUT_OF_MEMORY),
        ("54000", IndexFailure.VALUE_TOO_LARGE),
        ("42P17", IndexFailure.UNEXPECTED),
    ],
)
def test_sqlstate_to_reason(sqlstate: str, reason: IndexFailure) -> None:
    assert failure_of(_Driver(sqlstate)) == reason
    assert failure_of(_Wrapped(_Driver(sqlstate))) == reason


def test_a_cause_chain_is_followed_and_unknown_errors_are_unexpected() -> None:
    outer = RuntimeError("outer")
    outer.__cause__ = _Driver("55P03")
    assert failure_of(outer) == IndexFailure.BUSY
    assert failure_of(ValueError("no state")) == IndexFailure.UNEXPECTED
