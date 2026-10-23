"""`python -m tooling.wait_for_job`: hold a pod until this release's migrate Job is done (WP-014).

The API and worker pods run it as an init container, so new code never serves on a schema that
is still behind (first install and every upgrade). It reads the Job through the Kubernetes API
with the pod's service account (RBAC: `get` on jobs in the release namespace only); no kubectl.

Outcomes: the Job succeeded → start; the Job failed → exit 1 (the pod restarts and says why);
the Job is gone for `GONE_GRACE_SECONDS` → start (a newer release replaced it, so the schema is
at least as new; this happens when an old pod restarts after an upgrade); no answer within the
timeout → exit 1.

Environment: SUPPORTX_MIGRATE_JOB (the Job name), POD_NAMESPACE (downward API), optional
SUPPORTX_WAIT_TIMEOUT_SECONDS (900).
"""

import os
import ssl
import sys
import time
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx

SERVICE_ACCOUNT = Path("/var/run/secrets/kubernetes.io/serviceaccount")
API = "https://kubernetes.default.svc"
GONE_GRACE_SECONDS = 30.0
POLL_SECONDS = 2.0


class JobState(StrEnum):
    """Where the Job is."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RUNNING = "running"
    GONE = "gone"


def job_state(job: dict[str, Any] | None) -> JobState:
    """Interpret a batch/v1 Job object (None = 404)."""
    if job is None:
        return JobState.GONE
    status = job.get("status") or {}
    for condition in status.get("conditions") or []:
        if condition.get("status") != "True":
            continue
        if condition.get("type") in {"Complete", "SuccessCriteriaMet"}:
            return JobState.SUCCEEDED
        if condition.get("type") in {"Failed", "FailureTarget"}:
            return JobState.FAILED
    if (status.get("succeeded") or 0) >= 1:
        return JobState.SUCCEEDED
    return JobState.RUNNING


def fetch(client: httpx.Client, namespace: str, name: str) -> dict[str, Any] | None:
    """The Job, or None when it does not exist."""
    response = client.get(f"{API}/apis/batch/v1/namespaces/{namespace}/jobs/{name}")
    if response.status_code == 404:  # noqa: PLR2004 - HTTP Not Found
        return None
    response.raise_for_status()
    body: dict[str, Any] = response.json()
    return body


def wait(client: httpx.Client, namespace: str, name: str, timeout: float) -> JobState:
    """Poll until the Job is decided; GONE only after the grace period."""
    deadline = time.monotonic() + timeout
    gone_since: float | None = None
    while time.monotonic() < deadline:
        try:
            state = job_state(fetch(client, namespace, name))
        except httpx.HTTPError as exc:
            sys.stderr.write(f"wait_for_job: {type(exc).__name__}, retrying\n")
            state = JobState.RUNNING
        if state is JobState.GONE:
            gone_since = gone_since or time.monotonic()
            if time.monotonic() - gone_since >= GONE_GRACE_SECONDS:
                return JobState.GONE
        elif state is not JobState.RUNNING:
            return state
        else:
            gone_since = None
        time.sleep(POLL_SECONDS)
    return JobState.RUNNING


def main() -> int:  # pragma: no cover - needs a cluster; job_state and wait are tested
    """Init-container entry point."""
    name = os.environ["SUPPORTX_MIGRATE_JOB"]
    namespace = os.environ["POD_NAMESPACE"]
    timeout = float(os.environ.get("SUPPORTX_WAIT_TIMEOUT_SECONDS", "900"))
    token = (SERVICE_ACCOUNT / "token").read_text(encoding="utf-8").strip()
    context = ssl.create_default_context(cafile=str(SERVICE_ACCOUNT / "ca.crt"))
    with httpx.Client(
        verify=context, headers={"Authorization": f"Bearer {token}"}, timeout=10
    ) as client:
        state = wait(client, namespace, name, timeout)
    messages = {
        JobState.SUCCEEDED: f"migrate job {name} succeeded",
        JobState.GONE: f"migrate job {name} no longer exists (replaced by a newer release)",
        JobState.FAILED: f"migrate job {name} FAILED: see its logs",
        JobState.RUNNING: f"migrate job {name} did not finish within {timeout:.0f}s",
    }
    sys.stdout.write(messages[state] + "\n")
    return 0 if state in {JobState.SUCCEEDED, JobState.GONE} else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
