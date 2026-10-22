# migrations

Alembic migrations for the Core API database. Set up in **WP-005** (data layer, RLS and tenancy).

Rules (CLAUDE.md §5–§6): every business table gets `tenant_id` and an RLS policy, migrations follow
expand/contract and must downgrade cleanly. Never run a downgrade against a database holding real data.
