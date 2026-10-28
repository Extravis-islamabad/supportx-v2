import {
  DASHBOARD_ME,
  type BuiltinReport,
  type DashboardFilters,
  type DashboardRecords,
  type DashboardWidget,
  type IncidentsQuery,
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
  if (widget.records) return null; // a list of records: recordsQuery()
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
  // A created-vs-resolved report has its own range (D-114); "created in the last N days" would
  // empty its backlog, so the bar's range does not apply to it.
  if (filters.days && !skip.has('days') && !own.flow) {
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

// The list's sort for each records-widget order (D-114).
const RECORD_SORTS: Record<NonNullable<DashboardRecords['sort']>, string> = {
  updated: '-updated_at',
  created: '-created_at',
  due: 'resolution_due_at',
  priority: 'priority',
};

/**
 * The list query of a records widget for one viewer: its filter with "me" as the viewer and the
 * dashboard's filters added, its order and its size. The list applies the viewer's scope.
 */
export function recordsQuery(
  records: DashboardRecords,
  { userId, filters }: { userId: string; filters: DashboardFilters },
): IncidentsQuery {
  const parts: unknown[] = [];
  if (records.filter) parts.push(withViewer(records.filter, userId));
  if (filters.site_id) parts.push({ field: 'site_id', op: 'eq', value: filters.site_id });
  if (filters.group_id) parts.push({ field: 'group_id', op: 'eq', value: filters.group_id });
  if (filters.days) parts.push({ field: 'created_at', op: 'last_n_days', value: filters.days });
  const filter = parts.length === 0 ? undefined : parts.length === 1 ? parts[0] : { and: parts };
  return {
    filter: filter as IncidentsQuery['filter'],
    sort: RECORD_SORTS[records.sort],
    limit: records.limit,
  };
}
