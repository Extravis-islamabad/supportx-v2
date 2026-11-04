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
