"""A request's money stays withheld in reports (WP-047b S1; lane B's #633 note). No I/O.

Every decimal (money) field the service request report source offers, and the frozen charge,
must be in MONEY_FIELDS, so a new money column can never reach a report without the cost right
(work_items is granted to the report role table-wide, so the source is the only guard).
"""

from app.modules.work_items.service.access import SERVICE_REQUEST_FIELDS
from app.modules.work_items.service.reporting import MONEY_FIELDS
from app.shared.api.filters import FieldType


def test_every_money_field_of_a_request_is_withheld_without_the_cost_right() -> None:
    money = {name for name, f in SERVICE_REQUEST_FIELDS.items() if f.type is FieldType.DECIMAL}
    assert money  # the estimate and the charged amount at least
    assert money <= MONEY_FIELDS
    charge = {name for name in SERVICE_REQUEST_FIELDS if name.startswith("charge")}
    assert charge <= MONEY_FIELDS
