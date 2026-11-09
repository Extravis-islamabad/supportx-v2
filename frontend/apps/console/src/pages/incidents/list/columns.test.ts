import { describe, expect, it } from 'vitest';

import { chosenColumns, DEFAULT_COLUMNS, type ColumnSpec } from './columns';

const catalogue = new Map<string, ColumnSpec>(
  [...DEFAULT_COLUMNS, 'group_id', 'created_at'].map((key) => [key, { key } as ColumnSpec]),
);

describe('D-147 template C: default columns by window width', () => {
  it('Group joins the defaults, before Status, only in a wide window', () => {
    const narrow = chosenColumns([], catalogue).map((c) => c.key);
    const wide = chosenColumns([], catalogue, true).map((c) => c.key);
    expect(narrow).not.toContain('group_id');
    expect(wide.indexOf('group_id')).toBe(wide.indexOf('status') - 1);
  });

  it("never changes a person's own choice", () => {
    const own = [
      { key: 'subject', width: null },
      { key: 'created_at', width: 140 },
    ];
    expect(chosenColumns(own, catalogue, true)).toEqual(own);
    expect(chosenColumns(own, catalogue, false)).toEqual(own);
  });
});
