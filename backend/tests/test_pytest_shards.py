"""The CI shard split (tooling/pytest_shards.py): balanced, complete, the same on every shard."""

import json
from pathlib import Path

import pytest

from tooling import pytest_shards
from tooling.pytest_shards import DEFAULT_SECONDS, assign, fallback_seconds, unweighted

WEIGHTS = {"a.py": 200.0, "b.py": 180.0, "c.py": 100.0, "d.py": 90.0, "e.py": 60.0}


def test_every_file_lands_on_exactly_one_shard_and_the_load_is_balanced() -> None:
    files = [*WEIGHTS, "new.py"]  # a file without a weight counts the median file
    placed = assign(files, WEIGHTS, 3)
    assert sorted(placed) == sorted(files)
    load = dict.fromkeys((1, 2, 3), 0.0)
    for name, shard in placed.items():
        load[shard] += WEIGHTS.get(name, fallback_seconds(WEIGHTS))
    # Longest-first onto the lightest shard: no shard waits on more than the heaviest file plus
    # a fair share.
    assert max(load.values()) <= 200.0 + sum(load.values()) / 3


def test_the_split_depends_only_on_the_files_and_weights() -> None:
    files = [*WEIGHTS, "new.py"]
    assert assign(files, WEIGHTS, 4) == assign(list(reversed(files)), WEIGHTS, 4)
    assert set(assign(files, WEIGHTS, 1).values()) == {1}


def test_an_unweighted_file_counts_a_heavy_measured_file_of_its_kind() -> None:
    """The 90th percentile, not the median (three shard timeouts from new files, #307)."""
    assert fallback_seconds(WEIGHTS) == 200.0  # 60, 90, 100, 180, 200: the top tenth
    assert fallback_seconds({}) == DEFAULT_SECONDS
    mixed = {"tests/db/a.py": 300.0, "tests/db/b.py": 280.0, "tests/u.py": 1.0, "tests/v.py": 2.0}
    assert fallback_seconds(mixed, "tests/db/new.py") == 300.0  # against database tests
    assert fallback_seconds(mixed, "tests/new.py") == 2.0  # against the quick ones


def test_unweighted_files_are_dealt_round_robin_never_packed() -> None:
    files = [*WEIGHTS, *(f"new{i}.py" for i in range(6))]
    placed = assign(files, WEIGHTS, 3)
    shards = [placed[f"new{i}.py"] for i in range(6)]
    assert sorted(shards) == [1, 1, 2, 2, 3, 3]  # two each, whatever the guess
    assert placed == assign(list(reversed(files)), WEIGHTS, 3)  # still the same everywhere


def test_the_unweighted_files_are_the_ones_the_weights_do_not_know() -> None:
    assert unweighted([*WEIGHTS, "new.py"], WEIGHTS) == ["new.py"]


def test_serial_files_are_spread_so_no_shard_waits_on_one_long_chain() -> None:
    weights = {"kc_a.py": 500.0, "kc_b.py": 300.0, **{f"db{n}.py": 100.0 for n in range(16)}}
    files = sorted(weights)
    placed = assign(files, weights, 4, serial=frozenset({"kc_a.py", "kc_b.py"}), workers=4)
    assert placed["kc_a.py"] != placed["kc_b.py"]
    # Without the serial rule both could land together (800 s on one worker).
    totals: dict[int, float] = {}
    chains: dict[int, float] = {}
    for name, shard in placed.items():
        totals[shard] = totals.get(shard, 0.0) + weights[name]
        if name.startswith("kc_"):
            chains[shard] = chains.get(shard, 0.0) + weights[name]
    finish = max(max(chains.get(s, 0.0), totals[s] / 4) for s in totals)
    assert finish <= 500.0


def test_without_serial_files_and_one_worker_the_split_is_the_old_one() -> None:
    files = sorted(WEIGHTS)
    assert assign(files, WEIGHTS, 3, serial=frozenset(), workers=1) == assign(files, WEIGHTS, 3)


def test_the_nightly_weights_overlay_the_committed_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    committed = tmp_path / "committed.json"
    committed.write_text(json.dumps({"a.py": 10.0, "new.py": 50.0}))
    nightly = tmp_path / "nightly.json"
    nightly.write_text(json.dumps({"a.py": 30.0, "b.py": 20.0}))
    monkeypatch.setattr(pytest_shards, "WEIGHTS", committed)
    monkeypatch.setenv("SUPPORTX_TEST_WEIGHTS", str(nightly))
    assert pytest_shards._weights() == {"a.py": 30.0, "b.py": 20.0, "new.py": 50.0}  # noqa: SLF001
    monkeypatch.setenv("SUPPORTX_TEST_WEIGHTS", str(tmp_path / "missing.json"))
    assert pytest_shards._weights() == {"a.py": 10.0, "new.py": 50.0}  # noqa: SLF001


