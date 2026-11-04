"""A warning when the gateway in front of the API is not among its trusted proxies (WP-014b).

uvicorn believes X-Forwarded-For only from FORWARDED_ALLOW_IPS (the chart's api.trustedProxies).
When a request carries the header but the client address is none of its entries, uvicorn ignored
it: the peer that sent it is not trusted. Then every request seems to come from that proxy, and
per-address rate limits are shared by everyone. Logged once per process, with the peer's address
and how to fix it.
"""

from starlette.datastructures import Headers
from starlette.types import Scope

from app.core.logging import get_logger

log = get_logger(__name__)

_warned = False


def check_forwarded(scope: Scope) -> bool:
    """True when this request's X-Forwarded-For was ignored (logged the first time only)."""
    global _warned  # noqa: PLW0603 - one warning per process, by design
    forwarded = Headers(scope=scope).get("x-forwarded-for")
    client = scope.get("client")
    if not forwarded or client is None:
        return False
    entries = {part.strip() for part in forwarded.split(",") if part.strip()}
    if client[0] in entries:
        return False  # uvicorn took the client from the header: its sender is trusted
    if not _warned:
        _warned = True
        log.warning(
            "forwarded_header_ignored",
            peer=client[0],
            hint="add the gateway's or load balancer's addresses to api.trustedProxies "
            "(FORWARDED_ALLOW_IPS); until then every client looks like this peer",
        )
    return True


def reset_for_tests() -> None:
    """Forget that the warning was logged."""
    global _warned  # noqa: PLW0603 - see check_forwarded
    _warned = False
