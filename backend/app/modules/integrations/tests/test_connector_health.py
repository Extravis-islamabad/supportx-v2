"""When a connector fails and when its admins hear about it, without I/O (WP-040, REQ-INT-005)."""

from app.modules.integrations.domain.connector_health import Health, Notice, after_run


def _runs(*outcomes: str) -> list[Notice | None]:
    """Feed runs ("ok", "net" for a network failure, "auth" for a refused credential)."""
    health, notices = Health(), []
    for outcome in outcomes:
        health, notice = after_run(health, ok=outcome == "ok", auth_failure=outcome == "auth")
        notices.append(notice)
    return notices


def test_three_network_failures_in_a_row_turn_it_failing_once() -> None:
    assert _runs("net", "net", "net", "net") == [None, None, Notice.FAILING, None]


def test_a_success_in_between_starts_counting_again() -> None:
    assert _runs("net", "net", "ok", "net", "net") == [None] * 5


def test_a_refused_credential_fails_at_once() -> None:
    assert _runs("auth", "auth") == [Notice.FAILING, None]


def test_fifty_failures_are_one_notice_and_the_recovery_another() -> None:
    notices = _runs(*(["net"] * 50), "ok", "ok")
    assert [n for n in notices if n is not None] == [Notice.FAILING, Notice.RECOVERED]


def test_a_success_while_working_says_nothing() -> None:
    assert _runs("ok", "ok") == [None, None]
