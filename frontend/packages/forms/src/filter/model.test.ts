import { describe, expect, it } from 'vitest';

import { fromDsl, newRow, OPERATORS, rowProblems, toDsl, type FilterModel } from './model';

describe('filter model (REQ-RPT-029)', () => {
  it('turns rows into the shared DSL and back', () => {
    const model: FilterModel = {
      join: 'or',
      rows: [
        { field: 'priority', op: 'in', value: ['p1', 'p2'] },
        { field: 'created_at', op: 'last_n_days', value: 30 },
        { field: 'group_id', op: 'is_null', value: null },
      ],
    };
    const dsl = toDsl(model);
    expect(dsl).toEqual({
      or: [
        { field: 'priority', op: 'in', value: ['p1', 'p2'] },
        { field: 'created_at', op: 'last_n_days', value: 30 },
        { field: 'group_id', op: 'is_null' },
      ],
    });
    expect(fromDsl(dsl)).toEqual(model);
    expect(toDsl({ join: 'and', rows: [] })).toBeUndefined();
    const [first] = model.rows;
    if (first === undefined) throw new Error('no row');
    expect(toDsl({ join: 'and', rows: [first] })).toEqual(first);
  });

  it('keeps nested filters read-only instead of flattening them', () => {
    expect(fromDsl({ and: [{ or: [{ field: 'a', op: 'eq', value: 1 }] }] })).toBeNull();
  });

  it('flags a condition with a field but no value (AC2)', () => {
    const problems = rowProblems({
      join: 'and',
      rows: [
        { field: 'priority', op: 'in', value: [] },
        { field: 'created_at', op: 'today', value: null },
        { field: 'subject', op: 'contains', value: '' },
        { field: 'reopen_count', op: 'between', value: ['1', null] },
      ],
    });
    expect([...problems.keys()]).toEqual([0, 2, 3]);
  });

  it('offers every relative period for dates and starts a row with its first operator', () => {
    expect(OPERATORS.datetime).toEqual(
      expect.arrayContaining(['today', 'this_week', 'last_month', 'last_n_days', 'between']),
    );
    expect(newRow({ name: 'created_at', type: 'datetime', label: 'Created' })).toEqual({
      field: 'created_at',
      op: 'today',
      value: null,
    });
  });
});
