"""The login-events reader's secret reaches two pods only (WP-057 S1b; lane B's condition 2).

`supportx-events` may read every tenant's login events (view-events), so its secret goes to the
consumers worker (the import) and the keycloak-identity Job (which makes the client), never to
the API, the other workers or the migrate Job.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

CHART = Path(__file__).resolve().parents[2] / "deploy" / "helm" / "supportx"
VARIABLE = "SUPPORTX_KEYCLOAK_EVENTS_CLIENT_SECRET"

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None
    or not list((CHART / "charts").glob("nats-*.tgz"))
    or not list((CHART / "charts").glob("valkey-*.tgz")),
    reason="needs Helm and the chart's dependencies (make chart-deps); run by the chart job",
)


_KIND = re.compile(r"^kind: (\w+)$", re.MULTILINE)
_NAME = re.compile(r"^metadata:\n  name: ([\w.-]+)$", re.MULTILINE)


def _holders() -> set[str]:
    """`<kind>/<name>` of every rendered object whose env names the variable."""
    done = subprocess.run(  # noqa: S603 - the test's own helm call
        ["helm", "template", "supportx", str(CHART), "-n", "supportx",  # noqa: S607
         "-f", str(CHART / "values-single-node.yaml"), "--set", "publicUrl=https://x.example.com",
         "--set", "routing.hostnames={x.example.com}", "--set", "routing.gateway.tlsSecret=t"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    found: set[str] = set()
    for doc in done.stdout.split("\n---\n"):
        if f"- name: {VARIABLE}" not in doc:
            continue
        kind, name = _KIND.search(doc), _NAME.search(doc)
        assert kind is not None, doc[:200]
        assert name is not None, doc[:200]
        found.add(f"{kind[1]}/{name[1]}")
    return found


def test_only_the_consumers_worker_and_the_identity_job_hold_the_events_secret() -> None:
    holders = _holders()
    assert len(holders) == 2, holders
    assert any(h.startswith("Deployment/") and "consumers" in h for h in holders), holders
    assert any(h.startswith("Job/") and "keycloak-identity" in h for h in holders), holders
    assert not any(h.endswith("-api") for h in holders)
