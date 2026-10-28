import { Tooltip } from 'antd';
import type { ReactNode } from 'react';

import type {
  IncidentCatalogue,
  IncidentListField,
  IncidentListItem,
  IncidentPerson,
  ListColumn,
  ReportField,
} from '@supportx/api-client';
import type { useDateTime } from '@supportx/ui';

import type { ReportWords } from '../../reports/names';
import { closureCodeLabel, personName } from '../labels';
import { PriorityTag, SlaTag, StatusTag } from '../tags';

// The columns the incident list can show (REQ-INC-104): its own columns, more built-in fields and
// the tenant's custom fields (`custom.<key>`), each named, sortable when the API sorts by it, in
// the order and width the user chose. Values are always rendered as words, never codes (rule d).

export interface ColumnContext {
  t: (key: string, params?: Record<string, string | number>) => string;
  words: ReportWords;
  dates: ReturnType<typeof useDateTime>;
  catalogue: IncidentCatalogue | undefined;
  people: Record<string, IncidentPerson>;
  groupNames: Map<string, string>;
  locale: string;
  /** The language's list format ("a, b and c"; useListFormat). */
  list: (items: readonly string[]) => string;
}

export interface ColumnSpec {
  key: string;
  /** The API field it sorts by, when the list sorts by it across pages (AC2). */
  sortField?: string;
  width: number;
  title: (context: ColumnContext) => string;
  render: (row: IncidentListItem, context: ColumnContext) => ReactNode;
}

/** The list's columns until the user chooses (D1: as before WP-020d). */
export const DEFAULT_COLUMNS: readonly string[] = [
  'display_id',
  'subject',
  'requester_id',
  'status',
  'priority',
  'group_id',
  'technician_id',
  'resolution_due_at',
  'updated_at',
];

const field = (name: string) => (c: ColumnContext) => c.words.field(name);

const OWN: ColumnSpec[] = [
  {
    key: 'display_id',
    sortField: 'display_number',
    width: 110,
    title: (c) => c.t('incidents.col.id'),
    render: (row) => row.display_id,
  },
  {
    key: 'subject',
    sortField: 'subject',
    width: 360,
    title: field('subject'),
    // The whole subject is the tooltip, and it reads in its own direction (QA BUG-12, BUG-16).
    render: (row) => (
      <bdi dir="auto" title={row.subject}>
        {row.subject}
      </bdi>
    ),
  },
  {
    key: 'requester_id',
    width: 180,
    title: field('requester_id'),
    render: (row, c) => personName(c.people, row.requester_id),
  },
  {
    key: 'status',
    width: 150,
    title: field('status'),
    render: (row, c) => <StatusTag status={row.status} catalogue={c.catalogue} />,
  },
  {
    key: 'priority',
    sortField: 'priority',
    width: 120,
    title: field('priority'),
    render: (row) => <PriorityTag priority={row.priority} source={row.priority_source} />,
  },
  {
    key: 'group_id',
    width: 170,
    title: field('group_id'),
    render: (row, c) => (row.group_id === null ? '' : (c.groupNames.get(row.group_id) ?? '')),
  },
  {
    key: 'technician_id',
    width: 170,
    title: field('technician_id'),
    render: (row, c) => personName(c.people, row.technician_id),
  },
  {
    key: 'resolution_due_at',
    sortField: 'resolution_due_at',
    width: 170,
    title: (c) => c.t('incidents.col.due'),
    render: (row, c) => (
      <SlaTag policyId={row.sla_policy_id} dueAt={row.resolution_due_at} format={c.dates.format} />
    ),
  },
  {
    key: 'updated_at',
    sortField: 'updated_at',
    width: 150,
    title: (c) => c.t('incidents.col.updated'),
    render: (row, c) => (
      <Tooltip title={c.dates.format(row.updated_at)}>
        <span>{c.dates.relative(row.updated_at)}</span>
      </Tooltip>
    ),
  },
];

// Built-in fields the rows carry, beyond the list's own columns.
const MORE = [
  'created_at',
  'status_changed_at',
  'first_responded_at',
  'resolved_at',
  'closed_at',
  'status_category',
  'channel',
  'impact',
  'urgency',
  'level',
  'closure_code',
  'site_id',
  'department_id',
  'category_id',
  'reopen_count',
] as const;

function rowValue(row: IncidentListItem, name: string): unknown {
  if (name.startsWith('custom.')) return row.custom?.[name.slice('custom.'.length)];
  return (row as unknown as Record<string, unknown>)[name];
}

/** A list field in the shape the report naming helpers take (they name its values). */
export function asReportField(field: IncidentListField): ReportField {
  return {
    name: field.name,
    type: field.type,
    values: field.values,
    multiple: field.multiple,
    dimension: field.dimension === null ? null : { ...field.dimension, bucket: null },
  };
}

/** A field's value as words: dates formatted, codes and records named, lists joined. */
function fieldCell(spec: IncidentListField, value: unknown, c: ColumnContext): ReactNode {
  if (value === null || value === undefined || value === '') return '';
  if (spec.type === 'datetime' && typeof value === 'string') return c.dates.format(value);
  if (spec.name === 'closure_code' && typeof value === 'string') {
    return closureCodeLabel(c.t, c.catalogue, value, c.locale);
  }
  if (typeof value === 'boolean') return c.t(value ? 'filter.yes' : 'filter.no');
  const one = (item: unknown) =>
    spec.dimension === null
      ? typeof item === 'string' || typeof item === 'number'
        ? String(item)
        : ''
      : c.words.key({ ...spec.dimension, bucket: null }, item);
  return Array.isArray(value) ? c.list(value.map(one)) : one(value);
}

/** Every column the list can show, by key: its own, then more fields, then custom fields. */
export function columnCatalogue(fields: IncidentListField[]): Map<string, ColumnSpec> {
  const byName = new Map(fields.map((f) => [f.name, f]));
  const specs: ColumnSpec[] = [...OWN];
  const extra = [
    ...MORE.filter((name) => byName.has(name)),
    ...fields.filter((f) => f.name.startsWith('custom.')).map((f) => f.name),
  ];
  for (const name of extra) {
    const spec = byName.get(name);
    if (spec === undefined) continue;
    specs.push({
      key: name,
      sortField: spec.sortable ? name : undefined,
      width: spec.type === 'datetime' ? 170 : 160,
      title: field(name),
      render: (row, c) => fieldCell(spec, rowValue(row, name), c),
    });
  }
  return new Map(specs.map((s) => [s.key, s]));
}

/** The chosen columns that still exist (a removed custom field drops out), else the defaults. */
export function chosenColumns(
  saved: readonly ListColumn[],
  catalogue: Map<string, ColumnSpec>,
): ListColumn[] {
  const kept = saved.filter((c) => catalogue.has(c.key));
  return kept.length > 0
    ? kept
    : DEFAULT_COLUMNS.filter((key) => catalogue.has(key)).map((key) => ({ key, width: null }));
}

/** `-field` or `field` → the column it sorts and its order (null: not a column's sort). */
export function sortOf(sort: string): { field: string; descending: boolean } {
  return { field: sort.replace(/^-/, ''), descending: sort.startsWith('-') };
}
