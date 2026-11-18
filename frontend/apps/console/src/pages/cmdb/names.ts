import type { CiState, CiType } from '@supportx/api-client';

type Translate = (key: string, params?: Record<string, string | number>) => string;

/** A built-in type or state by its label; a tenant's own by its name in this language. */
export function nameOf(
  t: Translate,
  locale: string,
  item: Pick<CiType | CiState, 'api_name' | 'built_in' | 'names'>,
  prefix: 'cmdb_ci_type' | 'cmdb_ci_state',
): string {
  if (item.built_in && item.names[locale] === undefined) return t(`${prefix}.${item.api_name}`);
  return item.names[locale] ?? item.names.en ?? t(`${prefix}.${item.api_name}`);
}

export interface TypeNode {
  value: string;
  title: string;
  children: TypeNode[];
}

/** The type tree for a TreeSelect, names in this language, sorted by name. */
export function typeTree(types: CiType[], name: (type: CiType) => string): TypeNode[] {
  const byParent = new Map<string | null, CiType[]>();
  for (const type of types) {
    const key = type.parent_id ?? null;
    byParent.set(key, [...(byParent.get(key) ?? []), type]);
  }
  const build = (parent: string | null): TypeNode[] =>
    (byParent.get(parent) ?? [])
      .map((type) => ({
        value: type.id,
        title: `${name(type)} (${String(type.ci_count)})`,
        children: build(type.id),
      }))
      .sort((a, b) => a.title.localeCompare(b.title));
  return build(null);
}
