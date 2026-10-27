import {
  ApiError,
  useCustomFields,
  type RuleFieldOut,
  type TriggerActionIO,
} from '@supportx/api-client';
import { useAppearance, useLabel } from '@supportx/ui';

import { fieldName } from '../../customFields/values';

/** Operators per field kind, as the server allows them (automation/domain/rules.py). */
const COMPARE = ['eq', 'ne', 'in', 'not_in', 'is_null', 'is_not_null'] as const;
const CHANGE = ['changed', 'changed_from', 'changed_to'] as const;
const ORDERED = ['gt', 'gte', 'lt', 'lte'] as const;
export const OPERATORS: Record<RuleFieldOut['kind'], readonly string[]> = {
  text: [...COMPARE, ...CHANGE, 'contains', 'starts_with'],
  code: [...COMPARE, ...CHANGE],
  reference: [...COMPARE, ...CHANGE],
  number: [...COMPARE, ...CHANGE, ...ORDERED],
  boolean: ['eq', 'ne', 'changed', 'changed_to'],
  datetime: [...COMPARE, ...ORDERED, 'changed'],
  codes: [...COMPARE, ...CHANGE, 'contains'],
};
export const NO_VALUE = new Set(['is_null', 'is_not_null', 'changed']);
export const LIST = new Set(['in', 'not_in']);

export interface Condition {
  field: string;
  op: string;
  value?: unknown;
}

/** A flat condition list joined by AND or OR (what the editor builds). */
export interface Conditions {
  join: 'and' | 'or';
  rows: Condition[];
}

/** The server's tree from a flat list (none: matches every record). */
export function toTree(conditions: Conditions): Record<string, unknown> | null {
  const rows = conditions.rows.filter((row) => row.field !== '' && row.op !== '');
  if (rows.length === 0) return null;
  const clean = rows.map((row) =>
    NO_VALUE.has(row.op) ? { field: row.field, op: row.op } : { ...row },
  );
  return clean.length === 1 ? (clean[0] as Record<string, unknown>) : { [conditions.join]: clean };
}

/** A tree back into the flat list (one group deep; anything deeper keeps its first level). */
export function fromTree(tree: Record<string, unknown> | null | undefined): Conditions {
  if (tree == null) return { join: 'and', rows: [] };
  for (const join of ['and', 'or'] as const) {
    const items = tree[join];
    if (Array.isArray(items)) {
      return {
        join,
        rows: items.filter(
          (item): item is Condition => typeof item === 'object' && 'field' in item,
        ),
      };
    }
  }
  return { join: 'and', rows: [tree as unknown as Condition] };
}

/** How a rule field is named on screen. */
export function useFieldName(): (name: string) => string {
  const t = useLabel();
  const { locale } = useAppearance();
  const custom = useCustomFields('incident');
  return (name: string) => {
    if (name.startsWith('custom.')) {
      const found = custom.data?.find((f) => `custom.${f.key}` === name);
      return found === undefined ? t('custom_fields.unknown_field') : fieldName(found, locale);
    }
    if (name.startsWith('requester.')) return t(`automation.field.${name}`);
    return t(`work_item.field.${name}`);
  };
}

/** A problem of a save, in words, for the editor's list (its path names the part). */
export function problemsOf(t: ReturnType<typeof useLabel>, error: unknown): string[] {
  if (!(error instanceof ApiError) || error.status !== 422) return [];
  if (error.fieldErrors.length === 0) return [t(`errors.${error.code}`, error.params)];
  return error.fieldErrors.map((f) => t(f.message_key, f.params ?? {}));
}

/** Triggers learn only which fields changed, not from what: "changed from" is the status's. */
export function triggerOp(field: string, op: string): boolean {
  return op !== 'changed_from' || field === 'status';
}

/** "Offered when" looks at the record as it is: no change operators. */
export function stateOp(_field: string, op: string): boolean {
  return !op.startsWith('changed');
}

/** A new "set a field" action, nothing chosen yet. */
export function emptyAction(): TriggerActionIO {
  return { kind: 'set', field: null, value: null, mode: 'fill_empty' };
}
