import type { AssetProductType } from '@supportx/api-client';

export interface TypeNode extends AssetProductType {
  children?: TypeNode[];
}

/** The flat list as a tree, each level in its saved order. */
export function typeTree(types: AssetProductType[]): TypeNode[] {
  const byParent = new Map<string | null, AssetProductType[]>();
  for (const type of types) {
    const siblings = byParent.get(type.parent_id) ?? [];
    siblings.push(type);
    byParent.set(type.parent_id, siblings);
  }
  const build = (parent: string | null): TypeNode[] =>
    (byParent.get(parent) ?? [])
      .sort((a, b) => a.sort - b.sort)
      .map((type) => {
        const children = build(type.id);
        return children.length > 0 ? { ...type, children } : { ...type };
      });
  return build(null);
}
