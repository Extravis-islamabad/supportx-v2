"""The chart's sign-in key ring (D-162, ADR-048): secrets by reference, the old single key kept.

`secrets.sessionKeys` lists key IDs and the app Secret's keys that hold them. The rendered
SUPPORTX_SESSION_KEYS names each secret by $(VAR) only, so no secret is in values or manifests,
and with the list empty the chart renders SUPPORTX_SESSION_SECRET alone, as before.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

CHART = Path(__file__).resolve().parents[2] / "deploy" / "helm" / "supportx"
BASE = (
    "--set", "publicUrl=https://x.example.com", "--set", "routing.hostnames={x.example.com}",
    "--set", "routing.gateway.tlsSecret=t", "-f", str(CHART / "values-single-node.yaml"),
)  # fmt: skip

# Needs Helm and the chart's fetched dependencies: the chart job runs it (ci.yml).
pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None
    or not list((CHART / "charts").glob("nats-*.tgz"))
    or not list((CHART / "charts").glob("valkey-*.tgz")),
    reason="needs Helm and the chart's dependencies (make chart-deps); run by the chart job",
)


def _render(*values: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - the test's own helm call
        ["helm", "template", "supportx", str(CHART), "-n", "supportx", *BASE, *values,  # noqa: S607
         "--show-only", "templates/api.yaml"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip


_ENTRY = re.compile(r"^ +- name: (SUPPORTX_[A-Z0-9_]+)\n +(value|valueFrom): (.*)$", re.MULTILINE)


def _api_env(manifests: str) -> dict[str, tuple[str, str]]:
    """The API container's variables in order: name -> ("value" | "valueFrom", raw text)."""
    return {m[1]: (m[2], m[3]) for m in _ENTRY.finditer(manifests)}


def test_without_a_list_only_the_single_secret_is_rendered() -> None:
    done = _render()
    assert done.returncode == 0, done.stderr
    names = list(_api_env(done.stdout))
    assert "SUPPORTX_SESSION_SECRET" in names
    assert "SUPPORTX_SESSION_KEYS" not in names


def test_a_list_renders_the_ring_by_reference() -> None:
    done = _render(
        "--set", "secrets.sessionKeys[0].id=2026-11",
        "--set", "secrets.sessionKeys[0].key=session-key-2026-11",
        "--set", "secrets.sessionKeys[1].id=legacy",
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    env = _api_env(done.stdout)
    assert env["SUPPORTX_SECRET_SESSION_KEY_0"] == (
        "valueFrom",
        "{secretKeyRef: {name: supportx-app, key: session-key-2026-11}}",
    )
    kind, raw = env["SUPPORTX_SESSION_KEYS"]
    assert kind == "value"
    assert json.loads(json.loads(raw)) == [
        {"id": "2026-11", "secret": "$(SUPPORTX_SECRET_SESSION_KEY_0)"},
        {"id": "legacy"},
    ]
    assert "SUPPORTX_SESSION_SECRET" in env  # still the API-key, cursor and proof fallback
    names = list(env)
    # Kubernetes expands $(VAR) only from variables defined before it.
    assert names.index("SUPPORTX_SECRET_SESSION_KEY_0") < names.index("SUPPORTX_SESSION_KEYS")


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (("secrets.sessionKeys[0].id=Bad",), "must be 1 to 32"),
        (("secrets.sessionKeys[0].id=k2",), "needs `key`"),
    ],
)
def test_a_bad_list_refuses_to_render(values: tuple[str, ...], message: str) -> None:
    done = _render(*(arg for value in values for arg in ("--set", value)))
    assert done.returncode != 0
    assert message in done.stderr
