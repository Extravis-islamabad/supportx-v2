"""Every module whose tables name a person has an erasure port, or says why not (ADR-052 §4).

The readiness check of 2026-11-14 found two modules (assets, service_catalog) holding person
data with no erasure port: an erasure would have run and skipped them. This scans each module's
`infra/models.py` for columns that reference a person and fails unless the module registers an
erasure port (its key is the module, or `module.<part>`) or appears in `ERASURE_EXEMPT` with a
reason. A new table that names people therefore cannot slip past the erasure unnoticed.
"""

import ast
from pathlib import Path

from app.core.modules import discover_modules
from app.modules.identity_access.service.person_data import registered_ports
from tests.erasure_pending import PENDING

MODULES = Path(__file__).resolve().parents[1] / "app" / "modules"
PERSON_COLUMNS = frozenset(
    {
        "user_id",
        "owner_id",
        "holder_id",
        "borrower_id",
        "requester_id",
        "on_behalf_of_id",
        "assignee_id",
        "technician_id",
        "approver_id",
        "member_id",
        "person_id",
        "manager_id",
        "lead_id",
        "chair_id",
        "recipient_id",
        "author_id",
        "successor_id",
    }
)
AUDIT_ONLY = "audit columns (*_by) only: they point at the anonymised row (ADR-052 step 5)"
ERASURE_EXEMPT: dict[str, str] = {
    "licensing": AUDIT_ONLY,
    "metadata": "custom_fields.index_requested_by is the admin who asked for an index: an ID"
    " that points at the anonymised row, no personal data of theirs",
    # Ports still to come are required already (tests/erasure_pending.py): approval and the job
    # refuse until they register, and each key leaves this list with its port.
    **dict.fromkeys(PENDING, "required, its port still to come (erasure refuses meanwhile)"),
}


def is_person_column(name: str) -> bool:
    """A column that names a person: the known names, `*_user_id`, or an audit `*_by`."""
    return name in PERSON_COLUMNS or name.endswith(("_user_id", "_by"))


def person_columns(source: str) -> set[str]:
    """The person-referencing `Mapped[...]` columns a models file declares."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and "Mapped" in ast.unparse(node.annotation)
            and is_person_column(node.target.id)
        ):
            found.add(node.target.id)
    return found


def _uncovered() -> dict[str, list[str]]:
    discover_modules()  # every module's ports, as at start-up
    covered = {port.module.split(".")[0] for port in registered_ports()}
    gaps: dict[str, list[str]] = {}
    for models in sorted(MODULES.glob("*/infra/models.py")):
        module = models.parts[-3]
        columns = person_columns(models.read_text(encoding="utf-8"))
        if columns and module not in covered and module not in ERASURE_EXEMPT:
            gaps[module] = sorted(columns)
    return gaps


def test_every_module_naming_people_has_an_erasure_port_or_a_reason() -> None:
    assert _uncovered() == {}, "add an erasure port (ADR-052 §4) or an ERASURE_EXEMPT reason"


def test_exemptions_are_not_stale() -> None:
    """An exempt module that now has a port must leave the list (keep it honest)."""
    discover_modules()
    covered = {port.module.split(".")[0] for port in registered_ports()}
    assert sorted(set(ERASURE_EXEMPT) & covered) == []


def test_the_scan_finds_person_columns() -> None:
    """The scan itself works: a synthetic table naming a person is caught (and others are not)."""
    snippet = """
class Thing(Base):
    holder_id: Mapped[uuid.UUID]
    reviewed_by: Mapped[uuid.UUID | None]
    vendor_user_id: Mapped[uuid.UUID | None] = mapped_column()
    asset_id: Mapped[uuid.UUID]
    name: Mapped[str] = mapped_column(String(200))
"""
    assert person_columns(snippet) == {"holder_id", "reviewed_by", "vendor_user_id"}
