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
import { ChannelIcon, type useDateTime } from '@supportx/ui';

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

/** The list's columns until the user chooses (D-124; saved choices and views keep theirs). */
export const DEFAULT_COLUMNS: readonly string[] = [
  'display_id',
  'subject',
  'requester_id',
  'technician_id',
  'status',
  'priority',
  'resolution_due_at',
];
// The default widths fit their content (D-147 template C): IDs and tags never wrap or cut, the
// people columns may cut before the subject does, and the subject takes the remaining width. At
// 1280 px with the side navigation that leaves no room for Group as well, so it left the defaults
// (QA9-V-01, the coordinator's P2 review); it stays in the column chooser, and saved views keep it.
// "Created" left the defaults so they fit 1440 px with the side navigation (QA 2026-11-05 V1);
// it stays in the column chooser, and saved choices and views keep it.

const field = (name: string) => (c: ColumnContext) => c.words.field(name);

const OWN: ColumnSpec[] = [
  {
    key: 'display_id',
    sortField: 'display_number',
    width: 110,
    title: (c) => c.t('incidents.col.id'),
    // The channel it came from in front of the ID (UI pass 2), named by its label.
    render: (row) => (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, whiteSpace: 'nowrap' }}>
        <ChannelIcon channel={row.channel} />
        <strong>{row.display_id}</strong>
      </span>
    ),
  },
  {
    key: 'subject',
    sortField: 'subject',
    // The least it gets; it takes the room left over, with an ellipsis and the whole subject as
    // the tooltip (D-124; QA 2026-11-05 V1: the defaults fit 1440 px in the side layout).
    width: 240,
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
    width: 100,
    title: field('requester_id'),
    render: (row, c) => personName(c.people, row.requester_id),
  },
  {
    key: 'status',
    width: 130,
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
    width: 120,
    title: field('group_id'),
    render: (row, c) => (row.group_id === null ? '' : (c.groupNames.get(row.group_id) ?? '')),
  },
  {
    key: 'technician_id',
    width: 100,
    title: field('technician_id'),
    render: (row, c) => personName(c.people, row.technician_id),
  },
  {
    key: 'resolution_due_at',
    sortField: 'resolution_due_at',
    width: 150,
    title: (c) => c.t('incidents.col.due'),
    render: (row, c) => (
      <SlaTag
        policyId={row.sla_policy_id}
        dueAt={row.resolution_due_at}
        state={row.resolution_sla_state}
        resolvedAt={row.resolved_at}
        format={c.dates.format}
      />
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
/**
 * Group joins the defaults where it fits beside a usable subject: windows of at least this width
 * (1440 px and up with the side navigation; the coordinator's P2 review). Below, it waits in the
 * column chooser.
 */
export const GROUP_DEFAULT_MIN_WIDTH = 1400;

export function chosenColumns(
  saved: readonly ListColumn[],
  catalogue: Map<string, ColumnSpec>,
  wide = false,
): ListColumn[] {
  const kept = saved.filter((c) => catalogue.has(c.key));
  if (kept.length > 0) return kept; // the person's own choice is never changed by the width
  const keys = wide ? withGroup(DEFAULT_COLUMNS) : DEFAULT_COLUMNS;
  return keys.filter((key) => catalogue.has(key)).map((key) => ({ key, width: null }));
}

/** The defaults with Group before Status, where it sat before. */
function withGroup(keys: readonly string[]): string[] {
  const at = keys.indexOf('status');
  return [...keys.slice(0, at), 'group_id', ...keys.slice(at)];
}

/** `-field` or `field` → the column it sorts and its order (null: not a column's sort). */
export function sortOf(sort: string): { field: string; descending: boolean } {
  return { field: sort.replace(/^-/, ''), descending: sort.startsWith('-') };
}
