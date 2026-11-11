import type { TypeNode } from '../admin/assets/tree';

/** The tree's own row for "every type" (no filter). */
export const ALL_TYPES = '';

/** Each node's count with every type below it (the server counts per type only). */
export function branchCounts(
  nodes: TypeNode[],
  own: ReadonlyMap<string, number>,
): Map<string, number> {
  const found = new Map<string, number>();
  const walk = (node: TypeNode): number => {
    const total = (own.get(node.id) ?? 0) + (node.children ?? []).reduce((n, c) => n + walk(c), 0);
    found.set(node.id, total);
    return total;
  };
  nodes.forEach(walk);
  return found;
}

/** Keys typed within this many milliseconds form one typeahead prefix. */
export const TYPEAHEAD_MS = 500;

// Arabic script (Arabic and Urdu, with their presentation forms).
const ARABIC = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]/;

/**
 * Whether a row's name starts with what was typed, ignoring case in the person's language.
 * For Arabic-script names only the first character is compared: letters change shape and join
 * as they are typed, so a longer prefix is unreliable.
 */
export function startsWith(name: string, typed: string, locale: string): boolean {
  const label = name.trim().toLocaleLowerCase(locale);
  const text = typed.toLocaleLowerCase(locale);
  if (label === '' || text === '') return false;
  if (ARABIC.test(label.charAt(0)) || ARABIC.test(text.charAt(0))) {
    return label.startsWith(text.charAt(0));
  }
  return label.startsWith(text);
}
