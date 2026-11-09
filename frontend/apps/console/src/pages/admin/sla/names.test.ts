import { describe, expect, it } from 'vitest';

import { calendarNameOf, policyName } from './names';

// QA V6 / QA6-SLA-01: the seeded policy and calendars stayed English in Arabic and Urdu.
const t = (key: string) => `«${key}»`;

describe('V6: seeded SLA names in the user language', () => {
  it('QA6-SLA-01: the seeded fallback policy and calendars go through labels', () => {
    expect(policyName(t, 'Default policy')).toBe('«sla_policy.fallback»');
    expect(calendarNameOf(t, 'Operating hours')).toBe('«sla_calendar.operating_hours»');
    expect(calendarNameOf(t, 'Around the clock')).toBe('«sla_calendar.around_the_clock»');
  });

  it('QA6-SLA-01: a name someone typed stays as typed', () => {
    expect(policyName(t, 'VIP desk')).toBe('VIP desk');
    expect(calendarNameOf(t, 'Riyadh office')).toBe('Riyadh office');
    expect(policyName(t, null)).toBe('');
  });
});
