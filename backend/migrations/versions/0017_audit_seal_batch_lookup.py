"""audit_seal: batch from the queue, entries by key, no JIT (WP-018 follow-up).

The 10M volume run sealed at 875 entries/s against 8,415/s at 100k. Measured on one batch of
5,000 at 10M entries (98 monthly partitions):

- the batch query joined the queue to `audit_entries` and left the join order to the planner.
  Without statistics on freshly loaded partitions it started from the entries; with statistics
  it hash-joined the tenant's whole log. Either way each batch read every entry of the tenant
  (about 10 s at 10M);
- the planner's inflated cost estimate also crossed `jit_above_cost`, so PostgreSQL JIT-compiled
  the query on every call: 677 functions (about one per partition scan), 2.1 to 2.5 s per batch,
  for a query whose own work takes about 30 ms.

Now the batch is taken from the queue alone (its sealing-order index, migration 0015), each entry
is fetched by its key through LATERAL (run-time pruning to one partition, one index probe), and
the function runs with `jit = off`: JIT cannot help short row-by-row work. Same inputs, order and
hashes as before; only the plan changes. Reversible.

Revision ID: 0017
Revises: 0016
Created: 2026-10-26
"""

import importlib
from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEAL = """
CREATE OR REPLACE FUNCTION audit_seal(p_limit integer) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public SET jit = off AS $$
DECLARE
    t uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
    last_seq bigint;
    last_hash bytea;
    next_hash bytea;
    r record;
    sealed integer := 0;
BEGIN
    IF t IS NULL THEN
        RAISE EXCEPTION 'audit_seal needs app.tenant_id';
    END IF;
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 5000 THEN
        RAISE EXCEPTION 'audit_seal limit must be between 1 and 5000';
    END IF;
    -- One sealer per tenant at a time; others wait and then find the queue already sealed.
    PERFORM pg_advisory_xact_lock(724118, hashtext(t::text));
    SELECT c.seq, c.chain_hash INTO last_seq, last_hash
      FROM audit_chain c WHERE c.tenant_id = t ORDER BY c.seq DESC LIMIT 1;
    IF last_seq IS NULL THEN
        last_seq := 0;
        last_hash := decode(repeat('00', 32), 'hex');
    END IF;
    -- The batch comes from the queue alone; each entry is then fetched by its key. Never a join
    -- the planner may drive from audit_entries (that read the tenant's whole log per batch).
    FOR r IN
        WITH batch AS MATERIALIZED (
            SELECT q.entry_id, q.occurred_at
              FROM audit_queue q
             WHERE q.tenant_id = t
             ORDER BY q.occurred_at, q.entry_id
             LIMIT p_limit
        )
        SELECT b.entry_id, b.occurred_at, e.entry_hash
          FROM batch b
          CROSS JOIN LATERAL (
              SELECT x.entry_hash
                FROM audit_entries x
               WHERE x.tenant_id = t AND x.occurred_at = b.occurred_at AND x.id = b.entry_id
          ) e
         ORDER BY b.occurred_at, b.entry_id
    LOOP
        last_seq := last_seq + 1;
        -- Same bytes as app/modules/audit/domain/integrity.py chain_hash().
        next_hash := sha256(
            convert_to('sx-audit-v1', 'UTF8') || uuid_send(t) || int8send(last_seq)
            || last_hash || r.entry_hash
        );
        INSERT INTO audit_chain
            (tenant_id, seq, entry_id, entry_occurred_at, entry_hash, prev_hash, chain_hash,
             sealed_at)
        VALUES (t, last_seq, r.entry_id, r.occurred_at, r.entry_hash, last_hash, next_hash,
                clock_timestamp());
        DELETE FROM audit_queue WHERE tenant_id = t AND entry_id = r.entry_id;
        last_hash := next_hash;
        sealed := sealed + 1;
    END LOOP;
    RETURN sealed;
END
$$
"""


def upgrade() -> None:
    # CREATE OR REPLACE keeps the owner (the migrator: SECURITY DEFINER) and the grants.
    op.execute(SEAL)


def downgrade() -> None:
    previous = importlib.import_module("migrations.versions.0014_audit").SEAL
    op.execute(previous.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
