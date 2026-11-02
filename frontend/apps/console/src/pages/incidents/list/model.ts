import { useQueryClient } from '@tanstack/react-query';

import {
  allOf,
  queryKeys,
  type BulkAction,
  type BulkResult,
  type FilterExpression,
  type IncidentListField,
  type IncidentViewFilter,
  type SavedView,
} from '@supportx/api-client';
import {
  fromDsl,
  type FilterFieldOption,
  type FilterModel,
  type FilterValueType,
} from '@supportx/forms';
import { usePersonalChannel } from '@supportx/realtime';
import { instantOf, wallTimeIn } from '@supportx/ui';

import type { ReportWords } from '../../reports/names';
import { asReportField } from './columns';

// The incident list's pure parts (WP-020d): chips, time ranges, saved view drafts and bulk
// helpers, kept apart from the components so they test without a DOM.

export interface SearchChip {
  field: string;
  value: string;
  /** "Status is Open", as shown. */
  label: string;
}

// --- search chips (REQ-INC-109) ---

const MAX_SUGGESTIONS = 12;
// Fields people narrow by most, first among the suggestions.
const CHIP_FIELDS = [
  'status_category',
  'status',
  'priority',
  'group_id',
  'site_id',
  'category_id',
  'impact',
  'urgency',
  'channel',
  'level',
  'closure_code', // REQ-INC-093, QA BUG-05
] as const;

/** Chips as one condition each; the same field twice means either value. */
export function chipsFilter(chips: SearchChip[]): FilterExpression | undefined {
  const byField = new Map<string, string[]>();
  for (const chip of chips)
    byField.set(chip.field, [...(byField.get(chip.field) ?? []), chip.value]);
  const parts: FilterExpression[] = [...byField].map(([field, values]) =>
    values.length === 1
      ? { field, op: 'eq', value: values[0] ?? null }
      : { field, op: 'in', value: values },
  );
  if (parts.length === 0) return undefined;
  return parts.length === 1 ? parts[0] : { and: parts };
}

/** Suggestions for the text typed: values whose words match, or every value of a named field. */
export function chipSuggestions(
  text: string,
  fields: IncidentListField[],
  words: ReportWords,
  t: (key: string, params?: Record<string, string>) => string,
  taken: SearchChip[],
): SearchChip[] {
  const needle = text.trim().toLocaleLowerCase();
  if (needle === '') return [];
  const found: SearchChip[] = [];
  const byName = new Map(fields.map((f) => [f.name, f]));
  for (const name of CHIP_FIELDS) {
    const spec = byName.get(name);
    if (spec === undefined) continue;
    const fieldName = words.field(name);
    const named = fieldName.toLocaleLowerCase().includes(needle);
    for (const choice of words.choices(asReportField(spec)) ?? []) {
      if (!named && !choice.label.toLocaleLowerCase().includes(needle)) continue;
      if (taken.some((c) => c.field === name && c.value === choice.value)) continue;
      found.push({
        field: name,
        value: choice.value,
        label: t('incidents.chips.is', { field: fieldName, value: choice.label }),
      });
    }
  }
  return found.slice(0, MAX_SUGGESTIONS);
}

// --- time range (REQ-INC-108) ---

export const RANGE_FIELDS = [
  'created_at',
  'updated_at',
  'resolution_due_at',
  'resolved_at',
] as const;
export const PRESETS = [
  'today',
  'this_week',
  'last_7_days',
  'this_month',
  'this_quarter',
  'custom',
] as const;
export type RangeField = (typeof RANGE_FIELDS)[number];
export type Preset = (typeof PRESETS)[number];

export interface TimeRangeValue {
  field: RangeField;
  preset: Preset;
  /** A custom range: [from, to] as instants; either end may be open. */
  range?: [string | null, string | null];
}

/** The first instant of this quarter and of the next one, in `zone`. */
export function quarterOf(now: Date, zone: string): [string, string] {
  const wall = wallTimeIn(now.toISOString(), zone);
  const first = Math.floor(wall.month / 3) * 3;
  const start = { year: wall.year, month: first, day: 1, hour: 0, minute: 0 };
  const end =
    first === 9
      ? { year: wall.year + 1, month: 0, day: 1, hour: 0, minute: 0 }
      : { ...start, month: first + 3 };
  return [instantOf(start, zone), instantOf(end, zone)];
}

