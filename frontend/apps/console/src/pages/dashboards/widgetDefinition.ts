import {
  DASHBOARD_ME,
  type BuiltinReport,
  type DashboardFilters,
  type DashboardWidget,
  type ReportDefinition,
  type ReportField,
} from '@supportx/api-client';

/** The dashboard filter bar's fields (REQ-DSH-022): which report field each one filters. */
export const FILTER_FIELDS = {
  site_id: 'site_id',
  group_id: 'group_id',
  days: 'created_at',
} as const;
export type DashboardFilterKey = keyof typeof FILTER_FIELDS;

/** `value` with the viewer's id wherever a widget says "me" (`@me`). */
export function withViewer(value: unknown, userId: string): unknown {
  if (value === DASHBOARD_ME) return userId;
  if (Array.isArray(value)) return value.map((v) => withViewer(v, userId));
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, withViewer(v, userId)]),
    );
  }
  return value;
}

/**
 * Which filters of the bar a widget cannot use: its entity has no such field (REQ-DSH-022 AC2,
 * "not filtered by site"). `fields` are the entity's fields as the viewer may use them.
 */
export function unusableFilters(
  filters: DashboardFilters,
  fields: ReportField[] | undefined,
): DashboardFilterKey[] {
  if (fields === undefined) return [];
  const names = new Set(fields.map((f) => f.name));
  return (Object.keys(FILTER_FIELDS) as DashboardFilterKey[]).filter(
    (key) => filters[key] != null && !names.has(FILTER_FIELDS[key]),
  );
}

const NOW_MEASURES = new Set(['open_count', 'unassigned_open_count']);
const OPEN_CATEGORIES = new Set(['open', 'paused']);

/** The filter requires open records: a condition on status_category, alone or inside an AND. */
function requiresOpen(filter: unknown): boolean {
  if (filter === null || typeof filter !== 'object') return false;
  const node = filter as { and?: unknown[]; field?: string; op?: string; value?: unknown };
  if (Array.isArray(node.and)) return node.and.some(requiresOpen);
  return (
    node.field === 'status_category' &&
    node.op === 'in' &&
    Array.isArray(node.value) &&
    node.value.length > 0 &&
    node.value.every((value) => OPEN_CATEGORIES.has(String(value)))
  );
}

/**
 * An "open now" widget: what is open at this moment, however old (product owner on QA WP-036 Q1,
 * D-119). The time filter never narrows it, or "Open incidents" would shrink to those created
 * lately. Reports split over time (a date bucket) are trends; "by age" is still a picture of now.
 */
export function isOpenNow(definition: ReportDefinition | null | undefined): boolean {
  if (!definition) return false;
  const buckets = (definition.group_by ?? []) as { bucket?: string | null }[];
  if (buckets.some((group) => group.bucket != null && group.bucket !== 'age')) return false;
  if (requiresOpen(definition.filter)) return true;
  const measures = definition.measures ?? [];
  return measures.length > 0 && measures.every((m) => NOW_MEASURES.has(m));
}

/**
 * The report definition a widget runs for one viewer: its own definition (or the report it
 * refers to), "me" as the viewer, and the dashboard's filters added (AND) where the entity has
 * the field. Null when a referred report is not available (yet).
 */
export function widgetDefinition(
  widget: DashboardWidget,
  {
    userId,
    filters,
    builtin,
    saved,
    fields,
  }: {
    userId: string;
    filters: DashboardFilters;
    builtin: BuiltinReport[] | undefined;
    saved?: ReportDefinition;
    fields?: ReportField[];
  },
): ReportDefinition | null {
  let base: ReportDefinition | null | undefined = widget.report;
  if (!base && widget.report_ref?.startsWith('builtin:')) {
    const code = widget.report_ref.slice('builtin:'.length);
    base = builtin?.find((r) => r.code === code)?.definition;
  } else {
    base ??= saved;
  }
  if (!base) return null;
  const own = withViewer(base, userId) as ReportDefinition;
  const skip = new Set(unusableFilters(filters, fields));
  const extra: unknown[] = [];
  if (filters.site_id && !skip.has('site_id')) {
    extra.push({ field: 'site_id', op: 'eq', value: filters.site_id });
  }
  if (filters.group_id && !skip.has('group_id')) {
    extra.push({ field: 'group_id', op: 'eq', value: filters.group_id });
  }
  if (filters.days && !skip.has('days') && !isOpenNow(own)) {
    extra.push({ field: 'created_at', op: 'last_n_days', value: filters.days });
  }
  if (extra.length === 0) return own;
  const filter = own.filter
    ? { and: [own.filter, ...extra] }
    : extra.length === 1
      ? extra[0]
      : { and: extra };
  return { ...own, filter: filter as ReportDefinition['filter'] };
}

/**
 * The time filter moves from "used" to "not used" on an open-now widget, so its note says so.
 */
export function nowFilters(
  now: boolean,
  filters: DashboardFilters,
  applied: DashboardFilterKey[],
  unusable: DashboardFilterKey[],
): { filtered: DashboardFilterKey[]; unfiltered: DashboardFilterKey[] } {
  if (!now || filters.days == null) return { filtered: applied, unfiltered: unusable };
  return {
    filtered: applied.filter((key) => key !== 'days'),
    unfiltered: unusable.includes('days') ? unusable : [...unusable, 'days'],
  };
}

/**
 * The filters of the bar a widget does use (never silent: the widget names them beside those it
 * cannot use, coordinator and QA WP-036 Q1).
 */
export function appliedFilters(
  filters: DashboardFilters,
  fields: ReportField[] | undefined,
): DashboardFilterKey[] {
  const unusable = new Set(unusableFilters(filters, fields));
  return (Object.keys(FILTER_FIELDS) as DashboardFilterKey[]).filter(
    (key) => filters[key] != null && !unusable.has(key),
  );
}
