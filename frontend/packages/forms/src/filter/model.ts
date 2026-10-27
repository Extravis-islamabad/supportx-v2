// The shared filter builder's model (REQ-RPT-029, D-100 D6): one group of conditions joined by
// "all" or "any", turned into the shared filter DSL (architecture.md §6.5) and back. Pure, so lists,
// reports, rules and SLAs share it and the tests need no DOM. Nothing here is specific to a record
// type: the caller passes the field allowlist the API publishes.

export type FilterValueType =
  'string' | 'enum' | 'uuid' | 'datetime' | 'integer' | 'boolean' | 'decimal' | 'date';

export type FilterOp =
  | 'eq'
  | 'ne'
  | 'in'
  | 'not_in'
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte'
  | 'between'
  | 'contains'
  | 'starts_with'
  | 'is_null'
  | 'is_not_null'
  | 'today'
  | 'yesterday'
  | 'this_week'
  | 'last_week'
  | 'this_month'
  | 'last_month'
  | 'last_n_days'
  | 'next_n_days'
  | 'before_now'
  | 'after_now';

/** One choice of an enum or reference field: the code sent, and the words shown. */
export interface FilterChoice {
  value: string;
  label: string;
}

/** A field the caller allows (the API's allowlist), with its label and choices. */
export interface FilterFieldOption {
  name: string;
  type: FilterValueType;
  label: string;
  /** Choices for enum and reference (uuid) fields; without them a uuid field is free text. */
  choices?: FilterChoice[];
}

export type FilterValue =
  string | number | boolean | null | string[] | [string | null, string | null];

export interface FilterRow {
  field: string;
  op: FilterOp;
  value: FilterValue;
}

export interface FilterModel {
  join: 'and' | 'or';
  rows: FilterRow[];
}

// Operators per type, mirroring the API (app/shared/api/filters.py OPERATORS); list order is the
// order the UI offers them in.
const PRESENCE: FilterOp[] = ['is_null', 'is_not_null'];
const RELATIVE: FilterOp[] = [
  'today',
  'yesterday',
  'this_week',
  'last_week',
  'this_month',
  'last_month',
  'last_n_days',
  'next_n_days',
  'before_now',
  'after_now',
];
export const OPERATORS: Record<FilterValueType, FilterOp[]> = {
  string: ['contains', 'eq', 'ne', 'starts_with', ...PRESENCE],
  enum: ['in', 'not_in', ...PRESENCE],
  uuid: ['in', 'not_in', ...PRESENCE],
  datetime: [...RELATIVE, 'between', 'gte', 'lt', ...PRESENCE],
  integer: ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'between', ...PRESENCE],
  decimal: ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'between', ...PRESENCE],
  date: ['eq', 'gt', 'lt', 'between', ...PRESENCE],
  boolean: ['eq', ...PRESENCE],
};

const NO_VALUE: ReadonlySet<FilterOp> = new Set([
  ...PRESENCE,
  ...RELATIVE.filter((op) => op !== 'last_n_days' && op !== 'next_n_days'),
]);

/** Whether `op` needs a value at all (`is empty`, `today` … do not). */
export function needsValue(op: FilterOp): boolean {
  return !NO_VALUE.has(op);
}

/** A fresh row for `field`, with its type's first operator. */
export function newRow(field: FilterFieldOption): FilterRow {
  const op = OPERATORS[field.type][0] ?? 'eq';
  return { field: field.name, op, value: emptyValue(op) };
}

/** The empty value an operator starts with. */
export function emptyValue(op: FilterOp): FilterValue {
  if (op === 'in' || op === 'not_in') return [];
  if (op === 'between') return [null, null];
  if (op === 'last_n_days' || op === 'next_n_days') return 30;
  return null;
}

/** Problems per row index: `value_required` when a row has a field but no value (REQ-RPT-029 AC2). */
export function rowProblems(model: FilterModel): Map<number, 'value_required'> {
  const problems = new Map<number, 'value_required'>();
  model.rows.forEach((row, index) => {
    if (!needsValue(row.op)) return;
    const value = row.value;
    const empty =
      value === null ||
      value === '' ||
      (Array.isArray(value) &&
        (row.op === 'between' ? value.some((v) => v === null || v === '') : value.length === 0));
    if (empty) problems.set(index, 'value_required');
  });
  return problems;
}

type Dsl = Record<string, unknown>;

/** The DSL JSON for the model (undefined when it has no rows). */
export function toDsl(model: FilterModel): Dsl | undefined {
  const conditions = model.rows.map((row) =>
    needsValue(row.op)
      ? { field: row.field, op: row.op, value: row.value }
      : { field: row.field, op: row.op },
  );
  if (conditions.length === 0) return undefined;
  if (conditions.length === 1) return conditions[0];
  return { [model.join]: conditions };
}

function isCondition(node: unknown): node is { field: string; op: FilterOp; value?: FilterValue } {
  return typeof node === 'object' && node !== null && 'field' in node && 'op' in node;
}

/**
 * The model for a DSL tree, or null when the tree is deeper than one group (the builder then
 * shows it read-only rather than flattening it and changing its meaning).
 */
export function fromDsl(tree: unknown): FilterModel | null {
  if (tree === undefined || tree === null) return { join: 'and', rows: [] };
  const toRow = (node: unknown): FilterRow | null =>
    isCondition(node)
      ? { field: node.field, op: node.op, value: node.value ?? emptyValue(node.op) }
      : null;
  const single = toRow(tree);
  if (single !== null) return { join: 'and', rows: [single] };
  if (typeof tree !== 'object') return null;
  const group = tree as { and?: unknown[]; or?: unknown[] };
  const join = group.and !== undefined ? 'and' : group.or !== undefined ? 'or' : null;
  const nodes = group.and ?? group.or;
  if (join === null || !Array.isArray(nodes)) return null;
  const rows = nodes.map(toRow);
  return rows.every((row): row is FilterRow => row !== null) ? { join, rows } : null;
}
