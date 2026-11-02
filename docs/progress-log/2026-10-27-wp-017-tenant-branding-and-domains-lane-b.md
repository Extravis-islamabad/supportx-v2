### 2026-10-27 — WP-017 tenant branding and domains (lane B)

- Planned and built in `../supportx-v2-wp017` (branch `feat/wp-017-branding`). Migration 0022
  after lane A's 0021; decisions D-089 (the product owner's WP-039 answers) and D-090 (WP-017
  defaults); ADR-031 (proposed). The dev addresses' callbacks are registered by the e2e setup
  (realm files never carry UI origins). Lane A told: the mail foundation (D-089 D3), numbering (lane A
  takes D-091, D-092, migration 0023), the SSO attribute lookup shape for WP-021.
- A throwaway Keycloak 26.8.1 confirmed `org` in login templates, the `organization:<alias>`
  scope (only that organization in the token; none for non-members; not combinable with
  `organization:*`) and the theme property's environment substitution.
- The colour rules moved from `tooling/brand_assets.py` into the organization domain, so the
  default brand, tenants and the sign-in stylesheet share one implementation.
