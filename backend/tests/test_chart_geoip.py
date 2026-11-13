"""The place database is a volume, never in an image (WP-057 S2b; D-170; the coordinator).

`geoip.existingClaim` mounts the operator's claim read-only into the API pods only (they name the
sign-in place) and points SUPPORTX_GEOIP_DB at the file. Not set: nothing is rendered.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

CHART = Path(__file__).resolve().parents[2] / "deploy" / "helm" / "supportx"
BASE = (
    "--set", "publicUrl=https://x.example.com", "--set", "routing.tls.secretName=t",
)  # fmt: skip

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None or not list((CHART / "charts").glob("nats-*.tgz")),
    reason="needs Helm and the chart's dependencies (make chart-deps); run by the chart job",
)


def _render(*values: str) -> str:
    return subprocess.run(  # noqa: S603 - the test's own helm call
        ["helm", "template", "supportx", str(CHART), "-n", "supportx", *BASE, *values],  # noqa: S607
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip


def _deployments(rendered: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for doc in rendered.split("\n---"):
        if "\nkind: Deployment" in doc:
            name = doc.split("\n  name: ", 1)[1].split("\n", 1)[0]
            found[name] = doc
    return found


def test_no_place_database_without_the_setting() -> None:
    assert "geoip" not in _render().lower()


def test_the_claim_is_mounted_read_only_into_the_api_only() -> None:
    deployments = _deployments(_render("--set", "geoip.existingClaim=place-db"))
    api = deployments["supportx-api"]
    assert "SUPPORTX_GEOIP_DB" in api
    assert "/var/lib/supportx/geoip/dbip-city-lite.mmdb" in api
    assert "{name: geoip, mountPath: /var/lib/supportx/geoip, readOnly: true}" in api
    assert "claimName: place-db, readOnly: true" in api
    others = [
        name for name, doc in deployments.items() if name != "supportx-api" and "geoip" in doc
    ]
    assert others == []  # workers and the rest never get it


def test_the_file_must_be_a_plain_name_on_the_claim() -> None:
    """Lane B (#486): never a path, so the setting cannot point outside the mounted claim."""
    done = subprocess.run(  # noqa: S603 - the test's own helm call
        ["helm", "template", "supportx", str(CHART), "-n", "supportx", *BASE,  # noqa: S607
         "--set", "geoip.existingClaim=place-db", "--set", "geoip.file=../etc/passwd"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert done.returncode != 0
    assert "geoip.file must be a plain file name" in done.stderr
