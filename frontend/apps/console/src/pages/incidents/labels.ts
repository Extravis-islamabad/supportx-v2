import type {
  IncidentCatalogue,
  IncidentCategory,
  IncidentPerson,
  IncidentScale,
  IncidentTemplate,
  ListValue,
} from '@supportx/api-client';

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

/** An impact, urgency or priority value with the admin's labels (WP-020c), else the shipped one. */
export function scaleLabel(
  t: Translate,
  catalogue: IncidentCatalogue | undefined,
  scale: IncidentScale,
  code: string,
  locale: string,
): string {
  const value = catalogue?.scales.find((v) => v.scale === scale && v.code === code);
  return labelled(value?.labels, locale, () => t(`${scale}.${code}`));
}

/** Levels and closure codes: admin values carry their own labels, seeded ones a shipped label. */
export type ValueList = 'level' | 'closure_code';

export function listValueLabel(
  t: Translate,
  list: ValueList,
  value: Pick<ListValue, 'code' | 'labels'>,
  locale: string,
): string {
  return labelled(value.labels, locale, () => t(`${list}.${value.code}`));
}

/** A level code as people read it; a code the catalogue no longer has reads "Unknown value". */
export function levelLabel(
  t: Translate,
  catalogue: IncidentCatalogue | undefined,
  code: string | null,
  locale: string,
): string {
  if (code === null) return '';
  const value = catalogue?.levels.find((v) => v.code === code);
  return value === undefined
    ? t('incidents.unknown_value')
    : listValueLabel(t, 'level', value, locale);
}

/**
 * A reason code as people read it: the admin's labels, else the shipped label of its list.
 * A code no list has any more reads "Unknown value", never the code itself (rule d).
 */
export function reasonValueLabel(
  t: Translate,
  catalogue: IncidentCatalogue | undefined,
  code: string,
  locale: string,
  list?: string | null,
): string {
  const reasons = catalogue?.reasons ?? [];
  const reason =
    reasons.find((r) => r.code === code && (list == null || r.list === list)) ??
    reasons.find((r) => r.code === code);
  if (reason === undefined) return t('incidents.unknown_value');
  return labelled(reason.labels, locale, () => t(`reason.${reason.list}.${reason.code}`));
}

/** A template's name: its own translations, or the shipped name of a seeded template. */
export function templateLabel(
  t: Translate,
  template: Pick<IncidentTemplate, 'code' | 'labels'>,
  locale: string,
): string {
  return labelled(template.labels, locale, () => t(`incident_template.${template.code ?? ''}`));
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
