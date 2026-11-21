import type { SyncRuleInput } from '@supportx/api-client';

/** Where the sync rule pages are (WP-053 S4a). */
export const SYNC_RULES_PATH = '/admin/cmdb/sync-rules';
export const syncRuleHref = (id: string) => `${SYNC_RULES_PATH}/${id}`;

/** The filter the editor builds: assets of these product types, sites and states (all empty: every asset). */
export interface SimpleFilter {
  productTypeIds: string[];
  siteIds: string[];
  stateIds: string[];
}

const FIELDS: [keyof SimpleFilter, string][] = [
  ['productTypeIds', 'product_type_id'],
  ['siteIds', 'site_id'],
  ['stateIds', 'state_id'],
];

interface Condition {
  field: string;
  op: string;
  value?: unknown;
}
type Tree = Condition | { and: Tree[] } | { or: Tree[] };

/** The editor's choices as the asset list's DSL (`in` per field, joined with `and`). */
export function filterOf(simple: SimpleFilter): SyncRuleInput['filter'] {
  const conditions = FIELDS.filter(([key]) => simple[key].length > 0).map(([key, field]) => ({
    field,
    op: 'in' as const,
    value: simple[key],
  }));
  if (conditions.length === 0) return null;
  if (conditions.length === 1) return conditions[0] ?? null;
  return { and: conditions };
}

/**
 * A stored filter back as the editor's choices, or null when it has another shape (made through
 * the API): the editor then shows it as it is and keeps it unless the person replaces it.
 */
export function simpleOf(tree: unknown): SimpleFilter | null {
  const empty: SimpleFilter = { productTypeIds: [], siteIds: [], stateIds: [] };
  if (tree === null || tree === undefined) return empty;
  const node = tree as Tree;
  const parts: Tree[] = 'and' in node ? node.and : [node];
  const out = { ...empty };
  for (const part of parts) {
    if (!('field' in part) || (part.op !== 'in' && part.op !== 'eq')) return null;
    const match = FIELDS.find(([, field]) => field === part.field);
    if (match === undefined) return null;
    const values = Array.isArray(part.value) ? part.value : [part.value];
    if (!values.every((v): v is string => typeof v === 'string')) return null;
    out[match[0]] = values;
  }
  return out;
}
