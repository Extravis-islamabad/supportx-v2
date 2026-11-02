"""Exactly one Alembic head (LANES rule 3).

Lanes renumber their migration when the merge queue rejects a clash; this test is what rejects it.
It needs no database, so it runs in the required fast `backend` check.
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import Script, ScriptDirectory

BACKEND = Path(__file__).resolve().parents[1]


def _scripts() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))


def _file(script: Script) -> str:
    return Path(script.path).name


def branches(scripts: ScriptDirectory) -> str:
    """Each head and, for every revision two migrations build on, the files that branch."""
    lines = [
        f"heads: {', '.join(sorted(_file(scripts.get_revision(h)) for h in scripts.get_heads()))}"
    ]
    for script in scripts.walk_revisions():
        children = sorted(script.nextrev)
        if len(children) > 1:
            files = ", ".join(sorted(_file(scripts.get_revision(c)) for c in children))
            lines.append(f"{_file(script)} is revised by more than one migration: {files}")
    return "\n".join(lines)


def test_migrations_have_exactly_one_head() -> None:
    scripts = _scripts()
    heads = scripts.get_heads()
    assert len(heads) == 1, (
        "more than one migration head: renumber your migration after main's head and point its"
        f" down_revision there (LANES rule 3)\n{branches(scripts)}"
    )


def test_a_branch_is_reported_with_the_files_that_branch(tmp_path: Path) -> None:
    versions = tmp_path / "versions"
    versions.mkdir()
    for name, revision, down in (
        ("0001_base.py", "0001", None),
        ("0002_lane_a.py", "0002", "0001"),
        ("0002_lane_b.py", "0002b", "0001"),
    ):
        (versions / name).write_text(
            f"revision = {revision!r}\ndown_revision = {down!r}\nbranch_labels = None\n"
            "depends_on = None\n\n\ndef upgrade() -> None: ...\n\n\ndef downgrade() -> None: ...\n",
            encoding="utf-8",
        )
    config = Config()
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("version_locations", str(versions))
    scripts = ScriptDirectory.from_config(config)
    assert len(scripts.get_heads()) == 2
    report = branches(scripts)
    assert "heads: 0002_lane_a.py, 0002_lane_b.py" in report
    assert (
        "0001_base.py is revised by more than one migration: 0002_lane_a.py, 0002_lane_b.py"
        in report
    )
