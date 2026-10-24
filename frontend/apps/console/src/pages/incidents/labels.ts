import type { IncidentCatalogue, IncidentCategory, IncidentPerson } from '@supportx/api-client';

type Translate = (key: string, params?: Record<string, string | number>) => string;
type Labels = Record<string, string> | null | undefined;

/**
 * Admin values carry their own translations (REQ-WI-013 AC3): the user's language, else English,
 * else the shipped label of the code. Seeded values have no overrides and use the labels package.
 */
export function labelled(labels: Labels, locale: string, fallback: () => string): string {
  return labels?.[locale] ?? labels?.en ?? fallback();
}

export function statusLabel(
  t: Translate,
  catalogue: IncidentCatalogue | undefined,
  code: string,
  locale: string,
): string {
  const status = catalogue?.statuses.find((s) => s.code === code);
  return labelled(status?.labels, locale, () => t(`work_item_status.${code}`));
}

export function categoryLabel(t: Translate, node: IncidentCategory, locale: string): string {
  return labelled(node.labels, locale, () => t(`work_item_category.${node.code ?? ''}`));
}

/** "Category › Subcategory › Item" for a node, from the flat tree. */
export function categoryPath(
  t: Translate,
  nodes: readonly IncidentCategory[],
  id: string | null,
  locale: string,
): string {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const parts: string[] = [];
  let current = id === null ? undefined : byId.get(id);
  while (current !== undefined) {
    parts.unshift(categoryLabel(t, current, locale));
    current = current.parent_id === null ? undefined : byId.get(current.parent_id);
  }
  return parts.join(' › ');
}

export function personName(people: Record<string, IncidentPerson>, id: string | null): string {
  if (id === null) return '';
  return people[id]?.display_name ?? '';
}

/** Names that appear more than once in a list: those rows also show the email (Area 15). */
export function duplicateNames(names: readonly string[]): Set<string> {
  const seen = new Set<string>();
  const twice = new Set<string>();
  for (const name of names) {
    const key = name.trim().toLocaleLowerCase();
    if (seen.has(key)) twice.add(key);
    seen.add(key);
  }
  return twice;
}
