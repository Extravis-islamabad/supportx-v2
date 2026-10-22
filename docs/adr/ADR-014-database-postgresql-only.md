# ADR-014: Database engines supported: PostgreSQL only

- **Status:** Accepted
- **Date:** 2026-10-22
- **Source:** architecture.md §7.5
- **Owner:** TBC

## Context

SDP on-prem supports SQL Server and PostgreSQL. SupportX depends on RLS, JSONB indexing and pgvector; a second engine doubles migration, test and performance work.

## Decision

PostgreSQL 16 is the only system of record, bundled, installed, tuned and backed up by the installer. SQL Server shops get a reporting connector that replicates/exports into their SQL Server.

## Consequences

- **Positive:** One engine to optimise and test.
- **Negative:** Some tenders demanding SQL Server must be answered with the reporting connector.

## Notes

Accepted at bootstrap (architecture.md §19 listed it as *Proposed*); confirm owner at Stage 0 sign-off.
