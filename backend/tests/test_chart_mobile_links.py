"""The mobile app's verified links (ADR-044 item 3) come from the chart's mobile values.

The web pods serve apple-app-site-association and assetlinks.json only for the apps an
installation names, so only those apps receive the sign-in return. Nothing configured: no
ConfigMap and no mount, and the paths answer 404 (deploy/images/nginx.conf).
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

# Rendering needs Helm and the chart's fetched dependencies (`make chart-deps`): the backend
# shards skip, and the CI chart job runs every tests/test_chart_*.py after `make chart-lint`.
pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None
    or not list((CHART / "charts").glob("nats-*.tgz"))
    or not list((CHART / "charts").glob("valkey-*.tgz")),
    reason="needs Helm and the chart's dependencies (make chart-deps); run by the chart job",
)


def _render(*values: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - the test's own helm call
        ["helm", "template", "supportx", str(CHART), "-n", "supportx", *BASE, *values],  # noqa: S607
        capture_output=True, text=True, check=check,
    )  # fmt: skip


def _docs(rendered: str) -> list[str]:
    return [d for d in rendered.split("\n---") if d.strip()]


def test_no_app_configured_serves_no_file() -> None:
    out = _render().stdout
    assert "name: supportx-mobile-links" not in out
    assert "/etc/nginx/well-known" not in out


def test_the_named_apps_and_only_the_return_path() -> None:
    out = _render(
        "--set", "mobile.ios.appIds={ABCDE12345.com.extravis.supportx}",
        "--set", "mobile.android.package=com.extravis.supportx",
        "--set", "mobile.android.certSha256={AB:CD:EF}",
    ).stdout  # fmt: skip
    links = next(
        d for d in _docs(out) if "name: supportx-mobile-links" in d and "kind: ConfigMap" in d
    )
    lines = links.splitlines()
    aasa = json.loads(lines[lines.index("  apple-app-site-association: |") + 1])
    assert aasa == {
        "applinks": {
            "details": [
                {
                    "appIDs": ["ABCDE12345.com.extravis.supportx"],
                    "components": [{"/": "/mobile/auth*"}],
                }
            ]
        }
    }
    android = json.loads(lines[lines.index("  assetlinks.json: |") + 1])
    assert android[0]["target"] == {
        "namespace": "android_app",
        "package_name": "com.extravis.supportx",
        "sha256_cert_fingerprints": ["AB:CD:EF"],
    }
    web = next(d for d in _docs(out) if "kind: Deployment" in d and "name: supportx-web" in d)
    assert "mountPath: /etc/nginx/well-known, readOnly: true" in web


def test_an_android_app_needs_its_signing_fingerprint() -> None:
    done = _render("--set", "mobile.android.package=com.extravis.supportx", check=False)
    assert done.returncode != 0
    assert "certSha256 is required" in done.stderr
