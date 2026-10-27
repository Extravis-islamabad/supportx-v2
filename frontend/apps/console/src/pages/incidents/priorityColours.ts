import type { Priority } from '@supportx/api-client';

// The fallback colour of each priority while the tenant's own colours load (WP-020c): one map for
// priority tags and report charts, so P1 is the same red everywhere (REQ-RPT-044 AC2).
export const PRIORITY_COLOURS: Record<Priority, string> = {
  p1: '#cf1322',
  p2: '#fa541c',
  p3: '#faad14',
  p4: '#8c8c8c',
};
