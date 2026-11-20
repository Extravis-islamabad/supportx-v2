import { describe, expect, it } from 'vitest';

import { bodyOf, draftOf } from './draft';

// 0183 (D-172): an asset's managing group is set in the form and sent like its other links.

const GROUP = 'b0000000-0000-7000-8000-0000000000aa';

describe('the asset draft and its managing group', () => {
  it('a new asset sends its managing group when one is chosen', () => {
    const draft = {
      ...draftOf(null),
      name: 'Laptop',
      product_id: 'p-1',
      managed_by_group_id: GROUP,
    };
    expect(bodyOf(draft).managed_by_group_id).toBe(GROUP);
    expect('managed_by_group_id' in bodyOf({ ...draft, managed_by_group_id: null })).toBe(false);
  });

  it('a change sends the managing group only when it changed, and null clears it', () => {
    const before = {
      ...draftOf(null),
      name: 'Laptop',
      product_id: 'p-1',
      managed_by_group_id: GROUP,
    };
    expect('managed_by_group_id' in bodyOf({ ...before }, before)).toBe(false);
    expect(bodyOf({ ...before, managed_by_group_id: null }, before).managed_by_group_id).toBeNull();
  });
});
