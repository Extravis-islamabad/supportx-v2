### 2026-11-05 — WP-044a session 3: problems from incidents (lane A)

**Scope:** REQ-PRB-011, -012, -014, -015 on the problem type from sessions 1-2. PR #211 (draft).

**Built**
- `service/problems.py`: prefill, link_cause (one problem per incident; move on confirmation),
  already_caused, similar (search port), copy_values / copied_from.
- `api/problem_routes.py` (before `/{record_id}`): `GET /problems/prefill`, `GET
  /problems/similar`, `POST /problems/from-incidents/preview`, `POST /problems/from-incidents`,
  `POST /problems/{id}/incidents`, `GET` and `POST /problems/{id}/copy`.
- Bulk action `link_problem` (incidents only); `start_problem_links` queues one job to link
  and one to move.
- Migration 0089 (still unmerged) also takes the `caused_by` link kind, the one-cause partial
  unique index and the bulk action check.
- Record links read caused_by / causes and carry `other_type`. Visibility is checked against
  the other record's own type.
- Labels in en/ar/ur: link kind and relations, the bulk action, `errors.incident_has_problem`,
  `work_item.field.copied_from`, and `work_item_type.*` (now in the contract).

**Checks:**
- ruff, mypy (971 files), import-linter (16 kept);
- work_items unit tests (93), and DB tests for problems, list/bulk, parts and migrations (all
  pass);
- tsc, eslint, prettier, labels (65) and console incidents (500) tests;
- OpenAPI diff against the branch's previous head: no breaks.

**Not done (recorded):**
- attachment copy (REQ-PRB-011 AC3);
- the analysis and solution parts of a copy (WP-044b fields);
- REQ-PRB-013's other sources (changes, releases, CIs, reviews) wait for those records;
- the console screens come in S5.
