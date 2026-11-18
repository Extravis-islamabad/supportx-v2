import type { CiMapNode, RelationshipDirection, RelationshipType } from '@supportx/api-client';
import type { Tone } from '@supportx/ui';

type Translate = (key: string, params?: Record<string, string | number>) => string;

/** A name in this language from a tenant's {en, ar, ur}, else English. */
const own = (names: Record<string, string> | undefined, locale: string): string | undefined =>
  names?.[locale] ?? names?.en;

/** A map node's CI type in words: a built-in by its label, a tenant's own by its name. */
export function nodeType(t: Translate, locale: string, node: CiMapNode): string {
  if (node.restricted) return '';
  if (node.type_label_key != null && node.type_names?.[locale] === undefined) {
    return t(node.type_label_key);
  }
  return (
    own(node.type_names, locale) ?? (node.type_label_key == null ? '' : t(node.type_label_key))
  );
}

/** A map node's state in words; with no state name, its category's label. */
export function nodeState(t: Translate, locale: string, node: CiMapNode): string {
  if (node.restricted) return '';
  if (node.state_label_key != null && node.state_names?.[locale] === undefined) {
    return t(node.state_label_key);
  }
  const named = own(node.state_names, locale);
  if (named !== undefined) return named;
  if (node.state_label_key != null) return t(node.state_label_key);
  return node.state_category == null ? '' : t(`cmdb_state_category.${node.state_category}`);
}

/** The node's name, or "A CI you can't open" (condition 8). */
export function nodeName(t: Translate, node: CiMapNode): string {
  return node.restricted ? t('cmdb.map.restricted') : (node.name ?? '');
}

/**
 * States by tone AND by a shape (condition 8: never colour alone): active is solid and
 * success-toned, end of life warning-toned and dashed, a restricted node neutral and dotted.
 */
export function nodeLook(node: CiMapNode): { tone: Tone; border: 'solid' | 'dashed' | 'dotted' } {
  if (node.restricted) return { tone: 'default', border: 'dotted' };
  if (node.state_category === 'end_of_life') return { tone: 'warning', border: 'dashed' };
  return { tone: 'success', border: 'solid' };
}

/** A relationship read from one end: "runs on" from the source, "hosts" from the target. */
export function relationshipName(
  t: Translate,
  locale: string,
  type: RelationshipType | undefined,
  direction: RelationshipDirection,
): string {
  if (type === undefined) return t('cmdb.map.relationship_unknown');
  const names = direction === 'forward' ? type.names_forward : type.names_inverse;
  const named = own(names, locale);
  if (named !== undefined && named !== '') return named;
  return t(`cmdb_relationship.${type.code}.${direction}`);
}

/** The relationship type's own name for lists and pickers: "runs on / hosts". */
export function relationshipTypeName(t: Translate, locale: string, type: RelationshipType): string {
  const forward = relationshipName(t, locale, type, 'forward');
  const inverse = relationshipName(t, locale, type, 'inverse');
  return forward === inverse
    ? forward
    : t('cmdb.relationship_type.both_names', { forward, inverse });
}

/** What a screen reader hears on a node (condition 6): name, type, state, how many links. */
export function nodeAriaLabel(
  t: Translate,
  locale: string,
  node: CiMapNode,
  links: number,
): string {
  if (node.restricted) return t('cmdb.map.node_restricted_aria', { count: links });
  return t('cmdb.map.node_aria', {
    name: node.name ?? '',
    type: nodeType(t, locale, node),
    state: nodeState(t, locale, node),
    count: links,
  });
}
