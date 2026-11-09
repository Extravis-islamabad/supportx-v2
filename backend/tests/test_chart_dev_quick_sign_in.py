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

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="needs Helm")


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
