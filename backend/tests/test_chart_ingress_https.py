"""Ingress mode never serves the app over plain HTTP when TLS is on (audit row 5, lane C).

Gateway mode gives plain HTTP only a 301 route. An Ingress has no portable way to say that, so a
first visit could sign in over http before HSTS applies. For the classes the chart knows it says
so itself: Traefik serves the routes on websecure only, ingress-nginx redirects. Any other class
renders only once the installer states that the controller enforces HTTPS.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

CHART = Path(__file__).resolve().parents[2] / "deploy" / "helm" / "supportx"
BASE = (
    "-f", str(CHART / "values-single-node.yaml"),
    "--set", "publicUrl=https://x.example.com", "--set", "routing.mode=ingress",
    "--set", "routing.ingress.tlsSecret=t", "--set", "routing.hostnames={x.example.com}",
)  # fmt: skip

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


def _ingress(rendered: str) -> str:
    return next(d for d in rendered.split("\n---") if "\nkind: Ingress" in d)


def test_traefik_serves_the_routes_on_https_only() -> None:
    ingress = _ingress(_render("--set", "routing.ingress.className=traefik").stdout)
    assert "traefik.ingress.kubernetes.io/router.entrypoints: websecure" in ingress
    assert 'traefik.ingress.kubernetes.io/router.tls: "true"' in ingress


def test_nginx_redirects_to_https() -> None:
    ingress = _ingress(_render("--set", "routing.ingress.className=nginx").stdout)
    assert 'nginx.ingress.kubernetes.io/ssl-redirect: "true"' in ingress
    assert 'nginx.ingress.kubernetes.io/force-ssl-redirect: "true"' in ingress


def test_the_installer_s_own_annotations_are_kept() -> None:
    out = _render(
        "--set", "routing.ingress.className=traefik",
        "--set", "routing.ingress.annotations.example\\.com/team=sx",
    ).stdout  # fmt: skip
    ingress = _ingress(out)
    assert "example.com/team: sx" in ingress
    assert "router.entrypoints: websecure" in ingress


def test_another_class_needs_the_installer_to_say_it_enforces_https() -> None:
    refused = _render("--set", "routing.ingress.className=haproxy", check=False)
    assert refused.returncode != 0
    assert "routing.ingress.enforcesHttps=true" in refused.stderr
    accepted = _render(
        "--set", "routing.ingress.className=haproxy", "--set", "routing.ingress.enforcesHttps=true"
    )
    assert "router.entrypoints" not in _ingress(accepted.stdout)


def test_tls_off_adds_nothing() -> None:
    out = _render(
        "--set", "routing.ingress.className=traefik", "--set", "routing.tls.enabled=false"
    )  # fmt: skip
    ingress = _ingress(out.stdout)
    assert "router.entrypoints" not in ingress
    assert "tls:" not in ingress.split("spec:", 1)[1]


@pytest.mark.parametrize(
    ("cls", "annotation"),
    [
        ("traefik", "traefik\\.ingress\\.kubernetes\\.io/router\\.entrypoints=web"),
        ("traefik", "traefik\\.ingress\\.kubernetes\\.io/router\\.entrypoints=web\\,websecure"),
        ("nginx", "nginx\\.ingress\\.kubernetes\\.io/ssl-redirect=false"),
    ],
)
def test_an_annotation_reopening_plain_http_is_refused(cls: str, annotation: str) -> None:
    refused = _render(
        "--set", f"routing.ingress.className={cls}",
        "--set-string", f"routing.ingress.annotations.{annotation}",
        check=False,
    )  # fmt: skip
    assert refused.returncode != 0
    assert "serves the app over plain HTTP" in refused.stderr
