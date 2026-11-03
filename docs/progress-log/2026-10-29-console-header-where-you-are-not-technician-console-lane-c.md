### 2026-10-29 — Console header: where you are, not "Technician Console" (lane C)

- Product owner: the fixed "Technician Console" meant nothing to admins and managers. The header
  now shows breadcrumbs of the page ("Incidents › INC-42", the record's desk first when ESM is
  on); with the top menu they appear above the page for records and sub-pages. The browser tab
  follows ("INC-42 · Incidents · SupportX", the tenant's product name when branded).
- Phone width: only the page itself, cut short with a tooltip; RTL in Arabic and Urdu.
- "Technician Console" left every visible place (About shows the product); `app.console.name`
  stays the console's internal label key.
- Tests: 5 Vitest (crumbs, desk with and without ESM, tab title, top layout) and one e2e (Arabic,
  390 px, no sideways scroll, axe).
