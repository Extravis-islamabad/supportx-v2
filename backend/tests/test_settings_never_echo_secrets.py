"""A refused start-up never repeats a secret (D-162 review): not in the error, not in the logs.

Pydantic used to print the whole input with a refused setting, every secret included. The
settings now hide their input (`hide_input_in_errors`), and the session-key parser never chains
the JSON decoder's error (which holds the text). Checked in-process (the raised error, its
traceback and anything logged) and as the API process starts (its whole output).
"""

import logging
import os
import subprocess
import sys
import traceback
from pathlib import Path

import pytest
from pydantic import ValidationError

from conftest import make_settings

BACKEND = Path(__file__).resolve().parents[1]
MARKER = "sx-secret-marker-7f3a9c1e5b2d4086"  # recognisable, 32+ characters
REFUSALS = [
    # A malformed ring: a bad key ID next to a secret.
    {"session_keys": f'[{{"id": "Bad ID", "secret": "{MARKER}"}}]'},
    # Not JSON at all: the decoder's own error would hold the text.
    {"session_keys": f'[{{"id": "k2", "secret": "{MARKER}"'},
    # A short ring key next to the marker in another setting.
    {"session_keys": '[{"id": "k2", "secret": "short"}]', "session_secret": MARKER},
    # Production without its backing services, secrets set.
    {"profile": "production", "session_secret": MARKER, "api_key_secret": MARKER},
]


@pytest.mark.parametrize("values", REFUSALS)
def test_a_refused_setting_never_shows_a_secret_in_process(
    values: dict[str, str], caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ValidationError) as refused:
        make_settings(**values)
    shown = "".join(traceback.format_exception(refused.value))
    for text in (str(refused.value), repr(refused.value), shown, caplog.text, *capsys.readouterr()):
        assert MARKER not in text
    assert "SUPPORTX_" in str(refused.value)  # the reason is still named


@pytest.mark.parametrize("values", REFUSALS)
def test_a_refused_start_up_prints_no_secret(values: dict[str, str]) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("SUPPORTX_")}
    env |= {f"SUPPORTX_{name.upper()}": value for name, value in values.items()}
    env.setdefault("SUPPORTX_PROFILE", "test")
    done = subprocess.run(
        [sys.executable, "-c", "from app.main import create_app; create_app()"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode != 0
    assert "ValidationError" in done.stderr  # it was refused by the settings, not something else
    assert MARKER not in done.stdout
    assert MARKER not in done.stderr
