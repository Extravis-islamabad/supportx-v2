"""Guarded outbound HTTP (ADR-043 §8): the only way a tenant-aimed call leaves the platform."""

from app.core.config import Settings
from app.shared.egress.addresses import Allowance, AllowanceError, allowed, embedded_ipv4
from app.shared.egress.client import (
    Destination,
    EgressError,
    OutboundRequest,
    OutboundResponse,
    send,
)


def installation_allowance(settings: Settings) -> Allowance:
    """What this installation's configuration opens (never a tenant's).

    Loopback may be listed only in the dev and test profiles (their receivers run locally).
    """
    return Allowance.from_config(
        settings.egress_allow,
        settings.egress_extra_ports,
        allow_loopback=settings.profile in {"dev", "test"},
    )


__all__ = [
    "Allowance",
    "AllowanceError",
    "Destination",
    "EgressError",
    "OutboundRequest",
    "OutboundResponse",
    "allowed",
    "embedded_ipv4",
    "installation_allowance",
    "send",
]
