"""The conversation of a work item: replies, notes, followers and mentions (WP-020b).

Pure domain code, no I/O. The rules here decide:

* what an entry is (a reply to people, or a note on the record) and who may see it (public:
  the requester too; private: staff only, the default for notes, REQ-INC-061);
* whether an entry stamps the first response (REQ-INC-065): the first public reply or public
  note by staff, as the tenant chose; a private note never does by default;
* what happens to a reply while no email channel exists (WP-024): it is saved and shown as
  "not sent", with the reason, never silently dropped;
* which people a note mentions (REQ-INC-063), read from the sanitised HTML the editor produced.
"""

import re
from collections.abc import Collection
from enum import StrEnum

BODY_MAX = 100_000  # sanitised HTML, characters (as descriptions)
RECIPIENTS_MAX = 50
MENTIONS_MAX = 20
TEMPLATE_NAME_MAX = 120


class EntryKind(StrEnum):
    """A reply (to people, by a channel) or a note (on the record)."""

    REPLY = "reply"
    NOTE = "note"


class Visibility(StrEnum):
    """Public: the requester sees it (portal, email). Private: staff only."""

    PUBLIC = "public"
    PRIVATE = "private"


class ReplyMode(StrEnum):
    """Which composer a reply came from (REQ-INC-058)."""

    REPLY = "reply"
    REPLY_ALL = "reply_all"
    FORWARD = "forward"


class DeliveryState(StrEnum):
    """Where an outbound reply is (REQ-INC-059). Notes have none.

    The notification engine moves it as the e-mail to the requester goes (WP-024 session 3).
    """

    NOT_SENT = "not_sent"  # legacy (before WP-024 s3): saved, nothing could send it
    WAITING = "waiting"  # outgoing mail is not set up; sent once it is (REQ-INC-060)
    QUEUED = "queued"  # handed to the email channel (WP-024)
    RETRYING = "retrying"  # a temporary failure; the next attempt is scheduled
    SENT = "sent"
    FAILED = "failed"  # the reason says why; it can be resent


# Once sent, a late "retrying" or "failed" never moves a reply back (agreed with lane A).
FINAL_DELIVERY = frozenset({DeliveryState.SENT})


class DeliveryReason(StrEnum):
    """Why a reply is not (yet) sent: a code the timeline shows as its label."""

    EMAIL_CHANNEL_NOT_CONFIGURED = "email_channel_not_configured"  # legacy, as NOT_SENT
    MAIL_NOT_CONFIGURED = "mail_not_configured"
    NOT_SENT_IN_TIME = "not_sent_in_time"  # waited 7 days for outgoing mail: never sent late
    NO_ADDRESS = "no_address"  # the requester has no e-mail address
    MAIL_REFUSED = "mail_refused"  # the message broke a sending rule
    NOT_NOTIFIED = "not_notified"  # the requester gets no e-mail of it (access or preferences)
    # The mail server's answer (app.shared.mail.infra.smtp), as codes.
    RECIPIENT_REFUSED = "recipient_refused"
    RECIPIENT_DEFERRED = "recipient_deferred"
    MESSAGE_REFUSED = "message_refused"
    AUTHENTICATION_FAILED = "authentication_failed"
    SERVER_UNAVAILABLE = "server_unavailable"
    SERVER_BUSY = "server_busy"
    GAVE_UP = "gave_up"  # still failing after every retry


class FirstResponseAction(StrEnum):
    """Actions an admin may count as the first response (REQ-INC-065)."""

    REPLY = "reply"
    PUBLIC_NOTE = "public_note"
    PRIVATE_NOTE = "private_note"


DEFAULT_FIRST_RESPONSE: tuple[FirstResponseAction, ...] = (
    FirstResponseAction.REPLY,
    FirstResponseAction.PUBLIC_NOTE,
)


class FollowReason(StrEnum):
    """How someone came to follow a record (shown in the followers list)."""

    SELF = "self"  # they chose to follow
    ADDED = "added"  # someone with manage_followers added them
    HANDED_OVER = "handed_over"  # they handed it out of their own reach and kept following
    MENTIONED = "mentioned"  # they were mentioned in a note


def first_response_action(kind: EntryKind, visibility: Visibility) -> FirstResponseAction:
    """Which of the countable actions an entry is."""
    if kind == EntryKind.REPLY:
        return FirstResponseAction.REPLY
    if visibility == Visibility.PUBLIC:
        return FirstResponseAction.PUBLIC_NOTE
    return FirstResponseAction.PRIVATE_NOTE


def stamps_first_response(
    kind: EntryKind,
    visibility: Visibility,
    *,
    counted: Collection[str],
    already_stamped: bool,
    by_requester: bool,
) -> bool:
    """True when this entry is the first response (set once, never moved, REQ-INC-065 AC3)."""
    if already_stamped or by_requester:
        return False
    return first_response_action(kind, visibility) in counted


def delivery_for(kind: EntryKind, *, email_channel: bool) -> tuple[str | None, str | None]:
    """(state, reason) of a new entry: a reply is queued, or waits while mail is not set up."""
    if kind == EntryKind.NOTE:
        return None, None
    if not email_channel:
        return DeliveryState.WAITING, DeliveryReason.MAIL_NOT_CONFIGURED
    return DeliveryState.QUEUED, None


# What the editor writes for a mention (packages/ui/src/richtext, Tiptap Mention): a span with
# data-type="mention" and data-id="<user uuid>". The sanitiser keeps exactly these attributes.
_MENTION = re.compile(
    r"<span\b[^>]*\bdata-type=\"mention\"[^>]*>",
    re.IGNORECASE,
)
_MENTION_ID = re.compile(
    r"\bdata-id=\"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\"",
    re.IGNORECASE,
)


def mentioned_ids(html: str) -> list[str]:
    """User IDs mentioned in sanitised HTML, in order, each once (at most MENTIONS_MAX)."""
    found: list[str] = []
    for tag in _MENTION.finditer(html):
        match = _MENTION_ID.search(tag.group(0))
        if match is not None:
            value = match.group(1).lower()
            if value not in found:
                found.append(value)
    return found[:MENTIONS_MAX]


def unmention(html: str, user_ids: Collection[str]) -> str:
    """`html` with the mentions of `user_ids` turned into their plain words (QA C3).

    Used for mentions of people who are not users of the tenant (forged or from elsewhere): the
    text stays readable, but nothing looks like a mention of someone who does not exist.
    """
    wanted = {u.lower() for u in user_ids}
    if not wanted:
        return html

    def plain(match: re.Match[str]) -> str:
        found = _MENTION_ID.search(match.group(1))
        if found is not None and found.group(1).lower() in wanted:
            return match.group(2)
        return match.group(0)

    return _MENTION_SPAN.sub(plain, html)


_MENTION_SPAN = re.compile(
    r"(<span\b[^>]*\bdata-type=\"mention\"[^>]*>)(.*?)</span>", re.IGNORECASE | re.DOTALL
)
