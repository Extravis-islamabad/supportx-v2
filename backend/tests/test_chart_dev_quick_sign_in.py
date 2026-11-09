"""The Helm chart never carries the dev-only quick sign-in (D-151).

Rendering fails when anything would switch it on, and no realm the chart ships, the dev profile
included, allows the password grant the quick sign-in uses (only the local Compose stack does).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

CHART = Path(__file__).resolve().parents[2] / "deploy" / "helm" / "supportx"
BASE = (
    "--set", "publicUrl=https://x.example.com", "--set", "routing.hostnames={x.example.com}",
    "--set", "routing.gateway.tlsSecret=t",
)  # fmt: skip
PROFILES = ("values.yaml", "values-dev.yaml", "values-single-node.yaml", "values-ha.yaml")

# Rendering needs Helm and the chart's fetched dependencies (`make chart-deps`). The backend
# shards have neither fetched, so they skip; the CI chart job runs this file after `make
# chart-lint`, so it always runs there (ci.yml).
pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None
    or not list((CHART / "charts").glob("nats-*.tgz"))
    or not list((CHART / "charts").glob("valkey-*.tgz")),
    reason="needs Helm and the chart's dependencies (make chart-deps); run by the chart job",
)


def _render(*values: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - the test's own helm call
        ["helm", "template", "supportx", str(CHART), "-n", "supportx", *BASE, *values],  # noqa: S607
        capture_output=True, text=True, check=False,
    )  # fmt: skip


@pytest.mark.parametrize(
    "value",
    [
        "devQuickSignIn=true",
        "app.extraEnv.SUPPORTX_DEV_QUICK_SIGN_IN=true",
        "app.extraEnv.SUPPORTX_SHOWCASE_PASSWORD=x",
        "app.extraEnv.SUPPORTX_SHOWCASE_TOTP_KEY=x",
    ],
)
def test_the_chart_refuses_to_render_it(value: str) -> None:
    done = _render("--set", value)
    assert done.returncode != 0
    assert "D-151" in done.stderr


@pytest.mark.parametrize("profile", PROFILES)
def test_no_realm_the_chart_ships_allows_the_password_grant(profile: str) -> None:
    done = _render("-f", str(CHART / profile), "--show-only", "templates/keycloak.yaml")
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "supportx-realm.json: |")
    body = []
    for line in lines[start + 1 :]:
        if line and not line.startswith("    "):
            break
        body.append(line[4:])
    realm = json.loads("\n".join(body))
    assert all(c.get("directAccessGrantsEnabled") is not True for c in realm["clients"])
    # The production session limits, never the Compose stack's week with "remember me".
    assert (
        realm["rememberMe"],
        realm["ssoSessionIdleTimeout"],
        realm["ssoSessionMaxLifespan"],
    ) == (
        False,
        1800,
        43200,
    )
    assert realm.get("ssoSessionIdleTimeoutRememberMe", 0) == 0
    assert realm.get("ssoSessionMaxLifespanRememberMe", 0) == 0
