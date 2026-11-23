"""Traefik keeps realtime connections open on every entry point SupportX serves (audit row 5).

WebSocket and HTTP-streaming connections (WP-011) need Traefik's read and write timeouts off,
or they are cut after 60 s. With routing.tls on (the default but in dev) every route is served
on HTTPS, the websecure entry point, and plain HTTP only redirects: a setting on `web` alone
would leave every production and HA realtime connection on the default. Each HelmChartConfig the
repo ships for k3s must set both entry points.
"""

import re
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
CONFIGS = sorted(
    p
    for p in (
        DEPLOY / "k3d" / "traefik-config.yaml",  # single-node k3d and the k3s single-node example
        DEPLOY / "k3s" / "traefik-ha.yaml",  # HA installs and the k3d HA cluster
        DEPLOY / "staging" / "traefik-config.yaml",  # the staging laptop (D-169), once on main
    )
    if p.exists()
)


def _entry_point(text: str, name: str) -> str:
    """The indented block under `ports:` → `<name>:` in a HelmChartConfig's valuesContent."""
    pattern = rf"^(?P<indent> +){name}:\n(?P<body>(?:(?P=indent) +.*\n|\s*#.*\n)+)"
    found = re.search(pattern, text, re.MULTILINE)
    return found.group("body") if found else ""


@pytest.mark.parametrize("config", CONFIGS, ids=lambda p: str(p.relative_to(DEPLOY)))
@pytest.mark.parametrize("entry", ["web", "websecure"])
def test_streaming_timeouts_are_off_on_every_entry_point(config: Path, entry: str) -> None:
    block = _entry_point(config.read_text(), entry)
    assert block, f"{config.name} does not configure the {entry} entry point"
    for setting in ("readTimeout: 0", "writeTimeout: 0", "idleTimeout: 3600s"):
        assert setting in block, f"{config.name}: {entry} lacks `{setting}`"


def test_the_shipped_configs_are_all_checked() -> None:
    assert len(CONFIGS) >= 2
