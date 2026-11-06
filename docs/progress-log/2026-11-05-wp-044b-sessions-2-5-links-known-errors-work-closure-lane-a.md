### 2026-11-05 — WP-044b sessions 2-5: links, known errors, work on the problem, closure (lane A)

**Scope:** D9-D12 of ~/Desktop/wp-044-plan.md, on draft #222. Migrations: 0104 (allotted), and
0078 extended (still unmerged).

**Built:**
- **S2, links and merge:**
  - 0104 widens the link kinds (`merged_into`), the transition actions (`merge`,
    `undo_merge`) and the bulk actions (`unlink_problem`), each from its live check.
  - Merge with undo; unlinking incidents, one at a time or in bulk; related problems.
  - The generic link delete refuses causes and merges (a gap from WP-044a, on record in
    D-140).
- **S3, known errors:**
  - the workaround (`problems.edit_solution`);
  - the flag (`problems.mark_known_error`, needing something written first);
  - retirement on resolve; the marker live on incidents;
  - the database and its page; suggestions in the incident's editors;
  - problems in the record-facts port (knowledge links, save as knowledge).
- **S4, work on the problem:**
  - the review as a closing rule (P1 and major, with a setting);
  - approvals on the WP-030 engine, including accept-without-fix with a review date 90 days
    ahead;
  - messages: recipient sets, and requesters reached through their incidents.
- **S5, closure and follow-up:** pending approvals block closing, and the follow-up resolves
  the chosen linked incidents through their own bulk job.
- **Console:** the analysis, evidence and review tabs; links, related problems, merge and undo;
  the known error action, marker, database and tool; approvals; messages; follow-up.

**Also today:**
- #229: the seeding tools register every module's tables (QA major).
- #230: D-143 (preview approved) and D-144 (WP-045 answers, approval ties).
- Reviews: #219 S6 (6 points, all fixed) and ADR-043 §5-7 (3 notes, all taken).
- #211 kept current with main, including the 0076 re-points.

**Tests:**
- DB: test_problem_analysis_api, test_known_errors_api, test_merged_into_migration and
  test_problems_api, plus the service request approval suites, which still pass.
- Vitest: the problem page (11) and the known-error tool.
- e2e in problems.spec.ts. Local runs covered only this area, at the coordinator's request
  (load on the Mac); CI runs the full suites.

**Not yet:** see PROGRESS (workaround articles in lane C's WP-060, portal known issues in WP-034,
the change and release conditions, problem tabs in 044c).
