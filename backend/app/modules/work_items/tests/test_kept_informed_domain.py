"""People kept informed by e-mail (WP-046a S6; REQ-INC-066)."""

from datetime import UTC, datetime, timedelta

from app.modules.work_items.domain import kept_informed as rules


def test_addresses_are_cleaned_capped_and_named_when_wrong() -> None:
    kept, found = rules.problems([" Sara@Acme.Test ", "sara@acme.test", "not-an-address"])
    assert kept == ["sara@acme.test"]
    assert found == [("notify_emails", "invalid_email")]
    many = [f"p{i}@acme.test" for i in range(rules.MAX + 1)]
    assert rules.problems(many)[1] == [("notify_emails", "too_many_addresses")]


def test_the_first_mails_cc_skips_our_addresses_and_stops_at_the_cap() -> None:
    cc = [
        "help@ours.test",
        "Boss@acme.test",
        "sara@acme.test",
        *[f"p{i}@x.test" for i in range(30)],
    ]
    joined = rules.from_first_mail(cc, excluded=["help@ours.test", "sara@acme.test"])
    assert joined[0] == "boss@acme.test"
    assert "help@ours.test" not in joined
    assert "sara@acme.test" not in joined
    assert len(joined) == rules.MAX


def test_a_stop_link_lives_until_the_earliest_limit() -> None:
    now = datetime(2026, 11, 13, tzinfo=UTC)
    assert rules.link_expiry(now, closed_at=None) == now + rules.MAX_AGE
    closed = now - timedelta(days=10)
    assert rules.link_expiry(now, closed_at=closed) == closed + rules.AFTER_CLOSE
    assert rules.link_expiry(now, closed_at=None, retention=timedelta(days=30)) == now + timedelta(
        days=30
    )


def test_masked() -> None:
    assert rules.masked("sara@acme.test") == "s***@acme.test"
    assert rules.masked("nonsense") == "***"


def test_expiry_is_min_of_closed_plus_30_days_180_days_and_retention() -> None:
    """Lane B: min(record closed + 30 d, sent + 180 d, sent + mail_content_retention_days), so a
    stored mail body never holds a live token past its purge."""
    now = datetime(2026, 11, 13, tzinfo=UTC)
    for closed_days_ago, retention_days, expected_days in (
        (None, 3650, 180),  # a long retention: 180 days caps it
        (None, 30, 30),  # the default retention: 30 days
        (20, 30, 10),  # closed 20 days ago: 30 days after closing
    ):
        closed = None if closed_days_ago is None else now - timedelta(days=closed_days_ago)
        found = rules.link_expiry(now, closed_at=closed, retention=timedelta(days=retention_days))
        assert found == now + timedelta(days=expected_days)