def test_unweighted_keycloak_files_keep_the_chain_aware_placement() -> None:
    """Serial files are placed by their Keycloak chain, never dealt round-robin (#321)."""
    files = [*WEIGHTS, "kc_new1.py", "kc_new2.py"]
    serial = frozenset({"kc_new1.py", "kc_new2.py"})
    placed = assign(files, WEIGHTS, 3, serial=serial, workers=4)
    # Placed as heavy files by finish time: two Keycloak chains go to different shards.
    assert placed["kc_new1.py"] != placed["kc_new2.py"]
    assert placed == assign(list(reversed(files)), WEIGHTS, 3, serial=serial, workers=4)


# --- SUPPORTX_TEST_SELECT (tooling/test_select.py): only the selected files, then the split ---


class _Item:
    def __init__(self, nodeid: str) -> None:
        self.nodeid = nodeid
        self.fixturenames: tuple[str, ...] = ()


class _Hook:
    def __init__(self) -> None:
        self.deselected: list[_Item] = []

    def pytest_deselected(self, items: list[_Item]) -> None:
        self.deselected.extend(items)


class _Config:
    def __init__(self) -> None:
        self.hook = _Hook()
        self.stash = pytest.Stash()
        self.option = type("Option", (), {"numprocesses": 4})()


def _collect(items: list[_Item]) -> tuple[list[str], _Config]:
    config = _Config()
    kept: list[pytest.Item] = items  # type: ignore[assignment]  # stand-ins with the used attributes
    pytest_shards.pytest_collection_modifyitems(config, kept)  # type: ignore[arg-type]  # same
    return [item.nodeid for item in kept], config


ITEMS = [
    "tests/db/test_a.py::t1",
    "tests/db/test_a.py::t2",
    "tests/db/test_b.py::t",
    "tests/test_c.py::t",
]


def test_a_selection_keeps_only_its_files_before_the_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selection = tmp_path / "selection.json"
    selection.write_text(
        json.dumps({"all": False, "files": ["tests/db/test_a.py", "tests/test_c.py"]})
    )
    monkeypatch.setenv("SUPPORTX_TEST_SELECT", str(selection))
    monkeypatch.delenv("SUPPORTX_TEST_SHARD", raising=False)
    kept, config = _collect([_Item(n) for n in ITEMS])
    assert kept == ["tests/db/test_a.py::t1", "tests/db/test_a.py::t2", "tests/test_c.py::t"]
    assert [i.nodeid for i in config.hook.deselected] == ["tests/db/test_b.py::t"]
    # Then the shards split only the kept files: together they run exactly those.
    together: list[str] = []
    for shard in (1, 2):
        monkeypatch.setenv("SUPPORTX_TEST_SHARD", f"{shard}/2")
        together += _collect([_Item(n) for n in ITEMS])[0]
    assert sorted(together) == kept


def test_a_selection_of_everything_or_none_given_keeps_every_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SUPPORTX_TEST_SHARD", raising=False)
    monkeypatch.delenv("SUPPORTX_TEST_SELECT", raising=False)
    assert _collect([_Item(n) for n in ITEMS])[0] == ITEMS
    everything = tmp_path / "all.json"
    everything.write_text(json.dumps({"all": True, "files": []}))
    monkeypatch.setenv("SUPPORTX_TEST_SELECT", str(everything))
    kept, config = _collect([_Item(n) for n in ITEMS])
    assert kept == ITEMS
    assert config.stash.get(pytest_shards._SELECT_WARNING, None) is None  # noqa: SLF001


@pytest.mark.parametrize(
    "content",
    [
        None,
        "not json",
        '{"files": []}',
        '{"all": false, "files": []}',
        '{"all": "no", "files": ["x"]}',
    ],
)
def test_a_missing_or_bad_selection_runs_everything_with_a_warning(
    content: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never silently nothing: a selection that cannot be used runs every test, and says so."""
    selection = tmp_path / "selection.json"
    if content is not None:
        selection.write_text(content)
    monkeypatch.setenv("SUPPORTX_TEST_SELECT", str(selection))
    monkeypatch.delenv("SUPPORTX_TEST_SHARD", raising=False)
    kept, config = _collect([_Item(n) for n in ITEMS])
    assert kept == ITEMS
    warning = config.stash[pytest_shards._SELECT_WARNING]  # noqa: SLF001
    assert "running every test" in warning


def test_the_selection_warning_reaches_the_summary_and_the_job_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lines: list[str] = []
    reporter = type("Reporter", (), {"write_line": lambda _self, line, **_: lines.append(line)})()
    config = _Config()
    config.stash[pytest_shards._SELECT_WARNING] = "selection unusable"  # noqa: SLF001
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    pytest_shards.pytest_terminal_summary(reporter, config)  # type: ignore[arg-type]  # stand-ins
    assert lines == [
        "WARNING: selection unusable",
        "::warning title=Test selection ignored::selection unusable",
    ]
