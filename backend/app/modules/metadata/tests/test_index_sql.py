"""Promoted custom-field indexes lead with the type only where the table holds many types."""

from app.modules.metadata.domain.fields import FieldType
from app.modules.metadata.infra.expressions import index_sql


def test_work_items_indexes_lead_with_tenant_and_type() -> None:
    sql = index_sql("work_items", "incident", "room", FieldType.TEXT)
    assert " ON work_items (tenant_id, type, " in sql


def test_a_module_s_own_table_leads_with_the_tenant_only() -> None:
    sql = index_sql("assets", "asset", "cost_centre", FieldType.TEXT)
    assert " ON assets (tenant_id, " in sql
    assert "type" not in sql.split(" ON assets ", 1)[1].split(",", 2)[1]
