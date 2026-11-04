"""The Temporal test-server helper retries a failed download and uses the cached folder."""

from pathlib import Path
from typing import Any

import pytest

from tooling import temporal_testing


async def test_a_rate_limited_download_is_tried_again(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPPORTX_TEMPORAL_TEST_SERVER_DIR", raising=False)
    calls: list[Any] = []
    pauses: list[float] = []

    async def start(**kwargs: Any) -> str:  # noqa: ANN401 - the SDK's keyword arguments
        calls.append(kwargs)
        if len(calls) < 3:
            msg = "failed to download ephemeral server executable: 429 Too Many Requests"
            raise RuntimeError(msg)
        return "environment"

    async def sleep(seconds: float) -> None:
        pauses.append(seconds)

    found: object = await temporal_testing.time_skipping(start, sleep)  # type: ignore[arg-type]  # a fake start
    assert found == "environment"
    assert pauses == [5.0, 10.0]
    assert calls[0] == {"download_dest_dir": None}


async def test_other_errors_and_the_last_attempt_are_not_hidden() -> None:
    async def broken(**kwargs: Any) -> str:  # noqa: ANN401 - the SDK's keyword arguments
        del kwargs
        msg = "port in use"
        raise RuntimeError(msg)

    async def no_sleep(seconds: float) -> None:
        del seconds

    with pytest.raises(RuntimeError, match="port in use"):
        await temporal_testing.time_skipping(broken, no_sleep)  # type: ignore[arg-type]  # a fake start


def test_the_cache_folder_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    folder = tmp_path / "temporal"
    monkeypatch.setenv("SUPPORTX_TEMPORAL_TEST_SERVER_DIR", str(folder))
    assert temporal_testing.download_dir() == str(folder)
    assert folder.is_dir()
