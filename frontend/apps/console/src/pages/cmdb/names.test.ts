import { describe, expect, it } from 'vitest';

import type { CiType } from '@supportx/api-client';

import { nameOf, typeTree } from './names';

const t = (key: string) => `[${key}]`;

function type(id: string, parent: string | null, extra: Partial<CiType> = {}): CiType {
  return {
    id,
    parent_id: parent,
    api_name: id,
    built_in: true,
    names: {},
    icon: null,
    ci_count: 1,
    child_count: 0,
    version: 1,
    ...extra,
  };
}

describe('CMDB names', () => {
  it('shows a built-in type by its label and a tenant type by its own name', () => {
    expect(nameOf(t, 'ar', type('server', null), 'cmdb_ci_type')).toBe('[cmdb_ci_type.server]');
    const own = type('kiosk', null, { built_in: false, names: { en: 'Kiosk', ar: 'كشك' } });
    expect(nameOf(t, 'ar', own, 'cmdb_ci_type')).toBe('كشك');
    expect(nameOf(t, 'ur', own, 'cmdb_ci_type')).toBe('Kiosk');
  });

  it('builds the tree below each parent', () => {
    const tree = typeTree(
      [type('hardware', null), type('server', 'hardware'), type('app', null)],
      (x) => x.api_name,
    );
    expect(tree.map((n) => n.value)).toEqual(['app', 'hardware']);
    expect(tree[1]?.children.map((n) => n.value)).toEqual(['server']);
  });
});
