import { describe, expect, it } from 'vitest';

import { deliveryText } from './items';

// F2 (Haider, 2026-11-10): the wording of an item's expected delivery.
const t = ((key: string, params?: { count?: number }) =>
  `${key}:${String(params?.count ?? '')}`) as Parameters<typeof deliveryText>[0];

describe('deliveryText', () => {
  it('says nothing when no SLA applies', () => {
    expect(deliveryText(t, null)).toBeNull();
  });
  it('counts working days, working hours, or hours around the clock', () => {
    const at = (amount: number, unit: string, around = false) =>
      deliveryText(t, { amount, unit, around_the_clock: around });
    expect(at(3, 'business_days')).toBe('requests.delivery.working_days:3');
    expect(at(8, 'hours')).toBe('requests.delivery.working_hours:8');
    expect(at(8, 'hours', true)).toBe('requests.delivery.hours:8');
    // An hour or more in minutes says hours, rounded up; under an hour, minutes.
    expect(at(90, 'minutes')).toBe('requests.delivery.working_hours:2');
    expect(at(45, 'minutes')).toBe('requests.delivery.minutes:45');
  });
});
