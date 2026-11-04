"""Action link rules (WP-030 s3; lane B's conditions 2 and 5)."""

import uuid
from datetime import UTC, datetime, timedelta

from app.shared.action_links.domain import (
    MAX_TTL,
    TOKEN_LENGTH,
    LinkState,
    Refusal,
    digest_of,
    expiry,
    new_token,
    refusal,
    well_formed,
)

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
ME, OTHER = uuid.uuid4(), uuid.uuid4()


def link(**over: object) -> LinkState:
    values: dict[str, object] = {
        "recipient_id": ME,
        "object_version": 3,
        "expires_at": NOW + timedelta(hours=1),
        "used_at": None,
        "revoked_at": None,
    }
    values.update(over)
    return LinkState(**values)  # type: ignore[arg-type]  # test helper: keys checked above


def test_a_token_is_32_random_bytes_kept_only_as_its_digest() -> None:
    first, second = new_token(), new_token()
    assert len(first.secret) == TOKEN_LENGTH
    assert well_formed(first.secret)
    assert first.secret != second.secret
    assert len(first.digest) == 32
    assert first.digest == digest_of(first.secret) != digest_of(second.secret)
    assert first.secret.encode() not in first.digest


def test_only_a_well_formed_token_is_looked_up() -> None:
    assert not well_formed("")
    assert not well_formed("a" * 42)
    assert not well_formed("a" * 42 + "=")
    assert not well_formed("a" * 42 + "/")
    assert well_formed("A" * 21 + "-_" + "z" * 20)


def test_a_link_acts_once_for_its_recipient_on_the_version_it_was_sent_for() -> None:
    def why(state: LinkState | None) -> Refusal | None:
        return refusal(state, now=NOW, actor=ME, current_version=3)

    assert why(link()) is None
    assert why(None) is Refusal.NOT_FOUND
    assert why(link(used_at=NOW)) is Refusal.USED
    assert why(link(revoked_at=NOW)) is Refusal.REVOKED
    assert why(link(expires_at=NOW)) is Refusal.EXPIRED
    # Someone else's link is as unknown, whatever its state (a forwarded link reveals nothing).
    assert refusal(link(), now=NOW, actor=OTHER, current_version=3) is Refusal.NOT_FOUND
    assert refusal(link(used_at=NOW), now=NOW, actor=OTHER, current_version=3) is (
        Refusal.NOT_FOUND
    )
    assert refusal(link(), now=NOW, actor=ME, current_version=4) is Refusal.STALE
    # For its recipient, used beats expired and stale: a second click never learns more.
    assert refusal(link(used_at=NOW, expires_at=NOW), now=NOW, actor=ME, current_version=9) is (
        Refusal.USED
    )


def test_a_link_never_lives_longer_than_a_week() -> None:
    assert expiry(NOW) == NOW + timedelta(hours=72)
    assert expiry(NOW, timedelta(days=30)) == NOW + MAX_TTL
