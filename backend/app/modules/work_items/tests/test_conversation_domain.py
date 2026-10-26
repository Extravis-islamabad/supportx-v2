"""Conversation rules without I/O (WP-020b; REQ-INC-061, 063, 065)."""

from app.modules.work_items.domain.conversation import (
    DEFAULT_FIRST_RESPONSE,
    MENTIONS_MAX,
    DeliveryReason,
    DeliveryState,
    EntryKind,
    FirstResponseAction,
    Visibility,
    delivery_for,
    first_response_action,
    mentioned_ids,
    stamps_first_response,
)

USER = "0192a1b2-0000-7000-8000-000000000001"
OTHER = "0192a1b2-0000-7000-8000-000000000002"


def test_req_inc_065_default_counts_public_reply_and_public_note_only() -> None:
    counted = DEFAULT_FIRST_RESPONSE
    stamp = {
        (kind, visibility): stamps_first_response(
            kind, visibility, counted=counted, already_stamped=False, by_requester=False
        )
        for kind, visibility in (
            (EntryKind.REPLY, Visibility.PUBLIC),
            (EntryKind.NOTE, Visibility.PUBLIC),
            (EntryKind.NOTE, Visibility.PRIVATE),
        )
    }
    assert stamp == {
        (EntryKind.REPLY, Visibility.PUBLIC): True,
        (EntryKind.NOTE, Visibility.PUBLIC): True,
        (EntryKind.NOTE, Visibility.PRIVATE): False,
    }


def test_req_inc_065_ac3_once_and_never_by_the_requester() -> None:
    args = {"counted": DEFAULT_FIRST_RESPONSE}
    assert not stamps_first_response(
        EntryKind.REPLY, Visibility.PUBLIC, already_stamped=True, by_requester=False, **args
    )
    assert not stamps_first_response(
        EntryKind.REPLY, Visibility.PUBLIC, already_stamped=False, by_requester=True, **args
    )
    assert first_response_action(EntryKind.NOTE, Visibility.PRIVATE) == (
        FirstResponseAction.PRIVATE_NOTE
    )


def test_replies_wait_for_the_email_channel_and_say_why() -> None:
    assert delivery_for(EntryKind.REPLY, email_channel=False) == (
        DeliveryState.NOT_SENT,
        DeliveryReason.EMAIL_CHANNEL_NOT_CONFIGURED,
    )
    assert delivery_for(EntryKind.REPLY, email_channel=True) == (DeliveryState.QUEUED, None)
    assert delivery_for(EntryKind.NOTE, email_channel=False) == (None, None)


def test_req_inc_063_mentions_read_from_the_editor_markup() -> None:
    html = (
        f'<p><span data-type="mention" data-id="{USER}" data-label="A">@A</span> '
        f'<span data-id="{OTHER}" data-type="mention">@B</span> '
        f'<span data-type="mention" data-id="{USER}">@A again</span> '
        f'<span data-id="{OTHER}">not a mention</span>'
        '<span data-type="mention" data-id="not-a-uuid">@x</span></p>'
    )
    assert mentioned_ids(html) == [USER, OTHER]
    many = "".join(
        f'<span data-type="mention" data-id="0192a1b2-0000-7000-8000-{n:012d}">@x</span>'
        for n in range(MENTIONS_MAX + 5)
    )
    assert len(mentioned_ids(many)) == MENTIONS_MAX
