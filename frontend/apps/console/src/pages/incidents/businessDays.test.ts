import { describe, expect, it } from 'vitest';

import { addBusinessDays } from './businessDays';

describe('business days (the server counts the same, D-107)', () => {
  it('REQ-INC-096: three business days after a Friday afternoon is the Wednesday', () => {
    expect(addBusinessDays(new Date('2026-10-30T16:00:00Z'), 3).toISOString()).toBe(
      '2026-11-04T16:00:00.000Z',
    );
  });

  it('REQ-INC-096: one business day after a Saturday is the Monday', () => {
    expect(addBusinessDays(new Date('2026-10-31T09:00:00Z'), 1).toISOString()).toBe(
      '2026-11-02T09:00:00.000Z',
    );
  });
});
