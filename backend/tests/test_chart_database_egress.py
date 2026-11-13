"""An external backup target is open to the database's pods only (D-166, least privilege).

With the egress allow-list on, `networkPolicies.egress.database` adds one NetworkPolicy that
selects CloudNativePG's pods (cnpg.io/cluster, which every instance and a restore cluster carry)
and nothing else: the backup address never reaches the API, the workers or anyone else.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

CHART = Path(__file__).resolve().parents[2] / "deploy" / "helm" / "supportx"
TARGET = "10.89.0.9/32"
BASE = (
    "-f", str(CHART / "values-ha.yaml"),
    "--set", "publicUrl=https://x.example.com", "--set", "routing.tls.secretName=t",
    "--set", "networkPolicies.egress.enabled=true",
    "--set", "networkPolicies.egress.kubeApiCidrs={10.0.0.10/32}",
)  # fmt: skip

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None
    or not list((CHART / "charts").glob("nats-*.tgz"))
    or not list((CHART / "charts").glob("valkey-*.tgz")),
    reason="needs Helm and the chart's dependencies (make chart-deps); run by the chart job",
)


def _render(*values: str) -> str:
    return subprocess.run(  # noqa: S603 - the test's own helm call
        ["helm", "template", "supportx", str(CHART), "-n", "supportx", *BASE, *values],  # noqa: S607
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip


def _policies(rendered: str) -> list[str]:
    return [d for d in rendered.split("\n---") if "\nkind: NetworkPolicy" in d]


def test_the_backup_target_is_open_to_the_database_pods_only() -> None:
    out = _render(
        "--set-json",
        f'networkPolicies.egress.database=[{{"to":[{{"ipBlock":{{"cidr":"{TARGET}"}}}}],'
        '"ports":[{"protocol":"TCP","port":8333}]}]',
    )
    holding = [p for p in _policies(out) if TARGET in p]
    assert len(holding) == 1, "exactly one policy names the backup target"
    (policy,) = holding
    assert "name: supportx-database-egress" in policy
    assert "key: cnpg.io/cluster, operator: Exists" in policy
    assert "podSelector: {}" not in policy  # never every pod in the namespace


def test_no_database_rule_without_the_setting() -> None:
    assert not [p for p in _policies(_render()) if "supportx-database-egress" in p]
