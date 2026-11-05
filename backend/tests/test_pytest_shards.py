"""The CI shard split (tooling/pytest_shards.py): balanced, complete, the same on every shard."""

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


def test_an_unweighted_file_counts_the_median_measured_file() -> None:
    assert fallback_seconds(WEIGHTS) == 100.0  # 60, 90, 100, 180, 200
    assert fallback_seconds({}) == DEFAULT_SECONDS
    # Three new files of 100 s each are no longer "light": they don't all pile onto one shard.
    files = [*WEIGHTS, "new1.py", "new2.py", "new3.py"]
    shards = {assign(files, WEIGHTS, 3)[name] for name in ("new1.py", "new2.py", "new3.py")}
    assert len(shards) > 1


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
