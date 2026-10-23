"""Realtime: channel names, tokens, Centrifugo client, module declarations (WP-011).

See docs/architecture/realtime.md for how a change reaches every screen.
"""

from app.shared.realtime.centrifugo import (
    ACCESS_CHANGED,
    SESSION_ENDED,
    CentrifugoClient,
    CentrifugoError,
    Disconnect,
    Publish,
)
from app.shared.realtime.channels import (
    BROADCAST,
    PERSONAL,
    QUEUE,
    Channel,
    ChannelNameError,
    broadcast,
    personal,
    queue,
    record,
)
from app.shared.realtime.lists import LiveList, ScopedSubject
from app.shared.realtime.specs import (
    ChannelAccess,
    ChannelRequest,
    ChannelSpec,
    Publication,
    RealtimeEffects,
    RealtimeRegistrationError,
    RealtimeRegistry,
    RealtimeRoute,
)
from app.shared.realtime.tokens import connection_token, realtime_user, subscription_token

REALTIME_STATE = "realtime"  # app.state attribute holding the RealtimeRegistry
CENTRIFUGO_STATE = "centrifugo"  # app.state attribute holding the CentrifugoClient (or None)

__all__ = [
    "ACCESS_CHANGED",
    "BROADCAST",
    "CENTRIFUGO_STATE",
    "PERSONAL",
    "QUEUE",
    "REALTIME_STATE",
    "SESSION_ENDED",
    "CentrifugoClient",
    "CentrifugoError",
    "Channel",
    "ChannelAccess",
    "ChannelNameError",
    "ChannelRequest",
    "ChannelSpec",
    "Disconnect",
    "LiveList",
    "Publication",
    "Publish",
    "RealtimeEffects",
    "RealtimeRegistrationError",
    "RealtimeRegistry",
    "RealtimeRoute",
    "ScopedSubject",
    "broadcast",
    "connection_token",
    "personal",
    "queue",
    "realtime_user",
    "record",
    "subscription_token",
]
