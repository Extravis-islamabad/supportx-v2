import type { ReportDefinition } from '@supportx/api-client';

// KPI tiles (REQ-DSH-008): the value, its change against the previous period and a sparkline.
// The period is the widget's own "last N days" window on a date field; a tile counting what is
// open now (no window) shows its value only.

interface Condition {
  field: string;
  op: string;
  value: unknown;
}
type Node = Condition | { and: Node[] } | { or: Node[] } | null | undefined;

export interface KpiPeriod {
  field: string;
  days: number;
}

const SPARK_PERIODS = 8;
const DAY_MS = 86_400_000;

function isWindow(node: Node): node is Condition {
  return (
    node !== null &&
    node !== undefined &&
    'op' in node &&
    node.op === 'last_n_days' &&
    typeof node.value === 'number'
  );
}

/** The widget's period: a top-level "last N days" condition (alone or inside an AND). */
export function kpiPeriod(definition: ReportDefinition): KpiPeriod | null {
  const filter = definition.filter as Node;
  const parts = filter && 'and' in filter ? filter.and : [filter];
  const window = parts.find(isWindow);
  return window ? { field: window.field, days: window.value as number } : null;
}

function replaceWindow(filter: Node, replacement: Condition): Node {
  if (isWindow(filter)) return replacement;
  if (filter && 'and' in filter) {
    return { and: filter.and.map((part) => (isWindow(part) ? replacement : part)) };
  }
  return filter;
}

/** The same KPI over the period before (for the trend): between 2N and N days ago. */
export function previousPeriod(
  definition: ReportDefinition,
  period: KpiPeriod,
  now: Date,
): ReportDefinition {
  const end = new Date(now.getTime() - period.days * DAY_MS);
  const start = new Date(now.getTime() - 2 * period.days * DAY_MS);
  return {
    ...definition,
    group_by: [],
    filter: replaceWindow(definition.filter, {
      field: period.field,
      op: 'between',
      value: [start.toISOString(), end.toISOString()],
    }) as ReportDefinition['filter'],
  };
}

/** The KPI over 8 periods, one bucket each (a day, a week or a month), for the sparkline. */
export function sparkline(definition: ReportDefinition, period: KpiPeriod): ReportDefinition {
  const bucket = period.days <= 1 ? 'day' : period.days <= 7 ? 'week' : 'month';
  const span = Math.min(366, { day: 8, week: 56, month: 245 }[bucket]);
  return {
    ...definition,
    group_by: [{ field: period.field, bucket }],
    order: 'key',
    chart: 'line',
    filter: replaceWindow(definition.filter, {
      field: period.field,
      op: 'last_n_days',
      value: span,
    }) as ReportDefinition['filter'],
  };
}

/** How the value moved, and whether that is good for this measure (REQ-DSH-008 AC2). */
export function trend(
  current: number | null | undefined,
  previous: number | null | undefined,
  better: string,
): { delta: number; good: boolean | null } | null {
  if (current == null || previous == null) return null;
  const delta = current - previous;
  if (delta === 0 || better === 'neutral') return { delta, good: null };
  return { delta, good: better === 'up' ? delta > 0 : delta < 0 };
}

export const KPI_SPARK_PERIODS = SPARK_PERIODS;
