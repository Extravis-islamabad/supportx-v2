import { describe, expect, it } from 'vitest';

import { draftOf, hasWithheld, withoutWithheld } from './model';

// Lane C (#551): a saved view's condition on a field the person cannot see now comes back
// withheld; running the view leaves it out, editing never rewrites the filter.
const HIDDEN = { field: 'custom.passport', op: 'eq', value: null, withheld: true };
const P1 = { field: 'priority', op: 'eq', value: 'p1' };
const P2 = { field: 'priority', op: 'eq', value: 'p2' };

describe('withheld conditions', () => {
  it('are found anywhere in the tree', () => {
    expect(hasWithheld(HIDDEN)).toBe(true);
    expect(hasWithheld({ and: [P1, { or: [P2, HIDDEN] }] })).toBe(true);
    expect(hasWithheld({ and: [P1, P2] })).toBe(false);
    expect(hasWithheld(null)).toBe(false);
  });

  it('are left out of the filter that runs, emptied groups dropped, single ones unwrapped', () => {
    expect(withoutWithheld(HIDDEN)).toBeUndefined();
    expect(withoutWithheld({ and: [P1, HIDDEN] })).toEqual(P1);
    expect(withoutWithheld({ and: [P1, { or: [HIDDEN] }, P2] })).toEqual({ and: [P1, P2] });
    expect(withoutWithheld({ and: [P1, P2] })).toEqual({ and: [P1, P2] });
  });

  it('mark the draft, so the editor keeps the saved filter as it is', () => {
    const draft = draftOf({
      id: 'v1',
      version: 2,
      name: 'Mine',
      visibility: 'private',
      group_ids: [],
      owner_id: 'u1',
      mine: true,
      favourite: false,
      filter: { and: [P1, HIDDEN] },
      columns: [],
      sort: null,
      updated_at: '2026-11-19T00:00:00Z',
    });
    expect(draft.withheld).toBe(true);
    expect(draft.filter.rows).toHaveLength(1);
  });
});
