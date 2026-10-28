import type { Dashboard } from '@supportx/api-client';

/** A dashboard's name in the viewer's language (REQ-DSH-045 AC3: falls back to its name). */
export function dashboardName(
  dashboard: Dashboard,
  t: (key: string) => string,
  locale: string,
): string {
  if (dashboard.builtin) return t(`dashboard.${dashboard.builtin}`);
  return dashboard.names[locale] ?? dashboard.name ?? '';
}
