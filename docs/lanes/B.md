# Lane B

This lane's own file (D-127): only this lane edits it, at every start and finish of a
work package. The index and the rules are in [`docs/LANES.md`](../LANES.md).

## Area

Identity, mail, notifications, CI

## Current WP

**Paused 2026-11-04 (product owner, via the coordinator).** Resume: write `integrations/service/ldap_directories.py` (create/update/remove/list; `has_feature(DIRECTORY_FEDERATION)`; refused unless single-tenant (`settings.multi_tenant` off, as identity_settings does) and the federation secret is installed; bind password in the secrets store as type `password`; audited plain choice), then the consumer applying it to Keycloak. Done so far on #175: federation account, chart, licence add-on, LDAP domain rules, KeycloakAdmin federation calls, migration 0055. Also open: #179 (stack-smoke shards, full-ci, not yet on --auto: queue it once its own stack smoke shows both shards finish). WP-040 session 2's rest on #175: AD/LDAP through Keycloak federation (D-118; product owner 2026-11-03: separate supportx-federation account, manage-realm only, on-prem LDAP only), then the connector defaults screen (D-041). Merged: #150, #168, #171 (D-127). Queue after WP-040: QA round, WP-013 (licence core, private repo), WP-014b, WP-014c. WP-037/038 (AI) moved to lane C; lane B reviews the gateway's security parts when asked.

## Branch

`feat/wp-040-ldap` (#175)

## Worktree

`../supportx-v2-entra`

## Claimed migration

0024, 0026, 0032, 0033, 0037, 0042, 0043, 0045, 0049, 0052, 0053 (merged); 0055 AD/LDAP directories (#175, revises main's head 0051 after #159; lane A's 0054 (#172) and 0058 (#178) also follow 0051, so whoever merges second re-points)

## Claimed decisions

D-098, D-099, D-103, D-104, D-106, D-109, D-116, D-118, D-123, D-127 (D-126 reserved: the Dependabot rule, waiting for the product owner)
