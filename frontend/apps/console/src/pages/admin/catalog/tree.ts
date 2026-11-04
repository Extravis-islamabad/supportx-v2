import type { CatalogCategory } from '@supportx/api-client';
import { textIn } from '@supportx/ui';

// The category tree (WP-031 plan D1) from the flat list the API gives, in order.

/** Children of each category (null: the roots), each list in the catalog's order. */
export function childrenOf(categories: CatalogCategory[]): Map<string | null, CatalogCategory[]> {
  const known = new Set(categories.map((c) => c.id));
  const byParent = new Map<string | null, CatalogCategory[]>();
  for (const category of categories) {
    // A parent the reader may not see (a disabled branch, for a requester) makes it a root.
    const parent =
      category.parent_id !== null && known.has(category.parent_id) ? category.parent_id : null;
    byParent.set(parent, [...(byParent.get(parent) ?? []), category]);
  }
  for (const list of byParent.values()) {
    list.sort((a, b) => a.sort_order - b.sort_order || a.id.localeCompare(b.id));
  }
  return byParent;
}

/** Each category's full path in `locale` ("Hardware › Laptops"), for tables and pickers. */
export function categoryPaths(categories: CatalogCategory[], locale: string): Map<string, string> {
  const byId = new Map(categories.map((c) => [c.id, c]));
  const paths = new Map<string, string>();
  for (const category of categories) {
    const names: string[] = [];
    let cursor: CatalogCategory | undefined = category;
    const seen = new Set<string>();
    while (cursor !== undefined && !seen.has(cursor.id)) {
      seen.add(cursor.id);
      names.unshift(textIn(cursor.names, locale));
      cursor = cursor.parent_id === null ? undefined : byId.get(cursor.parent_id);
    }
    paths.set(category.id, names.join(' › '));
  }
  return paths;
}

/** Categories `id` may move under: not itself, nothing below it (no loops, plan D1). */
export function possibleParents(categories: CatalogCategory[], id: string | undefined) {
  if (id === undefined) return categories;
  const below = new Set<string>([id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const c of categories) {
      if (c.parent_id !== null && below.has(c.parent_id) && !below.has(c.id)) {
        below.add(c.id);
        grew = true;
      }
    }
  }
  return categories.filter((c) => !below.has(c.id));
}
