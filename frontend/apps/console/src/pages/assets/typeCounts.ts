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
