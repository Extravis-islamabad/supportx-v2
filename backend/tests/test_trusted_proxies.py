"""Whose X-Forwarded-For the API believes (lane B review of #182, 2026-11-04).

The image used `--forwarded-allow-ips "*"`: any client could set its own address and slip past
per-address rate limits (e.g. the public action links) or fake the audited client address. Now
only the gateway's network counts (the chart's api.trustedProxies, as FORWARDED_ALLOW_IPS).
"""

import re
from pathlib import Path
from typing import Any

import pytest
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "deploy" / "images" / "backend.Dockerfile"
VALUES = ROOT / "deploy" / "helm" / "supportx" / "values.yaml"
CONFIGMAP = ROOT / "deploy" / "helm" / "supportx" / "templates" / "configmap-env.yaml"


def _chart_default() -> str:
    found = re.search(r'^\s+trustedProxies:\s*"([^"]+)"', VALUES.read_text(), re.MULTILINE)
    assert found, "api.trustedProxies is set in values.yaml"
    return found.group(1)


def test_the_image_and_the_chart_never_trust_every_address() -> None:
    api_cmd = next(
        line
        for line in DOCKERFILE.read_text().splitlines()
        if "uvicorn" in line and line.startswith("CMD")
    )
    assert '"*"' not in api_cmd
    assert "--forwarded-allow-ips" not in api_cmd  # the chart's FORWARDED_ALLOW_IPS decides
    assert "*" not in _chart_default()
    assert "FORWARDED_ALLOW_IPS: {{ .Values.api.trustedProxies | quote }}" in CONFIGMAP.read_text()


async def _client_of(peer: str, forwarded_for: str) -> tuple[str, int] | None:
    seen: dict[str, Any] = {}

    async def app(scope: dict[str, Any], _receive: Any, _send: Any) -> None:  # noqa: ANN401 - ASGI
        seen["client"] = scope["client"]

    middleware = ProxyHeadersMiddleware(app, trusted_hosts=_chart_default())  # type: ignore[arg-type]  # a bare ASGI callable
    scope = {
        "type": "http",
        "scheme": "http",
        "client": (peer, 40000),
        "headers": [(b"x-forwarded-for", forwarded_for.encode())],
    }
    await middleware(scope, None, None)  # type: ignore[arg-type]  # receive/send are unused
    client = seen["client"]
    return (client[0], client[1]) if client else None


@pytest.mark.parametrize(
    ("peer", "forwarded_for", "client"),
    [
        # Straight from outside, with a forged header: the header is ignored.
        ("198.51.100.7", "203.0.113.9", "198.51.100.7"),
        # Through the gateway (a pod address): the last address the gateway added.
        ("10.42.1.15", "203.0.113.9", "203.0.113.9"),
        # A forged entry before the real one: the rightmost untrusted address wins.
        ("10.42.1.15", "6.6.6.6, 203.0.113.9", "203.0.113.9"),
    ],
)
async def test_only_the_gateway_may_say_who_the_client_is(
    peer: str, forwarded_for: str, client: str
) -> None:
    found = await _client_of(peer, forwarded_for)
    assert found is not None
    assert found[0] == client
