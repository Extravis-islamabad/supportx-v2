### 2026-11-02 — WP-040 session 2: Entra ID sync and leavers (lane B)

- **Docs conflicts ended first (#160, D-123):** one file per decision and per session-log entry,
  with a renderer and a format test; plus a test that fails on two Alembic heads.
- **#150** merged main twice (#133, then #160), lane A's two review notes applied, and two
  guard failures fixed (OpenAPI after a docstring change, `connector_health.updated_at`).
- **Entra ID sync** on `feat/wp-040-entra` (migration 0053): Graph delta client and a fake Graph;
  mapping with skip reasons; people created, adopted by address, or updated through
  identity_access in the connector's own name; leavers deactivated, never deleted, their
  sessions ended from the worker; the last administrator kept; mapped groups followed;
  managers resolved after each round; Admin › Integrations › Directories; the person drawer
  says "managed by the directory" and locks those fields; imports leave synced people alone.
- **Tests:** domain and Graph client 12, PostgreSQL 17 (sync, API, RLS, migrations), console 9.
- **Dependabot:** #164-#166 closed (majors); #167 stops majors for npm and uv until the pilot.
  Auto-merge of #161-#163 refused by this session's permission check: left to the product owner.
- **Next:** AD/LDAP through Keycloak federation (D-118), the connector defaults screen (D-041).
