"""work_items registers the requested-records lister with ai at import (ADR-052; lane A, #502).

The erasure job runs in the consumers worker, which may never run the API's startup hooks, so the
ai port's embeddings phase must find the lister from imports alone. Checked in a fresh
interpreter: another test's app shutdown clears the registry in this one.
"""

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
_CHECK = (
    "import app.modules.work_items\n"
    "from app.modules.ai.service import person_data\n"
    "assert len(person_data._requested) == 1, person_data._requested\n"
)


def test_the_lister_is_there_without_any_startup() -> None:
    done = subprocess.run(  # noqa: S603 - this interpreter, a fixed script
        [sys.executable, "-c", _CHECK], cwd=BACKEND, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr[-2000:]
