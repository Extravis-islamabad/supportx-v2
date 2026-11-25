"""The person IDs in a request's stage snapshot are covered by a required erasure port.

WP-047a S2a, the coordinator's snapshot condition 2. The column scan in
`test_erasure_ports_cover_person_columns.py` reads typed columns only; IDs inside JSON are
listed here with the port that removes them, which must be registered and required (so an
erasure refuses to start without it, ADR-052 §4).
"""

from app.core.modules import discover_modules
from app.modules.identity_access import REQUIRED_PORTS
from app.modules.identity_access.service.person_data import registered_ports
from app.modules.work_items.service.person_data import REFERENCE_PHASES, References

# (table.column holding person IDs in JSON) -> (the port's key, the kind it counts)
JSON_PERSON_IDS = {
    "work_items.approval_stages": ("work_items.references", "stage_approvers_removed"),
}


def test_json_person_ids_have_a_registered_required_port() -> None:
    discover_modules()  # every module's ports, as at start-up
    ports = {port.module: port for port in registered_ports()}
    for column, (key, kind) in JSON_PERSON_IDS.items():
        assert key in REQUIRED_PORTS, column
        assert key in ports, column
        assert kind in ports[key].kinds, column


def test_the_snapshot_phase_runs_after_the_approvals_are_rerouted() -> None:
    """Their pending rows reroute first; the snapshot then drops them for stages not yet open."""
    names = [name for name, _ in REFERENCE_PHASES]
    assert names.index("approvals") < names.index("stage_snapshots")
    assert "stage_approvers_removed" in References.kinds