/** The condition the range adds to the list's filter (undefined: none yet). */
export function rangeFilter(
  value: TimeRangeValue | undefined,
  zone: string,
  now: Date = new Date(),
): FilterExpression | undefined {
  if (value === undefined) return undefined;
  const field = value.field;
  switch (value.preset) {
    case 'today':
    case 'this_week':
    case 'this_month':
      return { field, op: value.preset, value: null };
    case 'last_7_days':
      return { field, op: 'last_n_days', value: 7 };
    case 'this_quarter': {
      const [start, end] = quarterOf(now, zone);
      return {
        and: [
          { field, op: 'gte', value: start },
          { field, op: 'lt', value: end },
        ],
      };
    }
    case 'custom': {
      const [from, to] = value.range ?? [null, null];
      const parts: FilterExpression[] = [];
      if (from !== null) parts.push({ field, op: 'gte', value: from });
      if (to !== null) parts.push({ field, op: 'lte', value: to });
      if (parts.length === 0) return undefined;
      return parts.length === 1 ? parts[0] : { and: parts };
    }
  }
}

// --- saved views (REQ-INC-106) ---

const TYPES: readonly FilterValueType[] = [
  'string',
  'enum',
  'uuid',
  'datetime',
  'integer',
  'boolean',
  'decimal',
  'date',
];

/** The builder's fields: every list field people can pick a value for, named, grouped by kind. */
export function builderFields(
  fields: IncidentListField[],
  words: ReportWords,
): FilterFieldOption[] {
  return fields
    .filter((f) => f.dimension?.reference !== 'user') // people are views ("my open"), not ids
    .filter((f) => f.type !== 'uuid' || f.dimension !== null) // a bare id is never typed
    .map((f) => {
      const choices = words.choices(asReportField(f));
      const type = TYPES.find((known) => known === f.type) ?? 'string';
      return {
        name: f.name,
        // Codes kept as text (level, closure code) are picked by name like any choice: the API
        // takes `in` on text too (WP-020f QA BUG-05).
        type: type === 'string' && choices !== undefined ? 'enum' : type,
        label: words.field(f.name),
        choices,
      };
    })
    .sort(
      (a, b) =>
        Number(a.name.startsWith('custom.')) - Number(b.name.startsWith('custom.')) ||
        a.label.localeCompare(b.label),
    );
}

export interface ViewDraft {
  id?: string;
  version?: number;
  name: string;
  visibility: SavedView['visibility'];
  groupIds: string[];
  filter: FilterModel;
}

export function draftOf(view: SavedView | undefined): ViewDraft {
  return view === undefined
    ? { name: '', visibility: 'private', groupIds: [], filter: { join: 'and', rows: [] } }
    : {
        id: view.id,
        version: view.version,
        name: view.name,
        visibility: view.visibility,
        groupIds: view.group_ids,
        filter: fromDsl(view.filter) ?? { join: 'and', rows: [] },
      };
}

// --- bulk (REQ-INC-119, 120) ---

export const BULK_ACTIONS: readonly BulkAction[] = ['edit', 'assign', 'take', 'resolve', 'close'];
export const BULK_MAX = 1000;
const PROGRESS = 'work_items.bulk_progress';

export interface Selection {
  /** Picked rows, when not "all matching". */
  ids: string[];
  /** Every record of the list as shown (the view's filter, fixed when the job starts). */
  all: boolean;
}

/** A skipped record's reason in words: the field's problem, else the error's. */
export function skipReason(
  t: (key: string, params?: Record<string, string | number>) => string,
  result: BulkResult,
): string {
  const params = Object.fromEntries(
    Object.entries(result.params ?? {}).map(([k, v]) => [k, String(v)]),
  );
  if (result.field) {
    return t('incidents.bulk.field_problem', {
      field: t(`work_item.field.${result.field}`),
      problem: t(`errors.field.${result.code ?? 'invalid'}`, params),
    });
  }
  return t(`errors.${result.code ?? 'internal_error'}`, params);
}

/** Keeps every job you look at live: progress refetches when your channel says it moved. */
export function useBulkLive() {
  const queryClient = useQueryClient();
  usePersonalChannel((message) => {
    if (message.type !== PROGRESS) return;
    for (const id of message.ids) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.bulkJob(id) });
    }
    void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.bulkJobs });
  });
}

// --- export ---

/** The filter the export runs: the view's equivalent plus the list's filter; null: cannot. */
export function exportFilter(
  view: string | null,
  viewFilters: IncidentViewFilter[] | undefined,
  filter: FilterExpression | undefined,
): FilterExpression | undefined | null {
  if (view === null) return filter;
  const found = viewFilters?.find((v) => v.view === view);
  if (!found?.expressible) return null;
  return allOf((found.filter ?? undefined) as FilterExpression | undefined, filter);
}
